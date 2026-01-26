#!/usr/bin/env python3
# Usage:
#   python3 validate_spec_format.py path/to/spec.jsonc
#   e.g. python3 isa/validate_spec_format.py isa/spec.jsonc

from __future__ import annotations

import argparse
import json
import os
import sys


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
                while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
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


def add_error(errors, path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


def path_key(path: str, key: str) -> str:
    return f"{path}.{key}"


def path_index(path: str, idx: int) -> str:
    return f"{path}[{idx}]"


def ensure_dict(value, path: str, errors) -> bool:
    if not isinstance(value, dict):
        add_error(errors, path, "expected object")
        return False
    return True


def ensure_list(value, path: str, errors) -> bool:
    if not isinstance(value, list):
        add_error(errors, path, "expected list")
        return False
    return True


def validate_string_list(value, path: str, errors, unique: bool = False):
    if not ensure_list(value, path, errors):
        return []
    seen = set()
    out = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            add_error(errors, path_index(path, idx), "expected string")
            continue
        if unique and item in seen:
            add_error(errors, path_index(path, idx), f"duplicate value '{item}'")
        seen.add(item)
        out.append(item)
    return out


def validate_semantics(value, path: str, errors) -> None:
    if not ensure_dict(value, path, errors):
        return
    allowed = {"effect", "SASS", "notes"}
    for key in value:
        if key not in allowed:
            add_error(errors, path_key(path, key), "unexpected field")
    if "effect" in value and not isinstance(value["effect"], str):
        add_error(errors, path_key(path, "effect"), "expected string")
    if "SASS" in value:
        sass = value["SASS"]
        if isinstance(sass, str):
            pass
        elif isinstance(sass, list):
            for idx, item in enumerate(sass):
                if not isinstance(item, str):
                    add_error(
                        errors,
                        path_index(path_key(path, "SASS"), idx),
                        "expected string",
                    )
        else:
            add_error(
                errors, path_key(path, "SASS"), "expected string or list of strings"
            )
    if "notes" in value:
        notes = value["notes"]
        if not ensure_list(notes, path_key(path, "notes"), errors):
            return
        for idx, item in enumerate(notes):
            if not isinstance(item, str):
                add_error(
                    errors, path_index(path_key(path, "notes"), idx), "expected string"
                )


def validate_modifier_def(
    value, path: str, errors, allow_can_apply: bool, instruction_names
):
    if not ensure_dict(value, path, errors):
        return None, []
    allowed = {"bits", "enum", "default", "meaning"}
    if allow_can_apply:
        allowed.add("can_apply_to_inst")
    for key in value:
        if key not in allowed:
            add_error(errors, path_key(path, key), "unexpected field")
    if "enum" not in value:
        add_error(errors, path, "missing required field 'enum'")
        return None, []
    bits = value.get("bits")
    if bits is not None and not (is_int(bits) and bits >= 0):
        add_error(errors, path_key(path, "bits"), "expected non-negative integer")
    enum = value.get("enum")
    labels = set()
    if isinstance(enum, list):
        for idx, item in enumerate(enum):
            if not isinstance(item, str):
                add_error(
                    errors, path_index(path_key(path, "enum"), idx), "expected string"
                )
            else:
                labels.add(item)
        if len(labels) != len(enum):
            add_error(errors, path_key(path, "enum"), "duplicate enum labels")
        if bits is not None and len(enum) > (1 << bits):
            add_error(errors, path_key(path, "enum"), "enum size exceeds bits capacity")
    elif isinstance(enum, dict):
        values_seen = set()
        max_value = -1
        for k, v in enum.items():
            if not isinstance(k, str):
                add_error(errors, path_key(path, "enum"), "enum keys must be strings")
                continue
            if not (is_int(v) and v >= 0):
                add_error(
                    errors,
                    path_key(path, "enum"),
                    f"enum value for '{k}' must be non-negative integer",
                )
                continue
            if v in values_seen:
                add_error(errors, path_key(path, "enum"), f"duplicate enum value {v}")
            values_seen.add(v)
            max_value = max(max_value, v)
            labels.add(k)
        if bits is not None and max_value > (1 << bits) - 1:
            add_error(
                errors, path_key(path, "enum"), "enum values exceed bits capacity"
            )
    else:
        add_error(errors, path_key(path, "enum"), "expected list or object")
    if "default" in value:
        default = value["default"]
        if not isinstance(default, str):
            add_error(errors, path_key(path, "default"), "expected string")
        elif default not in labels:
            add_error(errors, path_key(path, "default"), "default not in enum labels")
    if "meaning" in value:
        meaning = value["meaning"]
        if isinstance(meaning, str):
            pass
        elif isinstance(meaning, list):
            for idx, item in enumerate(meaning):
                if not isinstance(item, str):
                    add_error(
                        errors,
                        path_index(path_key(path, "meaning"), idx),
                        "expected string",
                    )
        else:
            add_error(
                errors, path_key(path, "meaning"), "expected string or list of strings"
            )
    pending = []
    if allow_can_apply and "can_apply_to_inst" in value:
        can_apply = value["can_apply_to_inst"]
        can_apply_path = path_key(path, "can_apply_to_inst")
        names = validate_string_list(can_apply, can_apply_path, errors, unique=False)
        if instruction_names is None:
            pending.append((can_apply_path, names))
        else:
            for name in names:
                if name not in instruction_names:
                    add_error(errors, can_apply_path, f"unknown instruction '{name}'")
    return {"labels": labels}, pending


def validate_modifier_defs(
    value,
    path: str,
    errors,
    allow_can_apply: bool,
    instruction_names,
    forbidden_names=None,
):
    if not ensure_dict(value, path, errors):
        return {}, []
    defs = {}
    pending = []
    forbidden = set(forbidden_names or [])
    for name, entry in value.items():
        entry_path = path_key(path, name)
        if name in forbidden:
            add_error(
                errors, entry_path, f"modifier '{name}' conflicts with outer scope"
            )
        info, pend = validate_modifier_def(
            entry, entry_path, errors, allow_can_apply, instruction_names
        )
        if info is not None:
            defs[name] = info
        pending.extend(pend)
    return defs, pending


def resolve_modifier_def(name: str, local_defs, global_defs):
    if name in local_defs:
        return local_defs[name]
    if name in global_defs:
        return global_defs[name]
    return None


def validate_operands(
    value,
    path: str,
    errors,
    canonical_roles,
    operand_width_bits,
    global_oprnd_flags,
    ancestor_names,
):
    if not ensure_list(value, path, errors):
        return set()
    allowed = {"name", "role", "kind", "oprnd_flag"}
    names = set()
    for idx, opr in enumerate(value):
        opr_path = path_index(path, idx)
        if not ensure_dict(opr, opr_path, errors):
            continue
        for key in opr:
            if key not in allowed:
                add_error(errors, path_key(opr_path, key), "unexpected field")
        if "name" not in opr:
            add_error(errors, opr_path, "missing required field 'name'")
        if "role" not in opr:
            add_error(errors, opr_path, "missing required field 'role'")
        if "kind" not in opr:
            add_error(errors, opr_path, "missing required field 'kind'")
        name = opr.get("name")
        if isinstance(name, str):
            if name in names:
                add_error(
                    errors,
                    path_key(opr_path, "name"),
                    f"duplicate operand name '{name}'",
                )
            if name in ancestor_names:
                add_error(
                    errors,
                    path_key(opr_path, "name"),
                    f"name '{name}' shadows ancestor operand",
                )
            names.add(name)
        elif name is not None:
            add_error(errors, path_key(opr_path, "name"), "expected string")
        role = opr.get("role")
        if isinstance(role, str):
            if role not in canonical_roles:
                add_error(errors, path_key(opr_path, "role"), f"unknown role '{role}'")
        elif role is not None:
            add_error(errors, path_key(opr_path, "role"), "expected string")
        kind = opr.get("kind")
        if isinstance(kind, str):
            if kind not in operand_width_bits:
                add_error(errors, path_key(opr_path, "kind"), f"unknown kind '{kind}'")
        elif kind is not None:
            add_error(errors, path_key(opr_path, "kind"), "expected string")
        if "oprnd_flag" in opr:
            flags = opr["oprnd_flag"]
            flag_path = path_key(opr_path, "oprnd_flag")
            if ensure_list(flags, flag_path, errors):
                for fidx, flag in enumerate(flags):
                    if not isinstance(flag, str):
                        add_error(
                            errors, path_index(flag_path, fidx), "expected string"
                        )
                    elif flag not in global_oprnd_flags:
                        add_error(
                            errors,
                            path_index(flag_path, fidx),
                            f"unknown operand flag '{flag}'",
                        )
    return names


def validate_fixed_modi_vals(value, path: str, errors, required_defs):
    if not ensure_dict(value, path, errors):
        return
    expected = set(required_defs.keys())
    actual = set(value.keys())
    if actual != expected:
        add_error(errors, path, "keys must match fixed_modifiers exactly")
    for name, label in value.items():
        if name not in required_defs:
            continue
        if not isinstance(label, str):
            add_error(errors, path_key(path, name), "expected string enum label")
            continue
        if label not in required_defs[name]["labels"]:
            add_error(errors, path_key(path, name), f"invalid enum label '{label}'")


def validate_forms_list(
    forms,
    path: str,
    errors,
    global_mods,
    instr_local_mods,
    instruction_names,
    global_oprnd_flags,
    canonical_roles,
    operand_width_bits,
    forbidden_mods,
    required_fixed_defs,
    ancestor_operands,
    ancestor_local_mods,
):
    if not ensure_dict(forms, path, errors):
        return
    for form_key, form in forms.items():
        form_path = path_key(path, form_key)
        if not ensure_dict(form, form_path, errors):
            continue
        allowed = {
            "semantics",
            "fixed_modi_vals",
            "local_modifier_defs",
            "inst_modifiers",
            "fixed_modifiers",
            "operands",
            "forms",
        }
        for key in form:
            if key not in allowed:
                add_error(errors, path_key(form_path, key), "unexpected field")
        if "semantics" in form:
            validate_semantics(
                form["semantics"], path_key(form_path, "semantics"), errors
            )
        form_local_defs = {}
        if "local_modifier_defs" in form:
            form_local_defs, _ = validate_modifier_defs(
                form["local_modifier_defs"],
                path_key(form_path, "local_modifier_defs"),
                errors,
                allow_can_apply=True,
                instruction_names=instruction_names,
                forbidden_names=set(global_mods.keys()) | ancestor_local_mods,
            )
        inst_mods = []
        if "inst_modifiers" in form:
            inst_mods = validate_string_list(
                form["inst_modifiers"],
                path_key(form_path, "inst_modifiers"),
                errors,
                unique=True,
            )
        fixed_mods = []
        if "fixed_modifiers" in form:
            fixed_mods = validate_string_list(
                form["fixed_modifiers"],
                path_key(form_path, "fixed_modifiers"),
                errors,
                unique=True,
            )
        inst_mods_set = set(inst_mods)
        fixed_mods_set = set(fixed_mods)
        overlap = inst_mods_set & fixed_mods_set
        if overlap:
            add_error(
                errors,
                form_path,
                f"inst_modifiers and fixed_modifiers overlap: {sorted(overlap)}",
            )
        for name in inst_mods:
            if name in forbidden_mods:
                add_error(
                    errors,
                    path_key(form_path, "inst_modifiers"),
                    f"modifier '{name}' is forbidden by parent",
                )
            if (
                name not in global_mods
                and name not in instr_local_mods
                and name not in form_local_defs
            ):
                add_error(
                    errors,
                    path_key(form_path, "inst_modifiers"),
                    f"unknown modifier '{name}'",
                )
        for name in fixed_mods:
            if name in forbidden_mods:
                add_error(
                    errors,
                    path_key(form_path, "fixed_modifiers"),
                    f"modifier '{name}' is forbidden by parent",
                )
            if name not in global_mods and name not in instr_local_mods:
                add_error(
                    errors,
                    path_key(form_path, "fixed_modifiers"),
                    f"unknown modifier '{name}'",
                )
        if fixed_mods and "forms" not in form:
            add_error(errors, form_path, "fixed_modifiers requires child forms object")
        if required_fixed_defs:
            if "fixed_modi_vals" not in form:
                add_error(errors, form_path, "missing required field 'fixed_modi_vals'")
            else:
                validate_fixed_modi_vals(
                    form["fixed_modi_vals"],
                    path_key(form_path, "fixed_modi_vals"),
                    errors,
                    required_fixed_defs,
                )
        else:
            if "fixed_modi_vals" in form:
                add_error(
                    errors,
                    form_path,
                    "fixed_modi_vals present without fixed_modifiers in parent",
                )
        current_operands = set()
        if "operands" in form:
            current_operands = validate_operands(
                form["operands"],
                path_key(form_path, "operands"),
                errors,
                canonical_roles,
                operand_width_bits,
                global_oprnd_flags,
                ancestor_operands,
            )
        new_ancestor_operands = set(ancestor_operands) | current_operands
        new_ancestor_local_mods = set(ancestor_local_mods) | set(form_local_defs.keys())
        child_required_defs = {}
        if fixed_mods:
            for name in fixed_mods:
                resolved = resolve_modifier_def(name, instr_local_mods, global_mods)
                if resolved is not None:
                    child_required_defs[name] = resolved
        if "forms" in form:
            validate_forms_list(
                form["forms"],
                path_key(form_path, "forms"),
                errors,
                global_mods,
                instr_local_mods,
                instruction_names,
                global_oprnd_flags,
                canonical_roles,
                operand_width_bits,
                forbidden_mods | inst_mods_set | fixed_mods_set,
                child_required_defs,
                new_ancestor_operands,
                new_ancestor_local_mods,
            )


def validate_instruction(
    name: str,
    value,
    path: str,
    errors,
    global_mods,
    global_oprnd_flags,
    canonical_roles,
    operand_width_bits,
    instruction_names,
):
    if not ensure_dict(value, path, errors):
        return
    allowed = {
        "semantics",
        "local_modifier_defs",
        "inst_modifiers",
        "fixed_modifiers",
        "forms",
    }
    for key in value:
        if key not in allowed:
            add_error(errors, path_key(path, key), "unexpected field")
    if "forms" not in value:
        add_error(errors, path, "missing required field 'forms'")
    if "semantics" in value:
        validate_semantics(value["semantics"], path_key(path, "semantics"), errors)
    instr_local_defs = {}
    if "local_modifier_defs" in value:
        instr_local_defs, _ = validate_modifier_defs(
            value["local_modifier_defs"],
            path_key(path, "local_modifier_defs"),
            errors,
            allow_can_apply=True,
            instruction_names=instruction_names,
            forbidden_names=global_mods.keys(),
        )
    inst_mods = []
    if "inst_modifiers" in value:
        inst_mods = validate_string_list(
            value["inst_modifiers"],
            path_key(path, "inst_modifiers"),
            errors,
            unique=True,
        )
    fixed_mods = []
    if "fixed_modifiers" in value:
        fixed_mods = validate_string_list(
            value["fixed_modifiers"],
            path_key(path, "fixed_modifiers"),
            errors,
            unique=True,
        )
    inst_mods_set = set(inst_mods)
    fixed_mods_set = set(fixed_mods)
    overlap = inst_mods_set & fixed_mods_set
    if overlap:
        add_error(
            errors,
            path,
            f"inst_modifiers and fixed_modifiers overlap: {sorted(overlap)}",
        )
    for name in inst_mods:
        if name not in global_mods and name not in instr_local_defs:
            add_error(
                errors, path_key(path, "inst_modifiers"), f"unknown modifier '{name}'"
            )
    for name in fixed_mods:
        if name not in global_mods and name not in instr_local_defs:
            add_error(
                errors, path_key(path, "fixed_modifiers"), f"unknown modifier '{name}'"
            )
    required_defs = {}
    if fixed_mods:
        for name in fixed_mods:
            resolved = resolve_modifier_def(name, instr_local_defs, global_mods)
            if resolved is not None:
                required_defs[name] = resolved
    if "forms" in value:
        validate_forms_list(
            value["forms"],
            path_key(path, "forms"),
            errors,
            global_mods,
            instr_local_defs,
            instruction_names,
            global_oprnd_flags,
            canonical_roles,
            operand_width_bits,
            inst_mods_set | fixed_mods_set,
            required_defs,
            set(),
            set(instr_local_defs.keys()),
        )


def validate_spec(data):
    errors = []
    path = "root"
    if not ensure_dict(data, path, errors):
        return errors
    required_keys = {
        "gpidl_version",
        "operand_width_bits",
        "canonical_roles",
        "global_oprnd_flag_defs",
        "global_modifier_defs",
        "instructions",
    }
    for key in data:
        if key not in required_keys:
            add_error(errors, path_key(path, key), "unexpected field")
    for key in required_keys:
        if key not in data:
            add_error(errors, path, f"missing required field '{key}'")
    if "gpidl_version" in data and not isinstance(data["gpidl_version"], str):
        add_error(errors, path_key(path, "gpidl_version"), "expected string")
    operand_width_bits = {}
    if "operand_width_bits" in data:
        owb_path = path_key(path, "operand_width_bits")
        if ensure_dict(data["operand_width_bits"], owb_path, errors):
            for k, v in data["operand_width_bits"].items():
                if not is_int(v) or v < 0:
                    add_error(
                        errors, path_key(owb_path, k), "expected non-negative integer"
                    )
                else:
                    operand_width_bits[k] = v
    canonical_roles = []
    if "canonical_roles" in data:
        canonical_roles = validate_string_list(
            data["canonical_roles"],
            path_key(path, "canonical_roles"),
            errors,
            unique=True,
        )
    global_oprnd_flags = {}
    if "global_oprnd_flag_defs" in data:
        global_oprnd_flags, _ = validate_modifier_defs(
            data["global_oprnd_flag_defs"],
            path_key(path, "global_oprnd_flag_defs"),
            errors,
            allow_can_apply=False,
            instruction_names=None,
            forbidden_names=None,
        )
    global_mods = {}
    pending_can_apply = []
    if "global_modifier_defs" in data:
        global_mods, pending_can_apply = validate_modifier_defs(
            data["global_modifier_defs"],
            path_key(path, "global_modifier_defs"),
            errors,
            allow_can_apply=True,
            instruction_names=None,
            forbidden_names=None,
        )
    instructions = {}
    instruction_names = set()
    if "instructions" in data:
        inst_path = path_key(path, "instructions")
        if ensure_dict(data["instructions"], inst_path, errors):
            instructions = data["instructions"]
            instruction_names = set(instructions.keys())
    for can_apply_path, names in pending_can_apply:
        for name in names:
            if name not in instruction_names:
                add_error(errors, can_apply_path, f"unknown instruction '{name}'")
    for inst_name, inst_obj in instructions.items():
        validate_instruction(
            inst_name,
            inst_obj,
            path_key(path_key(path, "instructions"), inst_name),
            errors,
            global_mods,
            global_oprnd_flags,
            canonical_roles,
            operand_width_bits,
            instruction_names,
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate spec.jsonc against spec_notes.md format."
    )
    parser.add_argument("path", help="Path to spec.jsonc")
    args = parser.parse_args()
    try:
        data = load_jsonc(args.path)
    except Exception as exc:
        print(f"failed to parse JSONC: {exc}", file=sys.stderr)
        return 2
    errors = validate_spec(data)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(f"total errors: {len(errors)}", file=sys.stderr)
        return 1
    print("OK: spec format valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
