"""Verify the frozen index-256 source and authentic input archives."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = (
    ROOT
    / "qualification"
    / "hcsn_currentstate_n256_authentic_checkpoint_profile256"
)
FORBIDDEN = {
    "_result_if_unique",
    "_round_fraction",
    "advance_signed_recurrence_cursor",
    "non_substochastic_signed_outputs_from_fp64_intervals",
    "non_substochastic_signed_batch_outputs_from_fp64_intervals",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(relative):
    return digest((ROOT / relative).read_bytes())


def joined_parts(relative, count):
    root = ROOT / relative
    return b"".join(
        (root / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(count)
    )


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for group in ("files", "inputs"):
        for relative, expected in freeze[group].items():
            if file_digest(relative) != expected:
                raise SystemExit(f"exact {group[:-1]} mismatch: {relative}")

    manifest = json.loads(
        (ROOT / "qualification/hcsn_ci_readbacks/6940/MANIFEST.json").read_text()
    )
    for name, expected in manifest["parts"].items():
        relative = f"qualification/hcsn_ci_readbacks/6940/{name}"
        if file_digest(relative) != expected:
            raise SystemExit(f"index-128 part mismatch: {name}")
    if (
        digest(joined_parts("qualification/hcsn_ci_readbacks/6940", 28))
        != "2ecc44ac2d769105908e1b44b5bfabb99713c791b45c237da48913847af9de41"
        or digest(joined_parts("qualification/hcsn_ci_readbacks/6936", 31))
        != "e1775ee832acc431282bcca9b7b5f0e21b38ac5a0f3ac46c2228f787c0e8a0a8"
        or digest(joined_parts("qualification/hcsn_ci_readbacks/6931", 3))
        != "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
        or file_digest("qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip")
        != "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
    ):
        raise SystemExit("authentic archive digest mismatch")

    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["execution_key"]
        != "hcsn-n256-authentic-checkpoint-profile256-20261122-c6bc-001"
        or request["boundary"] != 256
        or request["index_two_relation_recomputations"] != 20
        or request["index32_source_replay_row_actions"] != 600
        or request["index128_source_replay_row_actions"] != 1920
        or request["warm_extension_row_actions"] != 1280
        or request["cold_extension_row_actions"] != 1280
        or request["total_row_actions"] != 5080
        or request["tail_checks"] != 0
        or request["provider_outputs"] != 0
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
    ):
        raise SystemExit("request is not the fixed fail-closed profile")

    row_action_callsites = 0
    for name in ("profile256.py", "run.py", "test_profile256.py"):
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
        if name == "profile256.py":
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
        review["planned_work"]["total_row_actions"] != 5080
        or review["planned_work"]["tail_checks"] != 0
        or review["planned_work"]["provider_outputs"] != 0
        or review["scope"]["resource_gate_closed"] is not False
        or review["scope"]["n256_qualified"] is not False
        or review["scope"]["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
        or review["historical_statuses"]["6939"]
        != "RED_DECIMAL_INTEGER_DIGIT_LIMIT"
    ):
        raise SystemExit("review is not fail closed")
    print("PASS_N256_AUTHENTIC_CHECKPOINT_PROFILE256_SOURCE")


if __name__ == "__main__":
    main()
