"""Recompute frozen mechanism results from raw records and complete-worker bills.

Scores do not come from summary score fields. Bootstrap resamples fitted seeds
then paired episodes/cases. Three fitted seeds warrant descriptive intervals,
not a claim about arbitrary architectures, datasets, or training pipelines.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np


ARMS = {"A": "ordinary_gated__lightweight", "B": "ordinary_gated__task_value",
        "C": "analytic__lightweight", "D": "analytic__task_value"}
METRICS = ("accuracy", "nll", "brier", "reads", "read_fees", "task_utility")
PAIRS = {"B-A": ("B", "A"), "D-C": ("D", "C"), "D-B": ("D", "B"), "C-A": ("C", "A")}
INTERVENTIONS = {
    "forecast_risk_suppression": (ARMS["D"], "analytic__task_value__forecast_risk_suppressed"),
    "fixed_actions_analytic_minus_ordinary": (ARMS["C"], "ordinary_gated__fixed_analytic_lightweight_actions"),
    "fixed_actions_analytic_minus_frozen": (ARMS["C"], "frozen_content__fixed_analytic_lightweight_actions")}


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as source:
        return [json.loads(line) for line in source if line.strip()]


def save(path, value, jsonl=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as target:
        if jsonl:
            for row in value:
                target.write(json.dumps(row, allow_nan=False) + "\n")
        else:
            json.dump(value, target, indent=2, allow_nan=False)
            target.write("\n")


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hierarchical(groups, replicates, seed):
    """Equal-weight fit means; multinomial episode weights preserve pairing."""
    arrays = [np.asarray(groups[key], dtype=float) for key in sorted(groups)]
    if len(arrays) != 3 or any(a.ndim != 2 or len(a) == 0 for a in arrays):
        raise ValueError("formal aggregation requires three nonempty fitted-seed groups")
    rng = np.random.default_rng(seed)
    boot = np.zeros((replicates, arrays[0].shape[1]))
    for _ in arrays:
        selected = rng.integers(len(arrays), size=replicates)
        for j, array in enumerate(arrays):
            positions = np.flatnonzero(selected == j)
            if len(positions):
                weights = rng.multinomial(len(array), np.full(len(array), 1 / len(array)), size=len(positions))
                boot[positions] += (weights @ array) / len(array) / len(arrays)
    point = np.mean([a.mean(axis=0) for a in arrays], axis=0)
    low, high = np.quantile(boot, [.025, .975], axis=0)
    return [{"mean": float(p), "ci95": [float(lo), float(hi)],
             "fit_seed_means": [float(a[:, i].mean()) for a in arrays]}
            for i, (p, lo, hi) in enumerate(zip(point, low, high))]


def content_map(trace, predictions):
    mapping = {r["tick"]: (r["propagated_content"], r["observed_state"]) for r in trace}
    mapping.update({r["tick"]: (r["probabilities"], r["observed_state"]) for r in predictions})
    return mapping


def divergences(left_trace, right_trace, left_predictions, right_predictions):
    left = {r["tick"]: r for r in left_trace}; right = {r["tick"]: r for r in right_trace}
    action = None
    for tick in sorted(set(left) | set(right)):
        a, b = left.get(tick), right.get(tick)
        aa = a["executed_action"] if a else "NO_FURTHER_CONTROL"
        bb = b["executed_action"] if b else "NO_FURTHER_CONTROL"
        if aa != bb:
            action = {"tick": tick, "left": aa, "right": bb,
                      "same_visible_state": bool(a and b and a["observed_state"] == b["observed_state"]),
                      "left_observed_state": a["observed_state"] if a else None,
                      "right_observed_state": b["observed_state"] if b else None}
            break
    lc, rc = content_map(left_trace, left_predictions), content_map(right_trace, right_predictions)
    content = None
    for tick in sorted(set(lc) & set(rc)):
        error = float(np.max(np.abs(np.array(lc[tick][0]) - rc[tick][0])))
        if error > 1e-8:
            content = {"tick": tick, "maximum_absolute_difference": error,
                       "same_visible_state": lc[tick][1] == rc[tick][1],
                       "left_probabilities": lc[tick][0], "right_probabilities": rc[tick][0]}
            break
    return {"first_actual_action_difference": action, "first_content_difference": content,
            "content_compared_only_at_common_evaluated_ticks": True}


def recompute_run(directory):
    job, summary = read(directory / "job.json"), read(directory / "summary.json")
    if job["split"] != "test":
        raise ValueError("development output cannot enter the formal aggregate")
    fit_seed = int(summary["training_cost_once"]["seed"])
    grouped, access, trace = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in lines(directory / "predictions.jsonl"):
        grouped[(row["episode"], row["arm"])].append(row)
    for row in lines(directory / "access.jsonl"):
        access[(row["episode"], row["arm"])].append(row)
    for row in lines(directory / "trace.jsonl"):
        trace[(row["episode"], row["arm"])].append(row)
    records, divergence_rows = [], []
    for (episode, arm), predictions in sorted(grouped.items()):
        p = np.asarray([r["probabilities"] for r in predictions], float)
        truth = np.asarray([r["truth_for_scoring_only"] for r in predictions], int)
        if np.any(p < -1e-12) or not np.allclose(p.sum(axis=1), 1, atol=1e-8):
            raise ValueError("invalid raw content probability")
        count = len(access[(episode, arm)])
        accuracy = float(np.mean(p.argmax(axis=1) == truth))
        row = {"job": directory.name, "condition": job["condition"], "fit_seed": fit_seed,
               "episode": episode, "episode_seed": predictions[0]["seed"], "arm": arm,
               "accuracy": accuracy, "nll": float(-np.log(np.maximum(p[np.arange(len(truth)), truth], 1e-12)).mean()),
               "brier": float(np.square(p - np.eye(p.shape[1])[truth]).sum(axis=1).mean()),
               "reads": count, "read_fees": count * job["read_cost"],
               "zero_label_probability_fraction": float(np.mean(p[np.arange(len(truth)), truth] <= 0)),
               "task_utility": accuracy - count * job["read_cost"], "outputs": len(truth)}
        records.append(row)
    compared = {"ordinary_controller": (ARMS["B"], ARMS["A"]),
                "analytic_controller": (ARMS["D"], ARMS["C"]),
                "core_under_lightweight": (ARMS["C"], ARMS["A"]),
                "core_under_task_value": (ARMS["D"], ARMS["B"]), **INTERVENTIONS}
    for episode in sorted({key[0] for key in grouped}):
        for name, (left, right) in compared.items():
            divergence_rows.append({"condition": job["condition"], "fit_seed": fit_seed,
                "episode": episode, "comparison": name, "left_arm": left, "right_arm": right,
                **divergences(trace[(episode, left)], trace[(episode, right)],
                              grouped[(episode, left)], grouped[(episode, right)])})
    return records, divergence_rows, summary


def aggregate_conditions(records, divergence_rows, replicates, seed):
    output = {}
    for condition in sorted({r["condition"] for r in records}):
        rows = [r for r in records if r["condition"] == condition]
        lookup = {(r["fit_seed"], r["episode"], r["arm"]): r for r in rows}
        columns = [(label, m) for label in ARMS for m in METRICS]
        columns += [(label, m) for label in (*PAIRS, "interaction", *INTERVENTIONS) for m in METRICS]
        groups = defaultdict(list)
        for fit, episode in sorted({(r["fit_seed"], r["episode"]) for r in rows}):
            arms = {a: lookup[(fit, episode, name)] for a, name in ARMS.items()}
            values = {}
            for metric in METRICS:
                for arm, row in arms.items():
                    values[(arm, metric)] = row[metric]
                for label, (a, b) in PAIRS.items():
                    values[(label, metric)] = arms[a][metric] - arms[b][metric]
                values[("interaction", metric)] = (arms["D"][metric] - arms["C"][metric]
                                                     - arms["B"][metric] + arms["A"][metric])
                for label, (a, b) in INTERVENTIONS.items():
                    values[(label, metric)] = lookup[(fit, episode, a)][metric] - lookup[(fit, episode, b)][metric]
            groups[fit].append([values[c] for c in columns])
        estimates = hierarchical(groups, replicates, seed)
        estimates_by_label = defaultdict(dict)
        for (label, metric), result in zip(columns, estimates):
            estimates_by_label[label][metric] = result
        differences = {}
        for name in sorted({r["comparison"] for r in divergence_rows}):
            chosen = [r for r in divergence_rows if r["condition"] == condition and r["comparison"] == name]
            item = {"paired_episodes": len(chosen)}
            for field in ("first_actual_action_difference", "first_content_difference"):
                observed = [r[field] for r in chosen if r[field] is not None]
                item[field] = {"episodes": len(observed), "fraction": len(observed) / len(chosen),
                    "median_tick": float(np.median([r["tick"] for r in observed])) if observed else None,
                    "same_visible_state_episodes": sum(r["same_visible_state"] for r in observed)}
            item["witnesses"] = [next((r for r in chosen if r["fit_seed"] == fit
                                      and (r["first_actual_action_difference"] or r["first_content_difference"])), None)
                                 for fit in sorted(groups)]
            differences[name] = item
        output[condition] = {"estimates": dict(estimates_by_label), "divergences": differences,
            "fit_seeds": sorted(groups), "episodes_per_fit": {str(k): len(v) for k, v in groups.items()},
            "primary_D_minus_B_utility_interval_above_zero": estimates_by_label["D-B"]["task_utility"]["ci95"][0] > 0,
            "metric_direction": "higher accuracy/utility better; lower nll/brier/reads/fees better; differences are literal left-minus-right"}
    return output


def recompute_diagnostics(directory):
    summary = read(directory / "summary.json")
    fit_seed = int(summary["training_cost_once"]["seed"])
    cases = {r["case"]: r for r in lines(directory / "cases.jsonl")}
    rows, by_case = [], defaultdict(dict)
    for item in lines(directory / "predictions.jsonl"):
        case = cases[item["case"]]; p = np.array(item["count_probabilities"]); z = np.array(item["content_probabilities"])
        counts, labels = np.array(case["sample_counts"]), np.array(case["sample_content"])
        row = {"fit_seed": fit_seed, "case": item["case"], "variant": item["variant"],
               "content_nll": float(-np.log(np.maximum(z[labels], 1e-12)).mean()),
               "content_brier": float(np.square(z[None] - np.eye(len(z))[labels]).sum(axis=1).mean()),
               "content_accuracy": float((labels == z.argmax()).mean()),
               "count_nll": float(-np.log(np.maximum(p[counts], 1e-12)).mean()),
               "event_brier": float(np.square((1 - p[0]) - (counts > 0)).mean()),
               "zero_content_label_probability_fraction": float(np.mean(z[labels] <= 0)),
               "zero_count_label_probability_fraction": float(np.mean(p[counts] <= 0)),
               "expected_count_error": float(p @ np.arange(len(p)) - counts.mean()),
               **{k: item[k] for k in ("wall_seconds_per_query", "cpu_seconds_per_query",
                       "cdf_terms_per_query", "density_integrand_evaluations_per_query")}}
        rows.append(row); by_case[item["case"]][item["variant"]] = item
    precision = []
    for case_id, variants in by_case.items():
        a, n = variants["analytic_full_distribution"], variants["matched_numerical_integral"]
        error = float(np.max(np.abs(np.array(a["count_probabilities"]) - n["count_probabilities"])))
        precision.append({"fit_seed": fit_seed, "case": case_id, "max_absolute_probability_error": error,
            "meets_1e_8": error <= 1e-8,
            "numerical_over_analytic_wall_ratio": n["wall_seconds_per_query"] / a["wall_seconds_per_query"],
            "numerical_over_analytic_cpu_ratio": n["cpu_seconds_per_query"] / a["cpu_seconds_per_query"]})
    a, b = cases[0], cases[1]
    alias = {"fit_seed": fit_seed, "mean_difference": a["posterior_mean"] - b["posterior_mean"],
             "variance_difference": a["posterior_variance"] - b["posterior_variance"],
             "shared_estimates_identical": a["shared_calibration"]["estimated"] == b["shared_calibration"]["estimated"],
             "analytic_content_L1": float(np.abs(np.array(by_case[0]["analytic_full_distribution"]["content_probabilities"])
                                                - by_case[1]["analytic_full_distribution"]["content_probabilities"]).sum())}
    return rows, precision, alias


def costs(meter, plan):
    receipts, entries = [], []
    root = Path(plan["repository_root"])
    for job in plan["jobs"]:
        receipt = read(meter / "receipts" / job["id"] / "whole_process.json")
        if receipt["exit_code"] != 0:
            raise ValueError(f"incomplete/failed formal job: {job['id']}")
        for output in receipt["outputs"]:
            if hash_file(root / output["path"]) != output["sha256"]:
                raise ValueError(f"evidence changed after measurement: {output['path']}")
        category = "training_once" if job["id"].startswith("fit_") else (
            "diagnostics" if job["id"].startswith("diagnostics_") else "evaluation_all_seven_arms")
        entries.append({"job": job["id"], "category": category, **{k: receipt[k] for k in
            ("wall_sec", "cpu_total_sec", "cpu_user_sec", "cpu_system_sec", "peak_rss_kib")}})
        receipts.append(receipt)
    supervisor = read(meter / "summary.json")
    return {"whole_process_jobs": entries,
            "cpu_totals_by_category": {k: sum(r["cpu_total_sec"] for r in entries if r["category"] == k)
                                       for k in sorted({r["category"] for r in entries})},
            "total_worker_cpu_seconds": sum(r["cpu_total_sec"] for r in entries),
            "study_elapsed_wall_seconds": supervisor["wall_sec"],
            "supervisor_cpu_seconds": supervisor["supervisor_cpu_sec"],
            "max_worker_rss_kib": supervisor["max_worker_rss_kib"],
            "training_bill_count": sum(r["category"] == "training_once" for r in entries),
            "fit_bill_not_duplicated_across_arms_conditions_or_embedded_reports": True,
            "maximum_worker_RSS_is_not_concurrent_total_memory": True,
            "direct_energy_joules": None,
            "scope": "complete fresh worker interpreter through serialization; all seven arms and independent diagnostics included",
            "wall_times_not_added_to_infer_parallel_elapsed_time": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=Path, required=True); parser.add_argument("--meter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True); parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--analysis-seed", type=int, default=20261101)
    args = parser.parse_args()
    if not (args.meter / "summary.json").exists():
        raise RuntimeError("formal supervisor has not completed; no partial success conclusions")
    plan = read(args.meter / "plan.json"); complete_costs = costs(args.meter, plan)
    records, divergence_rows, diagnostic_rows, precision, aliases, internal_timings = [], [], [], [], [], []
    for job in plan["jobs"]:
        directory = args.jobs / job["id"]
        if job["id"].startswith("test_"):
            rows, diffs, summary = recompute_run(directory)
            records.extend(rows); divergence_rows.extend(diffs)
            for row in summary["episodes"]:
                internal_timings.append({"job": job["id"], "arm": row["arm"], "episode": row["episode"],
                    **{k: row[k] for k in ("arm_wall_seconds", "controller_wall_seconds_inclusive",
                                           "core_wall_seconds_inclusive", "core_calls", "cdf_terms")}})
        elif job["id"].startswith("diagnostics_"):
            rows, exactness, alias = recompute_diagnostics(directory)
            diagnostic_rows.extend(rows); precision.extend(exactness); aliases.append(alias)
    conditions = aggregate_conditions(records, divergence_rows, args.bootstrap, args.analysis_seed)
    diag_metrics = ("content_nll", "content_brier", "content_accuracy", "count_nll", "event_brier",
                    "zero_content_label_probability_fraction", "zero_count_label_probability_fraction",
                    "wall_seconds_per_query", "cpu_seconds_per_query", "cdf_terms_per_query", "density_integrand_evaluations_per_query")
    variants = sorted({r["variant"] for r in diagnostic_rows})
    diagnostic_aggregate = {name: {m: float(np.mean([r[m] for r in diagnostic_rows if r["variant"] == name]))
                                 for m in diag_metrics} for name in variants}
    analytic_cost = diagnostic_aggregate["analytic_full_distribution"]
    numeric_cost = diagnostic_aggregate["matched_numerical_integral"]
    result = {"schema": "hcsn_mechanism_analysis.v1", "plan_sha256": hash_file(args.meter / "plan.json"),
        "analysis_source_sha256": hash_file(__file__), "bootstrap": {"replicates": args.bootstrap,
        "seed": args.analysis_seed, "method": "fit_seed_then_paired_episode_hierarchical_percentile",
        "interpretation": "descriptive_95_percent_intervals_only_three_fitted_seeds"},
        "arm_mapping": ARMS, "conditions": conditions, "complete_costs": complete_costs,
        "nll_probability_floor": 1e-12,
        "diagnostics": {"aggregate": diagnostic_aggregate, "precision_cases": precision,
            "all_384_precision_cases_pass": len(precision) == 384 and all(r["meets_1e_8"] for r in precision),
            "maximum_probability_error": max(r["max_absolute_probability_error"] for r in precision),
            "same_precision_cost_comparison": {
                "numerical_over_analytic_cpu_ratio_of_means": numeric_cost["cpu_seconds_per_query"] / analytic_cost["cpu_seconds_per_query"],
                "numerical_over_analytic_wall_ratio_of_means": numeric_cost["wall_seconds_per_query"] / analytic_cost["wall_seconds_per_query"],
                "analytic_mean_cdf_terms_per_query": analytic_cost["cdf_terms_per_query"],
                "numerical_mean_density_evaluations_per_query": numeric_cost["density_integrand_evaluations_per_query"],
                "comparison_includes_content_mixture_evaluation": True,
                "operation_types_are_different_not_equivalent_network_updates": True},
            "alias_pairs": aliases, "density_evaluations_are_not_network_updates": True},
        "limits": plan["limits"] + ["Fixed zero log-gap boundary; no trained optimal free boundary or joint physical-parameter learning",
            "Task utility subtracts READ fees only; measured CPU is a separate axis",
            "Forecast-risk suppression is not an independent Put-channel ablation",
            "Internal core/controller times overlap and must not be added",
            "Point and missing-reset/refractory variants are specified model ablations, not strong ordinary baselines"]}
    save(args.output / "episode_metrics.jsonl", records, True)
    save(args.output / "first_divergences.jsonl", divergence_rows, True)
    save(args.output / "diagnostic_metrics.jsonl", diagnostic_rows, True)
    save(args.output / "internal_timings.jsonl", internal_timings, True)
    save(args.output / "MECHANISM_RESULTS.json", result)
    print(json.dumps({"output": str(args.output / "MECHANISM_RESULTS.json"),
        "matched_primary": conditions["matched"]["estimates"]["D-B"]["task_utility"],
        "all_precision_pass": result["diagnostics"]["all_384_precision_cases_pass"]}))


if __name__ == "__main__":
    main()
