#!/usr/bin/env python3
"""Pre-registered paired cluster-bootstrap quality gate; shadow evidence only.

For connected Cell events, case count is not the number of independent
replicates. Resample source groups, not individual ticks. Neither a positive
offline gate nor an NDU field authorizes production promotion.
"""
import argparse
from collections import defaultdict
import math
import random

from qualified_eval import (audit_dataset, brier_and_ece, evaluate, percentile,
                            read_jsonl, validate_predictions, write_json)


def per_case_metrics(row, prediction):
    p = prediction["probabilities"]
    truth = row["label"]
    return {
        "accuracy": float(max(range(len(p)), key=p.__getitem__) == truth),
        "brier": sum((v - float(i == truth)) ** 2 for i, v in enumerate(p)) / len(p),
    }


def grouped_paired_delta(dataset, before, after, split):
    groups = defaultdict(list)
    for row in dataset:
        if row["split"] == split:
            a = per_case_metrics(row, before[row["case_id"]])
            b = per_case_metrics(row, after[row["case_id"]])
            groups[(row["scope_id"], row["group_id"])].append(
                (b["accuracy"] - a["accuracy"], b["brier"] - a["brier"]))
    return [(
        sum(d[0] for d in values) / len(values),
        sum(d[1] for d in values) / len(values),
    ) for _, values in sorted(groups.items())]


def confidence_interval(group_values, *, seed=20261011, replicates=2000):
    if type(replicates) is not int or replicates < 1000:
        raise ValueError("at least 1000 bootstrap replicates required")
    if not group_values:
        raise ValueError("no independent evaluation groups")
    n = len(group_values)
    rng = random.Random(seed)
    bootstrap = [[], []]
    for _ in range(replicates):
        sample = [group_values[rng.randrange(n)] for _ in range(n)]
        for i in range(2):
            bootstrap[i].append(sum(s[i] for s in sample) / n)
    result = {}
    for i, key in enumerate(("accuracy_gain", "brier_delta")):
        result[key] = {
            "estimate": sum(g[i] for g in group_values) / n,
            "ci_95": [percentile(bootstrap[i], .025), percentile(bootstrap[i], .975)],
        }
    return result


def qualify(dataset, baseline, candidate, *, min_future_groups=30,
            max_task_brier_regression=0.01, seed=20261011, replicates=2000):
    if type(min_future_groups) is not int or min_future_groups < 2:
        raise ValueError("too few required independent groups")
    if not math.isfinite(max_task_brier_regression) or max_task_brier_regression < 0:
        raise ValueError("invalid regression tolerance")
    audit_dataset(dataset)
    before = validate_predictions(baseline, dataset)
    after = validate_predictions(candidate, dataset)
    report = evaluate(dataset, baseline, candidate)
    by_split = {}
    for split in ("test", "future"):
        groups = grouped_paired_delta(dataset, before, after, split)
        by_split[split] = {
            "independent_groups": len(groups),
            "paired_group_bootstrap": confidence_interval(
                groups, seed=seed, replicates=replicates) if groups else None,
        }
    future = by_split["future"]
    ci = future["paired_group_bootstrap"]
    regressions = [
        {"task_id": task, "split": split, "delta_brier": result["delta_brier"]}
        for task, splits in report["per_task_results"].items()
        for split, result in splits.items()
        if result["delta_brier"] > max_task_brier_regression
    ]
    passes = bool(
        ci is not None
        and future["independent_groups"] >= min_future_groups
        and ci["accuracy_gain"]["ci_95"][0] > 0
        and ci["brier_delta"]["ci_95"][1] < 0
        and not regressions
    )
    return {
        "schema": "hepta.neuron-stem-paired-statistical-gate.v1",
        "status": "offline_quality_gate_pass" if passes else "offline_quality_gate_not_passed",
        "offline_quality_gate_passed": passes,
        "production_promotion_permitted": False,
        "ndu_independent_signature_verified": False,
        "confidence_procedure": "paired source-group nonparametric bootstrap",
        "bootstrap_replicates": replicates, "seed": seed,
        "precommitted_limits": {
            "minimum_future_independent_groups": min_future_groups,
            "maximum_task_mean_brier_regression": max_task_brier_regression,
            "required_future_accuracy_gain_ci_lower_gt": 0,
            "required_future_brier_delta_ci_upper_lt": 0,
        },
        "evaluation": by_split, "task_regressions": regressions,
        "descriptive_ndu_only": report["descriptive_ndu_delta"],
        "ndu_receipt_count_unverified": report["ndu_matched_receipt_count"],
        "dataset": report["dataset"],
        "candidate_model": report["candidate_model"],
        "candidate_revision": report["candidate_revision"],
        "baseline_model": report["baseline_model"],
        "baseline_revision": report["baseline_revision"],
        "baseline_predictions_sha256": report["baseline_predictions_sha256"],
        "candidate_predictions_sha256": report["candidate_predictions_sha256"],
        "resource_paths": report["candidate_resource_paths"],
        "limitations": [
            "Source groups may still correlate across principals or time",
            "Offline classifier utility is not causal online NDU evidence",
            "No validated signature, selection, or executor promotion authority",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--min-future-groups", type=int, default=30)
    p.add_argument("--max-task-brier-regression", type=float, default=0.01)
    p.add_argument("--bootstrap-replicates", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261011)
    a = p.parse_args()
    write_json(a.output, qualify(
        read_jsonl(a.dataset), read_jsonl(a.baseline), read_jsonl(a.candidate),
        min_future_groups=a.min_future_groups,
        max_task_brier_regression=a.max_task_brier_regression,
        seed=a.seed, replicates=a.bootstrap_replicates))


if __name__ == "__main__":
    main()
