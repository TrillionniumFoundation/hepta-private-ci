"""Paired fit-cluster inference and complete quality/resource summaries."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from .study import PRIMARY, SECONDARY, STRESS_ARMS, verify_freeze, checkpoint_path


METRICS = ("registered_return", "task_return", "quality", "action_cost", "decisions",
           "event_count", "prediction_ns", "kernel_ns", "wire_bytes", "state_bytes_max",
           "process_cpu_ns", "guard_fallbacks", "compute_proxy_cost", "event_proxy_cost")


def paired_interval(values, *, alpha=0.05, seed=770000007, replicates=10000):
    """Fit clusters resampled first, then paired whole episodes inside each fit."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("complete finite fit-by-episode contrast required")
    fits, episodes = values.shape
    rng = np.random.default_rng(seed)
    draws = []
    for begin in range(0, replicates, 250):
        size = min(250, replicates - begin)
        chosen_fits = rng.integers(0, fits, (size, fits))
        chosen_episodes = rng.integers(0, episodes, (size, fits, episodes))
        samples = values[chosen_fits[:, :, None], chosen_episodes]
        draws.extend(samples.mean(axis=(1, 2)).tolist())
    seed_means = values.mean(axis=1)
    mean = float(seed_means.mean())
    sem = float(seed_means.std(ddof=1) / np.sqrt(fits)) if fits > 1 else None
    interval = np.quantile(draws, [alpha / 2, 1 - alpha / 2]).tolist()
    critical = float(student_t.ppf(1 - alpha / 2, fits - 1)) if fits > 1 else None
    return {"mean": mean, "bootstrap_interval": interval, "confidence": 1 - alpha,
            "fit_means": seed_means.tolist(), "positive_fits": int((seed_means > 0).sum()),
            "fit_count": fits, "episodes_per_fit": episodes, "bootstrap_replicates": replicates,
            "seed_level_t_interval": None if sem is None else [mean - critical * sem, mean + critical * sem],
            "inference_scope": "conditional on fixed shared train/dev and registered fit-seed protocol"}


def load_trajectories(path):
    data, failures = {}, []
    with gzip.open(path, "rt", encoding="utf8") as source:
        for line in source:
            record = json.loads(line)
            if record["status"] != "complete":
                failures.append(record)
                continue
            key = record["regime"], record["arm"], record["fit_seed"], record["episode_index"]
            if key in data:
                raise ValueError("duplicate trajectory identity")
            data[key] = {metric: record[metric] for metric in METRICS}
            data[key]["episode_seed"] = record["episode_seed"]
            data[key]["latent_seed"] = record["latent_seed"]
    return data, failures


def validate_identity_grid(data, failures, receipt, *, nominal_count=512, stress_count=256):
    expected, seed_mismatches, expected_counts = set(), [], {}
    regimes = (("nominal", nominal_count, 2000000), ("drift", stress_count, 3000000),
               ("missing", stress_count, 4000000), ("cost_shift", stress_count, 6000000))
    for regime_index, (regime, count, base) in enumerate(regimes):
        arms = list(PRIMARY) + list(SECONDARY) + ["task_DP", "myopic_DP"] if regime == "nominal" else STRESS_ARMS
        for arm in arms:
            expected_counts[regime + "/" + arm] = 5 * count
            for fit_index, fit in enumerate(range(11, 16)):
                for episode in range(count):
                    key = regime, arm, fit, episode
                    expected.add(key)
                    if key in data:
                        external = base + fit_index * 10000 + episode
                        internal = 920000000 + regime_index * 1000000 + fit_index * 10000 + episode
                        if (data[key]["episode_seed"], data[key]["latent_seed"]) != (external, internal):
                            seed_mismatches.append(key)
    observed = set(data)
    missing, unexpected = sorted(expected - observed), sorted(observed - expected)
    receipt_errors = []
    if receipt.get("status") != "complete" or receipt.get("development_only"):
        receipt_errors.append("receipt is not a complete confirmation")
    if receipt.get("failures"):
        receipt_errors.append("run receipt records an operational failure")
    if receipt.get("trajectories") != len(expected):
        receipt_errors.append("receipt total differs from frozen registration")
    if receipt.get("arm_counts") != expected_counts:
        receipt_errors.append("receipt arm counts differ from frozen registration")
    complete = not (failures or missing or unexpected or seed_mismatches or receipt_errors)
    return {"status": "complete" if complete else "incomplete", "expected": len(expected),
            "observed_successes": len(data), "failures": len(failures),
            "missing_identities": missing, "unexpected_identities": unexpected,
            "seed_mismatches": seed_mismatches, "receipt_errors": receipt_errors}


def matrix(data, regime, arm, metric):
    keys = sorted(key for key in data if key[:2] == (regime, arm))
    fits = sorted({key[2] for key in keys})
    episodes = sorted({key[3] for key in keys})
    if len(fits) != 5 or len(keys) != len(fits) * len(episodes):
        raise ValueError(f"incomplete arm {regime}/{arm}")
    return np.asarray([[data[regime, arm, fit, ep][metric] for ep in episodes] for fit in fits])


