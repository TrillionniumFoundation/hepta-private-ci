#!/usr/bin/env python3
"""Exact-tree entrypoint that fail-closes required filtered tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(__file__).with_name("hepta-learning-eval-exact.py")
SPEC = importlib.util.spec_from_file_location("hepta_learning_eval_exact", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
ORIGINAL_COMMANDS = MODULE.commands

AGENTD_REQUIRED_TEST = "signed_candidate_passes_only_with_bound_owner_run_context_and_root_trust"


def commands(output: Path):
    result = []
    for name, argv, cwd in ORIGINAL_COMMANDS(output):
        if name == "agentd-consumer":
            result.append((
                name,
                [
                    sys.executable,
                    "scripts/hepta-nextest-require.py",
                    "--manifest-path", "codex-rs/Cargo.toml",
                    "--package", "codex-hepta-agentd",
                    "--filter", AGENTD_REQUIRED_TEST,
                    "--label", "agentd-current-owner-context-root-trust",
                    "--evidence", str(output / "agentd-consumer-discovery.json"),
                ],
                ".",
            ))
        else:
            result.append((name, argv, cwd))
    return result


MODULE.commands = commands

if __name__ == "__main__":
    raise SystemExit(MODULE.main())
