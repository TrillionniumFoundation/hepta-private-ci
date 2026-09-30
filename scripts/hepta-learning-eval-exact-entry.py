#!/usr/bin/env python3
"""Exact-tree entrypoint that fail-closes every filtered qualification test."""
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

REQUIRED_FILTERS = {
    "signed-e2e": {
        "package": "codex-hepta-intelligence-eval",
        "filter": "signed_qualification_e2e",
        "label": "owner-signed-e2e",
    },
    "shadow-consumer": {
        "package": "codex-hepta-intelligence",
        "filter": "evaluated_shadow",
        "label": "intelligence-shadow-consumer",
    },
    "plasticity-consumer": {
        "package": "codex-hepta-intelligence",
        "filter": "plasticity_product",
        "label": "intelligence-plasticity-consumer",
    },
    "agentd-consumer": {
        "package": "codex-hepta-agentd",
        "filter": "signed_candidate_passes_only_with_bound_owner_run_context_and_root_trust",
        "label": "agentd-current-owner-context-root-trust",
    },
    "agentd-outcome-consumer": {
        "package": "codex-hepta-agentd",
        "filter": "multi_outcome_consumer_rejects_context_owner_and_signature_substitution",
        "label": "agentd-multi-outcome-binding",
    },
    "cold-recovery-e2e": {
        "package": "codex-hepta-intelligence-eval",
        "filter": "cold_process_recovery_uses_only_persisted_inputs_and_current_trust",
        "label": "cold-process-persisted-inputs-current-trust",
        "tests": ["cold_recovery_e2e"],
    },
}


def required_command(output: Path, spec: dict[str, object]) -> list[str]:
    argv = [
        sys.executable,
        "scripts/hepta-nextest-require.py",
        "--manifest-path", "codex-rs/Cargo.toml",
        "--package", str(spec["package"]),
        "--filter", str(spec["filter"]),
        "--label", str(spec["label"]),
        "--evidence", str(output / f"{spec['label']}-discovery.json"),
    ]
    for target in spec.get("tests", []):
        argv.extend(["--test", str(target)])
    return argv


def commands(output: Path):
    result = []
    fixture_inserted = False
    for name, argv, cwd in ORIGINAL_COMMANDS(output):
        if name in REQUIRED_FILTERS:
            result.append((name, required_command(output, REQUIRED_FILTERS[name]), "."))
        else:
            result.append((name, argv, cwd))
        if name == "api-surface":
            result.append((
                "trusted-compatibility-fixture",
                [
                    sys.executable,
                    "scripts/hepta-learning-eval-compat-fixture.py",
                    "--offline",
                    "--evidence", str(output / "trusted-compatibility-fixture.json"),
                ],
                ".",
            ))
            fixture_inserted = True
    if not fixture_inserted:
        raise RuntimeError("exact command inventory lost api-surface insertion point")
    return result


MODULE.commands = commands

if __name__ == "__main__":
    raise SystemExit(MODULE.main())
