#!/usr/bin/env python3
# Usage:
#   python3 isa/encoding_synthesis.v1.py isa/spec.jsonc -o isa/encoding.v1.json

from __future__ import annotations

import argparse
import json
import os
import sys

INSTRUCTION_WIDTH_BITS = 128


def strip_jsonc_comments(text: str) -> str:
    out = []
    i = 0
    in_str = False
    escaped = False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < len(text) and text[i] != "\n":
                    i += 1
                if i < len(text):
                    out.append("\n")
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < len(text) and not (
                    text[i] == "*" and text[i + 1] == "/"
                ):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_trailing_commas(text: str) -> str:
    out = []
    i = 0
    in_str = False
    escaped = False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "]}":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def load_jsonc(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    raw = strip_jsonc_comments(raw)
    raw = strip_trailing_commas(raw)
    return json.loads(raw)


def bits_needed(count: int) -> int:
    if count <= 1:
        return 0
    return (count - 1).bit_length()


def enum_bits(enum_def) -> int:
    if isinstance(enum_def, list):
        return bits_needed(len(enum_def))
    if isinstance(enum_def, dict):
        if not enum_def:
            return 0
        max_val = max(enum_def.values())
        return bits_needed(max_val + 1)
    raise ValueError("enum must be list or dict")


def modifier_bits(mod_def: dict) -> int:
    if "bits" in mod_def and mod_def["bits"] is not None:
        return mod_def["bits"]
    return enum_bits(mod_def.get("enum"))


def update_max_count(counts: list[int], depth: int, count: int) -> None:
    if depth >= len(counts):
        counts.extend([0] * (depth + 1 - len(counts)))
    if count > counts[depth]:
        counts[depth] = count


def collect_form_counts(instructions: dict) -> list[int]:
    counts: list[int] = []
    for inst in instructions.values():
        forms = inst.get("forms", [])
        update_max_count(counts, 0, len(forms))
        for form in forms:
            collect_form_counts_rec(form, 1, counts)
    return counts


def collect_form_counts_rec(form: dict, depth: int, counts: list[int]) -> None:
    child_forms = form.get("forms")
    if not child_forms:
        return
    update_max_count(counts, depth, len(child_forms))
    for child in child_forms:
        collect_form_counts_rec(child, depth + 1, counts)


def get_operand_bits(operand: dict, operand_width_bits: dict) -> int:
    kind = operand.get("kind")
    if kind not in operand_width_bits:
        raise ValueError(f"unknown operand kind '{kind}'")
    return operand_width_bits[kind]


def get_modifier_bits(name: str, mod_defs: dict) -> int:
    if name not in mod_defs:
        raise ValueError(f"unknown modifier '{name}'")
    return modifier_bits(mod_defs[name])


def get_flag_bits(name: str, flag_defs: dict) -> int:
    if name not in flag_defs:
        raise ValueError(f"unknown operand flag '{name}'")
    return modifier_bits(flag_defs[name])


def build_ranges(
    inst_opcode: int,
    form_indices: list[int],
    bits_inst: int,
    bits_form: list[int],
    operands: list[dict],
    modifiers: list[str],
    operand_width_bits: dict,
    flag_defs: dict,
    mod_defs: dict,
) -> list[dict]:
    ranges: list[dict] = []
    cursor = 0

    def add_range(
        rtype: str,
        length: int,
        name=None,
        constant=None,
        oprnd_idx=None,
    ) -> None:
        nonlocal cursor
        if length == 0:
            return
        ranges.append(
            {
                "type": rtype,
                "start": cursor,
                "length": length,
                "name": name,
                "constant": constant,
                "oprnd_idx": oprnd_idx,
            }
        )
        cursor += length

    if bits_inst:
        add_range("constant", bits_inst, constant=inst_opcode)

    for depth, bits in enumerate(bits_form):
        if not bits:
            continue
        value = form_indices[depth] if depth < len(form_indices) else 0
        add_range("constant", bits, constant=value)

    for operand in operands:
        width = get_operand_bits(operand, operand_width_bits)
        add_range("operand", width, name=operand.get("name"))

    for operand in operands:
        flags = operand.get("oprnd_flag", [])
        for flag in flags:
            width = get_flag_bits(flag, flag_defs)
            add_range("oprnd_flag", width, name=flag, oprnd_idx=operand.get("name"))

    for modifier in modifiers:
        width = get_modifier_bits(modifier, mod_defs)
        add_range("modifier", width, name=modifier)

    if cursor > INSTRUCTION_WIDTH_BITS:
        raise ValueError(
            f"encoding exceeds {INSTRUCTION_WIDTH_BITS} bits: {cursor} bits"
        )

    if cursor < INSTRUCTION_WIDTH_BITS:
        add_range("reserved", INSTRUCTION_WIDTH_BITS - cursor)

    return ranges


def synthesize_encodings(spec: dict) -> dict:
    instructions = spec["instructions"]
    operand_width_bits = spec["operand_width_bits"]
    flag_defs = spec["global_oprnd_flag_defs"]
    global_mod_defs = spec["global_modifier_defs"]

    inst_names = list(instructions.keys())
    inst_count = len(inst_names)

    form_counts = collect_form_counts(instructions)
    form_bits = [bits_needed(n) for n in form_counts]
    bits_inst = bits_needed(inst_count)

    encodings: dict = {}

    for inst_idx, inst_name in enumerate(inst_names):
        inst = instructions[inst_name]
        inst_mod_defs = dict(global_mod_defs)
        inst_mod_defs.update(inst.get("local_modifier_defs", {}))

        inst_modifiers = list(inst.get("inst_modifiers", []))
        inst_fixed_mods = list(inst.get("fixed_modifiers", []))
        forms = inst.get("forms", [])

        def walk_forms(
            forms_list: list,
            form_path: list[str],
            form_indices: list[int],
            operands: list[dict],
            modifiers: list[str],
            mod_defs: dict,
            parent_fixed_mods: list[str],
        ) -> None:
            for idx, form in enumerate(forms_list):
                new_form_path = form_path + [form.get("key")]
                new_form_indices = form_indices + [idx]

                new_operands = operands + list(form.get("operands", []))

                new_mod_defs = mod_defs
                local_defs = form.get("local_modifier_defs")
                if local_defs:
                    new_mod_defs = dict(mod_defs)
                    new_mod_defs.update(local_defs)

                # Fixed modifiers defined by the parent level come before this form's inst_modifiers.
                new_modifiers = modifiers + list(parent_fixed_mods)
                new_modifiers += list(form.get("inst_modifiers", []))

                child_fixed_mods = list(form.get("fixed_modifiers", []))
                child_forms = form.get("forms")
                if child_forms:
                    walk_forms(
                        child_forms,
                        new_form_path,
                        new_form_indices,
                        new_operands,
                        new_modifiers,
                        new_mod_defs,
                        child_fixed_mods,
                    )
                else:
                    ranges = build_ranges(
                        inst_idx,
                        new_form_indices,
                        bits_inst,
                        form_bits,
                        new_operands,
                        new_modifiers,
                        operand_width_bits,
                        flag_defs,
                        new_mod_defs,
                    )
                    key = inst_name + "." + ".".join(new_form_path)
                    encodings[key] = {
                        "instruction": inst_name,
                        "form_path": new_form_path,
                        "ranges": ranges,
                    }

        walk_forms(
            forms,
            [],
            [],
            [],
            inst_modifiers,
            inst_mod_defs,
            inst_fixed_mods,
        )

    meta = {
        "encoding_version": 1,
        "statistics": {
            "instruction_count": inst_count,
            "instruction_bits": bits_inst,
            "form_level_counts": form_counts,
            "form_level_bits": form_bits,
        },
    }

    return {"meta": meta, "encodings": encodings}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize instruction encodings from spec.jsonc (version 1)."
    )
    parser.add_argument("spec_path", help="Path to spec.jsonc")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = args.spec_path
    output_path = args.output

    spec = load_jsonc(spec_path)
    output = synthesize_encodings(spec)

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
