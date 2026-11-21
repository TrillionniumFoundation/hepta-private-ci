"""Validate the read-only N256 arithmetic-path gap review."""

import ast
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def review():
    record = json.loads((HERE / "REVIEW.json").read_text())
    oracle = record["oracle"]
    candidate = record["candidate"]
    observed = record["observations"]
    finding = record["finding"]

    assert (oracle["run"], oracle["job"]) == (44848445922, 136673835596)
    assert (candidate["run"], candidate["job"]) == (44914033031, 136875692405)
    for key in (
        "runner_image_provisioner_version",
        "runner_image",
        "runner_image_version",
        "region",
        "cloud",
        "python",
        "python_executable_sha256",
        "numpy",
        "numpy_record_sha256",
        "scipy",
        "scipy_record_sha256",
        "thread_count",
    ):
        assert oracle[key] == candidate[key]
    assert oracle["worker_id"] != candidate["worker_id"]
    assert candidate["strict_bitwise_mismatches"] == 665
    assert candidate["max_ulp_distance"] == 98
    assert observed["candidate_boundary_comparisons"] == 68105
    assert observed["candidate_boundary_mismatches"] == 0
    assert all(observed[key] for key in (
        "same_runner_image",
        "same_python_numpy_scipy_records",
        "same_single_thread_environment",
        "different_worker_ids",
        "stream_action_body_equal_ignoring_terminal_lf",
    ))
    assert not any(observed[key] for key in (
        "cpu_model_recorded_by_both",
        "cpu_feature_set_recorded_by_both",
        "blas_vendor_and_runtime_dispatch_recorded_by_both",
        "oracle_boundary_bytes_published",
    ))
    assert finding == {
        "python_minor_version_explanation": "ELIMINATED",
        "cross_worker_hardware_arithmetic_path": "UNBOUND",
        "oracle_candidate_input_byte_equality": "UNPROVEN",
        "arithmetic_or_path_cause": "UNKNOWN",
    }
    assert all(record[key] == 0 for key in (
        "review_numerical_calls",
        "review_dynamic_steps",
        "review_expm_actions",
        "review_torch_calls",
        "review_optimizer_steps",
    ))
    assert record["qualification"] is False
    assert record["production_adoption"] is False
    assert record["c2_full_replay_completed_fits"] == 0
    assert record["hpca_status"] == "NoUpdate"
    assert record["historical_negative_and_unknown_preserved"] is True
    assert record["all_closed"] is False
    return record


def inspect_source():
    tree = ast.parse(Path(__file__).read_text())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not ({"numpy", "scipy", "torch"} & imports)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"expm", "solve_ivp", "backward", "step"}
        for node in ast.walk(tree)
    )


if __name__ == "__main__":
    inspect_source()
    print(json.dumps(review(), indent=2, sort_keys=True))

