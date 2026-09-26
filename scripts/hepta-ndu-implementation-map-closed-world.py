#!/usr/bin/env python3
"""Fail closed when the utility.ndu implementation maps drift from source.

The repository-wide implementation-map verifier owns SHA/tree/blob freshness
for the primary map. This module validator treats the primary map and its
explicit extension as one closed world: unique operations, real native/test
symbols, and explicit coverage for every tracked Rust source below sourceRoot.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json"
EXTENSION = ROOT / "docs/modules/utility.ndu/IMPLEMENTATION_MAP_EXTENSIONS.json"


class DuplicateKey(ValueError):
    pass


def object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKey(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(), object_pairs_hook=object_no_duplicates)


def all_strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, list):
        for item in value:
            found.update(all_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(all_strings(item))
    return found


def tracked_files(root: str) -> set[str]:
    output = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--", root], text=True
    )
    return {line for line in output.splitlines() if line.endswith(".rs")}


def rust_symbol_exists(path: Path, symbol: str) -> bool:
    terminal = symbol.rsplit("::", 1)[-1]
    escaped = re.escape(terminal)
    text = path.read_text()
    patterns = [
        rf"\bfn\s+{escaped}\s*(?:<[^>]*>)?\s*\(",
        rf"\b(?:struct|enum|union|trait|type|const|static|mod)\s+{escaped}\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def symbol_exists(path: Path, symbol: str) -> bool:
    if path.suffix == ".rs":
        return rust_symbol_exists(path, symbol)
    if path.suffix == ".py":
        return bool(re.search(rf"\bdef\s+{re.escape(symbol)}\s*\(", path.read_text()))
    return symbol in path.read_text()


def main() -> int:
    errors: list[str] = []
    try:
        primary = load(PRIMARY)
        extension = load(EXTENSION)
    except (OSError, json.JSONDecodeError, DuplicateKey) as error:
        print(json.dumps({"passed": False, "errors": [str(error)]}, indent=2))
        return 1

    for name, mapping in (("primary", primary), ("extension", extension)):
        if mapping.get("module") != "utility.ndu":
            errors.append(f"{name} map module is not utility.ndu")
    if extension.get("extends") != "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json":
        errors.append("extension map does not name the canonical primary map")

    operations: list[Any] = []
    for name, mapping in (("primary", primary), ("extension", extension)):
        mapped = mapping.get("operations")
        if not isinstance(mapped, list) or not mapped:
            errors.append(f"{name} operations must be a non-empty list")
        else:
            operations.extend(mapped)

    seen_operations: set[str] = set()
    seen_native: set[str] = set()
    seen_tests: set[tuple[str, str]] = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(f"operations[{index}] is not an object")
            continue
        name = operation.get("operation")
        native = operation.get("nativeSymbol")
        source = operation.get("sourcePath")
        if not isinstance(name, str) or not name:
            errors.append(f"operations[{index}] missing operation")
        elif name in seen_operations:
            errors.append(f"duplicate operation: {name}")
        else:
            seen_operations.add(name)
        if not isinstance(native, str) or not native:
            errors.append(f"{name!r} missing nativeSymbol")
        elif native in seen_native:
            errors.append(f"duplicate nativeSymbol: {native}")
        else:
            seen_native.add(native)
        if operation.get("sourcePathExists") is not True:
            errors.append(f"{name!r} sourcePathExists is not true")
        if not isinstance(source, str):
            errors.append(f"{name!r} missing sourcePath")
        else:
            source_path = ROOT / source
            if not source_path.is_file():
                errors.append(f"{name!r} source file missing: {source}")
            elif isinstance(native, str) and not symbol_exists(source_path, native):
                errors.append(f"{name!r} native symbol missing: {native} in {source}")

        tests = operation.get("tests")
        if not isinstance(tests, list) or not tests:
            errors.append(f"{name!r} must map at least one executable test")
            continue
        for test_index, test in enumerate(tests):
            if not isinstance(test, dict):
                errors.append(f"{name!r} tests[{test_index}] is not an object")
                continue
            path, symbol = test.get("path"), test.get("symbol")
            if not isinstance(path, str) or not isinstance(symbol, str):
                errors.append(f"{name!r} tests[{test_index}] missing path/symbol")
                continue
            identity = (path, symbol)
            if identity in seen_tests:
                errors.append(f"duplicate test identity: {path}::{symbol}")
            seen_tests.add(identity)
            test_path = ROOT / path
            if not test_path.is_file():
                errors.append(f"mapped test file missing: {path}")
            elif not symbol_exists(test_path, symbol):
                errors.append(f"mapped test symbol missing: {path}::{symbol}")

    roots = primary.get("sourceRoot")
    if not isinstance(roots, list) or not roots:
        errors.append("sourceRoot must be a non-empty list")
        roots = []
    strings = all_strings(primary) | all_strings(extension)
    tracked: set[str] = set()
    for root in roots:
        if not isinstance(root, str):
            errors.append("sourceRoot entries must be strings")
            continue
        root_path = ROOT / root
        if not root_path.is_dir():
            errors.append(f"sourceRoot missing: {root}")
            continue
        tracked.update(tracked_files(root))
    for path in sorted(path for path in tracked if path not in strings):
        errors.append(f"tracked Rust source is outside the closed map: {path}")

    result = {
        "schema": "hepta.ndu.closed-world-map-validation.v2",
        "module": primary.get("module"),
        "operationCount": len(seen_operations),
        "testIdentityCount": len(seen_tests),
        "trackedRustSourceCount": len(tracked),
        "maps": [str(PRIMARY.relative_to(ROOT)), str(EXTENSION.relative_to(ROOT))],
        "passed": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
