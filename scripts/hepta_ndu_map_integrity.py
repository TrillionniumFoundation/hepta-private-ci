#!/usr/bin/env python3
"""Exact typed source inventory for NDU maps; never a qualification attestation.

The immutable primary and extension maps retain their historical semantics. The
unified candidate overlay owns the current exact object manifest, so the older
maps are themselves hashed inputs rather than being rewritten after every
candidate change. The overlay cannot hash itself.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

PRIMARY = "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json"
EXTENSION = "docs/modules/utility.ndu/IMPLEMENTATION_MAP_EXTENSIONS.json"
UNIFIED = "docs/modules/utility.ndu/IMPLEMENTATION_MAP_UNIFIED.json"
INPUTS = (
    "justfile",
    PRIMARY,
    EXTENSION,
    "docs/modules/MODULE_DOCS.json",
    "docs/modules/utility.ndu/PUBLIC_API_BASELINE_V1.json",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/rustfmt.toml",
    "scripts/hepta-ndu-qualification.py",
    "scripts/test_hepta_ndu_qualification.py",
    "scripts/hepta-ndu-implementation-map-closed-world.py",
    "scripts/hepta_ndu_map_integrity.py",
    "scripts/test_hepta_ndu_map_integrity.py",
    "scripts/hepta-ndu-public-api-compat.py",
    "scripts/test_hepta_ndu_public_api_compat.py",
    "scripts/hepta-ndu-source-policy.py",
    "scripts/test_hepta_ndu_source_policy.py",
    "scripts/hepta_ndu_evidence.py",
    "scripts/test_hepta_ndu_evidence.py",
    ".github/workflows/hepta-ndu-recursion.yml",
    ".github/workflows/hepta-ndu-public-api.yml",
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(root), *args], text=True
    ).strip()


def checked_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or any(c in name for c in "\x00\r\n\\"):
        raise ValueError("invalid evidence path")
    pure = PurePosixPath(name)
    if (
        pure.is_absolute()
        or pure.as_posix() != name
        or any(part in (".", "..") for part in pure.parts)
    ):
        raise ValueError(f"non-canonical evidence path: {name}")
    path = root
    for part in pure.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlinked evidence path: {name}")
    if not path.exists():
        raise ValueError(f"missing evidence path: {name}")
    return path


def evidence_paths(
    root: Path,
    primary: dict[str, Any],
    extension: dict[str, Any],
    unified: dict[str, Any] | None = None,
) -> set[str]:
    paths = set(INPUTS)
    roots = primary.get("sourceRoot", [])
    if not isinstance(roots, list) or not roots:
        raise ValueError("sourceRoot must contain typed source roots")
    paths.update(roots)
    paths.add(primary["technicalGuide"])
    paths.update(primary.get("executionSpecifications", []))

    mappings = [primary, extension]
    if unified is not None:
        mappings.append(unified)
    for mapping in mappings:
        support = mapping.get("supportingSources", [])
        if not isinstance(support, list):
            raise ValueError("supportingSources must be a list")
        paths.update(support)
        operations = mapping.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("operations must be a list")
        for operation in operations:
            paths.add(operation["sourcePath"])
            for test in operation["tests"]:
                paths.add(test["path"])
            for delegate in operation.get("delegatedCallees", []):
                paths.add(
                    delegate
                    if isinstance(delegate, str)
                    else delegate.get("sourcePath", delegate.get("path"))
                )
            if operation.get("ownerEntrypoint"):
                paths.add(operation["ownerEntrypoint"]["path"])
        for caller in mapping.get("productCallers", []):
            paths.add(caller.get("sourcePath", caller.get("path")))

    if UNIFIED in paths:
        raise ValueError("unified map cannot hash itself")
    for name in paths:
        checked_path(root, name)
    return paths


def merge_source_objects(
    primary: dict[str, Any], unified: dict[str, Any]
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for label, entries in (
        ("primary sourceObjects", primary.get("sourceObjects")),
        ("unified sourceObjectOverrides", unified.get("sourceObjectOverrides")),
    ):
        if not isinstance(entries, list):
            raise ValueError(f"{label} must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "object"}:
                raise ValueError(f"invalid entry in {label}")
            path, object_id = entry["path"], entry["object"]
            if not isinstance(path, str) or not isinstance(object_id, str):
                raise ValueError(f"non-string entry in {label}")
            merged[path] = {"path": path, "object": object_id}
    return [merged[path] for path in sorted(merged)]


def verify_manifest(root: Path, objects: list[dict], expected: set[str]) -> None:
    actual: dict[str, str] = {}
    if not isinstance(objects, list):
        raise ValueError("sourceObjects must be a list")
    for entry in objects:
        if not isinstance(entry, dict) or set(entry) != {"path", "object"}:
            raise ValueError("invalid source object entry")
        name, oid = entry["path"], entry["object"]
        checked_path(root, name)
        if name in actual:
            raise ValueError(f"duplicate source object: {name}")
        if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise ValueError(f"invalid source object id: {name}")
        actual[name] = oid
    if set(actual) != expected:
        raise ValueError(
            "source manifest closure mismatch: "
            f"missing={sorted(expected-set(actual))}, "
            f"extra={sorted(set(actual)-expected)}"
        )
    for name, oid in actual.items():
        if git(root, "rev-parse", f"HEAD:{name}") != oid:
            raise ValueError(f"source object drift: {name}")


RAW_STRING = re.compile(r'(?:br|cr|r)(#*)"')
CHARACTER = re.compile(r"'(?:[^'\\\n]|\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.))'")


def code_only(text: str) -> str:
    """Mask comments and string/char literals without treating lifetimes as chars."""
    out = list(text)
    i = 0
    while i < len(text):
        start = i
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                i = len(text)
        elif text.startswith("/*", i):
            i += 2
            depth = 1
            while i < len(text) and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("unterminated Rust block comment")
        elif raw := RAW_STRING.match(text, i):
            end = '"' + raw.group(1)
            closing = text.find(end, raw.end())
            if closing < 0:
                raise ValueError("unterminated Rust raw string")
            i = closing + len(end)
        elif text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise ValueError("unterminated Rust string")
        elif text[i] == "'" and (char := CHARACTER.match(text, i)):
            i += len(char.group(0))
        else:
            i += 1
            continue
        for j in range(start, min(i, len(text))):
            if out[j] != "\n":
                out[j] = " "
    return "".join(out)


def rust_symbol_exists(path: Path, symbol: str) -> bool:
    name = re.escape(symbol.rsplit("::", 1)[-1])
    text = code_only(path.read_text(encoding="utf-8"))
    return bool(
        re.search(
            rf"\bfn\s+{name}\s*(?:<[^>]*>)?\s*\(|"
            rf"\b(?:struct|enum|union|trait|type|const|static|mod)\s+{name}\b",
            text,
        )
    )


def executable_test_exists(path: Path, symbol: str) -> bool:
    name = symbol.rsplit("::", 1)[-1]
    if path.suffix == ".py":
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
            for node in ast.walk(ast.parse(path.read_text()))
        )
    if path.suffix != ".rs":
        return False
    text = code_only(path.read_text(encoding="utf-8"))
    pattern = (
        r"((?:#\[[^\]]+\]\s*)+)"
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
        r"fn\s+([A-Za-z_]\w*)\s*\("
    )
    for attributes, function in re.findall(pattern, text):
        if function == name and re.search(
            r"#\[\s*(?:[A-Za-z_]\w*::)*test\s*(?:\([^\]]*\))?\s*\]",
            attributes,
        ):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebind-index", action="store_true", required=True)
    parser.add_argument("--candidate-branch", required=True)
    parser.add_argument("--baseline-main", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.baseline_main):
        parser.error("baseline main must be an exact commit SHA")
    root = Path(__file__).resolve().parents[1]
    primary = json.loads((root / PRIMARY).read_text())
    extension = json.loads((root / EXTENSION).read_text())
    unified = json.loads((root / UNIFIED).read_text())
    tree = git(root, "write-tree")
    unified["sourceObjectOverrides"] = [
        {"path": name, "object": git(root, "rev-parse", f"{tree}:{name}")}
        for name in sorted(evidence_paths(root, primary, extension, unified))
    ]
    unified["currentSourceEvidence"] = {
        "baselineMainCommit": args.baseline_main,
        "branch": args.candidate_branch,
        "sourceBinding": "exact_typed_overlay_path_object_manifest_v1",
        "qualificationBinding": (
            "suite receipts contain actual source and synthetic commit/tree identities"
        ),
        "productionActivation": False,
    }
    (root / UNIFIED).write_text(json.dumps(unified, indent=2) + "\n")


if __name__ == "__main__":
    main()
