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
the call site. Qualified symbol calls remain checked alongside the additional
pattern. Rows without it retain the original exact-symbol behavior.
"""

from __future__ import annotations

import argparse
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


def _strip_cfg_test_items(code: str) -> str:
    """Blank Rust items whose cfg expression cannot hold outside a test build.

    The input has already had comments and literals blanked, so bracket/brace
    matching cannot be confused by braces inside strings. Newlines are retained
    to keep diagnostics stable. This intentionally removes both `cfg(test)` and
    compound forms such as `cfg(all(test, unix))`, while retaining `not(test)`
    and `any(test, unix)` product code.
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
        if not _cfg_is_test_only(attribute):
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
                return "".join(output)
            cursor = extra_end + 1

        item_end = _rust_item_end(code, cursor)
        if item_end is None:
            item_end = len(code) - 1
        for offset in range(start, item_end + 1):
            if output[offset] != "\n":
                output[offset] = " "
        index = item_end + 1
    return "".join(output)


def _cfg_is_test_only(attribute: str) -> bool:
    """Evaluate cfg with test=false and every other atom unknown, fail closed."""
    match = re.fullmatch(r"#\[\s*cfg\s*\((.*)\)\s*\]", attribute, re.DOTALL)
    if match is None:
        return False
    tokens = re.findall(r"[A-Za-z_]\w*|[(),=]", match.group(1))
    cursor = 0

    def expression() -> bool | None:
        nonlocal cursor
        if cursor >= len(tokens) or tokens[cursor] in {"(", ")", ",", "="}:
            raise ValueError("invalid cfg expression")
        name = tokens[cursor]
        cursor += 1
        if cursor < len(tokens) and tokens[cursor] == "=":
            # String literal values were already blanked by the lexical pass.
            # Every value-bearing target/feature predicate stays unknown.
            cursor += 1
            while cursor < len(tokens) and tokens[cursor] not in {",", ")"}:
                cursor += 1
            return None
        if cursor >= len(tokens) or tokens[cursor] != "(":
            return False if name == "test" else None
        if name not in {"all", "any", "not"}:
            raise ValueError("unknown cfg operator")
        cursor += 1
        values = []
        while cursor < len(tokens) and tokens[cursor] != ")":
            values.append(expression())
            if cursor < len(tokens) and tokens[cursor] == ",":
                cursor += 1
            elif cursor >= len(tokens) or tokens[cursor] != ")":
                raise ValueError("invalid cfg arguments")
        if cursor >= len(tokens):
            raise ValueError("unclosed cfg expression")
        cursor += 1
        if name == "not":
            if len(values) != 1:
                raise ValueError("invalid cfg not")
            return None if values[0] is None else not values[0]
        if name == "all":
            if False in values:
                return False
            return None if None in values else True
        if True in values:
            return True
        return None if None in values else False

    try:
        result = expression()
    except (ValueError, RecursionError):
        return False
    return cursor == len(tokens) and result is False


