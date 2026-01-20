#!/usr/bin/env python3
# 用法：
#   1) 默认读取同目录下的 ref-encoding.json，并把分析报告打印到 stdout：
#        python3 analyze_ref_encoding.py
#   2) 指定输入文件，并把报告写到文件：
#        python3 analyze_ref_encoding.py /path/to/ref-encoding.json --out report.md
#   3) 额外输出“每条指令”的结构摘要（可能很长），可用正则过滤并限制条数：
#        python3 analyze_ref_encoding.py --per-instruction --filter 'IADD3|FSET' --limit 50
#
# 说明：
#   - 输出是 Markdown 文本，方便直接保存成 .md 阅读。
#   - ranges.inst 是 16 字节(32 hex)的小端序表示；ranges.ranges 的 start 是从最低有效位开始计数的 bit index。

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Iterable


EXPECTED_RANGE_KEYS = {
    "type",
    "start",
    "length",
    "operand_index",
    "group_id",
    "name",
    "constant",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze ref-encoding.json and summarize common schema / field meanings."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(Path(__file__).with_name("ref-encoding.json")),
        help="Path to ref-encoding.json (default: ./ref-encoding.json next to this script).",
    )
    parser.add_argument("--out", default="-", help="Output file (default: '-' for stdout).")
    parser.add_argument(
        "--per-instruction",
        action="store_true",
        help="Also include a per-instruction summary section (may be large).",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Regex to filter instruction keys (applies only with --per-instruction).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max instructions to print under --per-instruction (0 means no limit).",
    )
    parser.add_argument(
        "--max-table-items",
        type=int,
        default=16,
        help="Max number of entries printed for each modifiers table in the report.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Top-level JSON must be an object/dict, got {type(data).__name__}")
    return data


def inst_int_from_hex_le(inst_hex: str) -> int:
    raw = bytes.fromhex(inst_hex)
    if len(raw) != 16:
        raise ValueError(f"Expected 16 bytes (32 hex chars), got {len(raw)} bytes from {inst_hex!r}")
    return int.from_bytes(raw, "little", signed=False)


def extract_bits(inst: int, start: int, length: int) -> int:
    if length <= 0:
        raise ValueError(f"Invalid length={length}")
    mask = (1 << length) - 1
    return (inst >> start) & mask


def fmt_bits(start: int, length: int) -> str:
    return f"[{start}..{start + length - 1}]({length}b)"


def fmt_table(table: list[list[Any]], max_items: int) -> str:
    # table: [[value:int, text:str], ...]
    items = []
    for entry in table[:max_items]:
        if not (isinstance(entry, list) and len(entry) == 2):
            items.append(repr(entry))
            continue
        val, text = entry
        items.append(f"{val}:{str(text).strip()!r}")
    suffix = "" if len(table) <= max_items else f" ... (+{len(table) - max_items})"
    return ", ".join(items) + suffix


def split_modifier_tokens(text_with_dots: str) -> list[str]:
    # "F16x2.RN." -> ["F16x2", "RN"]
    text = text_with_dots.rstrip(".")
    return [t for t in text.split(".") if t]


