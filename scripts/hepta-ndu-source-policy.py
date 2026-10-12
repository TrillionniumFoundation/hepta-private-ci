#!/usr/bin/env python3
"""Fail closed on new callers of the legacy NDU evaluator."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_CALL = re.compile(r"\bevaluate_candidates\s*\(")
LEGACY_DEFINITION_PATH = Path("codex-rs/hepta-ndu/src/lib.rs")
LEGACY_DEFINITION = re.compile(
    r"(?m)^[ \t]*pub\s+fn\s+(?P<name>evaluate_candidates)\s*\("
)
ALLOWED = {
    Path("codex-rs/hepta-ndu/src/evaluator_tests.rs"),
}


def legacy_call_lines(path: Path, text: str) -> list[int]:
    if path in ALLOWED:
        return []
    # Only the approved declaration's name is exempt, never calls in its body
    # or any other call in the root file. Other definitions fail closed.
    declarations = (
        {match.start("name") for match in LEGACY_DEFINITION.finditer(text)}
        if path == LEGACY_DEFINITION_PATH
        else set()
    )
    return [
        text.count("\n", 0, match.start()) + 1
        for match in LEGACY_CALL.finditer(text)
        if match.start() not in declarations
    ]


def main() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "codex-rs").glob("**/*.rs")):
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for line in legacy_call_lines(rel, text):
            violations.append(f"{rel}:{line}")
    if violations:
        raise SystemExit(
            "FAIL_NDU_LEGACY_CALLER_POLICY: "
            + ", ".join(violations)
            + "; use evaluate_candidates_with_policy"
        )
    print("PASS_NDU_LEGACY_CALLER_POLICY")


if __name__ == "__main__":
    main()
