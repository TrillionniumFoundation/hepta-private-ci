#!/usr/bin/env python3
"""Fail closed when utility.ndu changes a frozen V1 source surface in place."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from hepta_ndu_map_integrity import executable_test_exists, rust_symbol_exists

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/modules/utility.ndu/PUBLIC_API_BASELINE_V1.json"
LIB = ROOT / "codex-rs/hepta-ndu/src/lib.rs"


class DuplicateKey(ValueError):
    pass


def object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKey(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_baseline(path: Path = BASELINE) -> dict[str, Any]:
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=object_no_duplicates
    )


def extract_public_fields(text: str, struct_name: str) -> list[str]:
    match = re.search(rf"\bpub\s+struct\s+{re.escape(struct_name)}\s*\{{", text)
    if match is None:
        raise ValueError(f"public struct missing: {struct_name}")
    start = match.end() - 1
    depth = 0
    end = None
    for offset in range(start, len(text)):
        character = text[offset]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                end = offset
                break
    if end is None:
        raise ValueError(f"unterminated public struct: {struct_name}")
    body = text[start + 1 : end]
    return re.findall(r"(?m)^\s*pub\s+([A-Za-z_]\w*)\s*:", body)


def validate() -> dict[str, Any]:
    baseline = load_baseline()
    errors: list[str] = []
    if baseline.get("schema") != "hepta.ndu.public-api-baseline.v1":
        errors.append("unexpected public API baseline schema")
    if baseline.get("module") != "utility.ndu":
        errors.append("public API baseline module is not utility.ndu")

    v1_structs = baseline.get("v1Structs")
    checked_structs = 0
    if not isinstance(v1_structs, list) or not v1_structs:
        errors.append("v1Structs must be a non-empty list")
    else:
        for entry in v1_structs:
            if not isinstance(entry, dict):
                errors.append("v1Structs entry is not an object")
                continue
            name, path, expected = (
                entry.get("name"),
                entry.get("path"),
                entry.get("fields"),
            )
            if not isinstance(name, str) or not isinstance(path, str):
                errors.append("v1Structs entry is missing name/path")
                continue
            if not isinstance(expected, list) or any(
                not isinstance(field, str) for field in expected
            ):
                errors.append(f"{name} fields are not a string list")
                continue
            source = ROOT / path
            if not source.is_file():
                errors.append(f"V1 source missing: {path}")
                continue
            try:
                actual = extract_public_fields(source.read_text(encoding="utf-8"), name)
            except ValueError as error:
                errors.append(str(error))
                continue
            if actual != expected:
                errors.append(
                    f"{name} public fields changed in place: expected={expected!r} actual={actual!r}"
                )
            checked_structs += 1

    required = baseline.get("requiredSymbols")
    checked_symbols = 0
    if not isinstance(required, list) or not required:
        errors.append("requiredSymbols must be a non-empty list")
    else:
        for entry in required:
            if not isinstance(entry, dict):
                errors.append("requiredSymbols entry is not an object")
                continue
            name, path = entry.get("name"), entry.get("path")
            if not isinstance(name, str) or not isinstance(path, str):
                errors.append("requiredSymbols entry is missing name/path")
                continue
            source = ROOT / path
            if not source.is_file() or not rust_symbol_exists(source, name):
                errors.append(f"required compatibility symbol missing: {path}::{name}")
            checked_symbols += 1

    compile_test = baseline.get("externalCompileTest")
    if not isinstance(compile_test, dict):
        errors.append("externalCompileTest must be an object")
    else:
        path, symbol = compile_test.get("path"), compile_test.get("symbol")
        if not isinstance(path, str) or not isinstance(symbol, str):
            errors.append("externalCompileTest is missing path/symbol")
        else:
            test_path = ROOT / path
            if not test_path.is_file() or not executable_test_exists(test_path, symbol):
                errors.append(f"external compatibility test missing: {path}::{symbol}")

    lib_text = LIB.read_text(encoding="utf-8")
    for symbol in (
        "NduIterationReceiptV1",
        "ZQ24ConversionReceiptV1",
        "NduIterationReceiptV2",
        "ZQ24ConversionReceiptV2",
        "migrate_iteration_receipt_v1",
        "migrate_z_q24_receipt_v1",
    ):
        if not re.search(rf"\b{re.escape(symbol)}\b", lib_text):
            errors.append(f"crate export missing: {symbol}")

    return {
        "schema": "hepta.ndu.public-api-compat-result.v1",
        "module": "utility.ndu",
        "checkedStructCount": checked_structs,
        "checkedSymbolCount": checked_symbols,
        "baseline": str(BASELINE.relative_to(ROOT)),
        "passed": not errors,
        "errors": errors,
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
