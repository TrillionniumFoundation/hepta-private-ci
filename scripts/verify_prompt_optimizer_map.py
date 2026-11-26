#!/usr/bin/env python3
"""Static source-map check; compilation and executed test evidence are separate.

Follow literal module declarations (including cfg(test) and #[path]) from the
crate root. This does not evaluate cfg predicates or expand macros. Rust's
compiled test inventory remains the authority for which tests actually run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "codex-rs" / "hepta-prompt-optimizer" / "src"
MAP = ROOT / "docs" / "modules" / "prompt.optimizer" / "IMPLEMENTATION_MAP.json"
CANONICAL_OPERATIONS = (
    "enumerate_factors_v1", "price_factors_v1", "select_portfolio_v1", "exercise_v1",
)
# Only literal, line-oriented declarations are supported by this static check.
MODULE = re.compile(
    r'(?P<attrs>(?:^[ \t]*#\[[^\n]*\][ \t]*\n)*)'
    r'^[ \t]*(?:pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>\w+)\s*;', re.MULTILINE,
)
PATH = re.compile(r'#\[path\s*=\s*"([^"\n]+)"\]')
TEST = re.compile(
    r'^[ \t]*#\[(?:test|(?:tokio|async_std)::test(?:\([^\n]*\))?)\][ \t]*\n'
    r'(?:^[ \t]*#\[[^\n]*\][ \t]*\n)*'
    r'^[ \t]*(?:(?:pub(?:\([^)]*\))?|async|unsafe)\s+)*fn\s+(\w+)\s*\(',
    re.MULTILINE,
)


RAW_LITERAL = re.compile(r'(?:b|c)?r(\#*)"')
QUOTED_LITERAL = re.compile('(?:b|c)?"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\(?:u\\{[0-9a-fA-F]+\\}|x[0-9a-fA-F]{2}|.)|[^\'\\\\])\'', re.DOTALL)


def fail(message: str) -> None:
    raise SystemExit(f"prompt.optimizer implementation-map check failed: {message}")



def rust_code(source: str) -> str:
    """Mask comments/literals at identical offsets; keep attributes and newlines.

    Prevent commented tests and fixture strings from becoming inventory entries.
    This small lexer does not expand macros or evaluate conditional compilation.
    """
    out = list(source)
    index = 0
    while index < len(source):
        end = None
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            depth, cursor = 1, index + 2
            while depth and cursor < len(source):
                if source.startswith("/*", cursor):
                    depth, cursor = depth + 1, cursor + 2
                elif source.startswith("*/", cursor):
                    depth, cursor = depth - 1, cursor + 2
                else:
                    cursor += 1
            if depth:
                raise ValueError("unterminated Rust block comment")
            end = cursor
        else:
            raw = RAW_LITERAL.match(source, index)
            quoted = QUOTED_LITERAL.match(source, index)
            if raw:
                closing = '"' + raw[1]
                position = source.find(closing, raw.end())
                if position < 0:
                    raise ValueError("unterminated Rust raw string")
                end = position + len(closing)
            elif quoted:
                end = quoted.end()
        if end is None:
            index += 1
        else:
            out[index:end] = ["\n" if c == "\n" else " " for c in source[index:end]]
            index = end
    return "".join(out)


def source_has_function(source: str, name: str) -> bool:
    return re.search(rf"\bpub\s+fn\s+{re.escape(name)}\s*\(", rust_code(source)) is not None


def discover_sources(crate: Path) -> dict[Path, str]:
    """Read linked sources once, rejecting missing/ambiguous/out-of-root files.

    Inline tests reside in their containing file, so they need no separate
    '*tests.rs' filename. An orphan test file does not enter this inventory.
    """
    crate = crate.resolve()
    pending = [crate / "lib.rs"]
    sources: dict[Path, str] = {}
    while pending:
        path = pending.pop().resolve()
        if not path.is_relative_to(crate):
            raise ValueError(f"module escapes crate source root: {path}")
        if path in sources:
            continue
        source = path.read_text(encoding="utf-8")
        sources[path] = source
        for declaration in MODULE.finditer(rust_code(source)):
            start, end = declaration.span("attrs")
            explicit = PATH.search(source[start:end])
            if explicit:
                candidates = [path.parent / explicit[1]]
            else:
                directory = path.parent if path.stem in {"lib", "main", "mod"} else path.with_suffix("")
                name = declaration["name"]
                candidates = [directory / f"{name}.rs", directory / name / "mod.rs"]
            existing = [candidate for candidate in candidates if candidate.is_file()]
            if len(existing) != 1:
                raise ValueError(f"missing or ambiguous module {declaration['name']} in {path}")
            pending.append(existing[0])
    return sources


def test_inventory(sources: dict[Path, str]) -> set[str]:
    """Discover #[test] functions, not unannotated helpers, in linked sources."""
    return {name for source in sources.values() for name in TEST.findall(rust_code(source))}