def summarize(root, confirmation):
    root, confirmation = Path(root), Path(confirmation)
    frozen = verify_freeze(root)
    receipt = json.loads((confirmation / "RUN_RECEIPT.json").read_text())
    if receipt.get("frozen_manifest_sha256") != frozen["sha256"]:
        raise ValueError("run receipt is bound to a different frozen study")
    actual_sha = hashlib.sha256((confirmation / "trajectories.jsonl.gz").read_bytes()).hexdigest()
    if receipt["records_sha256"] != actual_sha:
        raise ValueError("raw evidence hash differs from its run receipt")
    data, failures = load_trajectories(confirmation / "trajectories.jsonl.gz")
    identities = validate_identity_grid(data, failures, receipt)
    if identities["status"] != "complete":
        result = {"status": "incomplete", "identity_audit": identities, "failures": failures,
                  "contrasts": {}, "mainline_promotion": False,
                  "reason": "No efficacy gate may be computed from an incomplete or mismatched registered family."}
        (confirmation / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    arms, contrasts = {}, {}
    for regime, arm in sorted({key[:2] for key in data}):
        values = {metric: matrix(data, regime, arm, metric) for metric in METRICS}
        summary = {metric: float(value.mean()) for metric, value in values.items()}
        summary["quality_accuracy"] = (summary["quality"] + 1) / 2
        summary["prediction_ns_p50_p95"] = np.quantile(values["prediction_ns"], [0.5, 0.95]).tolist()
        summary["registered_return_by_fit"] = values["registered_return"].mean(axis=1).tolist()
        summary["episodes"] = int(values["quality"].size)
        arms[regime + "/" + arm] = summary
    def difference(regime, weights):
        return sum(weight * matrix(data, regime, arm, "registered_return") for arm, weight in weights.items())
    for name, weights in (
        ("B-A", {"B": 1, "A": -1}),
        ("D-B", {"D": 1, "B": -1}),
        ("interaction", {"D": 1, "C": -1, "B": -1, "A": 1}),
    ):
        result = paired_interval(difference("nominal", weights), alpha=0.05 / 3)
        threshold = 0 if name == "interaction" else 0.005
        result["practical_threshold"] = threshold
        result["registered_gate_pass"] = result["bootstrap_interval"][0] > threshold
        result["seed_t_sensitivity_pass"] = result["seed_level_t_interval"][0] > threshold
        contrasts[name] = result
    secondary_pairs = [("D", "continuous"), ("D", "direct_Q"), ("D", "temperature"),
                       ("D", "continuous_hard"), ("D_mean", "continuous"),
                       ("D", "D_mean"), ("B", "B_mean"), ("D", "D_soft"),
                       ("D_q24", "D_mean"), ("B_q24", "B_mean")]
    secondary_pairs += [("D", "freeze_" + group) for group in
                        ("content", "dynamics", "noise", "boundary", "reset", "recovery")]
    secondary_pairs += [("B", "clocked_freeze_boundary")]
    for index, (left, right) in enumerate(secondary_pairs):
        contrasts[left + "-" + right] = paired_interval(difference("nominal", {left: 1, right: -1}),
                                                        seed=770000100 + index)
    for index, regime in enumerate(("drift", "missing", "cost_shift")):
        contrasts[regime + "/D-B"] = paired_interval(difference(regime, {"D": 1, "B": -1}),
                                                     seed=770000200 + index)
    training = {}
    registered_models = sorted({(mode, freeze) for mode, freeze, _, _ in
                                list(PRIMARY.values()) + list(SECONDARY.values())})
    paths = [checkpoint_path(root / "evidence", mode, freeze, seed)
             for mode, freeze in registered_models for seed in range(11, 16)]
    for path in paths:
        record = json.loads(path.read_text())
        if "metadata" not in record:
            continue
        metadata = record["metadata"]
        training[path.name] = {key: metadata[key] for key in
                              ("training_wall_seconds", "training_process_cpu_seconds", "best_epoch",
                               "total_parameters", "trainable_parameters", "selected_physical")}
    run_costs = [json.loads(path.read_text()) for path in (root / "evidence").glob("fits*/TRAINING_RUN_*.json")]
    amortization = {}
    for arm, mode in (("B", "clocked"), ("D", "first_passage"),
                      ("continuous", "continuous"), ("direct_Q", "direct")):
        fit_cost = np.mean([v["training_process_cpu_seconds"] for k, v in training.items()
                           if k.startswith(mode + "_none_")])
        online = arms["nominal/" + arm]["process_cpu_ns"] / 1e9
        amortization[arm] = {str(n): float(online + fit_cost / n) for n in (1, 100, 10000, 1000000)}
    numerical = json.loads((root / "evidence" / "numerical_audit.json").read_text())
    result = {"status": "complete" if not failures else "incomplete", "failures": failures,
              "identity_audit": identities,
              "arms": arms, "contrasts": contrasts, "training": training,
              "all_training_runs_wall_seconds_sum": sum(v["wall_seconds"] for v in run_costs),
              "all_training_runs_cpu_seconds_sum": sum(v["process_cpu_seconds"] for v in run_costs),
              "training_run_coverage": [v["configuration"] for v in run_costs],
              "training_run_coverage_exclusions": "Batch sums cover named fits* jobs, including the five superseded temperature attempts inside fits_primary; early development smokes lack whole-process receipts and are separately itemized in the report.",
              "amortized_fit_plus_online_cpu_seconds": amortization,
              "amortization_exclusions": "Partial component table: per-fit epoch CPU plus online episode CPU. Per-fit model/optimizer setup and checkpoint serialization are excluded here but included in batch receipts. Shared fixture/oracle setup, experiment-only validation/ablations and historical build are separately disclosed, not zero.",
              "wire_metric_scope": "Serialized policy packet size, not physical transport. Actual broker UTF-8 transport is separately measured by audits.py.",
              "numerical_audit_status": numerical.get("status"),
              "mainline_promotion": False,
              "scope": "known finite task/internal Markov models; no production, continuous-OU accuracy, sparse hardware, or energy claim"}
    (confirmation / "SUMMARY.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args()
    result = summarize(args.root, args.confirmation)
    print(json.dumps({"status": result["status"], "primary": {k: result["contrasts"].get(k)
          for k in ("B-A", "D-B", "interaction")}}, indent=2))


if __name__ == "__main__":
    main()
