"""Read retained bytes and integer intent; never execute the static profile."""

import ast
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    b = root / "qualification/hcsn_currentstate_scale_spec"
    evidence = b / "evidence/static-intent-attempt001"
    freeze = json.loads((evidence / "FREEZE.json").read_text())
    result = json.loads((evidence / "STATIC_PROFILE.json").read_text())
    assert (
        freeze["source_commit"]
        == result["source_freeze_commit"]
        == "a26231befccb88c8784d29a748e2ed41e8042cd2"
    )
    assert (
        len(freeze["source_sha256"]),
        len(freeze["input_sha256"]),
        len(freeze["protocol_sha256"]),
    ) == (10, 5, 5)
    actual = {
        k: {p: sha(root / p) for p in freeze[k]}
        for k in ("source_sha256", "input_sha256", "protocol_sha256")
    }
    assert actual == result["before"] == result["after"]
    assert all(actual[k] == freeze[k] for k in actual)
    assert (evidence / "STATIC_PROFILE.json").stat().st_size <= 100000
    source = ast.parse((b / "static_profile.py").read_text())
    allowed = {"ast", "hashlib", "json", "pathlib", "struct", "zipfile", "argparse"}
    imports = set()
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module.split(".")[0])
    assert imports <= allowed
    manifest = json.loads((b / "SOURCE_INPUT_MANIFEST.json").read_text())
    assert (
        manifest["N256_input_present"] is False
        and manifest["dynamic_execution_allowed"] is False
    )
    assert len(result["scale_table"]) == 3
    comparisons = 0
    refs = 0
    for row, N in zip(result["scale_table"], (128, 256, 512)):
        n = N - 1
        assert (
            row["intervals"] == N
            and row["interior_nodes"] == n
            and row["channels"] == 5
        )
        assert row["main_augmented_dimension_after_feedback"] == 3 * n + 9
        assert row["largest_pending_generator_dimension"] == 2 * n + 1
        assert row["one_dense_augmented_matrix_bytes"] == 8 * (3 * n + 9) ** 2
        assert row["largest_pending_generator_dense_bytes"] == 8 * (2 * n + 1) ** 2
        minimum = row["minimum_singlecall_scenario"]
        warm = row["declared_warm_scenario"]
        assert minimum["persistent_floats"] == 37 * n * n + 180 * n + 113
        assert (
            minimum["hex_array_payload_lower_bound_bytes"]
            == 11 * minimum["persistent_floats"] - 53
            > 900000
        )
        assert minimum["segments"] == 15 and minimum["pending_packets"] == 16
        assert warm["persistent_floats"] == 52 * n * n + 246 * n + 134
        assert (
            warm["hex_array_payload_lower_bound_bytes"]
            == 11 * warm["persistent_floats"] - 71
        )
        assert warm["segments"] == 21 > 20 and warm["pending_packets"] == 22
        assert row["comparison_scalar_denominator"] == 14 * (10 * n + 80)
        assert row["reference_scalar_denominator"] == 8 * (10 * n + 80)
        assert row["static_total_expm_counter"] == 244 + 94 + 122 == 460
        assert row["static_total_segments"] == 21 + 15 + 9 == 45
        assert row["dynamic_execution_admissible"] is False
        comparisons += row["comparison_scalar_denominator"]
        refs += row["reference_scalar_denominator"]
    assert (comparisons, refs) == (128380, 73360)
    for N in (128, 512):
        h = result["npz_headers_only"][str(N)]
        assert h["active.npy"]["shape"] == h["nodes.npy"]["shape"] == [N + 1]
        assert h["content.npy"]["shape"] == [N + 1, 4]
        assert all(x["dtype"] == "<f8" for x in h.values())
        metadata = result["actual_metadata"][str(N)]
        assert (
            metadata["reset_distance"] == 0.3131468965881033
            and metadata["phase_bins"] == 8
        )
        assert metadata["source_visit"]["index"] == 897
    reasons = [x["reason"] for x in result["static_protocol_negative_cases"]]
    assert reasons == [
        "OUTSIDE_STAGED_INTENT",
        "PREDECESSOR_NOT_QUALIFIED",
        "MAPPED_INPUT_MISSING",
        "SIGNED_CHANNELS_MISSING",
        "PHASE_LAW_MISSING",
        "WRONG_ACTUAL_RESET",
        "WRONG_UPPER_SEMANTICS",
        "LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN",
    ]
    assert all(x["rejected"] is True for x in result["static_protocol_negative_cases"])
    assert all(
        result[k] == 0
        for k in (
            "candidate_imports",
            "scipy_imports",
            "numpy_imports",
            "dynamic_runs",
            "matrix_exponentials_executed",
            "reference_evaluations",
            "optimizer_steps",
        )
    )
    assert result["largegrid_qualification"] is False and result["all_closed"] is False
    assert result["admission"] == "HOLD_INTENT_ONLY"
    assert {k: {p: sha(root / p) for p in freeze[k]} for k in actual} == actual
    print(
        json.dumps(
            {
                "read_only": True,
                "retained_static_invocations": 1,
                "profile_replays": 0,
                "source_files": 10,
                "inputs": 5,
                "protocol_files": 5,
                "integer_rows": 3,
                "protocol_refusals": 8,
                "planned_scalar_denominator": comparisons,
                "planned_expm_counter": 1380,
                "matrix_exponentials_executed": 0,
                "dynamic_runs": 0,
                "largegrid_qualification": False,
                "admission": "HOLD_INTENT_ONLY",
                "all_closed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
