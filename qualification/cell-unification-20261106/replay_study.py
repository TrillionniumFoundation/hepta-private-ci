#!/usr/bin/env python3
"""Independently replay saved FP64 predictions without importing study code.

This reconstructs RNG inputs, scalar model predictions, losses, demand flags,
decisions and physical event totals. It does not retrain models or certify
hardware measurements, authenticated lifecycle ownership or production use.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ARMS = (
    "frozen_incumbent", "continued_parent", "expanded_monolith",
    "fixed_experts", "random_grouping", "demand_specialization",
)
SCENARIOS = ("helpful_specialization", "redundant_specialization")
SEEDS = (7, 17, 29, 43, 71)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def near(left, right, label):
    require(math.isfinite(left) and math.isfinite(right)
            and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), label)


def reconstruct(seed, scenario, split):
    split_number, per_task = {
        "pretrain": (0, 256), "train": (1, 128), "monitor": (2, 96),
        "validation": (3, 64), "test": (4, 96),
    }[split]
    result = []
    for task in (0,) if split == "pretrain" else (0, 1):
        rng = np.random.default_rng(np.random.SeedSequence([seed, split_number, task]))
        features = rng.normal(size=(per_task, 4)).astype(np.float64)
        coefficients = [-1.4, 0.8, 0.4, -0.6] if task and scenario == SCENARIOS[0] else [1.4, -0.8, 0.4, 0.6]
        noise = rng.normal(scale=0.05, size=per_task)
        for index, (row, epsilon) in enumerate(zip(features, noise, strict=True)):
            target = math.fsum(float(x) * w for x, w in zip(row, coefficients, strict=True)) + 0.1 + float(epsilon)
            result.append((f"{scenario}/{seed}/{split}/{task}/{index}", task, row.tolist(), target, index // 32))
    return result


def predict(model, request, task, features):
    mode = model["router"]
    if mode == "shared":
        index = 0
    elif mode == "task":
        index = task
    elif mode == "random":
        index = hashlib.sha256((model["salt"] + "/" + request).encode()).digest()[0] % 2
    else:
        raise ValueError("unrecognized routing")
    expert = model["experts"][index]
    vector = [1.0, *features, task]
    if expert["mode"] == "expanded":
        vector += [value * task for value in features]
    else:
        require(expert["mode"] == "shared", "unknown feature contract")
    return math.fsum(weight * feature for weight, feature in zip(expert["weights"], vector, strict=True))


def check_observation(model, rows, observation):
    require(len(rows) == len(observation["records"]), "request roster changed")
    losses, old, new = [], [], []
    max_prediction_error = 0.0
    for (request, task, features, target, _), observed in zip(rows, observation["records"], strict=True):
        require(observed["id"] == request and observed["task"] == task
                and observed["status"] == "completed" and observed["reason"] is None,
                "request identity, status or task changed")
        near(target, observed["target"], "regenerated target differs")
        predicted = predict(model, request, task, features)
        near(predicted, observed["prediction"], "scalar prediction differs")
        max_prediction_error = max(max_prediction_error, abs(predicted - observed["prediction"]))
        squared = (predicted - target) ** 2
        near(squared, observed["squared_error"], "recomputed squared error differs")
        losses.append(squared)
        (new if task else old).append(squared)
    for key, values in [("summary", losses), ("old_task", old), ("new_task", new)]:
        summary = observation[key]
        require(summary["requested"] == len(values) and summary["completed"] == len(values)
                and summary["failed"] == 0 and summary["incomplete"] == 0,
                "observation denominator changed")
        for statistic in ("mse", "completed_only_mse"):
            near(math.fsum(values) / len(values), summary[statistic], "reported MSE differs")
    return {"mse": math.fsum(losses) / len(losses), "old_mse": math.fsum(old) / len(old),
            "losses": losses, "max_prediction_error": max_prediction_error, "count": len(rows)}


def review(report):
    require([(r["scenario"], r["seed"]) for r in report["runs"]]
            == [(scenario, seed) for scenario in SCENARIOS for seed in SEEDS], "trial denominator changed")
    require(report["plan"]["seeds"] == list(SEEDS) and report["plan"]["arms"] == list(ARMS), "plan roster changed")
    require(report["plan"]["training_steps"] == 128 and report["plan"]["learning_rate"] == 0.1
            and report["plan"]["ridge"] == 0.0001, "optimizer plan changed")
    policy = report["plan"]["policy"]
    require(policy == {"persistent_window_mse": 0.1, "negative_transfer_mse_increase": 0.01,
                       "minimum_mse_gain": 0.0005, "maximum_old_task_mse_increase": 0.01,
                       "maximum_float_ops_ratio_to_continued": 3.0, "maximum_parameter_bytes": 4096},
            "registered decision thresholds changed")
    require(digest(report["plan"]) == report["plan_digest"]
            and digest(report["source_files"]) == report["source_digest"], "commitment changed")
    total_predictions, max_error, cost_events, float_ops, route_decisions = 0, 0.0, 0, 0, 0
    results = []
    for run in report["runs"]:
        require(set(run["arms"]) == set(ARMS), "comparator population changed")
        require(run["pretrain_failure"] is None, "incumbent training failure")
        parent_digest = digest(run["incumbent_model"])
        require(parent_digest == run["incumbent_digest_before_training"]
                == run["incumbent_digest_after_training"], "incumbent changed")
        rows = {split: reconstruct(run["seed"], run["scenario"], split)
                for split in ("monitor", "validation", "test")}
        demand = run["demand_evidence"]
        demand_checks = [check_observation(demand[model], rows["monitor"], demand[observation])
                         for model, observation in (("parent_model", "before"), ("probe_model", "probe"))]
        persistent = all(math.fsum(loss for row, loss in zip(rows["monitor"], demand_checks[0]["losses"], strict=True)
                                   if row[1] == 1 and row[4] == window) / 32 >= 0.1 for window in range(3))
        negative_transfer = demand_checks[1]["old_mse"] - demand_checks[0]["old_mse"] >= 0.01
        require(demand["persistent_demand"] is persistent and demand["negative_transfer_observed"] is negative_transfer
                and demand["propose_child"] is (persistent and negative_transfer), "demand flags changed")
        checked = list(demand_checks)
        metrics = {}
        physical_events = list(run["shared_ledger"])
        for name in ARMS:
            arm = run["arms"][name]
            require(arm["failure"] is None and digest(arm["model"]) == arm["model_digest"], "model identity or failure")
            migration = arm["migration"]
            require(migration["roundtrip_model"] == arm["model"]
                    and migration["roundtrip_digest"] == arm["model_digest"]
                    and migration["parameter_digest"] == arm["model_digest"]
                    and migration["exact_validation_behavior"] is True, "serialization identity changed")
            checks = [check_observation(arm["model"], rows[split], observation) for split, observation in
                      (("validation", arm["validation"]), ("test", arm["test"]), ("validation", migration["after"]))]
            checked.extend(checks)
            metrics[name] = {"test_mse": checks[1]["mse"], "old_mse": checks[1]["old_mse"]}
            events = run["shared_ledger"] + arm["ledger"]
            require(all(e["complete"] is True for e in events), "incomplete cost stage")
            require(sum(e["estimated_float_ops"] for e in events) == arm["cost"]["estimated_float_ops"], "cost sum differs")
            require(sum(e["route_decisions"] for e in events) == arm["cost"]["route_decisions"], "routing sum differs")
            require(max(e["parameter_bytes"] for e in events) == arm["cost"]["retained_parameter_bytes"], "parameter bytes differ")
            physical_events.extend(arm["ledger"])
        candidate = metrics["demand_specialization"]
        reasons = []
        if not persistent:
            reasons.append("no_persistent_demand")
        if not negative_transfer:
            reasons.append("negative_transfer_not_observed")
        old_regression = candidate["old_mse"] - metrics["frozen_incumbent"]["old_mse"]
        if old_regression > 0.01:
            reasons.append("old_task_regression")
        for name in ARMS[:-1]:
            gain = metrics[name]["test_mse"] - candidate["test_mse"]
            near(gain, run["decision"]["paired_test_mse_gains"][name], "gain changed")
            if gain < 0.0005:
                reasons.append(f"insufficient_gain_over:{name}")
        c = run["arms"]["demand_specialization"]["cost"]
        if c["estimated_float_ops"] > 3 * run["arms"]["continued_parent"]["cost"]["estimated_float_ops"]:
            reasons.append("total_algorithmic_compute_budget_exceeded")
        if c["retained_parameter_bytes"] > 4096:
            reasons.append("parameter_storage_budget_exceeded")
        require(reasons == run["decision"]["reasons"], "decision reasons changed")
        require(run["decision"]["decision"] == ("HOLD" if reasons else "RESEARCH_ELIGIBLE"), "decision changed")
        total_predictions += sum(x["count"] for x in checked)
        max_error = max(max_error, *(x["max_prediction_error"] for x in checked))
        cost_events += len(physical_events)
        float_ops += sum(e["estimated_float_ops"] for e in physical_events)
        route_decisions += sum(e["route_decisions"] for e in physical_events)
        results.append({"scenario": run["scenario"], "seed": run["seed"], "metrics": metrics,
                        "decision": run["decision"]["decision"], "reasons": reasons,
                        "candidate_old_task_mse_increase": old_regression})
    return {"replay_passed": True, "trials": len(results), "arms": len(results) * len(ARMS),
            "scalar_prediction_replays": total_predictions, "max_absolute_prediction_error": max_error,
            "cost_events_counted_once": cost_events, "estimated_float_ops_shared_counted_once": float_ops,
            "route_decisions_shared_counted_once": route_decisions, "trials_reviewed": results,
            "limitations": "Shared NumPy RNG implementation, independent scalar model evaluation and decision reconstruction. No study imports, no training replay, no hardware/energy or lifecycle attestation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    decoded = gzip.decompress(raw) if args.report.suffix == ".gz" else raw
    result = review(json.loads(decoded))
    result["report_sha256"] = hashlib.sha256(decoded).hexdigest()
    result["reviewer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "trials_reviewed"}, indent=2))


if __name__ == "__main__":
    main()
