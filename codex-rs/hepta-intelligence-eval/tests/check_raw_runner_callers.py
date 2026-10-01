#!/usr/bin/env python3
"""Reject default-build callers that bypass the recorded learning.eval runner."""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAW_RUNNER = re.compile(
    r"(?<![A-Za-z0-9_])ProductEvaluationRunnerV1(?![A-Za-z0-9_])"
)
RAW_STRING_PREFIX = re.compile(r'(?:br|r)(?P<hashes>#{0,255})"')
PUBLIC_LOW_LEVEL = re.compile(
    r"(?m)^\s*pub\s+use\s+signed_evaluation::decide_with_signed_evidence_v[23]\s*;"
)


def strip_comments_and_literals(source: str) -> str:
    """Return Rust code with comments and string bodies replaced by spaces."""

    out: list[str] = []
    index = 0
    block_depth = 0
    length = len(source)

    while index < length:
        if block_depth:
            if source.startswith("/*", index):
                block_depth += 1
                out.extend("  ")
                index += 2
            elif source.startswith("*/", index):
                block_depth -= 1
                out.extend("  ")
                index += 2
            else:
                out.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue

        if source.startswith("//", index):
            end = source.find("\n", index)
            if end == -1:
                out.extend(" " * (length - index))
                break
            out.extend(" " * (end - index))
            out.append("\n")
            index = end + 1
            continue

        if source.startswith("/*", index):
            block_depth = 1
            out.extend("  ")
            index += 2
            continue

        raw = RAW_STRING_PREFIX.match(source, index)
        if raw:
            prefix_end = raw.end()
            hashes = raw.group("hashes")
            terminator = '"' + hashes
            end = source.find(terminator, prefix_end)
            if end == -1:
                out.extend(" " * (length - index))
                break
            stop = end + len(terminator)
            segment = source[index:stop]
            out.extend("\n" if char == "\n" else " " for char in segment)
            index = stop
            continue

        quote_offset = 1 if source.startswith('b"', index) else 0
        if source[index + quote_offset : index + quote_offset + 1] == '"':
            start = index
            index += quote_offset + 1
            escaped = False
            while index < length:
                char = source[index]
                index += 1
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    break
            segment = source[start:index]
            out.extend("\n" if char == "\n" else " " for char in segment)
            continue

        out.append(source[index])
        index += 1

    return "".join(out)


def main() -> int:
    repo = Path(__file__).resolve().parents[3]
    crate = repo / "codex-rs" / "hepta-intelligence-eval"
    lib = (crate / "src" / "lib.rs").read_text(encoding="utf-8")

    required = (
        '#[cfg(feature = "trusted-inprocess-eval")]\n'
        'pub use product_runner::ProductEvaluationRunnerV1;',
        'mod product_runner;',
        'pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;',
    )
    missing = [snippet for snippet in required if snippet not in lib]
    if missing:
        print("learning.eval API boundary is missing required private/default gates:")
        for snippet in missing:
            print(f"  - {snippet!r}")
        return 1

    code = strip_comments_and_literals(lib)
    if (
        not re.search(r"(?m)^\s*mod\s+product_runner\s*;", code)
        or re.search(r"(?m)^\s*pub(?:\([^)]*\))?\s+mod\s+product_runner\s*;", code)
        or len(re.findall(r"(?m)^\s*pub\s+use\s+product_runner::ProductEvaluationRunnerV1\s*;", code)) != 1
    ):
        print("raw runner must remain in a private module with only its gated compatibility export")
        return 1

    if PUBLIC_LOW_LEVEL.search(code):
        print("low-level signed decision primitive is publicly exported")
        return 1

    violations: list[str] = []
    for path in sorted(repo.rglob("*.rs")):
        if crate in path.parents:
            continue
        if any(part in {"target", ".git", "vendor"} for part in path.parts):
            continue
        code = strip_comments_and_literals(path.read_text(encoding="utf-8"))
        if RAW_RUNNER.search(code):
            violations.append(path.relative_to(repo).as_posix())

    if violations:
        print("raw ProductEvaluationRunnerV1 callers found outside the owner crate:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("learning.eval production API surface is closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
