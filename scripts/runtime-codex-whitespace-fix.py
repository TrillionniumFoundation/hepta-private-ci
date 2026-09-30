#!/usr/bin/env python3
"""Normalize EOFs introduced by append-only one-shot migrations.

The structural migrations intentionally append reviewed tests and operator
notes. Four targets inherited a pre-existing trailing blank line and therefore
ended with two newlines after append. Normalize only those reviewed targets to
one final newline so `git diff --check` is an invariant of materialization.

This helper is deleted with the construction migrations.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "codex-rs/hepta-infer-worker-host/src/native_execution.rs",
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
    "docs/modules/runtime.codex/QUICKSTART.md",
)


def main() -> None:
    for relative in TARGETS:
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
