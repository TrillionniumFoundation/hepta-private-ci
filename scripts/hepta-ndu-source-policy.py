#!/usr/bin/env python3
"""Fail closed on new callers of the legacy NDU evaluator."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_CALL = re.compile(r"\bevaluate_candidates\s*\(")
ALLOWED = {
    Path("codex-rs/hepta-ndu/src/evaluator.rs"),
    Path("codex-rs/hepta-ndu/src/evaluator_tests.rs"),
}


def main() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "codex-rs").glob("**/*.rs")):
        rel = path.relative_to(ROOT)
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for match in LEGACY_CALL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
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