def _strip_other_owner_self_calls(code: str, symbol: str) -> str:
    """Exclude self calls only for a different impl's own inherent method.

    Unknown receivers, autoderef wrappers and generic/trait impls remain matches.
    A concrete type alone does not establish its method's dispatch owner.
    """
    if "::" not in symbol:
        return code
    # Unknown conditional compilation can hide the inherent method or its impl
    # while leaving an autoderef call live in another build profile. Retain all
    # candidates in such files rather than infer an unconditional dispatch owner.
    if re.search(r"#\[\s*cfg(?:_attr)?\s*\(", code):
        return code
    owner, method = symbol.rsplit("::", 1)
    owner = owner.rsplit("::", 1)[-1]
    calls = list(re.finditer(r"\bself\s*\.\s*" + re.escape(method) + r"\s*\(", code))
    if not calls:
        return code
    implementations = []
    for match in re.finditer(r"\bimpl\s+([A-Za-z_]\w*)\s*\{", code):
        end = _matching_delimiter(code, match.end() - 1, "{", "}")
        if end is not None:
            own_method = False
            method_pattern = re.compile(
                r"\bfn\s+" + re.escape(method) + r"(?:\s*<[^{};]*>)?\s*\("
            )
            for method_match in method_pattern.finditer(code, match.end(), end):
                preceding = code[match.end() : method_match.start()]
                if preceding.count("{") != preceding.count("}"):
                    continue
                arguments_end = _matching_delimiter(
                    code, method_match.end() - 1, "(", ")"
                )
                if arguments_end is None:
                    continue
                arguments = code[method_match.end() : arguments_end]
                first_argument = arguments.split(",", 1)[0]
                if re.fullmatch(
                    r"\s*(?:&\s*(?:'\w+\s*)?(?:mut\s+)?)?(?:mut\s+)?self\s*",
                    first_argument,
                ):
                    own_method = True
                    break
            implementations.append((match.start(), end, match.group(1), own_method))
    output = list(code)
    for call in calls:
        enclosing = [
            impl for impl in implementations if impl[0] <= call.start() < impl[1]
        ]
        if not enclosing:
            continue
        innermost = min(enclosing, key=lambda impl: impl[1] - impl[0])
        preceding = code[innermost[0] : call.start()]
        nested_impl = any(
            preceding[: match.start()].count("{")
            > preceding[: match.start()].count("}") + 1
            for match in re.finditer(r"\bimpl\b", preceding)
        )
        # A trait/generic impl nested in a method changes self's owner, even
        # when its header is outside the deliberately small concrete matcher.
        # Retain the call if such a scope could intervene; signature impl Trait
        # parameters are at the enclosing impl's top brace depth and do not
        # themselves introduce a new self binding.
        if innermost[2] != owner and innermost[3] and not nested_impl:
            for offset in range(call.start(), call.end()):
                if output[offset] != "\n":
                    output[offset] = " "
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


def _source_files(
    root: Path,
    source_roots: tuple[str, ...],
    ignored_fragments: tuple[str, ...] = (),
) -> tuple[Path, ...]:
    files: list[Path] = []
    resolved_root = root.resolve()
    resolved_source_roots = tuple(
        (root / relative).resolve() for relative in source_roots
    )
    for relative_root, source_root in zip(source_roots, resolved_source_roots):
        if not source_root.is_relative_to(resolved_root):
            raise VerificationFailure(
                f"source root escapes repository: {relative_root}"
            )
        for directory, directories, names in os.walk(source_root, followlinks=False):
            directory_path = Path(directory)
            retained_directories = []
            for name in directories:
                child = directory_path / name
                if _is_ignored(
                    child.relative_to(root).as_posix() + "/", ignored_fragments
                ):
                    continue
                if child.is_symlink():
                    target = child.resolve()
                    if (
                        not target.is_dir()
                        or not target.is_relative_to(resolved_root)
                        or not any(
                            target.is_relative_to(scanned)
                            for scanned in resolved_source_roots
                        )
                    ):
                        raise VerificationFailure(
                            f"source directory symlink escapes scanned roots: {child.relative_to(root)}"
                        )
                    if _is_ignored(
                        target.relative_to(root).as_posix() + "/", ignored_fragments
                    ):
                        raise VerificationFailure(
                            f"source directory symlink targets unscanned source: {child.relative_to(root)}"
                        )
                    # The concrete in-root target is enumerated separately.
                    continue
                retained_directories.append(name)
            directories[:] = sorted(retained_directories)
            for name in names:
                if not name.endswith(".rs"):
                    continue
                path = directory_path / name
                if _is_ignored(path.relative_to(root).as_posix(), ignored_fragments):
                    continue
                if path.is_symlink():
                    raise VerificationFailure(
                        f"Rust source symlink is not allowed: {path.relative_to(root)}"
                    )
                files.append(path)
    return tuple(sorted(files))


def _is_ignored(relative: str, fragments: tuple[str, ...]) -> bool:
    normalized = f"/{relative.replace(os.sep, '/')}"
    return any(fragment in normalized for fragment in fragments)