def flatten_operand_atoms(
    operand: dict[str, Any],
    *,
    prefix: str,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Flatten parsed operands into "atoms" that correspond to operand_index space used by ranges.ranges.

    Many parsed operands are structured (e.g. AddressOperand has sub_operands like base reg + immediate).
    In ref-encoding.json, ranges entries use operand_index that often refers to these *sub-operands* rather
    than the top-level operand list index.
    """
    if "sub_operands" in operand and isinstance(operand["sub_operands"], list):
        out: list[tuple[str, dict[str, Any]]] = []
        for i, sub in enumerate(operand["sub_operands"]):
            if isinstance(sub, dict):
                out.extend(flatten_operand_atoms(sub, prefix=f"{prefix}.sub{i}"))
            else:
                out.append((f"{prefix}.sub{i}", {"type": type(sub).__name__, "value": sub}))
        return out
    return [(prefix, operand)]


def flatten_operands(parsed_operands: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    atoms: list[tuple[str, dict[str, Any]]] = []
    for i, op in enumerate(parsed_operands):
        if not isinstance(op, dict):
            atoms.append((f"op{i}", {"type": type(op).__name__, "value": op}))
            continue
        atoms.extend(flatten_operand_atoms(op, prefix=f"op{i}"))
    return atoms


def describe_operand_atom(atom: dict[str, Any]) -> str:
    t = atom.get("type")
    if t == "RegOperand":
        mods = atom.get("modifiers") or []
        mods_s = "" if not mods else f" mods={mods}"
        return f"Reg `{atom.get('reg_type')}{atom.get('ident')}`{mods_s}"
    if t == "IntIMMOperand":
        return f"IntImm `{atom.get('constant')}`"
    if t == "FloatIMMOperand":
        return f"FloatImm `{atom.get('constant')}`"
    if t == "ConstantMemOperand":
        return "ConstMem"
    if t == "DescOperand":
        return "Desc"
    if t == "AttributeOperand":
        return "Attr"
    return f"{t} {atom}"


def ensure_partition_128(ranges: list[dict[str, Any]]) -> str | None:
    used = [None] * 128
    for r in ranges:
        start = int(r["start"])
        length = int(r["length"])
        if start < 0 or length <= 0 or start + length > 128:
            return f"bit-range out of bounds: start={start} length={length}"
        for bit in range(start, start + length):
            if used[bit] is not None:
                return f"overlap at bit {bit}: {used[bit]} vs {r.get('type')}"
            used[bit] = r.get("type")
    if any(u is None for u in used):
        gaps = [i for i, u in enumerate(used) if u is None]
        return f"gaps (first 16): {gaps[:16]} (total {len(gaps)})"
    return None


@dataclass(frozen=True)
class DecodedModifierField:
    start: int
    length: int
    group_index: int  # 0-based among modifier fields in this instruction
    selected_value: int
    selected_text: str | None
    selected_tokens: tuple[str, ...]


def decode_modifier_fields(v: dict[str, Any]) -> list[DecodedModifierField]:
    inst = inst_int_from_hex_le(v["ranges"]["inst"])
    mod_fields = [r for r in v["ranges"]["ranges"] if r["type"] == "modifier"]
    mod_fields.sort(key=lambda r: (int(r["start"]), int(r["length"])))

    tables: list[list[list[Any]]] = v.get("modifiers") or []
    decoded: list[DecodedModifierField] = []
    for i, r in enumerate(mod_fields):
        start = int(r["start"])
        length = int(r["length"])
        val = extract_bits(inst, start, length)
        table = tables[i] if i < len(tables) else []
        selected_text = dict(table).get(val) if table else None
        tokens = tuple(split_modifier_tokens(selected_text)) if selected_text else tuple()
        decoded.append(
            DecodedModifierField(
                start=start,
                length=length,
                group_index=i,
                selected_value=val,
                selected_text=selected_text,
                selected_tokens=tokens,
            )
        )
    return decoded


def pick_representative_instruction(data: dict[str, Any]) -> str:
    # Heuristic: prefer an instruction that exercises more features so the report has a concrete example.
    best_key = ""
    best_score = -1
    for key, v in data.items():
        rr = v.get("ranges", {}).get("ranges", [])
        types = {r.get("type") for r in rr if isinstance(r, dict)}
        score = 0
        for t in [
            "operand",
            "operand_flag",
            "operand_modifier",
            "modifier",
            "flag",
            "predicate",
            "stall",
            "reuse",
            "b-mask",
        ]:
            score += 2 if t in types else 0
        score += 1 if (v.get("operand_interactions") is not None) else 0
        score += 1 if (v.get("opcode_modis") or []) else 0
        score += 1 if (v.get("operand_modifiers") and len(v.get("operand_modifiers")) > 0) else 0
        score += 1 if (v.get("modifiers") and len(v.get("modifiers")) > 0) else 0
        if score > best_score or (score == best_score and key < best_key):
            best_key = key
            best_score = score
    return best_key


def decode_control_fields(v: dict[str, Any]) -> dict[str, tuple[int, int, int] | None]:
    # Returns name -> (start,length,value) or None if not present.
    inst = inst_int_from_hex_le(v["ranges"]["inst"])
    rr = v["ranges"]["ranges"]
    out: dict[str, tuple[int, int, int] | None] = {}
    for t in ["predicate", "stall", "y", "r-bar", "w-bar", "b-mask", "reuse"]:
        r = next((x for x in rr if x["type"] == t), None)
        if r is None:
            out[t] = None
            continue
        start = int(r["start"])
        length = int(r["length"])
        out[t] = (start, length, extract_bits(inst, start, length))
    return out


def summarize_instruction(
    out: IO[str],
    key: str,
    v: dict[str, Any],
    *,
    max_table_items: int,
) -> None:
    out.write(f"\n### `{key}`\n\n")
    out.write(
        "这部分把“某一条指令”的结构用更接近人类阅读的方式摊开：\n"
        "你可以把它当成一个 128-bit 的 bit-layout，其中 `ranges.ranges` 是完整分区。\n\n"
    )
    out.write(f"- `canonical_name`: `{v.get('canonical_name')}`\n")
    out.write(f"- `disasm`: `{v.get('disasm')}`\n")
    out.write(f"- `parsed.base_name`: `{v['parsed'].get('base_name')}`\n")
    out.write(f"- `parsed.predicate`: `{v['parsed'].get('predicate')}`\n")
    out.write(f"- `parsed.modifiers`: `{v['parsed'].get('modifiers')}`\n")
    out.write(f"- `opcode_modis`: `{v.get('opcode_modis')}`\n")

    inst_hex = v["ranges"]["inst"]
    out.write(f"- `ranges.inst` (hex, 16B LE): `{inst_hex}`\n")

    # Ranges summary
    rr = v["ranges"]["ranges"]
    type_counts = Counter(r["type"] for r in rr)
    out.write(f"- `ranges.ranges`: {len(rr)} fields, types={dict(type_counts)}\n")

    # Control fields decoded
    ctrl = decode_control_fields(v)
    out.write("- control/schedule fields decoded from `ranges.inst`:\n")
    for t in ["predicate", "stall", "y", "r-bar", "w-bar", "b-mask", "reuse"]:
        info = ctrl.get(t)
        if info is None:
            out.write(f"  - {t}: (not present)\n")
        else:
            start, length, value = info
            out.write(f"  - {t}: {fmt_bits(start, length)} = {value}\n")

    # Constants (highlight opcode-like field)
    inst = inst_int_from_hex_le(inst_hex)
    constants = [r for r in rr if r["type"] == "constant"]
    opcode12 = next(
        (r for r in constants if int(r["start"]) == 0 and int(r["length"]) == 12),
        None,
    )
    if opcode12 is not None:
        prefix = None
        try:
            prefix = int(key.split(".", 1)[0])
        except Exception:  # noqa: BLE001
            prefix = None
        start = int(opcode12["start"])
        length = int(opcode12["length"])
        val = extract_bits(inst, start, length)
        out.write(
            f"- opcode-like `constant@start=0,length=12`: {fmt_bits(start, length)} = {val}"
            + (f" (key prefix={prefix})" if prefix is not None else "")
            + "\n"
        )
    # Non-zero constants besides opcode-like are often “secondary opcode / mode bits”.
    nonzero = []
    zero_count = 0
    for r in sorted(constants, key=lambda x: int(x["start"])):
        start = int(r["start"])
        length = int(r["length"])
        val = extract_bits(inst, start, length)
        if val == 0:
            zero_count += 1
            continue
        if opcode12 is not None and r is opcode12:
            continue
        nonzero.append((start, length, val))
    out.write(f"- constants: total={len(constants)}, zeros={zero_count}, nonzero(except opcode12)={len(nonzero)}\n")
    if nonzero:
        out.write("  - nonzero constants:\n")
        for start, length, val in nonzero[:16]:
            out.write(f"    - {fmt_bits(start, length)} = {val}\n")
        if len(nonzero) > 16:
            out.write(f"    - ... (+{len(nonzero) - 16})\n")

    # Operands
    operands = v["parsed"]["operands"]
    out.write(
        f"- parsed.operands (top-level, {len(operands)}):\n"
        "  - 注意：ranges 里的 `operand_index` 往往不是指向 top-level operands，而是指向“展开后的 operand atom”（例如 AddressOperand 的 sub_operands）。\n"
    )
    for i, op in enumerate(operands):
        if isinstance(op, dict) and op.get("type") == "RegOperand":
            out.write(f"  - op{i}: Reg `{op.get('reg_type')}{op.get('ident')}` mods={op.get('modifiers')}\n")
        else:
            out.write(f"  - op{i}: {op.get('type') if isinstance(op, dict) else type(op).__name__} {op}\n")

    atoms = flatten_operands(operands)
    out.write(f"- operand atoms (flattened, used by `operand_index`, {len(atoms)}):\n")
    for idx, (path, atom) in enumerate(atoms):
        out.write(f"  - atom#{idx} ({path}): {describe_operand_atom(atom)}\n")

    # Operand bit segments
    by_operand: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for r in rr:
        if r["type"] == "operand":
            by_operand[int(r["operand_index"])].append((int(r["start"]), int(r["length"])))
    for idx in by_operand:
        by_operand[idx].sort()
    if by_operand:
        out.write("- operand bitfields (`type=operand`):\n")
        for idx in sorted(by_operand):
            segs = by_operand[idx]
            total = sum(l for _, l in segs)
            seg_str = ", ".join(f"{fmt_bits(s, l)}" for s, l in segs)
            atom_desc = (
                describe_operand_atom(atoms[idx][1]) if 0 <= idx < len(atoms) else "(unknown atom_index)"
            )
            out.write(f"  - operand_index #{idx} ({atom_desc}): total={total}b, segments={seg_str}\n")

    # Flags / operand_flags
    flags = [r for r in rr if r["type"] == "flag"]
    if flags:
        flags.sort(key=lambda r: int(r["start"]))
        out.write(
            "- flags (`type=flag`, 1-bit):\n"
            "  - 这些通常对应 disasm 里额外出现/消失的 token（例如 `FTZ`），`ranges.inst` 的该 bit=1 表示启用。\n"
        )
        for r in flags:
            start = int(r["start"])
            length = int(r["length"])
            out.write(f"  - {r['name']}: {fmt_bits(start, length)} = {extract_bits(inst, start, length)}\n")

    op_flags = [r for r in rr if r["type"] == "operand_flag"]
    if op_flags:
        op_flags.sort(key=lambda r: (int(r["operand_index"]), int(r["start"])))
        out.write(
            "- operand flags (`type=operand_flag`, 1-bit):\n"
            "  - 这些是“挂在某个操作数上的一元修饰/开关”（例如取反/取负/取绝对值）。\n"
        )
        for r in op_flags:
            start = int(r["start"])
            length = int(r["length"])
            opi = int(r["operand_index"])
            atom_desc = describe_operand_atom(atoms[opi][1]) if 0 <= opi < len(atoms) else "(unknown atom_index)"
            out.write(
                f"  - operand_index #{opi} ({atom_desc}) {r['name']}: {fmt_bits(start, length)} = {extract_bits(inst, start, length)}\n"
            )

    # Modifiers (variable) and how they decode in this sample inst
    decoded_mods = decode_modifier_fields(v)
    if decoded_mods:
        out.write(
            "- modifier fields (`type=modifier`) decoded from `ranges.inst`:\n"
            "  - 每个 modifier bitfield 都会在 `modifiers[i]` 表里选出一个文本；该文本可能包含多个 token（用 `.` 拼起来）。\n"
        )
        tables: list[list[list[Any]]] = v.get("modifiers") or []
        for dm in decoded_mods:
            table = tables[dm.group_index] if dm.group_index < len(tables) else []
            out.write(
                f"  - group#{dm.group_index} {fmt_bits(dm.start, dm.length)} = {dm.selected_value}"
                f" -> {dm.selected_text!r} tokens={list(dm.selected_tokens)}"
                f" | table: {fmt_table(table, max_table_items) if table else '(empty)'}\n"
            )

    # Operand modifiers (variable)
    op_mod_fields = [r for r in rr if r["type"] == "operand_modifier"]
    if op_mod_fields:
        out.write("- operand modifier fields (`type=operand_modifier`) decoded from `ranges.inst`:\n")
        for r in sorted(op_mod_fields, key=lambda x: (int(x["operand_index"]), int(x["start"]))):
            opi = int(r["operand_index"])
            table = (v.get("operand_modifiers") or {}).get(str(opi), [])
            val = extract_bits(inst, int(r["start"]), int(r["length"]))
            txt = dict(table).get(val) if table else None
            atom_desc = describe_operand_atom(atoms[opi][1]) if 0 <= opi < len(atoms) else "(unknown atom_index)"
            out.write(
                f"  - operand_index #{opi} ({atom_desc}) {fmt_bits(int(r['start']), int(r['length']))} = {val}"
                f" -> {txt!r} | table: {fmt_table(table, max_table_items) if table else '(missing/empty)'}\n"
            )

    # Operand interactions
    oi = v.get("operand_interactions")
    if isinstance(oi, dict):
        out.write("- operand_interactions:\n")
        for cat in sorted(oi):
            items = oi[cat] or []
            if not items:
                out.write(f"  - {cat}: (empty)\n")
                continue
            # item: [operand_index, 'R'|'W', width]
            parts = []
            for it in items:
                if not (isinstance(it, list) and len(it) == 3):
                    parts.append(repr(it))
                    continue
                opi = int(it[0])
                atom_desc = describe_operand_atom(atoms[opi][1]) if 0 <= opi < len(atoms) else "(unknown atom_index)"
                parts.append(f"operand_index #{opi} ({atom_desc}) {it[1]} x{it[2]}")
            out.write(f"  - {cat}: {', '.join(parts)}\n")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    data = load_json(input_path)

    out: IO[str]
    if args.out == "-":
        out = sys.stdout
    else:
        out = Path(args.out).open("w", encoding="utf-8")

    try:
        # ===== Top-level schema =====
        out.write("# ref-encoding.json 格式分析报告\n\n")
        out.write(f"- input: `{str(input_path)}`\n")
        out.write(f"- instructions: {len(data)}\n\n")

        out.write("## 阅读指南（先看这段）\n\n")
        out.write(
            "- 这份报告的目标：把 `ref-encoding.json` 的“公共格式/字段语义/选项关系”解释清楚，方便你做进一步解析或生成代码。\n"
        )
        out.write(
            "- 最重要的概念：每条指令都是 **128-bit**，`ranges.ranges` 把 0..127 bit **完整切分**成若干字段；每个字段有 `type/start/length/...`。\n"
        )
        out.write(
            "- `start` 的含义：从 **最低有效位 (LSB)** 开始计数的 bit index；因此解析一个字段值就是：`value = (inst >> start) & ((1<<length)-1)`。\n"
        )
        out.write(
            "- `ranges.inst` 的含义：16 字节的 hex 字符串，按 **little-endian** 解释成 128-bit 整数后，再用上面的 `start/length` 取字段值。\n"
        )
        out.write(
            "- 如果你只想快速知道有哪些字段类型：直接跳到“`type` 包含哪些选项”。\n"
        )
        out.write(
            "- 如果你想看某条指令下各种选项怎么互动：用 `--per-instruction` 输出“逐指令摘要”。\n\n"
        )

        rep_key = pick_representative_instruction(data)
        if rep_key:
            rep = data[rep_key]
            rep_types = Counter(r["type"] for r in rep["ranges"]["ranges"])
            out.write("## 快速例子（用一条“功能比较全”的指令说明结构）\n\n")
            out.write(f"- example key: `{rep_key}`\n")
            out.write(f"- example disasm: `{rep.get('disasm')}`\n")
            out.write(
                "- 你可以把它理解为：`ranges.ranges` 定义了 bit-layout；`parsed` 给出语法层面的指令/操作数；"
                "`modifiers/flags/operand_*` 等字段共同决定 disasm 里会出现哪些 token。\n"
            )
            out.write(f"- example field types: {dict(rep_types)}\n\n")

        instr_keysets = Counter(tuple(sorted(v.keys())) for v in data.values())
        out.write("## 顶层结构（每条指令对象的字段）\n\n")
        out.write(
            "- 顶层 JSON 是一个 dict：key 是类似 `528.IADD3_R_P_P_R_R_R` 的字符串；value 是该“指令变体”的结构描述。\n"
        )
        out.write(f"- unique keysets: {len(instr_keysets)}\n")
        for ks, count in instr_keysets.most_common(5):
            out.write(f"- {count}x keys={list(ks)}\n")

        out.write("\n### 字段之间的关键关系\n\n")
        out.write(
            "- `parsed.base_name`：指令基本名字（例如 `IADD3`）。\n"
            "- `opcode_modis`：这条变体在“名字层面”额外附加到指令名的 token（也会体现在 `canonical_name` 里）。\n"
            "- `canonical_name`：**严格等于** `parsed.base_name` + `opcode_modis`（用 `.` 连接）。\n"
        )
        ok = 0
        for v in data.values():
            base = v["parsed"]["base_name"]
            opmods = v.get("opcode_modis") or []
            expect = base + ("" if not opmods else "." + ".".join(opmods))
            ok += 1 if v.get("canonical_name") == expect else 0
        out.write(
            "- 关系校验：`canonical_name == parsed.base_name + ('.' + '.'.join(opcode_modis) if opcode_modis else '')`\n"
        )
        out.write(f"  - {ok}/{len(data)} OK\n")

        # ===== ranges 格式校验 =====
        out.write("\n## ranges 字段的公共格式\n\n")
        out.write(
            "- `ranges` 是一个对象：\n"
            "  - `inst`: 一个 16B 的 hex（示例编码；常用于校验/展示默认值）。\n"
            "  - `ranges`: 一个 list，每项都是一个字段描述（`type/start/length/...`）。\n"
        )
        out.write(
            "- 报告里的校验项解释：\n"
            "  - `ranges.ranges` keyset：确认每个字段是否都长得像同一个 schema。\n"
            "  - partition(0..127)：确认字段把 128-bit 覆盖得严丝合缝（无重叠、无空洞）。\n"
            "  - constant vs inst：确认 `type=constant` 真的和 `ranges.inst` 的对应 bit 一致。\n\n"
        )
        ranges_keysets = Counter(tuple(sorted(v["ranges"].keys())) for v in data.values())
        out.write(f"- `ranges` object keysets: {dict(ranges_keysets)}\n")

        all_range_keysets = Counter()
        type_counts = Counter()
        type_nonnull = defaultdict(Counter)
        type_names = defaultdict(Counter)
        schedule_starts = defaultdict(Counter)
        flag_name_counts = Counter()
        operand_flag_name_counts = Counter()

        partition_errors: list[tuple[str, str]] = []
        inst_len_errors: list[tuple[str, str]] = []
        constant_mismatch: list[tuple[str, str]] = []
        opcode12_missing: list[str] = []
        opcode12_mismatch_key_prefix: list[tuple[str, int, int]] = []

        modifier_tables_stats = Counter()
        modifier_table_option_multi_token = 0
        modifier_table_option_single_token = 0
        modifier_table_option_empty = 0
        operand_modifier_table_option_empty = 0
        operand_modifier_table_option_nonempty = 0

        for key, v in data.items():
            rr = v["ranges"]["ranges"]
            all_range_keysets.update([tuple(sorted(r.keys())) for r in rr])
            type_counts.update([r["type"] for r in rr])

            # Validate partition and inst length / endianness assumptions.
            pe = ensure_partition_128(rr)
            if pe:
                partition_errors.append((key, pe))

            inst_hex = v["ranges"]["inst"]
            try:
                inst = inst_int_from_hex_le(inst_hex)
            except Exception as e:  # noqa: BLE001
                inst_len_errors.append((key, str(e)))
                inst = None

            # 常见“opcode-like”字段：start=0,length=12 的 constant；少数指令没有。
            opcode12 = None
            for r in rr:
                if r["type"] == "constant" and int(r["start"]) == 0 and int(r["length"]) == 12:
                    opcode12 = int(r["constant"])
                    break
            if opcode12 is None:
                opcode12_missing.append(key)
            else:
                # 对比 key 前缀（形如 "528.IADD3_..."）只是辅助统计：它并不总等于 opcode12。
                try:
                    prefix = int(key.split(".", 1)[0])
                    if prefix != opcode12:
                        opcode12_mismatch_key_prefix.append((key, prefix, opcode12))
                except Exception:  # noqa: BLE001
                    pass

            # modifiers 表：每条指令 modifiers 的“表数量”应当等于 modifier bitfield 数量（经验观察恒成立）。
            tables: list[list[list[Any]]] = v.get("modifiers") or []
            mod_fields = [r for r in rr if r["type"] == "modifier"]
            modifier_tables_stats[(len(mod_fields), len(tables))] += 1
            for table in tables:
                for _val, text in table or []:
                    if not text:
                        modifier_table_option_empty += 1
                        continue
                    txt = str(text).rstrip(".")
                    if not txt:
                        modifier_table_option_empty += 1
                    elif "." in txt:
                        modifier_table_option_multi_token += 1
                    else:
                        modifier_table_option_single_token += 1

            # operand_modifiers 表（操作数修饰符）：统计非空/空选项。
            om = v.get("operand_modifiers") or {}
            if isinstance(om, dict):
                for table in om.values():
                    for _val, text in table or []:
                        if not text:
                            operand_modifier_table_option_empty += 1
                        else:
                            operand_modifier_table_option_nonempty += 1

            for r in rr:
                t = r["type"]
                for f in ["operand_index", "group_id", "name", "constant"]:
                    type_nonnull[t][f"non_null_{f}"] += 0 if r.get(f) is None else 1
                if r.get("name") is not None:
                    type_names[t][str(r["name"])] += 1
                if t == "flag":
                    flag_name_counts[str(r["name"])] += 1
                if t == "operand_flag":
                    operand_flag_name_counts[str(r["name"])] += 1

                # Record schedule/control fields (these tend to have fixed positions).
                if t in {"stall", "y", "reuse", "r-bar", "w-bar", "b-mask", "predicate"}:
                    schedule_starts[t][(int(r["start"]), int(r["length"]))] += 1

                # Validate constant ranges match bits in inst (if inst was parsed OK).
                if inst is not None and t == "constant":
                    start = int(r["start"])
                    length = int(r["length"])
                    expected = int(r["constant"])
                    got = extract_bits(inst, start, length)
                    if got != expected:
                        constant_mismatch.append(
                            (key, f"constant mismatch at {fmt_bits(start, length)}: expected={expected} got={got}")
                        )

        out.write("- `ranges.ranges` 每个字段是否符合示例格式（固定 7 个 key）？\n")
        out.write(f"  - EXPECTED keys = {sorted(EXPECTED_RANGE_KEYS)}\n")
        out.write(f"  - observed unique keysets = {len(all_range_keysets)}\n")
        for ks, count in all_range_keysets.most_common(5):
            out.write(f"  - {count}x keys={list(ks)}\n")
        out.write(
            f"- partition(0..127) checks: {'OK' if not partition_errors else f'FAIL ({len(partition_errors)})'}\n"
        )
        out.write(
            f"- `ranges.inst` (16B little-endian hex) checks: {'OK' if not inst_len_errors else f'FAIL ({len(inst_len_errors)})'}\n"
        )
        out.write(
            f"- `type=constant` vs inst bits checks: {'OK' if not constant_mismatch else f'FAIL ({len(constant_mismatch)})'}\n"
        )
        out.write(
            "\n- opcode-like 字段（`constant@start=0,length=12`）解释：\n"
            "  - 大多数指令都有一个位于 bit[0..11] 的常量段，看起来像“主 opcode”。\n"
            "  - 少数指令缺失这个字段（例如 NOP / BMOV 相关），说明它们的编码形式不同。\n"
            "  - 另外：顶层 key 的数字前缀（例如 `551.`）并不保证等于该 12-bit 常量；它更像是这个数据集内部的编号/族标识。\n"
        )
        out.write(
            f"- opcode-like 字段（`constant@start=0,length=12`）: {len(data) - len(opcode12_missing)}/{len(data)} 有该字段\n"
        )
        if opcode12_missing:
            out.write(f"  - missing examples: {opcode12_missing[:10]}\n")

        # ===== type options =====
        out.write("\n## `type` 包含哪些选项\n\n")
        out.write(
            "- 下面列出的 `type` 是 `ranges.ranges` 里字段的分类。你可以把它理解为“这个 bitfield 在语义上表示什么”。\n\n"
        )
        out.write(f"- unique `type` values: {len(type_counts)}\n")
        for t, c in type_counts.most_common():
            out.write(f"- `{t}`: {c}\n")

        out.write("\n## flags / operand_flags 的 name 取值（摘要）\n\n")
        out.write(
            "- `type=flag`：指令级的 1-bit 开关（通常对应 disasm 里出现/消失一个 token）。\n"
            "- `type=operand_flag`：操作数级的 1-bit 开关（通常对应某个 operand 的一元变换，如取反/取负/取绝对值）。\n\n"
        )
        out.write(f"- `type=flag` unique names: {len(flag_name_counts)}\n")
        out.write(f"- `type=operand_flag` unique names: {len(operand_flag_name_counts)}\n")
        out.write(f"- `type=flag` top names: {flag_name_counts.most_common(25)}\n")
        out.write(f"- `type=operand_flag` names: {operand_flag_name_counts.most_common()}\n")

        out.write("\n## modifiers / operand_modifiers 的结构（摘要）\n\n")
        out.write(
            "- 这两块用于解释“枚举型字段”如何映射到 disasm 里的修饰符文本。\n"
            "- 建议记住一个简单规则：\n"
            "  - `type=modifier` 的第 0 个字段，对应 `modifiers[0]`；第 1 个字段对应 `modifiers[1]` ……（按字段出现顺序）。\n"
            "  - `type=operand_modifier` 则按 `operand_index` 去 `operand_modifiers[str(operand_index)]` 查表。\n\n"
        )
        out.write(
            "- `modifiers`：list[table]，其中 table 是 `[[value:int, text:str], ...]`；每条指令里 `type=modifier` 的 bitfield 数量 == `len(modifiers)`（按出现顺序一一对应）。\n"
        )
        out.write(f"- (modifier_fields, modifiers_tables) 分布：{modifier_tables_stats.most_common(10)}\n")
        out.write(
            f"- modifiers 选项文本：single-token={modifier_table_option_single_token}, multi-token(含'.')={modifier_table_option_multi_token}, empty={modifier_table_option_empty}\n"
        )
        out.write(
            "- `operand_modifiers`：dict[str(operand_index) -> table]；并且 `type=operand_modifier` 的 operand_index 集合与 dict key 完全一致。\n"
        )
        out.write(
            f"- operand_modifiers 选项文本：nonempty={operand_modifier_table_option_nonempty}, empty={operand_modifier_table_option_empty}\n"
        )

        # ===== type 字段含义（基于统计/约束推断） =====
        out.write("\n## 各 `type` 的字段约束与含义（推断）\n\n")
        out.write(
            "- 这一节试图回答“每种 `type` 究竟代表什么？”以及“要看懂字段之间的关系，该怎么做？”。\n"
            "- 下面两条是阅读后续内容的基础：\n"
            "  - `start/length`：该字段在 128-bit 指令里的 bit 位置与宽度（start 从 LSB 开始计数）。\n"
            "  - `ranges.ranges`：对每条指令都是一个 0..127 的完整分区，因此它就是该指令的完整 bit-layout。\n\n"
        )
        out.write("\n### 字段约束（哪些字段会非空）\n\n")
        for t in sorted(type_counts):
            c = type_counts[t]
            nn = type_nonnull[t]
            out.write(
                f"- `{t}` ({c}): "
                + ", ".join(
                    f"{f}={nn.get('non_null_' + f, 0)}/{c}"
                    for f in ["operand_index", "group_id", "name", "constant"]
                )
                + "\n"
            )

        out.write("\n### 语义总结（按 `type`）\n\n")
        out.write(
            "- `constant`：固定比特段；`constant` 给出该段的数值（与 `ranges.inst` 对应）。\n"
            "  - 常见用法：opcode、子操作选择、保留位/填充位。\n"
        )
        out.write(
            "- `operand`：操作数的编码比特段；`operand_index` 对应“展开后的 operand atom 索引”（由 `parsed.operands` 递归展开 `sub_operands` 得到）。\n"
            "  - 同一个 operand 有时会分成多个不连续 bit 段（脚本在逐指令摘要里会把 segments 合并展示）。\n"
        )
        out.write(
            "- `modifier`：可枚举的“指令修饰符”编码段；值在 `modifiers` 表里映射为形如 `XXX.` 的文本。\n"
            "  - 这些文本会变成 disasm 里的 `OP.MOD1.MOD2...` 形式；且一个选项文本可能自带多个 token（如 `F16x2.RN.`）。\n"
        )
        out.write(
            "  - 注意：`modifier` 与 `modifiers` 的匹配方式是“按 bitfield 出现顺序”一一对应；并且一个选项文本可能包含多个 token（如 `F16x2.RN.`）。\n"
        )
        out.write(
            "- `flag`：1-bit 指令级布尔开关；`name` 是开关名（如 `FTZ`、`SAT`）。\n"
            "  - `name` 的语义需要结合 ISA/微架构文档才能完全解释；本报告主要说明它们如何出现在编码里。\n"
        )
        out.write(
            "- `operand_modifier`：可枚举的“操作数修饰符”编码段；查 `operand_modifiers[str(operand_index)]`。\n"
        )
        out.write(
            "- `operand_flag`：1-bit 操作数级布尔开关；典型 name 包括 `cNEG/cABS/cNOT/cINV` 等。\n"
        )
        out.write(
            "- `predicate`：谓词寄存器选择（4-bit）；与 `parsed.predicate`（如 `@P0`）相关。\n"
        )
        out.write(
            "- `stall/y/reuse/r-bar/w-bar/b-mask`：统一的调度/控制字段（通常在所有指令里位置固定，见下节）。\n"
        )

        # ===== 固定位字段（调度/谓词等） =====
        out.write("\n## 固定位字段（调度/控制）\n\n")
        out.write(
            "- 这些字段在数据里表现为：几乎所有指令都包含，并且 `start/length` 完全固定。\n"
            "- 它们更多描述调度/依赖/复用等控制信息，而不是指令本身的“操作数/功能”。\n\n"
        )
        for t in ["predicate", "stall", "y", "r-bar", "w-bar", "b-mask", "reuse"]:
            dist = schedule_starts.get(t, Counter())
            if not dist:
                continue
            common = dist.most_common(5)
            out.write(f"- `{t}` start/len 分布：{common} (unique={len(dist)})\n")

        # ===== operand_interactions =====
        out.write("\n## operand_interactions 的含义与交互（推断）\n\n")
        out.write(
            "- `operand_interactions`（若存在）按寄存器文件分类（`GPR/PRED/UGPR/UPRED`），列出每个 operand_atom 的读写属性：`[operand_index, 'R'|'W'|'RW', n]`。\n"
        )
        out.write("- 其中 `n` 在数据里常见为 1/2/4（例如矩阵/向量指令可能一次读写多个寄存器）。\n")
        out.write(
            "- 这为“每条指令下 operand 的角色（dst/src、读写宽度）”提供了直接信息，可与 `parsed.operands` 的类型一起理解。\n"
        )
        out.write(
            "- 实用建议：如果你要构建 dataflow/寄存器依赖分析，`operand_interactions` 往往比仅看 `parsed.operands` 更直接。\n"
        )

        # ===== 可选：逐指令摘要 =====
        if args.per_instruction:
            out.write("\n## 每条指令的选项与交互摘要\n\n")
            out.write(
                "- 提示：这里只展示 `ref-encoding.json` 提供的“一个样例 inst”（通常各 operand=0），因此：\n"
                "  - `modifier/flag/operand_flag` 的解码结果仅代表该样例 inst 的默认选择。\n"
                "  - 但 bit-layout、枚举表、以及 operand_interactions 的读写关系对理解格式非常有帮助。\n\n"
            )
            pattern = re.compile(args.filter) if args.filter else None
            printed = 0
            for key in sorted(data.keys()):
                if pattern and not pattern.search(key):
                    continue
                summarize_instruction(out, key, data[key], max_table_items=args.max_table_items)
                printed += 1
                if args.limit and printed >= args.limit:
                    out.write(f"\n\n> 已达到 --limit={args.limit}，后续省略。\n")
                    break

    finally:
        if out is not sys.stdout:
            out.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
