"""Static N256 operator/count/resource audit; executes no dynamics or expm."""

import argparse
import hashlib
import json
from pathlib import Path

from .candidate import N128_PRIMITIVE_SOURCE_SHA256, build_graph


N128_COMPARISON_CAPS = {
    "per_capsule_raw_bytes": 8_388_608,
    "cumulative_logical_packet_bytes": 201_326_592,
    "canonical_archive_bytes": 268_435_456,
    "candidate_process_AS_bytes": 2_147_483_648,
    "oracle_process_AS_bytes": 2_147_483_648,
    "parent_process_AS_bytes": 536_870_912,
    "total_CPU_hard_seconds": 900,
    "wall_hard_seconds": 1200,
}


def run(metadata, state, phase, npz_b64, roster, package):
    package = Path(package)
    graph = build_graph(metadata, state, phase, npz_b64, roster)
    summary = graph.pop("summary")
    conceptual_bytes = summary["fp64_coordinate_denominator"] * 8
    largest_bytes = summary["largest_capsule_coordinates"] * 8
    combined_bytes = 2 * conceptual_bytes
    raw_size_caps_satisfied = (
        largest_bytes <= N128_COMPARISON_CAPS["per_capsule_raw_bytes"]
        and combined_bytes
        <= N128_COMPARISON_CAPS["cumulative_logical_packet_bytes"]
    )
    return {
        "schema": "hcsn-n256-engineering-static-resource-audit-v1",
        "status": (
            "PASS_SOURCE_BOUND_HOLD"
            if raw_size_caps_satisfied
            else "RED_RESOURCE_CAP_HOLD"
        ),
        "roster_identity": summary["coordinate_identity_sha256"],
        "input_sha256": graph["input_sha256"],
        "input_bundle_sha256": graph["input_bundle_sha256"],
        "historical_N256_export_present": False,
        "new_export_only": True,
        "capsules": summary["capsules"],
        "packet_tuples": summary["packet_tuples"],
        "coordinate_spans": summary["coordinate_spans"],
        "fp64_coordinate_denominator": summary["fp64_coordinate_denominator"],
        "conceptual_candidate_bytes": conceptual_bytes,
        "conceptual_candidate_and_dense_oracle_bytes": combined_bytes,
        "largest_capsule_bytes": largest_bytes,
        "candidate_operators": graph["operators"],
        "candidate_operator_nnz": graph["operator_nnz"],
        "unique_sparse_operator_bytes": graph["unique_sparse_operator_bytes"],
        "templates_emitted": graph["templates_emitted"],
        "transition_segments": graph["transition_segments"],
        "upper_sink_nnz": graph["upper_sink_nnz"],
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.glob("*.py"))
        },
        "pinned_n128_primitive_source_sha256": N128_PRIMITIVE_SOURCE_SHA256,
        "n128_caps_comparison_only": N128_COMPARISON_CAPS,
        "raw_size_caps_satisfied": raw_size_caps_satisfied,
        "n256_numerical_allocation_frozen": False,
        "dynamic_resource_safe": False,
        "dynamic_resource_reason": (
            "N128 raw caps are exceeded and no N256 expm workspace/RSS, "
            "serializer/oracle, host+cgroup allocation, or calendar is frozen"
        ),
        "dynamic_runs": 0,
        "spatial_operator_materializations": 1,
        "matrix_exponentials": 0,
        "oracle_numeric_calls": 0,
        "serializer_numeric_calls": 0,
        "torch_calls": 0,
        "backward_calls": 0,
        "optimizer_steps": 0,
        "training_runs": 0,
        "numerical_execution_key": None,
        "fullstate_oracle_complete": False,
        "largegrid_qualification": False,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--npz-b64", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(
        args.metadata,
        args.state,
        args.phase,
        args.npz_b64,
        args.roster,
        Path(__file__).resolve().parent,
    )
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "fp64_coordinate_denominator",
                    "candidate_operators",
                    "candidate_operator_nnz",
                    "raw_size_caps_satisfied",
                    "dynamic_runs",
                    "admission",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