def _marker_present(text: str, marker: str) -> bool:
    prefix = r"(?<![A-Za-z0-9_])" if marker[0].isalnum() or marker[0] == "_" else ""
    suffix = r"(?![A-Za-z0-9_])" if marker[-1].isalnum() or marker[-1] == "_" else ""
    return re.search(prefix + re.escape(marker) + suffix, text) is not None


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
        if not _marker_present(definition_text, marker):
            raise VerificationFailure(
                f"{boundary.identifier}: missing definition marker {marker!r}"
            )

    if boundary.call_pattern is None:
        call_pattern = re.compile(re.escape(boundary.symbol) + r"\s*\(")
    else:
        call_pattern = re.compile(
            "(?:" + re.escape(boundary.symbol) + r"\s*\(|" + boundary.call_pattern + ")"
        )
    observed: set[str] = set()
    for relative, code in source_index.items():
        if relative == boundary.definition_path or _is_ignored(
            relative, ignored_fragments
        ):
            continue
        if call_pattern.search(code) and call_pattern.search(
            _strip_other_owner_self_calls(code, boundary.symbol)
        ):
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
            if not _marker_present(caller_text, marker):
                raise VerificationFailure(
                    f"{boundary.identifier}: caller {caller} lacks guard marker {marker!r}"
                )
    return {
        "id": boundary.identifier,
        "symbol": boundary.symbol,
        "callPattern": boundary.call_pattern,
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
            if not _marker_present(text, marker):
                raise VerificationFailure(
                    f"{relative}: required marker missing: {marker!r}"
                )
        code = _strip_cfg_test_items(_strip_rust_non_code(text))
        for marker in _string_tuple(row, "forbidden"):
            if _marker_present(code, marker):
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
    files = _source_files(root, source_roots, ignored)
    boundaries = _boundary_rows(data)
    inventory = _verify_privileged_inventory(data, boundaries)
    source_index: dict[str, str] = {}
    for source_path in files:
        # Ignored build outputs can disappear while Cargo is running. They are
        # not product source and must be excluded before reading, not just before
        # classifying discovered calls.
        relative_path = "/" + source_path.relative_to(root).as_posix()
        if any(fragment in relative_path for fragment in ignored):
            continue
        raw = source_path.read_text(encoding="utf-8")
        code = _strip_rust_non_code(raw)
        source_index[source_path.relative_to(root).as_posix()] = _strip_cfg_test_items(
            code
        )
    results = [
        _verify_boundary(root, boundary, source_index, ignored)
        for boundary in boundaries
    ]
    protected = _verify_protected_files(root, data)
    return {
        "schema": "hepta.caller-proof-receipt.v2",
        "status": "PASS_HEPTA_CALLER_CLOSED_SET",
        "boundaries": results,
        "privilegedInventory": list(inventory),
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
        product_cfg = _strip_cfg_test_items(
            "#[cfg(not(test))]\nfn a() { authority.claim(a); }\n"
            "#[cfg(any(test, unix))]\nfn b() { authority.claim(b); }\n"
            "#[cfg(all(not(test), unix))]\nfn c() { authority.claim(c); }\n"
            "#[cfg(all(test, feature =       ))]\nfn d() { authority.claim(d); }\n"
        )
        if (
            product_cfg.count("authority.claim") != 3
            or "authority.claim(d)" in product_cfg
        ):
            raise VerificationFailure("product cfg preservation self-test failed")
        self_calls = _strip_other_owner_self_calls(
            "impl Other { fn consume(&self, x: X) {} fn run(&self) { self.consume(x); host.consume(y); } }\n"
            "impl Owner { fn run(&self) { self.consume(z); } }\n",
            "Owner::consume",
        )
        if (
            "self.consume(x)" in self_calls
            or "host.consume(y)" not in self_calls
            or "self.consume(z)" not in self_calls
        ):
            raise VerificationFailure("concrete self-call owner self-test failed")
        if (
            _marker_present(
                "codex_hepta_memory::CognitiveStoreError",
                "codex_hepta_memory::CognitiveStore",
            )
            or not _marker_present(
                "codex_hepta_memory::CognitiveStore",
                "codex_hepta_memory::CognitiveStore",
            )
            or _marker_present("pub fn verify_spoof()", "pub fn verify")
        ):
            raise VerificationFailure("exact identifier guard-marker self-test failed")
        with tempfile.TemporaryDirectory(prefix="hepta-caller-proof-") as temporary:
            fixture_root = Path(temporary)
            fixture_source = fixture_root / "src"
            fixture_source.mkdir()
            (fixture_source / "owner.rs").write_text(
                "impl Owner { pub fn consume(&self) {} }", encoding="utf-8"
            )
            (fixture_source / "product.rs").write_text(
                "fn product() { host.consume(x); }", encoding="utf-8"
            )
            boundary = Boundary(
                "fixture",
                "Owner::consume",
                "src/owner.rs",
                ("pub fn consume",),
                ("src/product.rs",),
                ("host.consume",),
                r"host\s*\.\s*consume\s*\(",
            )
            source_index = {
                "src/product.rs": "fn product() { host.consume(x); }",
                "src/other.rs": _strip_cfg_test_items(
                    "#[cfg(test)] fn test_only() { Owner::consume(x); }"
                ),
            }
            _verify_boundary(fixture_root, boundary, source_index, ())
            for non_test in [
                "#[cfg(not(test))] fn live() { Owner::consume(x); }",
                "#[cfg(any(test, unix))] fn live() { host.consume(x); }",
                "impl Wrapper { fn run(&self) { self.consume(x); } }",
                "impl Wrapper { fn consume(x: X) {} fn run(&self) { self.consume(x); } }",
                "impl Wrapper { fn consume(self: Box<Self>, x: X) {} fn run(&mut self) { self.consume(x); } }",
                "impl Wrapper { #[cfg(feature =    )] fn consume(&self, x: X) {} fn run(&self) { self.consume(x); } }",
                "impl Other { fn consume(&self, x: X) {} fn run(&self) { impl Runner for Wrapper { fn run(&self) { self.consume(x); } } } }",
                "impl Other { fn consume(&self, x: X) {} fn run(&self) { impl<T> Wrapper<T> { fn run(&self) { self.consume(x); } } } }",
            ]:
                source_index["src/other.rs"] = _strip_cfg_test_items(non_test)
                if "Wrapper" in non_test:
                    # A Deref<Target=Owner> wrapper can dispatch self.consume to
                    # the registered boundary; its concrete impl is not proof
                    # of a locally defined method.
                    boundary = Boundary(
                        "fixture",
                        "Owner::consume",
                        "src/owner.rs",
                        ("pub fn consume",),
                        ("src/product.rs",),
                        ("host.consume",),
                        r"\.\s*consume\s*\(",
                    )
                try:
                    _verify_boundary(fixture_root, boundary, source_index, ())
                except VerificationFailure as exc:
                    if "unexpected=['src/other.rs']" not in str(exc):
                        raise
                else:
                    raise VerificationFailure(
                        "unclassified non-test caller self-test failed"
                    )
            generated = fixture_source / "target"
            generated.mkdir()
            (generated / "generated.rs").symlink_to(generated / "disappeared.rs")
            if _source_files(fixture_root, ("src",), ("/target/",)) != (
                fixture_source / "owner.rs",
                fixture_source / "product.rs",
            ):
                raise VerificationFailure(
                    "ignored generated source pruning self-test failed"
                )
            outside = fixture_root / "outside"
            outside.mkdir()
            (outside / "concealed.rs").write_text("fn concealed() { host.consume(x); }")
            (fixture_source / "external_alias").symlink_to(
                outside, target_is_directory=True
            )
            try:
                _source_files(fixture_root, ("src",), ("/target/",))
            except VerificationFailure as exc:
                if "source directory symlink escapes scanned roots" not in str(exc):
                    raise
            else:
                raise VerificationFailure(
                    "outside source-directory symlink self-test failed"
                )
            (fixture_source / "external_alias").unlink()
            (fixture_source / "ignored_alias").symlink_to(
                generated, target_is_directory=True
            )
            try:
                _source_files(fixture_root, ("src",), ("/target/",))
            except VerificationFailure as exc:
                if "source directory symlink targets unscanned source" not in str(exc):
                    raise
            else:
                raise VerificationFailure(
                    "ignored-target source-directory alias self-test failed"
                )
            (fixture_source / "ignored_alias").unlink()
            (fixture_source / "internal_alias").symlink_to(
                fixture_source, target_is_directory=True
            )
            if len(_source_files(fixture_root, ("src",), ("/target/",))) != 2:
                raise VerificationFailure(
                    "in-root source-directory alias self-test failed"
                )
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
