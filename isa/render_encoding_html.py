#!/usr/bin/env python3
# Usage:
#   python3 isa/render_encoding_html.py isa/encoding.v1.json -o isa/encoding.v1.html
# Notes:
#   - index.html is written to the output root.
#   - per-instruction pages are written under <outdir>/instructions.

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

CSS = """
:root {
  --bg: #f7f4ef;
  --card: #ffffff;
  --text: #1e1e1e;
  --muted: #5a5a5a;
  --border: #d4cec4;
  --const: #cfd4da;
  --reserved: #f0f1f3;
  --modifier: #f6d365;
  --gap: #ececec;
  --link: #0b7285;
  --cell: 18px;
}
* { box-sizing: border-box; }
body {
  margin: 24px;
  background: var(--bg);
  color: var(--text);
  font-family: "IBM Plex Sans", "DejaVu Sans", sans-serif;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
header {
  display: flex;
  align-items: baseline;
  gap: 16px;
  flex-wrap: wrap;
}
code, .mono {
  font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
}
.summary {
  margin: 12px 0 20px 0;
  color: var(--muted);
}
.inst-list {
  columns: 3 240px;
  column-gap: 24px;
  padding-left: 18px;
}
.inst-list li { margin: 4px 0; }
.encoding {
  margin: 20px 0;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}
.encoding h2 {
  margin: 0 0 8px 0;
  font-size: 18px;
}
.encoding-meta {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 10px;
}
.bitgrid-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #faf9f7;
  padding: 6px;
}
.bitgrid {
  border-collapse: collapse;
  table-layout: fixed;
  width: auto;
  margin: 6px 0;
}
.bitgrid th,
.bitgrid td {
  border: 1px solid var(--border);
  width: var(--cell);
  min-width: var(--cell);
  height: 22px;
  text-align: center;
  font-size: 10px;
  padding: 0;
  font-family: "Courier Prime", "Courier New", "Nimbus Mono L",
    "Liberation Mono", monospace;
}
.bitgrid th.scale {
  background: #efe9e1;
  font-weight: 600;
}
.bitcell {
  font-size: 11px;
  line-height: 1.1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bitcell.flag { }
.vlabel {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  display: inline-block;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 10px 0;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.swatch {
  width: 12px;
  height: 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
}
.ranges {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 12px;
}
.ranges th, .ranges td {
  border: 1px solid var(--border);
  padding: 4px 6px;
  text-align: left;
}
.ranges th {
  background: #efe9e1;
  font-weight: 600;
}
.note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 6px;
}
@media (max-width: 900px) {
  .inst-list { columns: 2 200px; }
}
@media (max-width: 600px) {
  .inst-list { columns: 1 200px; }
  body { margin: 16px; }
}
"""

