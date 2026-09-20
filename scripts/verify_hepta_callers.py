#!/usr/bin/env python3
"""Verify the closed set of privileged Hepta product call sites.

This is a source proof, not a runtime or production-authority receipt. It uses a
small lexical Rust scanner so comments and string literals cannot manufacture a
fake call site. The manifest intentionally distinguishes product code from
examples and tests; ignored paths remain covered by ordinary compiler and test
checks but cannot satisfy a product-caller requirement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "CALLERS.toml"


class VerificationFailure(RuntimeError):
    """One or more caller-proof invariants failed."""


@dataclass(frozen=True)
class Boundary:
    identifier: str
    symbol: str
    definition_path: str
    definition_markers: tuple[str, ...]
    product_callers: tuple[str, ...]
    caller_markers: tuple[str, ...]


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise VerificationFailure(f"cannot read caller manifest: {exc}") from exc
    if data.get("schema_version") != 2:
        raise VerificationFailure("CALLERS.toml schema_version must be 2")
    if data.get("plan_id") != "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN":
        raise VerificationFailure("CALLERS.toml plan_id mismatch")
    authority = data.get("authority")
    if not isinstance(authority, dict) or not authority:
        raise VerificationFailure("CALLERS.toml requires a closed authority table")
    positive = sorted(key for key, value in authority.items() if value is not False)
    if positive:
        raise VerificationFailure(f"caller proof grants authority: {positive}")
    return data


def _boundary_rows(data: dict[str, Any]) -> tuple[Boundary, ...]:
    rows = data.get("boundary")
    if not isinstance(rows, list) or not rows:
        raise VerificationFailure("CALLERS.toml must declare at least one boundary")
    boundaries: list[Boundary] = []
    identifiers: set[str] = set()
    symbols: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise VerificationFailure("every boundary entry must be a table")
        identifier = row.get("id")
        symbol = row.get("symbol")
        definition_path = row.get("definition_path")
        if not all(
            isinstance(value, str) and value
            for value in (identifier, symbol, definition_path)
        ):
            raise VerificationFailure(
                "boundary id, symbol and definition_path are required"
            )
        if identifier in identifiers:
            raise VerificationFailure(f"duplicate boundary id: {identifier}")
        if symbol in symbols:
            raise VerificationFailure(f"duplicate boundary symbol: {symbol}")
        identifiers.add(identifier)
        symbols.add(symbol)
        boundaries.append(
            Boundary(
                identifier=identifier,
                symbol=symbol,
                definition_path=definition_path,
                definition_markers=_string_tuple(row, "definition_markers"),
                product_callers=_string_tuple(row, "product_callers"),
                caller_markers=_string_tuple(row, "caller_markers"),
            )
        )
    return tuple(boundaries)


def _string_tuple(row: dict[str, Any], key: str) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise VerificationFailure(f"{key} must be a list of non-empty strings")
    return tuple(value)


def _strip_rust_non_code(source: str) -> str:
    """Replace Rust comments and literals with spaces while preserving newlines."""

    output = list(source)
    length = len(source)
    index = 0
    state = "code"
    block_depth = 0
    raw_hashes = 0
    while index < length:
        char = source[index]
        next_char = source[index + 1] if index + 1 < length else ""
        if state == "code":
            if char == "/" and next_char == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if char == "/" and next_char == "*":
                output[index] = output[index + 1] = " "
                index += 2
                block_depth = 1
                state = "block_comment"
                continue
            if char == '"':
                output[index] = " "
                index += 1
                state = "string"
                continue
            if char == "'" and _looks_like_char_literal(source, index):
                output[index] = " "
                index += 1
                state = "char"
                continue
            if char == "r":
                raw_match = re.match(r'r(#{0,255})"', source[index:])
                if raw_match is not None:
                    raw_hashes = len(raw_match.group(1))
                    for offset in range(raw_match.end()):
                        output[index + offset] = " "
                    index += raw_match.end()
                    state = "raw_string"
                    continue
            index += 1
            continue
        if state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        if state == "block_comment":
            if char == "/" and next_char == "*":
                output[index] = output[index + 1] = " "
                block_depth += 1
                index += 2
            elif char == "*" and next_char == "/":
                output[index] = output[index + 1] = " "
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    state = "code"
            else:
                if char != "\n":
                    output[index] = " "
                index += 1
            continue
        if state in {"string", "char"}:
            delimiter = '"' if state == "string" else "'"
            if char == "\\":
                output[index] = " "
                if index + 1 < length:
                    if source[index + 1] != "\n":
                        output[index + 1] = " "
                    index += 2
                else:
                    index += 1
            elif char == delimiter:
                output[index] = " "
                index += 1
                state = "code"
            else:
                if char != "\n":
                    output[index] = " "
                index += 1
            continue
        if state == "raw_string":
            terminator = '"' + ("#" * raw_hashes)
            if source.startswith(terminator, index):
                for offset in range(len(terminator)):
                    output[index + offset] = " "
                index += len(terminator)
                state = "code"
            else:
                if char != "\n":
                    output[index] = " "
                index += 1
            continue
        raise AssertionError(f"unknown scanner state: {state}")
    return "".join(output)


def _looks_like_char_literal(source: str, index: int) -> bool:
    if index + 2 >= len(source):
        return False
    if source[index + 1] == "\\":
        return index + 3 < len(source) and source[index + 3] == "'"
    return source[index + 2] == "'"


def _source_files(root: Path, source_roots: tuple[str, ...]) -> tuple[Path, ...]:
    files: list[Path] = []
    resolved_root = root.resolve()
    for relative_root in source_roots:
        source_root = (root / relative_root).resolve()
        if not source_root.is_relative_to(resolved_root):
            raise VerificationFailure(
                f"source root escapes repository: {relative_root}"
            )
        for path in source_root.rglob("*.rs"):
            if path.is_symlink():
                raise VerificationFailure(
                    f"Rust source symlink is not allowed: {path.relative_to(root)}"
                )
            files.append(path)
    return tuple(sorted(files))


def _is_ignored(relative: str, fragments: tuple[str, ...]) -> bool:
    normalized = f"/{relative.replace(os.sep, '/')}"
    return any(fragment in normalized for fragment in fragments)


def _verify_boundary(
    root: Path,
    boundary: Boundary,
    source_index: dict[str, str],
    ignored_fragments: tuple[str, ...],
) -> dict[str, Any]:
    definition = root / boundary.definition_path
    if not definition.is_file():
        raise VerificationFailure(f"{boundary.identifier}: definition file is missing")
    definition_text = definition.read_text(encoding="utf-8")
    for marker in boundary.definition_markers:
        if marker not in definition_text:
            raise VerificationFailure(
                f"{boundary.identifier}: missing definition marker {marker!r}"
            )

    symbol_pattern = re.compile(re.escape(boundary.symbol) + r"\s*\(")
    observed: set[str] = set()
    for relative, code in source_index.items():
        if relative == boundary.definition_path or _is_ignored(
            relative, ignored_fragments
        ):
            continue
        if symbol_pattern.search(code):
            observed.add(relative)
    expected = set(boundary.product_callers)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise VerificationFailure(
            f"{boundary.identifier}: caller set mismatch; missing={missing}, unexpected={unexpected}"
        )
    for caller in boundary.product_callers:
        caller_path = root / caller
        if not caller_path.is_file():
            raise VerificationFailure(
                f"{boundary.identifier}: caller file is missing: {caller}"
            )
        caller_text = caller_path.read_text(encoding="utf-8")
        for marker in boundary.caller_markers:
            if marker not in caller_text:
                raise VerificationFailure(
                    f"{boundary.identifier}: caller {caller} lacks guard marker {marker!r}"
                )
    return {
        "id": boundary.identifier,
        "symbol": boundary.symbol,
        "productCallers": sorted(observed),
    }


def _verify_protected_files(root: Path, data: dict[str, Any]) -> list[str]:
    rows = data.get("protected_file")
    if not isinstance(rows, list) or not rows:
        raise VerificationFailure("CALLERS.toml must declare protected_file entries")
    checked: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise VerificationFailure("protected_file.path is required")
        relative = row["path"]
        path = root / relative
        if not path.is_file():
            raise VerificationFailure(f"protected file is missing: {relative}")
        text = path.read_text(encoding="utf-8")
        for marker in _string_tuple(row, "required"):
            if marker not in text:
                raise VerificationFailure(
                    f"{relative}: required marker missing: {marker!r}"
                )
        for marker in _string_tuple(row, "forbidden"):
            if marker in text:
                raise VerificationFailure(
                    f"{relative}: forbidden marker present: {marker!r}"
                )
        checked.append(relative)
    return checked


def verify(root: Path = ROOT, manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or root / "CALLERS.toml"
    data = _load_manifest(path)
    source_roots = _string_tuple(data, "source_roots")
    ignored = _string_tuple(data, "ignored_path_fragments")
    files = _source_files(root, source_roots)
    boundaries = _boundary_rows(data)
    symbols = tuple(boundary.symbol for boundary in boundaries)
    source_index: dict[str, str] = {}
    for source_path in files:
        raw = source_path.read_text(encoding="utf-8")
        if any(symbol in raw for symbol in symbols):
            source_index[source_path.relative_to(root).as_posix()] = (
                _strip_rust_non_code(raw)
            )
    results = [
        _verify_boundary(root, boundary, source_index, ignored)
        for boundary in boundaries
    ]
    protected = _verify_protected_files(root, data)
    return {
        "schema": "hepta.caller-proof-receipt.v1",
        "status": "PASS_HEPTA_CALLER_CLOSED_SET",
        "boundaries": results,
        "protectedFiles": protected,
        "rustFilesScanned": len(files),
        "authorityGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("verify", "self-test"), nargs="?", default="verify"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.command == "self-test":
        code = _strip_rust_non_code(
            'call(); // Hidden::new()\nlet s = "Hidden::new()"; /* Nested /* x */ */ real();\n'
        )
        if "Hidden::new" in code or "call" not in code or "real" not in code:
            raise VerificationFailure("lexical scanner self-test failed")
        print(
            json.dumps({"status": "PASS_HEPTA_CALLER_PROOF_SELF_TEST"}, sort_keys=True)
        )
        return 0
    try:
        receipt = verify(args.root.resolve(), args.manifest)
    except VerificationFailure as exc:
        print(f"FAIL_HEPTA_CALLER_PROOF: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
