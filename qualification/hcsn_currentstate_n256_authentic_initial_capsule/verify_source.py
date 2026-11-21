"""Verify the precommitted authentic initial-capsule source and scope."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_authentic_initial_capsule"
FORBIDDEN_CALLS = {
    "advance_signed_recurrence_cursor",
    "non_substochastic_signed_outputs_from_fp64_intervals",
    "non_substochastic_signed_batch_outputs_from_fp64_intervals",
    "_row_action",
}


def _digest(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for group in ("files", "inputs"):
        for relative, expected in freeze[group].items():
            if _digest(relative) != expected:
                raise SystemExit(f"exact {group[:-1]} mismatch: {relative}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["execution_key"]
        != "hcsn-n256-authentic-initial-capsule-20261121-c6bc-001"
        or request["authentic_provider_execution_allowed"] is not False
        or request["recurrence_execution_allowed"] is not False
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
    ):
        raise SystemExit("request is not fail closed")
    for name in ("capsule.py", "run.py", "test_capsule.py"):
        tree = ast.parse((PACKAGE / name).read_text())
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if calls & FORBIDDEN_CALLS:
            raise SystemExit(f"forbidden recurrence/provider call in {name}")
    review = json.loads((PACKAGE / "REVIEW.json").read_text())
    if (
        review["planned_work"]["tail_checks"] != 0
        or review["planned_work"]["recurrence_row_actions"] != 0
        or review["planned_work"]["provider_outputs"] != 0
        or review["scope"]["resource_gate_closed"] is not False
        or review["scope"]["n256_qualified"] is not False
        or review["scope"]["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
    ):
        raise SystemExit("review is not fail closed")
    print("PASS_N256_AUTHENTIC_INITIAL_CAPSULE_SOURCE")


if __name__ == "__main__":
    main()
