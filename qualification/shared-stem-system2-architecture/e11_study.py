"""E11 finite stochastic research execution, re-audit, and explicit NO-GO.

This is genuinely executed Python exact-arithmetic work on SYNTHETIC
registered finite laws. It makes zero neural/pretrained model forwards.
The audit independently re-solves the complete tree; CPU timings are
self-observed and explicitly not target-host independent attestations.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import process_time_ns, perf_counter_ns
import json

from e11_dense_reference import exact_dense_system
from e11_stochastic_tree import Law, affine_trace, certify, cheap_root

SCHEMA = "hepta.e11.finite-stochastic-coupled-costs.v1"
STUDIES = tuple((n, a) for n in (1, 2, 3) for a in ("0", "1/3"))
REPEATS = 6


def strict_json(path: str):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= 2_000_000:
        raise ValueError("missing or oversized research input")
    def pairs(entries):
        obj = {}
        for key, value in entries:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj
    doc = json.loads(raw, object_pairs_hook=pairs,
                     parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    return doc, sha256(raw).hexdigest()


def dump_once(path: str, value):
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    with Path(path).open("xb") as f:
        f.write(data)
    return sha256(data).hexdigest()


def meter(fn):
    cpu = process_time_ns()
    wall = perf_counter_ns()
    result = fn()
    return result, process_time_ns()-cpu, perf_counter_ns()-wall


def execute(path: str):
    all_records = []
    for n, a in STUDIES:
        law = Law(steps=n, a=a)
        cheap_cpu, tree_cpu, dense_cpu = [], [], []
        cheap_wall, tree_wall, dense_wall = [], [], []
        for _ in range(REPEATS):
            root, cpu, wall = meter(lambda: cheap_root(law))
            cheap_cpu.append(cpu); cheap_wall.append(wall)
            tree, cpu, wall = meter(lambda: affine_trace(law))
            tree_cpu.append(cpu); tree_wall.append(wall)
            dense, meta = None, None
            (dense, meta), cpu, wall = meter(lambda: exact_dense_system(law))
            dense_cpu.append(cpu); dense_wall.append(wall)
            if tree != dense or str(root) != tree.states[0].y:
                raise ValueError("independent finite stochastic control mismatch")
            if not certify(law, dense).globally_consistent_registered_law:
                raise ValueError("full-tree stochastic verification rejected")
        all_records.append({
            "law": asdict(law), "root_y": str(root),
            "complete_node_count": len(tree.states),
            "independent_dense_equations": meta["equation_count"],
            "dense_nonzero_eliminations": meta["nonzero_elimination_steps"],
            "root_only_cpu_ns": cheap_cpu, "root_only_wall_ns": cheap_wall,
            "cheap_full_tree_cpu_ns": tree_cpu, "cheap_full_tree_wall_ns": tree_wall,
            "exact_dense_cpu_ns": dense_cpu, "exact_dense_wall_ns": dense_wall,
        })
    result = {
        "schema": SCHEMA, "authority": "DENY_ALL",
        "production_accepted": False,
        "real_pretrained_encoder_forwards": 0,
        "natural_task_outcomes_observed": False,
        "continuous_fbsde_qualified": False,
        "source_signed_independently": False,
        "synthetic_law_only": True,
        "repeat_count": REPEATS, "cases": all_records,
    }
    return dump_once(path, result)


def audit(path: str, source_sha: str, output: str, *, e10_path: str | None = None):
    src, original_sha = strict_json(path)
    if type(source_sha) is not str or original_sha != source_sha:
        raise ValueError("source bytes not frozen before independent review")
    if (type(src) is not dict or set(src) != {
        "schema", "authority", "production_accepted",
        "real_pretrained_encoder_forwards", "natural_task_outcomes_observed",
        "continuous_fbsde_qualified", "source_signed_independently",
        "synthetic_law_only", "repeat_count", "cases",
    } or src["schema"] != SCHEMA or src["authority"] != "DENY_ALL"
            or src["production_accepted"] is not False
            or src["real_pretrained_encoder_forwards"] != 0
            or src["natural_task_outcomes_observed"] is not False
            or src["continuous_fbsde_qualified"] is not False
            or src["source_signed_independently"] is not False
            or src["synthetic_law_only"] is not True
            or type(src["repeat_count"]) is not int or src["repeat_count"] != REPEATS
            or type(src["cases"]) is not list or len(src["cases"]) != len(STUDIES)):
        raise ValueError("unqualified source or incomplete registered case set")
    max_cpu = 0
    for result, (n, a) in zip(src["cases"], STUDIES):
        if type(result) is not dict or set(result) != {
            "law", "root_y", "complete_node_count", "independent_dense_equations",
            "dense_nonzero_eliminations", "root_only_cpu_ns", "root_only_wall_ns",
            "cheap_full_tree_cpu_ns", "cheap_full_tree_wall_ns",
            "exact_dense_cpu_ns", "exact_dense_wall_ns",
        }:
            raise ValueError("incomplete timing and model output receipt")
        law = Law(steps=n, a=a)
        if result["law"] != asdict(law):
            raise ValueError("profile predeclared cases changed")
        root = cheap_root(law)
        dense, meta = exact_dense_system(law)
        if not certify(law, dense).globally_consistent_registered_law:
            raise ValueError("original full FBSDE model unsupported")
        if result["root_y"] != str(root) or dense.states[0].y != str(root):
            raise ValueError("forged or inconsistent reported root solution")
        if result["complete_node_count"] != len(dense.states) or (
            result["independent_dense_equations"] != meta["equation_count"]
            or result["dense_nonzero_eliminations"] != meta["nonzero_elimination_steps"]
        ):
            raise ValueError("false physical computation inventory")
        for key in ("root_only_cpu_ns", "root_only_wall_ns",
                    "cheap_full_tree_cpu_ns", "cheap_full_tree_wall_ns",
                    "exact_dense_cpu_ns", "exact_dense_wall_ns"):
            values = result[key]
            if type(values) is not list or len(values) != REPEATS or any(
                type(v) is not int or v <= 0 or v >= 10**12 for v in values
            ):
                raise ValueError("missing/nonphysical research samples")
            max_cpu = max(max_cpu, max(values))
    e10_result = None
    if e10_path is not None:
        e10, e10sha = strict_json(e10_path)
        if (type(e10) is not dict
                or e10.get("schema") != "hepta.e10.retrospective-three-metric-Pareto-and-exact-paired-review.v1"
                or e10.get("authority") != "DENY_ALL"
                or e10.get("decision") != "NO_GO_FOR_PROMOTION"
                or e10.get("all_four_policies_strictly_dominated_in_registered_historical_metrics") is not True
                or e10.get("production_accepted") is not False):
            raise ValueError("real predecessor negative-E10 receipt not intact")
        # Recompute E10 independently from both original inherited E7
        # reviewers, not merely from E10 self-asserted decision/status flags.
        # These are retrospective archive summaries, NOT original signer
        # authentication or new Encoder execution.
        from e10_paired_pareto import review as recompute_e10
        observations = Path(__file__).resolve().parent / "observations"
        first, first_sha = strict_json(str(
            observations / "E7_ORIGINAL_PHYSICAL_RETROSPECTIVE_20261015.json"))
        second, second_sha = strict_json(str(
            observations / "E7_INDEPENDENT_SECOND_ALGORITHM_20261015.json"))
        if recompute_e10(first, second) != e10:
            raise ValueError("E10 retrospective decision differs from two original E7 independent reviewers")
        e10_result = {
            "source_sha256": e10sha,
            "independent_e7_first_sha256": first_sha,
            "independent_e7_second_sha256": second_sha,
            "retrospective_no_go": True,
            "not_a_future_time_efficacy_result": True,
            "exact_paired_and_Holm_recomputed": True,
        }
    verdict = {
        "schema": "hepta.e11.independent-exact-stochastic-review.v1",
        "source_sha256": original_sha,
        "authority": "DENY_ALL",
        "all_exact_dense_and_affine_root_outputs_match": True,
        "all_full_binary_stochastic_trees_globally_verified": True,
        "registered_case_count": len(STUDIES),
        "root_control_result": "NO_INCREMENTAL_ANSWER_QUALITY_IN_LINEAR_SPECIAL_CASE",
        "E10_actual_archive_check": e10_result,
        "timings_are_self_observed_not_independently_attested": True,
        "actual_hardware_target_host_claim": False,
        "new_pretrained_forward_count": 0,
        "natural_reasoning_efficacy": False,
        "global_continuous_stochastic_fbsde_theorem": False,
        "production_accepted": False,
        "largest_reported_timer_ns_not_an_accepted_cost_proof": max_cpu,
    }
    return dump_once(output, verdict)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="mode", required=True)
    p_run = subs.add_parser("execute")
    p_run.add_argument("--output", required=True)
    p_audit = subs.add_parser("audit")
    p_audit.add_argument("--input", required=True)
    p_audit.add_argument("--input-sha256", required=True)
    p_audit.add_argument("--output", required=True)
    p_audit.add_argument("--e10", default=None)
    args = ap.parse_args()
    if args.mode == "execute":
        result = execute(args.output)
    else:
        result = audit(args.input, args.input_sha256, args.output,
                       e10_path=args.e10)
    print(json.dumps({"mode": args.mode, "file_sha256": result, "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
