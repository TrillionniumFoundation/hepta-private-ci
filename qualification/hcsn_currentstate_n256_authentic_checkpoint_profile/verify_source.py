"""Verify the frozen authentic checkpoint profile source and work boundary."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_authentic_checkpoint_profile"
FORBIDDEN = {
    "_result_if_unique",
    "_round_fraction",
    "advance_signed_recurrence_cursor",
    "non_substochastic_signed_outputs_from_fp64_intervals",
    "non_substochastic_signed_batch_outputs_from_fp64_intervals",
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
        != "hcsn-n256-authentic-checkpoint-profile-20261121-c6bc-001"
        or request["boundaries"] != [4, 8, 16, 32]
        or request["warm_row_actions"] != 300
        or request["cold_validation_row_actions"] != 520
        or request["index_two_relation_recomputations"] != 50
        or request["total_row_actions"] != 870
        or request["tail_checks"] != 0
        or request["provider_outputs"] != 0
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
    ):
        raise SystemExit("request is not the fixed fail-closed profile")
    row_action_callsites = 0
    for name in ("checkpoint.py", "run.py", "test_checkpoint.py"):
        tree = ast.parse((PACKAGE / name).read_text())
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if calls & FORBIDDEN:
            raise SystemExit(f"forbidden tail or provider call in {name}")
        if name == "checkpoint.py":
            row_action_callsites = sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_row_action"
                for node in ast.walk(tree)
            )
    if row_action_callsites != 1:
        raise SystemExit("profile must contain exactly one row-action callsite")
    review = json.loads((PACKAGE / "REVIEW.json").read_text())
    if (
        review["planned_work"]["index_two_relation_recomputations"] != 50
        or review["planned_work"]["total_row_actions"] != 870
        or review["planned_work"]["tail_checks"] != 0
        or review["planned_work"]["provider_outputs"] != 0
        or review["scope"]["resource_gate_closed"] is not False
        or review["scope"]["n256_qualified"] is not False
        or review["scope"]["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
    ):
        raise SystemExit("review is not fail closed")
    print("PASS_N256_AUTHENTIC_CHECKPOINT_PROFILE_SOURCE")


if __name__ == "__main__":
    main()
