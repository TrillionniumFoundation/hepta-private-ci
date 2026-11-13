"""Read-only structural/count/memory audit; executes no oracle or dynamics."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from .candidate import build_graph


def imports(path):
    tree = ast.parse(Path(path).read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def run(law, metadata, npz, roster, package):
    package = Path(package)
    oracle_imports = imports(package / "oracle.py")
    comparator_imports = imports(package / "compare.py")
    if any(
        "candidate" in name
        or "serializer" in name
        or "loader" in name
        or "compare" in name
        for name in oracle_imports
    ):
        raise ValueError("oracle source isolation")
    if any("candidate" in name or "oracle" in name for name in comparator_imports):
        raise ValueError("comparator source isolation")
    graph = build_graph(law, metadata, npz, roster)
    summary = graph.pop("summary")
    conceptual_bytes = summary["fp64_coordinate_denominator"] * 8
    largest_bytes = summary["largest_capsule_coordinates"] * 8
    result = {
        "schema": "hcsn-n128-engineering-static-audit-v1",
        "status": "PASS_SOURCE_BOUND_HOLD",
        "roster_identity": summary["coordinate_identity_sha256"],
        "input_sha256": graph["input_sha256"],
        "capsules": summary["capsules"],
        "packet_tuples": summary["packet_tuples"],
        "coordinate_spans": summary["coordinate_spans"],
        "fp64_coordinate_denominator": summary["fp64_coordinate_denominator"],
        "conceptual_candidate_bytes": conceptual_bytes,
        "conceptual_candidate_and_dense_oracle_bytes": 2 * conceptual_bytes,
        "largest_capsule_bytes": largest_bytes,
        "candidate_operators": graph["operators"],
        "candidate_operator_nnz": graph["operator_nnz"],
        "unique_sparse_operator_bytes": graph["unique_sparse_operator_bytes"],
        "templates_emitted": graph["templates_emitted"],
        "transition_segments": graph["transition_segments"],
        "oracle_imports": oracle_imports,
        "comparator_imports": comparator_imports,
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.glob("*.py"))
        },
        "predeclared_caps": {
            "per_capsule_raw_bytes": 8_388_608,
            "cumulative_logical_packet_bytes": 201_326_592,
            "canonical_archive_bytes": 268_435_456,
            "candidate_process_AS_bytes": 2_147_483_648,
            "oracle_process_AS_bytes": 2_147_483_648,
            "parent_process_AS_bytes": 536_870_912,
            "total_CPU_hard_seconds": 900,
            "wall_hard_seconds": 1200,
        },
        "raw_size_caps_satisfied": largest_bytes <= 8_388_608
        and 2 * conceptual_bytes <= 201_326_592,
        "dynamic_resource_safe": False,
        "dynamic_resource_reason": "no frozen expm workspace/RSS bound or durable host+cgroup allocation",
        "dynamic_runs": 0,
        "matrix_exponentials": 0,
        "oracle_numeric_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "numerical_execution_key": None,
        "largegrid_qualification": False,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
    }
    if not result["raw_size_caps_satisfied"]:
        result["status"] = "RED_RESOURCE_CAP"
        raise RuntimeError(json.dumps(result, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--law", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--npz", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    result = run(args.law, args.json, args.npz, args.roster, package)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "fp64_coordinate_denominator",
                    "candidate_operators",
                    "candidate_operator_nnz",
                    "dynamic_runs",
                    "admission",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
