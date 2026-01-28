#!/usr/bin/env python3
# Usage:
#   python3 isa/count_forms.py isa/spec.jsonc
from __future__ import annotations

import argparse
import sys

from validate_spec_format import load_jsonc


def count_flat_forms(node) -> int:
    if isinstance(node, list):
        return sum(count_flat_forms(item) for item in node)
    if isinstance(node, dict):
        forms = node.get("forms")
        if isinstance(forms, list):
            # Treat nested forms as containers; flatten all sub-forms.
            return count_flat_forms(forms)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Count flattened forms for each instruction in a JSONC spec."
    )
    parser.add_argument("path", help="Path to spec.jsonc")
    args = parser.parse_args()

    try:
        data = load_jsonc(args.path)
    except Exception as exc:
        print(f"failed to parse JSONC: {exc}", file=sys.stderr)
        return 2

    insts = data.get("instructions", {})
    if not isinstance(insts, dict):
        print("invalid spec: 'instructions' is not an object", file=sys.stderr)
        return 2

    counts = []
    for name, spec in insts.items():
        if not isinstance(spec, dict):
            continue
        forms = spec.get("forms", [])
        counts.append((name, count_flat_forms(forms)))

    counts.sort(key=lambda item: (-item[1], item[0]))
    for name, count in counts:
        print(f"{count:4d} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
