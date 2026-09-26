#!/usr/bin/env python3
"""Fail closed when utility.ndu source or registry projections drift.

This module validator treats the primary implementation map and its explicit
extension as one closed world. It binds execution to the exact candidate
SHA/tree, verifies unique operations, real native/test symbols, explicit source
coverage and an exact TECHNICAL.md projection of the canonical module registry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json"
EXTENSION = ROOT / "docs/modules/utility.ndu/IMPLEMENTATION_MAP_EXTENSIONS.json"
MODULE_DOCS = ROOT / "docs/modules/MODULE_DOCS.json"
TECHNICAL = ROOT / "docs/modules/utility.ndu/TECHNICAL.md"


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


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


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


def registry_module(registry: dict[str, Any]) -> dict[str, Any]:
    modules = registry.get("modules")
    if not isinstance(modules, list):
        raise ValueError("MODULE_DOCS modules must be a list")
    matches = [
        module
        for module in modules
        if isinstance(module, dict) and module.get("module") == "utility.ndu"
    ]
    if len(matches) != 1:
        raise ValueError("MODULE_DOCS must contain exactly one utility.ndu entry")
    return matches[0]


def markdown_code_list(text: str, start: str, end: str) -> list[str]:
    start_offset = text.find(start)
    if start_offset < 0:
        raise ValueError(f"TECHNICAL.md missing projection heading: {start}")
    body_start = start_offset + len(start)
    end_offset = text.find(end, body_start)
    if end_offset < 0:
        raise ValueError(f"TECHNICAL.md missing projection terminator: {end}")
    body = text[body_start:end_offset]
    entries: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"- `([^`]+)`", stripped)
        if match is None:
            raise ValueError(
                f"TECHNICAL.md projection contains non-generated content between {start!r} and {end!r}: {stripped!r}"
            )
        entries.append(match.group(1))
    if len(entries) != len(set(entries)):
        raise ValueError(f"TECHNICAL.md projection contains duplicates after {start}")
    return entries


def validate_registry_projection(errors: list[str]) -> dict[str, int]:
    try:
        registry = load(MODULE_DOCS)
        module = registry_module(registry)
        technical = TECHNICAL.read_text()
        projections = {
            "producedContracts": markdown_code_list(
                technical, "Produced contracts:", "Consumed contracts:"
            ),
            "consumedContracts": markdown_code_list(
                technical, "Consumed contracts:", "Critical protocol schemas:"
            ),
            "protocols": markdown_code_list(
                technical,
                "Critical protocol schemas:",
                "Every producer validates output before publication",
            ),
            "ownedDomains": markdown_code_list(
                technical,
                "Owned authoritative or rebuildable domains:",
                "Read-only data dependencies:",
            ),
            "readDomains": markdown_code_list(
                technical,
                "Read-only data dependencies:",
                "For every owned domain",
            ),
        }
    except (OSError, json.JSONDecodeError, DuplicateKey, ValueError) as error:
        errors.append(f"technical registry projection: {error}")
        return {}

    counts: dict[str, int] = {}
    for field, actual in projections.items():
        expected = module.get(field)
        if not isinstance(expected, list) or any(
            not isinstance(value, str) for value in expected
        ):
            errors.append(f"MODULE_DOCS utility.ndu {field} is not a string list")
            continue
        counts[field] = len(actual)
        if actual != expected:
            errors.append(
                f"TECHNICAL.md {field} differs from generated MODULE_DOCS projection: expected={expected!r} actual={actual!r}"
            )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    try:
        candidate_sha = git("rev-parse", "HEAD")
        candidate_tree = git("rev-parse", "HEAD^{tree}")
        if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
            raise ValueError("--expected-sha must be an exact Git object id")
        if not re.fullmatch(r"[0-9a-f]{40}", args.expected_tree):
            raise ValueError("--expected-tree must be an exact Git object id")
        if candidate_sha != args.expected_sha:
            raise ValueError(
                f"candidate SHA mismatch: expected={args.expected_sha} actual={candidate_sha}"
            )
        if candidate_tree != args.expected_tree:
            raise ValueError(
                f"candidate tree mismatch: expected={args.expected_tree} actual={candidate_tree}"
            )
        if git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("closed-world validation requires a clean checkout")
        primary = load(PRIMARY)
        extension = load(EXTENSION)
    except (
        OSError,
        json.JSONDecodeError,
        DuplicateKey,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
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

    registry_projection = validate_registry_projection(errors)
    try:
        if git("rev-parse", "HEAD") != candidate_sha or git(
            "rev-parse", "HEAD^{tree}"
        ) != candidate_tree:
            errors.append("candidate identity changed during validation")
        if git("status", "--porcelain", "--untracked-files=all"):
            errors.append("checkout changed during closed-world validation")
    except subprocess.CalledProcessError as error:
        errors.append(f"final candidate identity check failed: {error}")

    result = {
        "schema": "hepta.ndu.closed-world-map-validation.v4",
        "module": primary.get("module"),
        "sourceSha": candidate_sha,
        "sourceTree": candidate_tree,
        "operationCount": len(seen_operations),
        "testIdentityCount": len(seen_tests),
        "trackedRustSourceCount": len(tracked),
        "registryProjectionCounts": registry_projection,
        "maps": [str(PRIMARY.relative_to(ROOT)), str(EXTENSION.relative_to(ROOT))],
        "registry": str(MODULE_DOCS.relative_to(ROOT)),
        "technicalGuide": str(TECHNICAL.relative_to(ROOT)),
        "passed": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
