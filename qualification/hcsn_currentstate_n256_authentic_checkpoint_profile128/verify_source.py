"""Verify the frozen index-128 profile source and authentic inputs."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = (
    ROOT
    / "qualification"
    / "hcsn_currentstate_n256_authentic_checkpoint_profile128"
)
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
        != "hcsn-n256-authentic-checkpoint-hex-20261122-c6bc-001"
        or request["boundaries"] != [64, 128]
        or request["index32_source_replay_row_actions"] != 900
        or request["warm_extension_row_actions"] != 960
        or request["cold_extension_row_actions"] != 1280
        or request["index_two_relation_recomputations"] != 30
        or request["total_row_actions"] != 3140
        or request["tail_checks"] != 0
        or request["provider_outputs"] != 0
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
    ):
        raise SystemExit("request is not the fixed fail-closed profile")
    row_action_callsites = 0
    for name in ("extended.py", "run.py", "test_extended.py"):
        source = (PACKAGE / name).read_text()
        if "set_int_max_str_digits" in source:
            raise SystemExit(f"decimal integer safety override in {name}")
        tree = ast.parse(source)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if calls & FORBIDDEN:
            raise SystemExit(f"forbidden tail or provider call in {name}")
        if name == "extended.py":
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
        review["planned_work"]["index_two_relation_recomputations"] != 30
        or review["planned_work"]["total_row_actions"] != 3140
        or review["planned_work"]["tail_checks"] != 0
        or review["planned_work"]["provider_outputs"] != 0
        or review["scope"]["resource_gate_closed"] is not False
        or review["scope"]["n256_qualified"] is not False
        or review["scope"]["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
    ):
        raise SystemExit("review is not fail closed")
    print("PASS_N256_AUTHENTIC_CHECKPOINT_PROFILE128_SOURCE")


if __name__ == "__main__":
    main()
