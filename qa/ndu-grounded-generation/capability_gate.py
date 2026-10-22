"""Independent, fail-closed capability audit over *frozen* NDU v1 evidence.

This is a post-hoc readiness screen for a future v2 experiment, never a
retroactive change to the original v1 test protocol, metrics, or conclusions.
A pass of one gate cannot be promoted into an end-to-end capability claim.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


class EvidenceError(ValueError):
    pass


def _load_json(path):
    return json.loads(Path(path).read_text())


def _load_rows(path):
    with Path(path).open() as file:
        rows = [json.loads(line) for line in file if line.strip()]
    if not rows:
        raise EvidenceError(f"empty journal: {path}")
    return rows


def _gate(ok, reason, **facts):
    return {"status": "pass" if ok else "open", "reason": reason, "facts": facts}


def _reconcile_report(report, roster, expected_methods):
    """Independently compute reported v1 fields from every full scored row.

    Without this check, a mutated aggregate could silently flip a gate even
    though the immutable per-episode measurements disagree.
    """
    points = report.get("points")
    if not isinstance(points, list) or len(points) != len(expected_methods):
        raise EvidenceError("the aggregate point roster is missing or changed")
    by_method = {point.get("method"): point for point in points}
    if set(by_method) != expected_methods:
        raise EvidenceError("the aggregate method set disagrees with the journal")
    if any(set(rows) != expected_methods for rows in roster.values()):
        raise EvidenceError("a task-seed lacks at least one planned method")
    source_map = {}
    for (task_id, seed), rows in roster.items():
        sources = {row["score"]["source_id"] for row in rows.values()}
        if len(sources) != 1:
            raise EvidenceError(f"source mismatch within task-seed group: {task_id}")
        if task_id in source_map and source_map[task_id] != sources:
            raise EvidenceError(f"source ID changed across seeds: {task_id}")
        source_map[task_id] = sources
    alpha = report.get("alpha")
    if type(alpha) not in (int, float) or not 0 < alpha < 1:
        raise EvidenceError("invalid CVaR alpha")
    for method, point in by_method.items():
        group = [rows[method] for rows in roster.values()]
        n = len(group)
        quality, wall, coverage, severe = [], [], [], []
        for row in group:
            score = row["score"]
            values = (score.get("quality"), score.get("wall_seconds"),
                      score.get("coverage"), score.get("severe"), row["actual_wall_seconds"])
            if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                raise EvidenceError("missing/nonfinite scored quality/coverage/time")
            if not (0 <= values[0] <= 1 and 0 <= values[2] <= 1 and 0 <= values[3] <= 1):
                raise EvidenceError("invalid quality/coverage/severe in full journal")
            if abs(values[1] - values[4]) > 1e-8:
                raise EvidenceError("score and measured wall differ")
            quality.append(float(values[0])); wall.append(float(values[1]));
            coverage.append(float(values[2])); severe.append(float(values[3]))
        tail_count = (1-alpha)*n
        if tail_count <= 0:
            raise EvidenceError("CVaR tail mass is zero")
        losses = sorted((1-q for q in quality), reverse=True)
        full = int(tail_count)
        cvar = (sum(losses[:full]) + (tail_count - full)*losses[full]) / tail_count
        expected = {"episodes": n, "source_groups": len(source_map),
                    "quality": sum(quality)/n, "wall_seconds": sum(wall)/n,
                    "coverage": sum(coverage)/n, "severe": sum(severe)/n, "cvar": cvar}
        for field, value in expected.items():
            if field not in point or type(point[field]) not in (int, float) or abs(point[field] - value) > 1e-8:
                raise EvidenceError(f"aggregate/journal mismatch: {method}.{field}")
    return {"full_episode_rows": len(roster)*len(expected_methods),
            "task_seed_groups": len(roster), "source_groups": len(source_map),
            "reconciled_metrics": ["episodes", "source_groups", "quality", "wall_seconds", "coverage", "severe", "cvar"]}


def evaluate_capabilities(report, protocol, episodes, *,
                          minimum_decisions=8, maximum_decisions=16,
                          minimum_seeds=3, minimum_sources=128,
                          wall_tolerance=0.05):
    if (report.get("schema") != "hepta.ndu-grounded-evaluation.v1"
            or protocol.get("schema") != "hepta.ndu-grounded-protocol.v1"):
        raise EvidenceError("v1 report and protocol schemas required")
    if not episodes or not isinstance(episodes, list):
        raise EvidenceError("original full episode journal required")
    expected_methods = set(report["required_methods"])
    roster = defaultdict(dict)
    for row in episodes:
        if not isinstance(row, dict):
            raise EvidenceError("invalid journal record")
        for key in ("task_id", "method", "seed", "score", "trajectory", "actual_wall_seconds"):
            if key not in row:
                raise EvidenceError(f"missing journal field: {key}")
        key = (row["task_id"], row["seed"])
        method = row["method"]
        if method not in expected_methods or method in roster[key]:
            raise EvidenceError("unknown/duplicate method in task-seed roster")
        score = row["score"]
        if (score.get("quality") is None or score.get("coverage") is None
                or score.get("source_id") is None):
            raise EvidenceError("complete scored records and source IDs required")
        roster[key][method] = row
    original_methods = {method for rs in roster.values() for method in rs}
    if original_methods != expected_methods:
        raise EvidenceError("planned method menu is incomplete")
    ledger = _reconcile_report(report, roster, expected_methods)
    ndu = [row for row in episodes if row["method"] == "ndu"]
    if not ndu:
        raise EvidenceError("missing NDU episodes")
    decisions = [len((row.get("trajectory") or {}).get("actions", [])) for row in ndu]
    completed = [row for row in ndu if row["score"]["coverage"] == 1.0]
    valid_decisions = [len((row.get("trajectory") or {}).get("actions", [])) for row in completed]
    seed_values = sorted({row["seed"] for row in ndu})
    source_ids = {row["score"]["source_id"] for row in ndu}
    controls_pass = bool(completed) and all(minimum_decisions <= n <= maximum_decisions for n in valid_decisions)
    chosen_risk = report.get("selection", {}).get("chosen_risk_weight")
    if chosen_risk is None:
        raise EvidenceError("missing frozen development selection")
    # Identifiable covariance *causal* benefit requires predeclared paired
    # intervention outcomes. A nonzero scalar alone is never sufficient.
    paired = {}
    for row in ndu:
        counterpart = roster.get((row["task_id"], row["seed"]), {}).get("ablate_covariance")
        if counterpart is None:
            continue
        paired[row["task_id"], row["seed"]] = (row, counterpart)
    changed_outputs = sum((a.get("raw_text") != b.get("raw_text") or a.get("boxes") != b.get("boxes"))
                          for a,b in paired.values())
    jointly_completed = [(a,b) for a,b in paired.values()
                         if a["score"]["coverage"] == b["score"]["coverage"] == 1.0]
    changed_jointly_completed = sum((a.get("raw_text") != b.get("raw_text") or a.get("boxes") != b.get("boxes"))
                              for a,b in jointly_completed)
    # Some observable differences can be entirely induced by runtime failure:
    # no inference of a beneficial covariance mechanism follows from them.
    # Only one pre-selected weight and no pre-registered independent
    # terminal-covariance estimator: the v1 mechanism is unidentifiable,
    # regardless of post-hoc observed outcome changes.
    covariance_identified = False
    # The v1 protocol explicitly does not generate two independent modalities.
    # The v1 run cannot gain independent generation merely because someone
    # edits two protocol booleans after the fact. A separate v2 generator and
    # independent semantic/pixel receipts are required.
    independent_outputs = False
    # A single shared cap is not cost matching. We report actual measured cost.
    point_by_name = {point["method"]: point for point in report["points"]}
    if not {"ndu", "best_of_n"} <= set(point_by_name):
        raise EvidenceError("required NDU/best-of-N aggregate points unavailable")
    candidate, baseline = point_by_name["ndu"], point_by_name["best_of_n"]
    actual_cost_gap = candidate["wall_seconds"] / baseline["wall_seconds"] - 1
    coverage_gap = candidate["coverage"] - baseline["coverage"]
    paired_costs = [
        (row, roster[(row["task_id"], row["seed"])]["best_of_n"])
        for row in ndu if "best_of_n" in roster[(row["task_id"], row["seed"])]
    ]
    paired_matching = sum(
        abs(a["actual_wall_seconds"] - b["actual_wall_seconds"]) /
        max(b["actual_wall_seconds"], 1e-9) <= wall_tolerance and
        a["score"]["coverage"] == b["score"]["coverage"]
        for a, b in paired_costs
    )
    matched_pair_fraction = paired_matching / len(paired_costs) if paired_costs else 0.0
    cost_matched = (abs(actual_cost_gap) <= wall_tolerance and coverage_gap == 0
                    and matched_pair_fraction >= 0.95)
    frontier = set(report.get("empirical_frontier", []))
    frontier_ndu = any(point.get("point_id") in frontier for point in report["points"] if point["method"] == "ndu")
    # Conservative improvement demands independently confirmed outcomes,
    # never mere nondominance on a descriptive first test.
    # No single-seed, previously opened v1 test can be promoted into an
    # independent confirmatory experiment, even if aggregate flags are edited.
    confirmatory = False
    flags = Counter(decisions)
    gates = {
        "frozen_v1_ledger_consistency": _gate(True, "all journal rows reconcile to the original reported aggregates", **ledger),
        "actual_control_horizon": _gate(controls_pass, "require every completed NDU source to exercise 8-16 actual decisions", completed=len(completed), attempted=len(ndu), decisions_histogram=dict(sorted(flags.items())), min_required=minimum_decisions, max_allowed=maximum_decisions),
        "covariance_causal_identification": _gate(covariance_identified, "nonzero risk weight plus independently controlled, beneficial covariance intervention required", selected_risk_weight=chosen_risk, paired_ablation_rows=len(paired), changed_raw_outputs=changed_outputs, jointly_completed=len(jointly_completed), changed_jointly_completed=changed_jointly_completed, intervention_benefit_unverified=True),
        "independent_text_and_pixel_generation": _gate(independent_outputs, "both modalities must be independently learned and separately evaluated", free_text=protocol["task"].get("independent_free_text_generation"), pixels=protocol["task"].get("learned_pixel_generation")),
        "per_cell_counterfactual_attribution": _gate(False, "v1 has no four one-Cell-at-a-time matched ablation roster", required_cells=["semantic", "horizontal", "vertical", "completion"]),
        "cost_and_coverage_equivalence": _gate(cost_matched, "paired-design cost matching cannot be inferred from a common wall cap", actual_wall_ratio_minus_one=actual_cost_gap, coverage_delta=coverage_gap, wall_tolerance=wall_tolerance, paired_comparisons=len(paired_costs), matching_pairs=paired_matching, matching_pair_fraction=matched_pair_fraction, required_pair_fraction=0.95, method="ndu", comparator="best_of_n", mean_only_diagnostic_not_equivalence=True),
        "repeated_decoding_seeds_and_power": _gate(len(seed_values) >= minimum_seeds and len(source_ids) >= minimum_sources, "require >=3 decoder seeds and >=128 distinct held-out sources for v2 preflight (not sufficient for statistical power)", actual_seeds=seed_values, unique_sources=len(source_ids), min_seeds=minimum_seeds, min_sources=minimum_sources),
        "confirmatory_frontier_advantage": _gate(confirmatory, "descriptive nondominance is not a confirmatory quality-risk-cost gain", empirical_frontier=sorted(frontier), ndu_nondominated=frontier_ndu, experiment_pass=report.get("experiment_pass")),
        "untouched_v2_cohort": _gate(False, "v1 test cannot be recycled as the next confirmatory cohort; requires a separate v2 manifest and cross-history firewall", historical_test_sources=len(source_ids)),
        "complete_state_and_continuous_fbsde": _gate(False, "action-only discrete BSDE with incomplete observed state; no continuous FBSDE convergence", state_complete=protocol["training"]["ndu"]["state_representation_complete"], continuous_solved=protocol["training"]["ndu"]["continuous_FBSDE_solved"]),
    }
    return {"schema": "hepta.ndu-capability-gates.v2-preflight-1",
            "scope": "post-hoc eligibility audit of the immutable v1 run, not new v2 experimental outcomes",
            "measurement_receipt_hashes": {},
            "v1_engineering_pass": report.get("engineering_pass"),
            "v1_experiment_pass": report.get("experiment_pass"),
            "gates": gates,
            "passed": [k for k,v in gates.items() if v["status"] == "pass"],
            "open": [k for k,v in gates.items() if v["status"] != "pass"],
            "all_scientific_gates_closed": all(v["status"] == "pass" for v in gates.values()),
            "repository_ci_not_included": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    bundle = Path(args.bundle_root)
    try:
        paths = {
            "report": bundle / "results" / "summary-report.json",
            "protocol": bundle / "code" / "protocol.json",
            "episodes": bundle / "raw" / "test.episodes.jsonl",
        }
        result = evaluate_capabilities(_load_json(paths["report"]), _load_json(paths["protocol"]), _load_rows(paths["episodes"]))
        result["measurement_receipt_hashes"] = {key: hashlib.sha256(value.read_bytes()).hexdigest() for key,value in paths.items()}
        status = 0 if result["all_scientific_gates_closed"] else 2
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {"schema": "hepta.ndu-capability-gates.v2-preflight-1", "status": "invalid_evidence", "error": str(exc), "all_scientific_gates_closed": False}
        status = 2
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"all_scientific_gates_closed": result["all_scientific_gates_closed"], "output": str(dest), "open": result.get("open", [])}, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
