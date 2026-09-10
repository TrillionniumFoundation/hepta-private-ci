#!/usr/bin/env python3
"""Run the r13 convergence executor with untracked diagnostic receipts."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-r13-latest-owner-convergence.py")
SPEC = importlib.util.spec_from_file_location("hepta_r13_latest_owner", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load r13 executor from {SCRIPT}")
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def run_repository_gates_without_tree_mutation(head: str) -> None:
    executor.run(("python3", "scripts/hepta-repository-integrity.py", "self-test"))
    receipt = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "hepta-r13-repository-integrity.json"
    executor.run(
        (
            "python3",
            "scripts/hepta-repository-integrity.py",
            "verify",
            "--base",
            executor.REVIEW_ANCHOR,
            "--head",
            head,
            "--output",
            str(receipt),
        )
    )
    for command in executor.REPOSITORY_COMMANDS:
        if (executor.ROOT / command[1]).is_file():
            executor.run(command)


executor.run_repository_gates = run_repository_gates_without_tree_mutation

if __name__ == "__main__":
    raise SystemExit(executor.main())