PASTEL_PALETTE = [
    "#D7EAF8",
    "#F8D4C1",
    "#E5F1C8",
    "#F6D7EC",
    "#DCD9F6",
    "#FCE6B8",
    "#D2F0E6",
    "#F9D7D7",
    "#D9F2F2",
    "#F5E0C8",
    "#E3F2D6",
    "#EADCF6",
    "#D8E7FA",
    "#F3E3EE",
    "#E8F5D2",
    "#D6EDF7",
]
CONST_PALETTE = ["#E3E7EC", "#D6DCE3", "#CCD2DA", "#EDF0F4"]
RESERVED_PALETTE = ["#F1F2F4", "#E6E8EC", "#DDE1E6", "#F6F7F9"]
GAP_PALETTE = ["#ECECEC", "#E2E2E2", "#D7D7D7"]
DEFAULT_PALETTE = ["#D0D0D0", "#C4C4C4", "#B8B8B8"]


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def allocate_filenames(names: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: dict[str, str] = {}
    for name in names:
        base = safe_filename(name) or "inst"
        candidate = base
        idx = 1
        while candidate in used and used[candidate] != name:
            idx += 1
            candidate = f"{base}_{idx}"
        used[candidate] = name
        mapping[name] = candidate
    return mapping


def next_palette_color(
    palette: list[str], index: int, avoid: str | None
) -> tuple[str, int]:
    if not palette:
        palette = DEFAULT_PALETTE
    color = palette[index % len(palette)]
    if avoid is not None and color == avoid and len(palette) > 1:
        index += 1
        color = palette[index % len(palette)]
    return color, index + 1


def assign_range_colors(normalized: list[dict]) -> list[str]:
    colors: list[str] = []
    prev: str | None = None
    main_idx = 0
    const_idx = 0
    reserved_idx = 0
    gap_idx = 0
    for r in normalized:
        rtype = r.get("type")
        if rtype == "constant":
            color, const_idx = next_palette_color(CONST_PALETTE, const_idx, prev)
        elif rtype == "reserved":
            color, reserved_idx = next_palette_color(
                RESERVED_PALETTE, reserved_idx, prev
            )
        elif rtype == "gap":
            color, gap_idx = next_palette_color(GAP_PALETTE, gap_idx, prev)
        else:
            color, main_idx = next_palette_color(PASTEL_PALETTE, main_idx, prev)
        colors.append(color)
        prev = color
    return colors


def format_constant(value: int | None, length: int) -> str:
    if value is None:
        return ""
    hex_width = max(1, (length + 3) // 4)
    return f"{value} (0x{value:0{hex_width}X})"


def range_label(r: dict) -> str:
    rtype = r.get("type")
    name = r.get("name")
    if rtype == "operand":
        return name or "operand"
    if rtype == "oprnd_flag":
        return name or "flag"
    if rtype == "modifier":
        return name or "modifier"
    if rtype == "constant":
        const = r.get("constant")
        if const is None:
            return "const"
        if r.get("length", 0) <= 6:
            return str(const)
        return "const"
    if rtype == "reserved":
        return "reserved"
    if rtype == "gap":
        return "gap"
    return rtype or "range"


def range_title(r: dict) -> str:
    rtype = r.get("type")
    name = r.get("name")
    start = r.get("start", 0)
    length = r.get("length", 0)
    end = start + length - 1 if length else start
    bits = f"[{end}:{start}]"
    parts = [rtype or "range", bits, f"len={length}"]
    if name:
        parts.append(f"name={name}")
    if rtype == "oprnd_flag":
        oprnd = r.get("oprnd_idx")
        if oprnd:
            parts.append(f"oprnd={oprnd}")
    if rtype == "constant":
        parts.append(f"const={format_constant(r.get('constant'), length)}")
    return " ".join(parts)


def normalize_ranges(ranges: list[dict], bit_width: int) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    out: list[dict] = []
    cursor = 0
    sorted_ranges = sorted(ranges, key=lambda r: r.get("start", 0))
    for r in sorted_ranges:
        start = r.get("start", 0)
        length = r.get("length", 0)
        if start > cursor:
            out.append(
                {
                    "type": "gap",
                    "start": cursor,
                    "length": start - cursor,
                    "name": None,
                    "constant": None,
                    "oprnd_idx": None,
                }
            )
        elif start < cursor:
            warnings.append(f"overlap at bit {start}")
        out.append(r)
        cursor = max(cursor, start + length)
    if cursor < bit_width:
        out.append(
            {
                "type": "gap",
                "start": cursor,
                "length": bit_width - cursor,
                "name": None,
                "constant": None,
                "oprnd_idx": None,
            }
        )
    return out, warnings


def build_bit_map_from_normalized(
    normalized: list[dict], bit_width: int
) -> list[dict]:
    bit_map: list[dict] = [{"type": "gap"} for _ in range(bit_width)]
    for idx, r in enumerate(normalized):
        start = r.get("start", 0)
        length = r.get("length", 0)
        const = r.get("constant")
        for offset in range(length):
            bit = start + offset
            if bit < 0 or bit >= bit_width:
                continue
            bit_map[bit] = {
                "range_id": idx,
                "type": r.get("type"),
                "name": r.get("name"),
                "oprnd_idx": r.get("oprnd_idx"),
                "constant": const,
                "bit_value": ((const or 0) >> offset) & 1 if const is not None else None,
            }
    return bit_map


def build_bit_map(
    ranges: list[dict], bit_width: int
) -> tuple[list[dict], list[dict], list[str]]:
    normalized, warnings = normalize_ranges(ranges, bit_width)
    bit_map = build_bit_map_from_normalized(normalized, bit_width)
    return bit_map, normalized, warnings


def render_bitgrid(
    ranges: list[dict], bit_width: int, row_bits: int = 64
) -> tuple[str, list[str], list[dict], list[str]]:
    if bit_width <= 0:
        return "<div class='note'>no bit ranges</div>", [], [], []
    bit_map, normalized, warnings = build_bit_map(ranges, bit_width)
    range_colors = assign_range_colors(normalized)
    parts = ["<div class=\"bitgrid-wrap\">"]
    bit = bit_width - 1
    while bit >= 0:
        high = bit
        low = max(0, high - row_bits + 1)
        row_len = high - low + 1
        colgroup = "<colgroup>" + "".join("<col>" for _ in range(row_len)) + "</colgroup>"
        parts.append("<table class=\"bitgrid\">" + colgroup)
        scale_cells = "".join(
            f"<th class=\"scale\">{i}</th>" for i in range(high, low - 1, -1)
        )
        parts.append(f"<tr>{scale_cells}</tr>")
        row_cells: list[str] = []
        i = high
        while i >= low:
            info = bit_map[i]
            rtype = info.get("type")
            if rtype == "constant":
                label = str(info.get("bit_value", 0))
                range_id = info.get("range_id")
                title = range_title(normalized[range_id])
                color = range_colors[range_id]
                row_cells.append(
                    "<td class=\"bitcell\" style=\"background-color: "
                    + color
                    + ";\" title=\""
                    + html.escape(title)
                    + "\">"
                    + label
                    + "</td>"
                )
                i -= 1
                continue
            range_id = info.get("range_id")
            span = 1
            while (
                i - span >= low
                and bit_map[i - span].get("range_id") == range_id
                and bit_map[i - span].get("type") != "constant"
            ):
                span += 1
            r = normalized[range_id] if range_id is not None else {"type": "gap"}
            label = range_label(r)
            label_html = html.escape(label)
            if span == 1 and len(label) > 3:
                label_html = f"<span class=\"vlabel\">{label_html}</span>"
            color = range_colors[range_id] if range_id is not None else DEFAULT_PALETTE[0]
            classes = ["bitcell", f"type-{r.get('type', 'range')}"]
            if span > 1:
                classes.append("span")
            if r.get("type") == "oprnd_flag":
                classes.append("flag")
            title = html.escape(range_title(r))
            style = f"background-color: {color};"
            row_cells.append(
                f"<td class=\"{' '.join(classes)}\" colspan=\"{span}\" "
                f"style=\"{style}\" title=\"{title}\">{label_html}</td>"
            )
            i -= span
        parts.append("<tr>" + "".join(row_cells) + "</tr>")
        parts.append("</table>")
        bit = low - 1
    parts.append("</div>")
    return "".join(parts), warnings, normalized, range_colors


def render_legend(normalized: list[dict], range_colors: list[str]) -> str:
    items = []
    seen = set()
    for idx in range(len(normalized) - 1, -1, -1):
        r = normalized[idx]
        if r.get("type") == "gap":
            continue
        label = range_label(r)
        color = range_colors[idx]
        key = f"{label}|{color}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            f"<span class=\"legend-item\"><span class=\"swatch\" style=\"background:{color}\"></span>{html.escape(label)}</span>"
        )
    if not items:
        return ""
    return "<div class=\"legend\">" + "".join(items) + "</div>"


def render_ranges_table(ranges: list[dict]) -> str:
    rows = []
    for r in sorted(ranges, key=lambda r: r.get("start", 0)):
        start = r.get("start", 0)
        length = r.get("length", 0)
        end = start + length - 1 if length else start
        rtype = r.get("type")
        name = r.get("name") or ""
        const = format_constant(r.get("constant"), length)
        oprnd = r.get("oprnd_idx") or ""
        rows.append(
            "<tr>"
            f"<td class=\"mono\">[{end}:{start}]</td>"
            f"<td class=\"mono\">{length}</td>"
            f"<td>{html.escape(rtype or '')}</td>"
            f"<td>{html.escape(name)}</td>"
            f"<td class=\"mono\">{html.escape(const)}</td>"
            f"<td>{html.escape(oprnd)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"6\">(no ranges)</td></tr>")
    header = (
        "<tr>"
        "<th>bits</th>"
        "<th>len</th>"
        "<th>type</th>"
        "<th>name</th>"
        "<th>constant</th>"
        "<th>oprnd_idx</th>"
        "</tr>"
    )
    return "<table class=\"ranges\">" + header + "".join(rows) + "</table>"


def html_page(title: str, body: str) -> str:
    safe_title = html.escape(title)
    return (
        "<!doctype html><html><head>"
        "<meta charset=\"utf-8\">"
        f"<title>{safe_title}</title>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )


def render_instruction_page(
    instruction: str,
    enc_items: list[tuple[str, dict]],
    index_href: str,
) -> str:
    parts = [
        "<header>",
        f"<h1>{html.escape(instruction)}</h1>",
        f"<a href=\"{html.escape(index_href)}\">index</a>",
        "</header>",
        "<div class=\"summary\">",
        f"{len(enc_items)} forms; bit 0 is LSB (rightmost cell); each row shows up to 64 bits.",
        "</div>",
    ]
    for enc_key, enc in enc_items:
        form_path = enc.get("form_path") or []
        form_str = ".".join(str(x) for x in form_path) or "(none)"
        ranges = enc.get("ranges", [])
        bit_width = max(
            (r.get("start", 0) + r.get("length", 0) for r in ranges),
            default=0,
        )
        bitgrid_html, warnings, normalized, range_colors = render_bitgrid(
            ranges, bit_width, row_bits=64
        )
        legend_html = render_legend(normalized, range_colors)
        warn_html = ""
        if warnings:
            warn_html = "<div class=\"note\">warnings: " + ", ".join(warnings) + "</div>"
        parts.append("<section class=\"encoding\">")
        parts.append(f"<h2>{html.escape(enc_key)}</h2>")
        parts.append(
            "<div class=\"encoding-meta\">"
            f"form_path: <span class=\"mono\">{html.escape(form_str)}</span>"
            f" | width: {bit_width} bits"
            "</div>"
        )
        parts.append(bitgrid_html)
        parts.append(legend_html)
        parts.append(warn_html)
        parts.append(render_ranges_table(ranges))
        parts.append("</section>")
    return html_page(instruction, "".join(parts))


def render_index_page(
    source_path: str,
    meta: dict,
    instruction_groups: dict[str, list[tuple[str, dict]]],
    name_to_file: dict[str, str],
    inst_subdir: str,
) -> str:
    stats = meta.get("statistics") or {}
    summary_items = [
        f"source: {html.escape(source_path)}",
        f"encodings: {sum(len(v) for v in instruction_groups.values())}",
        f"instructions: {len(instruction_groups)}",
    ]
    if meta.get("encoding_version") is not None:
        summary_items.append(f"version: {meta.get('encoding_version')}")
    if stats:
        stat_bits = stats.get("instruction_bits")
        form_bits = stats.get("form_level_bits")
        if stat_bits is not None:
            summary_items.append(f"opcode bits: inst={stat_bits}")
        if form_bits:
            summary_items.append(f"form bits: {form_bits}")
    list_items = []
    for inst in sorted(instruction_groups):
        filename = f"{inst_subdir}/{name_to_file[inst]}.html"
        count = len(instruction_groups[inst])
        list_items.append(
            f"<li><a href=\"{html.escape(filename)}\">{html.escape(inst)}</a>"
            f" <span class=\"mono\">({count})</span></li>"
        )
    body = (
        "<header><h1>ISA Encoding Index</h1></header>"
        "<div class=\"summary\">"
        + " | ".join(summary_items)
        + "</div>"
        "<ul class=\"inst-list\">"
        + "".join(list_items)
        + "</ul>"
        "<div class=\"note\">Counts in parentheses are number of forms per instruction.</div>"
    )
    return html_page("ISA Encoding Index", body)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render encoding JSON into per-instruction HTML pages."
    )
    parser.add_argument("encoding_json", help="Path to encoding.v1.json")
    parser.add_argument(
        "-o",
        "--outdir",
        required=True,
        help="Output directory for HTML files",
    )
    args = parser.parse_args()

    encoding_path = Path(args.encoding_json)
    if not encoding_path.exists():
        print(f"error: file not found: {encoding_path}", file=sys.stderr)
        return 1

    data = load_json(str(encoding_path))
    encodings = data.get("encodings") or {}
    if not isinstance(encodings, dict):
        print("error: encodings must be an object", file=sys.stderr)
        return 1

    instruction_groups: dict[str, list[tuple[str, dict]]] = {}
    for enc_key, enc in encodings.items():
        instruction = enc.get("instruction", "")
        instruction_groups.setdefault(instruction, []).append((enc_key, enc))

    name_to_file = allocate_filenames(sorted(instruction_groups))
    outdir = Path(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    inst_subdir = "instructions"
    inst_dir = outdir / inst_subdir
    os.makedirs(inst_dir, exist_ok=True)

    meta = data.get("meta") or {}
    index_html = render_index_page(
        str(encoding_path),
        meta,
        instruction_groups,
        name_to_file,
        inst_subdir,
    )
    (outdir / "index.html").write_text(index_html, encoding="utf-8")

    for instruction, items in instruction_groups.items():
        items_sorted = sorted(items, key=lambda x: x[0])
        page_html = render_instruction_page(
            instruction,
            items_sorted,
            "../index.html",
        )
        filename = name_to_file[instruction] + ".html"
        (inst_dir / filename).write_text(page_html, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
