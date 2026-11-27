"""Bounded resource profile for the four authentic #6264 N128 operators.

This module deliberately performs no packet propagation, oracle comparison,
Torch operation, optimizer step, or training.  It materializes the exact
#6264 graph, captures the unique CSR generators created by that frozen source,
and calls SciPy ``expm`` exactly once for each unique dense generator at the
frozen interval of 0.2 seconds.
"""

import argparse
import hashlib
import json
import math
import resource
import time
from pathlib import Path

import numpy as np
from scipy.linalg import expm

from qualification.hcsn_currentstate_n128_engineering import candidate


EXPECTED_SHAPES = ((1, 0), (127, 379), (128, 381), (255, 762))
DT = 0.2


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def dense(operator):
    matrix = np.zeros((operator.dimension, operator.dimension), dtype=np.float64)
    for row in range(operator.dimension):
        left, right = operator.indptr[row], operator.indptr[row + 1]
        matrix[row, operator.indices[left:right]] = operator.data[left:right]
    return matrix


def capture_operators(law, metadata, arrays, roster):
    captured = []
    original = candidate.CSR.__dict__["from_rows"]

    def wrapper(cls, rows):
        operator = original.__func__(cls, rows)
        captured.append(operator)
        return operator

    candidate.CSR.from_rows = classmethod(wrapper)
    try:
        graph = candidate.build_graph(law, metadata, arrays, roster)
    finally:
        candidate.CSR.from_rows = original
    operators = {operator.identity: operator for operator in captured}
    ordered = sorted(
        operators.values(), key=lambda operator: (operator.dimension, len(operator.data))
    )
    shapes = tuple((operator.dimension, len(operator.data)) for operator in ordered)
    if shapes != EXPECTED_SHAPES:
        raise ValueError(f"authentic operator shapes differ: {shapes!r}")
    if graph["operators"] != 4 or graph["operator_nnz"] != 1522:
        raise ValueError("#6264 graph operator counts differ")
    return graph, ordered


def run(args):
    graph, operators = capture_operators(
        args.law, args.metadata, args.arrays, args.roster
    )
    rows = []
    expm_calls = 0
    for order, operator in enumerate(operators):
        matrix = dense(operator)
        started = time.perf_counter()
        expm_calls += 1
        result = expm(DT * matrix)
        wall = time.perf_counter() - started
        if result.shape != matrix.shape or not np.isfinite(result).all():
            raise ValueError("nonfinite or malformed matrix exponential")
        rows.append(
            {
                "order": order,
                "operator_identity": operator.identity,
                "dimension": operator.dimension,
                "nnz": len(operator.data),
                "dense_input_bytes": matrix.nbytes,
                "dense_output_bytes": result.nbytes,
                "wall_seconds": wall,
                "result_sha256": sha256(result.tobytes(order="C")),
                "result_frobenius_norm": float(np.linalg.norm(result)),
                "result_max_abs": float(np.max(np.abs(result))),
            }
        )
    if (
        len(rows) != 4
        or expm_calls != 4
        or any(not math.isfinite(row["wall_seconds"]) for row in rows)
    ):
        raise ValueError("four finite resource rows required")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": args.identity,
        "unique_execution_key": args.key,
        "status": "PASS_BOUNDED_N128_EXPM_RESOURCE_PROFILE_ONLY",
        "source_commit": args.source_commit,
        "dt": DT,
        "calls": {
            "candidate_graph_materializations": 1,
            "matrix_exponentials": expm_calls,
            "dynamic_packet_steps": 0,
            "oracle_calls": 0,
            "torch_operations": 0,
            "optimizer_updates": 0,
        },
        "operators": rows,
        "graph_counts": {
            "operators": graph["operators"],
            "operator_nnz": graph["operator_nnz"],
            "templates_emitted": graph["templates_emitted"],
            "transition_segments": graph["transition_segments"],
            "conceptual_coordinates": graph["conceptual_coordinates"],
        },
        "process_max_rss_kib": usage.ru_maxrss,
        "qualification": False,
        "remaining_open": [
            "dynamic packet core",
            "full-state oracle",
            "serializer and cold recovery",
            "current-state numerical qualification",
            "N256 and N512 actual execution",
        ],
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (output / "OPERATORS.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--law", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--arrays", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source-commit", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