def main() -> int:
    data = json.loads(MAP.read_text(encoding="utf-8"))
    try:
        sources = discover_sources(CRATE)
    except (OSError, ValueError) as error:
        fail(str(error))
    tests_present = test_inventory(sources)
    crate_root = sources[(CRATE / "lib.rs").resolve()]
    canonical_path = (CRATE / "canonical.rs").resolve()
    if canonical_path not in sources:
        fail("canonical.rs is not reachable from lib.rs")
    canonical_root = sources[canonical_path]

    if "pub mod canonical;" not in crate_root or "pub mod compat;" not in crate_root:
        fail("crate root must expose canonical and compat modules")
    if data.get("productionImplementation") is not False:
        fail("productionImplementation must remain false before exact product evidence")
    if data.get("claimBoundary", {}).get("productionImplementation") is not False:
        fail("claimBoundary cannot self-promote productionImplementation")
    surface = data.get("canonicalSurface", {})
    if not surface.get("uniqueActivePipeline") or not surface.get("verifiedTypeStateRequired"):
        fail("unique canonical pipeline and verified type-state must be explicit")
    for required_module in ("canonical_raw.rs", "canonical_verified.rs", "canonical_solver.rs", "canonical_runtime.rs"):
        if (CRATE / required_module).resolve() not in sources:
            fail(f"canonical module tree does not include {required_module}")
    for relative in surface.get("sourcePaths", []):
        if (ROOT / relative).resolve() not in sources:
            fail(f"canonical source is not linked: {relative}")
    if list(CRATE.glob("policy*.rs")):
        fail("orphan policy implementation remains in tree")

    entries = data.get("operations", [])
    mapped = {entry["operation"]: entry for entry in entries}
    if set(mapped) != set(CANONICAL_OPERATIONS) or len(entries) != len(mapped):
        fail(f"canonical operation inventory mismatch or duplicate: {sorted(mapped)}")
    for operation in CANONICAL_OPERATIONS:
        entry = mapped[operation]
        source_path = (ROOT / entry["sourcePath"]).resolve()
        if source_path not in sources or not source_has_function(sources[source_path], operation):
            fail(f"mapped linked source does not define {operation}")
        tests = entry.get("tests")
        if not tests:
            fail(f"{operation} has no mapped test identity")
        for test in tests:
            if test not in tests_present:
                fail(f"mapped #[test] is not present in linked sources: {test}")

    for operation in CANONICAL_OPERATIONS:
        if f"pub use raw::{operation}" in canonical_root:
            fail(f"raw product operation is publicly re-exported: {operation}")
    compat = sources.get((CRATE / "compat.rs").resolve(), "")
    for symbol in ("optimize", "optimize_with_factor_graph", "local_shadow"):
        if symbol not in compat:
            fail(f"compatibility surface is missing {symbol}")

    print("prompt.optimizer static source map verified; native execution is not asserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
