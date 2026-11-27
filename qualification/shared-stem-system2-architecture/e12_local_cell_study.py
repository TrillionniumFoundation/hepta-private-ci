"""Sealed Cell-message FBSDE solve; separately replayed with E12's prefix oracle.

The producer cannot read E12's global solution, test labels, or a model.
The reviewer replays every reported contraction iteration independently and
checks original E12 source algebra, all X/Y/Z interfaces and source bytes.
"""

from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import argparse
import json

from e12_nonlinear_cert import Law
from e12_independent_audit import reference, round_even
from e12_local_cell_solver import solve_local_cells
from e12_cell_boundary import review_segments, split_result
from e12_cell_boundary_study import _decode_bundle
from e12_study import PROFILES, _decode_cert, read_strict, write_once

SCHEMA = "hepta.e12.oracle-free-local-cells.v1"
_EXPECTED = {"schema", "scope_sha256", "authority", "cases", "original_global_solver_calls",
             "pretrained_model_forwards", "natural_reasoning_gain_proven",
             "continuous_time_fbsde_proven", "production_accepted"}


def _scope(law: Law) -> str:
    payload = json.dumps(asdict(law), sort_keys=True, separators=(",", ":"))
    return sha256((SCHEMA + "\n" + payload).encode()).hexdigest()


def produce(output: str) -> str:
    cases = []
    for depth, a in PROFILES:
        law = Law(depth=depth, a=a)
        # This is the entire producer's mathematical input. No source Solve.
        attempt = solve_local_cells(law)
        bundle = split_result(law, attempt.result, _scope(law))
        cases.append({
            "depth": depth, "coupling": a,
            "solution": asdict(attempt.result),
            "boundary": asdict(bundle),
            "iterations": [asdict(step) for step in attempt.iterations],
            "physical_forward_cells": attempt.forward_cell_invocations,
            "physical_backward_cells": attempt.backward_cell_invocations,
            "reference_operator_calls": attempt.reference_operator_calls,
            "pretrained_model_forwards": attempt.pretrained_model_forwards,
        })
    return write_once(output, {
        "schema": SCHEMA, "scope_sha256": sha256(SCHEMA.encode()).hexdigest(),
        "authority": "DENY_ALL", "cases": cases,
        "original_global_solver_calls": 0, "pretrained_model_forwards": 0,
        "natural_reasoning_gain_proven": False,
        "continuous_time_fbsde_proven": False, "production_accepted": False,
    })


def review(candidate: str, expected_sha: str, output: str) -> str:
    proposal, digest = read_strict(candidate)
    if (type(expected_sha) is not str or digest != expected_sha or
        type(proposal) is not dict or set(proposal) != _EXPECTED or
        proposal["schema"] != SCHEMA or
        proposal["scope_sha256"] != sha256(SCHEMA.encode()).hexdigest() or
        proposal["authority"] != "DENY_ALL" or
        type(proposal["original_global_solver_calls"]) is not int or
        proposal["original_global_solver_calls"] != 0 or
        type(proposal["pretrained_model_forwards"]) is not int or
        proposal["pretrained_model_forwards"] != 0 or
        any(proposal[k] is not False for k in
            ("natural_reasoning_gain_proven", "continuous_time_fbsde_proven",
             "production_accepted")) or
        type(proposal["cases"]) is not list or len(proposal["cases"]) != len(PROFILES)):
        raise ValueError("wrong source digest, schema, complete roster or authority")

    decisions = []
    for row, (depth, coupling) in zip(proposal["cases"], PROFILES):
        if (type(row) is not dict or set(row) != {
            "depth", "coupling", "solution", "boundary", "iterations",
            "physical_forward_cells", "physical_backward_cells",
            "reference_operator_calls", "pretrained_model_forwards",
        } or type(row["depth"]) is not int or row["depth"] != depth or
            row["coupling"] != coupling or
            type(row["reference_operator_calls"]) is not int or
            row["reference_operator_calls"] != 0 or
            type(row["pretrained_model_forwards"]) is not int or
            row["pretrained_model_forwards"] != 0):
            raise ValueError("wrong registered arm, row fields or model-call claim")
        law = Law(depth=depth, a=coupling)
        result = _decode_cert(row["solution"])
        p = law.values()
        if result.law != asdict(law) or result.authority != "DENY_ALL":
            raise ValueError("changed registered stochastic law")
        iterations = row["iterations"]
        n = (1 << depth) - 1
        if (type(iterations) is not list or len(iterations) != result.evaluations or
            not 1 <= len(iterations) <= 24 or
            type(row["physical_forward_cells"]) is not int or
            type(row["physical_backward_cells"]) is not int or
            row["physical_forward_cells"] != len(iterations) * n or
            row["physical_backward_cells"] != len(iterations) * n):
            raise ValueError("missing physical per-Cell event census")
        # INDEPENDENT prefix-map mathematical implementation; the reviewer
        # never invokes producer local Cell functions or E12.solve/operator.
        inputs = (Q(0),) * n
        for i, receipt in enumerate(iterations, 1):
            if type(receipt) is not dict or set(receipt) != {
                "index", "residual", "global_bound", "forward_cells",
                "backward_cells", "accepted",
            }:
                raise ValueError("incomplete iteration certificate")
            _forward, _backward, mapped = reference(law, inputs)
            residual = max(abs(left - right) for left, right in zip(inputs, mapped))
            bound = residual / (1 - p["q"])
            complete = bound <= Q(result.requested_tolerance)
            if (type(receipt["index"]) is not int or receipt["index"] != i or
                receipt["residual"] != str(residual) or
                receipt["global_bound"] != str(bound) or
                type(receipt["forward_cells"]) is not int or
                receipt["forward_cells"] != n or
                type(receipt["backward_cells"]) is not int or
                receipt["backward_cells"] != n or
                type(receipt["accepted"]) is not bool or
                receipt["accepted"] != complete or complete != (i == len(iterations))):
                raise ValueError("forged local iteration, premature stop or global bound")
            if not complete:
                inputs = tuple(round_even(v, result.quantization_bits) for v in mapped)
        original = tuple(Q(node.y) for node in result.trace.states[:n])
        if inputs != original:
            raise ValueError("final local Cell state differs from independent replay")
        verified = review_segments(law, result, _decode_bundle(row["boundary"]), _scope(law))
        decisions.append({
            "depth": depth, "coupling": coupling,
            "iterations_replayed": len(iterations),
            "per_cell_updates_checked": len(iterations) * n * 2,
            "original_global_solver_calls": 0,
            "whole_tree_certified_discrete": verified.certified_discrete_global_error_bound,
            "no_general_fbsde_or_task_gain": True,
        })
    return write_once(output, {
        "schema": SCHEMA + ".independent-review",
        "candidate_sha256": digest, "authority": "DENY_ALL",
        "complete_source_roster_verified": True,
        "producer_local_messages_replayed_independently": True,
        "original_model_owner_authenticated": False,
        "continuous_time_fbsde_proven": False,
        "online_reasoning_gain_proven": False,
        "production_accepted": False,
        "decisions": decisions,
    })


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    x = sub.add_parser("produce")
    x.add_argument("--output", required=True)
    y = sub.add_parser("review")
    y.add_argument("--candidate", required=True)
    y.add_argument("--sha256", required=True)
    y.add_argument("--output", required=True)
    args = ap.parse_args()
    digest = produce(args.output) if args.mode == "produce" else review(
        args.candidate, args.sha256, args.output)
    print(json.dumps({"mode": args.mode, "sha256": digest, "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
