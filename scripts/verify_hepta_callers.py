#!/usr/bin/env python3
"""Verify the closed set of privileged Hepta product call sites.

This is a source proof, not a runtime or production-authority receipt. It uses a
small lexical Rust scanner so comments, string literals and cfg-test-only items
cannot manufacture a product call site. The manifest intentionally distinguishes
product code from examples and tests; ignored paths remain covered by ordinary
compiler and test checks but cannot satisfy a product-caller requirement.

B4 has two independent closed sets:
1. every privileged boundary in the inventory must have a boundary row; and
2. every non-ignored Rust call matching that row's lexical call pattern must be
   one of the explicitly declared product callers.

The optional ``call_pattern`` is a Python regular expression over Rust code with
comments, literals and cfg-test items stripped. It exists for method syntax such
as ``authority.claim(...)`` where a fully-qualified symbol does not appear at
the call site. ``receiver_type`` instead derives receivers from explicit type,
binding and field declarations, refusing unresolved possible authority calls.
Rows without either option retain the original exact-symbol behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "CALLERS.toml"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hepta_typed_callers import (
    UnresolvedTypedReceiver,
    _impl_owner,
    _is_invocation,
    authority_fields,
    has_authority_call,
    normalize_symbol_aliases,
    symbol_aliases,
)

RAW_STRING_START = re.compile(r'r(#{0,255})"')


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
    call_pattern: str | None
    caller_type_marker: str | None
    receiver_type: str | None = None
    receiver_methods: tuple[str, ...] = ()
    receiver_associated_only: bool = False
    receiver_alternatives: tuple[str, ...] = ()
    free_function: bool = False


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
        call_pattern = row.get("call_pattern")
        caller_type_marker = row.get("caller_type_marker")
        if caller_type_marker is not None and (
            not isinstance(caller_type_marker, str) or not caller_type_marker
        ):
            raise VerificationFailure(
                f"{identifier}: caller_type_marker must be a non-empty string"
            )
        if call_pattern is not None:
            if not isinstance(call_pattern, str) or not call_pattern:
                raise VerificationFailure(
                    f"{identifier}: call_pattern must be a non-empty string"
                )
            try:
                re.compile(call_pattern)
            except re.error as exc:
                raise VerificationFailure(
                    f"{identifier}: invalid call_pattern: {exc}"
                ) from exc
        receiver_type = row.get("receiver_type")
        if receiver_type is not None and (
            not isinstance(receiver_type, str)
            or not re.fullmatch(r"[A-Za-z_]\w*", receiver_type)
        ):
            raise VerificationFailure(f"{identifier}: invalid receiver_type")
        receiver_methods = (
            _string_tuple(row, "receiver_methods") if "receiver_methods" in row else ()
        )
        if receiver_methods and (
            receiver_type is None
            or any(
                not re.fullmatch(r"[A-Za-z_]\w*", method) for method in receiver_methods
            )
        ):
            raise VerificationFailure(f"{identifier}: invalid receiver_methods")
        alternatives = (
            _string_tuple(row, "receiver_alternatives")
            if "receiver_alternatives" in row
            else ()
        )
        if alternatives and (
            receiver_type is None
            or any(
                not re.fullmatch(r"[A-Za-z_]\w*::[A-Za-z_]\w*", item)
                for item in alternatives
            )
        ):
            raise VerificationFailure(f"{identifier}: invalid receiver_alternatives")
        associated_only = row.get("receiver_associated_only", False)
        if not isinstance(associated_only, bool) or (
            associated_only and receiver_type is None
        ):
            raise VerificationFailure(f"{identifier}: invalid receiver_associated_only")
        free_function = row.get("free_function", False)
        if not isinstance(free_function, bool) or (
            free_function
            and (
                receiver_type is not None
                or re.fullmatch(r"[A-Za-z_]\w*", symbol) is None
            )
        ):
            raise VerificationFailure(
                f"{identifier}: invalid free_function classification"
            )
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
                call_pattern=call_pattern,
                caller_type_marker=caller_type_marker,
                receiver_type=receiver_type,
                receiver_methods=receiver_methods,
                receiver_associated_only=associated_only,
                receiver_alternatives=alternatives,
                free_function=free_function,
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


def _verify_privileged_inventory(
    data: dict[str, Any], boundaries: tuple[Boundary, ...]
) -> tuple[str, ...]:
    inventory = data.get("privileged_inventory")
    if not isinstance(inventory, dict):
        raise VerificationFailure("CALLERS.toml requires [privileged_inventory]")
    required = _string_tuple(inventory, "required_boundary_ids")
    if len(required) != len(set(required)):
        raise VerificationFailure(
            "privileged inventory contains duplicate boundary ids"
        )
    declared = {boundary.identifier for boundary in boundaries}
    required_set = set(required)
    if declared != required_set:
        missing = sorted(required_set - declared)
        unclassified = sorted(declared - required_set)
        raise VerificationFailure(
            "privileged boundary inventory mismatch; "
            f"missing={missing}, unclassified={unclassified}"
        )
    return tuple(sorted(required))


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
                raw_match = RAW_STRING_START.match(source, index)
                if raw_match is not None:
                    raw_hashes = len(raw_match.group(1))
                    for offset in range(index, raw_match.end()):
                        output[offset] = " "
                    index = raw_match.end()
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


def _cfg_without_test(expression: str) -> bool | None:
    """Evaluate only the test atom; unknown platform/features remain possible."""
    expression = expression.strip()
    if expression == "test":
        return False
    composite = re.fullmatch(r"(all|any|not)\s*\((.*)\)", expression, re.DOTALL)
    if composite is None:
        return None
    operator, body = composite.groups()
    arguments = []
    depth = start = 0
    for index, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append(body[start:index])
            start = index + 1
    if body[start:].strip():
        arguments.append(body[start:])
    values = [_cfg_without_test(argument) for argument in arguments]
    if operator == "not":
        return not values[0] if len(values) == 1 and values[0] is not None else None
    if operator == "all":
        return (
            False
            if False in values
            else (True if all(value is True for value in values) else None)
        )
    return (
        True
        if True in values
        else (False if all(value is False for value in values) else None)
    )


def _strip_cfg_test_items(code: str) -> str:
    """Blank Rust items whose cfg expression cannot hold outside tests.

    The input has already had comments and literals blanked, so bracket/brace
    matching cannot be confused by braces inside strings. Newlines are retained
    to keep diagnostics stable. `cfg(all(test, unix))` is test-only; production
    alternatives such as `cfg(any(test, unix))` and `cfg(not(test))` are retained.
    """

    output = list(code)
    index = 0
    while index < len(code):
        start = code.find("#[", index)
        if start < 0:
            break
        attr_end = _matching_delimiter(code, start + 1, "[", "]")
        if attr_end is None:
            break
        attribute = code[start : attr_end + 1]
        cfg = re.fullmatch(r"#\[\s*cfg\s*\((.*)\)\s*\]", attribute, re.DOTALL)
        if cfg is None or _cfg_without_test(cfg.group(1)) is not False:
            index = attr_end + 1
            continue

        cursor = attr_end + 1
        # Rust permits additional attributes between cfg(test) and the item.
        while True:
            cursor = _skip_space(code, cursor)
            if not code.startswith("#[", cursor):
                break
            extra_end = _matching_delimiter(code, cursor + 1, "[", "]")
            if extra_end is None:
                raise VerificationFailure("unbalanced Rust attribute in caller scan")
            cursor = extra_end + 1

        item_end = _rust_item_end(code, cursor)
        if item_end is None:
            raise VerificationFailure(
                "cannot determine cfg-test item boundary in caller scan"
            )
        for offset in range(start, item_end + 1):
            if output[offset] != "\n":
                output[offset] = " "
        index = item_end + 1
    return "".join(output)


def _matching_delimiter(
    source: str, open_index: int, opener: str, closer: str
) -> int | None:
    if open_index >= len(source) or source[open_index] != opener:
        return None
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _skip_space(source: str, index: int) -> int:
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _rust_item_end(source: str, start: int) -> int | None:
    """Find the end of one already-lexed Rust item conservatively."""

    # An attribute can guard a struct field or a struct-expression entry. Those
    # end at a top-level comma, not at the next function body or semicolon.
    # Preserve the enclosing brace even when the final field has no comma.
    field = re.match(r"(?:pub(?:\([^)]*\))?\s+)?\w+\s*:(?!:)", source[start:])
    if field:
        paren = bracket = brace = angle = 0
        for index in range(start, len(source)):
            char = source[index]
            if char == "(":
                paren += 1
            elif char == ")" and paren:
                paren -= 1
            elif char == "[":
                bracket += 1
            elif char == "]" and bracket:
                bracket -= 1
            elif char == "{":
                brace += 1
            elif char == "}" and brace:
                brace -= 1
            elif char == "}" and not (paren or bracket or angle):
                return index - 1
            elif char == "<" and not (paren or bracket or brace):
                angle += 1
            elif char == ">" and angle:
                angle -= 1
            elif char == "," and not (paren or bracket or brace or angle):
                return index
        return None

    paren = 0
    bracket = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif paren == 0 and bracket == 0 and char == ";":
            return index
        elif paren == 0 and bracket == 0 and char == "{":
            return _matching_delimiter(source, index, "{", "}")
        index += 1
    return None


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

    if boundary.receiver_associated_only:
        definition_code = _strip_cfg_test_items(_strip_rust_non_code(definition_text))
        for method in boundary.receiver_methods or (
            boundary.symbol.rsplit("::", 1)[-1],
        ):
            candidates = []
            for match in re.finditer(
                rf"\bpub\s+(?:(?:async|const)\s+)?fn\s+(?:r#)?{re.escape(method)}\s*(?:<[^{{}};]*>)?\s*\(",
                definition_code,
            ):
                try:
                    owner = _impl_owner(definition_code, match.start())
                except UnresolvedTypedReceiver as error:
                    raise VerificationFailure(
                        f"{boundary.identifier}: {error}"
                    ) from error
                if owner == boundary.receiver_type:
                    candidates.append(match)
            if len(candidates) != 1:
                raise VerificationFailure(
                    f"{boundary.identifier}: associated method signature is not unique"
                )
            opening = candidates[0].end() - 1
            closing = _matching_delimiter(definition_code, opening, "(", ")")
            if closing is None or re.search(
                r"\bself\b", definition_code[opening:closing]
            ):
                raise VerificationFailure(
                    f"{boundary.identifier}: associated-only method gained a receiver"
                )

    if boundary.call_pattern is None:
        call_pattern = re.compile(re.escape(boundary.symbol) + r"\s*\(")
    else:
        call_pattern = re.compile(boundary.call_pattern)
    receiver_specs = []
    if boundary.receiver_type:
        methods = boundary.receiver_methods or (boundary.symbol.rsplit("::", 1)[-1],)
        receiver_specs.extend((boundary.receiver_type, method) for method in methods)
        receiver_specs.extend(
            tuple(item.split("::")) for item in boundary.receiver_alternatives
        )
    try:
        fields_by_type = {
            target: authority_fields(source_index, target)
            for target in {target for target, _ in receiver_specs}
        }
    except UnresolvedTypedReceiver as error:
        raise VerificationFailure(f"{boundary.identifier}: {error}") from error
    free_aliases = (
        symbol_aliases(source_index, boundary.symbol)
        if boundary.free_function
        else frozenset()
    )
    observed: set[str] = set()
    for relative, code in source_index.items():
        if relative == boundary.definition_path or _is_ignored(
            relative, ignored_fragments
        ):
            continue
        if boundary.receiver_type:
            try:
                matched = any(
                    has_authority_call(
                        code,
                        target,
                        method,
                        fields_by_type[target],
                        associated_only=boundary.receiver_associated_only,
                    )
                    for target, method in receiver_specs
                )
            except UnresolvedTypedReceiver as error:
                raise VerificationFailure(
                    f"{boundary.identifier}: {relative}: {error}"
                ) from error
        else:
            if free_aliases:
                code = normalize_symbol_aliases(code, boundary.symbol, free_aliases)
            if boundary.free_function:
                reference_code = re.sub(r"\buse\s+[^;]+;", "", code)
                for reference in re.finditer(
                    rf"\b(?:r#)?{re.escape(boundary.symbol)}\b", reference_code
                ):
                    prefix = reference_code[: reference.start()].rstrip()
                    if prefix.endswith(".") or re.search(r"\bfn$", prefix):
                        continue
                    try:
                        direct = _is_invocation(reference_code, reference.end())
                    except UnresolvedTypedReceiver as error:
                        raise VerificationFailure(
                            f"{boundary.identifier}: {error}"
                        ) from error
                    if not direct:
                        raise VerificationFailure(
                            f"{boundary.identifier}: privileged function reference is not a direct call"
                        )
            if (
                boundary.caller_type_marker is not None
                and boundary.caller_type_marker not in code
            ):
                continue
            matched = bool(call_pattern.search(code))
        if matched:
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
        "callPattern": boundary.call_pattern,
        "callerTypeMarker": boundary.caller_type_marker,
        "receiverType": boundary.receiver_type,
        "receiverMethods": list(boundary.receiver_methods),
        "receiverAssociatedOnly": boundary.receiver_associated_only,
        "receiverAlternatives": list(boundary.receiver_alternatives),
        "freeFunction": boundary.free_function,
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
        code = (
            _strip_cfg_test_items(_strip_rust_non_code(text))
            if path.suffix == ".rs"
            else text
        )
        for marker in _string_tuple(row, "forbidden"):
            pattern = re.escape(marker)
            if marker and (marker[0].isalnum() or marker[0] == "_"):
                pattern = r"(?<!\w)" + pattern
            if marker and (marker[-1].isalnum() or marker[-1] == "_"):
                pattern += r"(?!\w)"
            if re.search(pattern, code):
                raise VerificationFailure(
                    f"{relative}: forbidden marker present: {marker!r}"
                )
        checked.append(relative)
    return checked


def _verified_method_delegate_spans(
    root: Path, boundaries: tuple[Boundary, ...], source_index: dict[str, str]
) -> dict[str, dict[str, list[tuple[int, int]]]]:
    """Bind the single reviewed internal method delegate, never a whole file."""
    policy_path = root / "qa/b4-no-bypass/KERNEL_AUTHORITY_EXTENSION_API.json"
    if not policy_path.is_file():
        return {}
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    delegates = policy.get("methodDelegates", [])
    if not isinstance(delegates, list) or len(delegates) > 1:
        raise VerificationFailure("expected at most one reviewed method delegate")
    result: dict[str, dict[str, list[tuple[int, int]]]] = {}
    by_id = {row.identifier: row for row in boundaries}
    required = {
        "sourcePath",
        "enclosingType",
        "enclosingMethod",
        "wrapperBoundary",
        "calleeBoundary",
        "expectedCalls",
        "definitionSha256",
    }
    for entry in delegates:
        if not isinstance(entry, dict) or set(entry) != required:
            raise VerificationFailure("invalid method delegate record")
        path, owner, method = (
            entry[key] for key in ("sourcePath", "enclosingType", "enclosingMethod")
        )
        if path != policy.get("sourcePath") or path not in source_index:
            raise VerificationFailure(
                "method delegate source does not match the extension"
            )
        if not all(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z_]\w*", value)
            for value in (owner, method)
        ):
            raise VerificationFailure("invalid method delegate owner")
        wrapper = by_id.get(entry["wrapperBoundary"])
        callee = by_id.get(entry["calleeBoundary"])
        classified = [
            row
            for row in policy.get("types", [])
            if row.get("typeName") == owner
            and row.get("privilegedMethods", {}).get(method) == entry["wrapperBoundary"]
        ]
        if (
            len(classified) != 1
            or wrapper is None
            or wrapper.symbol != f"{owner}::{method}"
            or wrapper.definition_path != path
        ):
            raise VerificationFailure(
                "method delegate wrapper is not an inventoried method"
            )
        if (
            callee is None
            or callee.receiver_type is None
            or callee.receiver_alternatives
        ):
            raise VerificationFailure(
                "method delegate callee must have one typed owner"
            )
        if type(entry["expectedCalls"]) is not int or entry["expectedCalls"] != 1:
            raise VerificationFailure("method delegate requires exactly one call")
        digest = entry["definitionSha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise VerificationFailure("invalid method delegate source digest")
        raw = (root / path).read_text(encoding="utf-8")
        code = source_index[path]
        spans = []
        for impl in re.finditer(rf"\bimpl\s+{re.escape(owner)}\s*\{{", code):
            impl_end = _matching_delimiter(code, impl.end() - 1, "{", "}")
            if impl_end is None:
                raise VerificationFailure("unbalanced method delegate impl")
            for function in re.finditer(
                rf"\bpub\s+(?:async\s+)?fn\s+{re.escape(method)}\s*\(",
                code[impl.end() : impl_end],
            ):
                start = impl.end() + function.start()
                prefix = code[impl.end() : start]
                if prefix.count("{") != prefix.count("}"):
                    continue
                opening = code.find("{", start, impl_end)
                end = (
                    _matching_delimiter(code, opening, "{", "}")
                    if opening >= 0
                    else None
                )
                if end is None or end > impl_end:
                    raise VerificationFailure("unbalanced method delegate body")
                spans.append((start, end + 1))
        if len(spans) != 1:
            raise VerificationFailure(
                "method delegate must identify exactly one function"
            )
        start, end = spans[0]
        if hashlib.sha256(raw[start:end].encode("utf-8")).hexdigest() != digest:
            raise VerificationFailure("method delegate source digest changed")
        body = code[start:end]
        methods = callee.receiver_methods or (callee.symbol.rsplit("::", 1)[-1],)
        pattern = rf"(?:\.|::)\s*(?:r#)?(?:{'|'.join(re.escape(name) for name in methods)})\b\s*(?:\(|::\s*<)"
        if len(re.findall(pattern, body)) != 1:
            raise VerificationFailure("method delegate call count changed")
        fields = authority_fields({path: body}, callee.receiver_type)
        if not any(
            has_authority_call(body, callee.receiver_type, name, fields)
            for name in methods
        ):
            raise VerificationFailure("method delegate has no verified typed callee")
        result.setdefault(callee.identifier, {}).setdefault(path, []).append(
            (start, end)
        )
    return result


def _mask_method_delegate_spans(code: str, spans: list[tuple[int, int]]) -> str:
    output = list(code)
    for start, end in spans:
        for index in range(start, end):
            if output[index] != "\n":
                output[index] = " "
    return "".join(output)


def verify(root: Path = ROOT, manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or root / "CALLERS.toml"
    data = _load_manifest(path)
    source_roots = _string_tuple(data, "source_roots")
    ignored = _string_tuple(data, "ignored_path_fragments")
    files = _source_files(root, source_roots)
    boundaries = _boundary_rows(data)
    inventory = _verify_privileged_inventory(data, boundaries)
    source_index: dict[str, str] = {}
    for source_path in files:
        raw = source_path.read_text(encoding="utf-8")
        code = _strip_rust_non_code(raw)
        source_index[source_path.relative_to(root).as_posix()] = _strip_cfg_test_items(
            code
        )
    delegates = _verified_method_delegate_spans(root, boundaries, source_index)
    results = []
    for boundary in boundaries:
        scoped_source = dict(source_index)
        for relative, spans in delegates.get(boundary.identifier, {}).items():
            scoped_source[relative] = _mask_method_delegate_spans(
                scoped_source[relative], spans
            )
        results.append(_verify_boundary(root, boundary, scoped_source, ignored))
    protected = _verify_protected_files(root, data)
    return {
        "schema": "hepta.caller-proof-receipt.v2",
        "status": "PASS_HEPTA_CALLER_CLOSED_SET",
        "boundaries": results,
        "privilegedInventory": list(inventory),
        "protectedFiles": protected,
        "rustFilesScanned": len(files),
        "authorityGranted": False,
        "internalMethodDelegateSpans": delegates,
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
        if re.search(r"authority\s*\.\s*claim\s*\(", "authority\n  .claim(x)") is None:
            raise VerificationFailure("method call-pattern self-test failed")
        cfg_code = _strip_cfg_test_items(
            "#[cfg(all(test, unix))]\nmod tests { fn x() { authority.claim(x); } }\nauthority.claim(y);\n"
        )
        if (
            cfg_code.count("authority.claim") != 1
            or "authority.claim(y)" not in cfg_code
        ):
            raise VerificationFailure("cfg-test stripping self-test failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "protected.rs"
            manifest = {
                "protected_file": [
                    {
                        "path": "protected.rs",
                        "required": ["required_error_code"],
                        "forbidden": ["codex_hepta_memory::CognitiveStore"],
                    }
                ]
            }
            protected.write_text(
                "let error = codex_hepta_memory::CognitiveStoreError;\n"
                'let code = "required_error_code";\n'
                "// codex_hepta_memory::CognitiveStore\n"
                'let example = "codex_hepta_memory::CognitiveStore";\n'
                "#[cfg(test)] mod tests { use codex_hepta_memory::CognitiveStore; }\n",
                encoding="utf-8",
            )
            _verify_protected_files(root, manifest)
            with protected.open("a", encoding="utf-8") as handle:
                handle.write("use codex_hepta_memory::CognitiveStore;\n")
            try:
                _verify_protected_files(root, manifest)
            except VerificationFailure:
                pass
            else:
                raise VerificationFailure("protected code boundary self-test failed")
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
