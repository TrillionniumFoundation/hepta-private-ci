"""Frozen paired utility, first-stage calibration and complete execution ledger."""

import argparse
from collections import Counter
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

from ..round4.runtime_evidence import write_json
from ..statistics import calibration, paired_interval
from .data import ARMS, DOMAINS, SEEDS
from .lifecycle import sha, verify
from .registration import REGISTRATION as REG


@lru_cache(maxsize=32768)
def interval(weights, means, variances):
    weights, means, variances = map(np.asarray, (weights, means, variances))
    standard = np.sqrt(variances)
    lower, upper = float(np.min(means - 12 * standard)), float(np.max(means + 12 * standard))
    def cdf(value):
        return float(weights @ ndtr((value - means) / standard))
    return tuple(float(brentq(lambda value: cdf(value) - level, lower, upper,
                             xtol=1e-11, rtol=8 * np.finfo(float).eps))
                 for level in (.025, .975))


def first_stage_metrics(rows):
    probabilities, labels, coverage, released_nll, physical_nll = [], [], [], [], []
    max_native_error, max_quantum_error = 0.0, 0.0
    for row in rows:
        stage = row["stages"][0]
        received = stage["runtime"]["law"]
        error = row["target"] - stage["public"]["initial"]
        cutoff = math.sqrt(stage["public"]["repair_cost"])
        label = 0 if error <= -cutoff else 2 if error > cutoff else 1
        probabilities.append(received["probabilities"])
        labels.append(label)
        released_nll.append(-math.log(received["probabilities"][label]))
        physical_nll.append(-received["physical_log_probabilities"][label])
        law = received["conditional_law"]
        lower, upper = interval(*(tuple(law[key]) for key in ("weights", "means", "variances")))
        coverage.append(lower <= error <= upper)
        max_native_error = max(max_native_error, received["native_vs_reference_max_absolute_error"])
        max_quantum_error = max(max_quantum_error, max(abs(a - b) for a, b in zip(
            received["probabilities"], received["native_mixture_probabilities"])))
    p, y = np.asarray(probabilities), np.asarray(labels)
    empirical = calibration(p[:, None, :], y[:, None])
    empirical.update({"interval_95_coverage": float(np.mean(coverage)),
                      "released_event_nll": float(np.mean(released_nll)),
                      "physical_event_nll": float(np.mean(physical_nll)),
                      "brier": float(np.mean(np.sum((p - np.eye(3)[y]) ** 2, axis=1))),
                      "maximum_native_cdf_absolute_error": max_native_error,
                      "maximum_release_absolute_error": max_quantum_error,
                      "category_labels_use_public_cost_cutoff": True,
                      "native_threshold_rounding_is_separate": True})
    empirical["ece_pass"] = empirical["classwise_ece"] <= REG["calibration"]["maximum_ece"]
    bounds = REG["calibration"]["coverage_range"]
    empirical["coverage_pass"] = bounds[0] <= empirical["interval_95_coverage"] <= bounds[1]
    empirical["calibration_pass"] = empirical["ece_pass"] and empirical["coverage_pass"]
    return empirical


def load_scopes(run_dir):
    root, scopes, identities = Path(run_dir), {}, {}
    for seed in SEEDS:
        for domain in DOMAINS:
            folder = root / "confirmation" / f"seed_{seed}" / domain
            complete = json.loads((folder / "RUN_COMPLETED.json").read_text())
            report = json.loads((folder / "SUMMARY.json").read_text())
            if (complete["namespace"] != "registered" or report["namespace"] != "registered"
                    or complete["summary_sha256"] != sha(folder / "SUMMARY.json")
                    or report["rows_sha256"] != sha(folder / "ROWS.json.gz")
                    or report["data_sha256"] != sha(folder / "DATA.npz")
                    or report["seed"] != seed or report["domain"] != domain
                    or report["independent_trajectories"] != 128):
                raise ValueError("Incomplete or altered registered confirmation scope")
            with gzip.open(folder / "ROWS.json.gz", "rt") as stream:
                rows = json.load(stream)
            if (len(rows) != 128 * len(ARMS)
                    or {(row["index"], row["arm"]) for row in rows}
                    != {(i, arm) for i in range(128) for arm in ARMS}):
                raise ValueError("Confirmation must contain every paired arm execution")
            for row in rows:
                if (not math.isfinite(row["utility"])
                        or row["utility"] != 1 - (row["delivered"] - row["target"]) ** 2 - row["cost"]
                        or not row["final_readback_ns"] < row["score_started_ns"]):
                    raise ValueError("Actual final readback and score identity mismatch")
            scopes[seed, domain] = {arm: sorted((row for row in rows if row["arm"] == arm),
                                               key=lambda row: row["index"]) for arm in ARMS}
            identities[str(folder.relative_to(root))] = {
                "run_completed_sha256": sha(folder / "RUN_COMPLETED.json"),
                "summary_sha256": sha(folder / "SUMMARY.json"),
                "rows_sha256": report["rows_sha256"], "data_sha256": report["data_sha256"]}
    return scopes, identities


def summarize(run_dir, expected_freeze_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(run_dir).resolve()
    if (root / "RESULTS.json").exists():
        raise FileExistsError("An existing scientific result is immutable")
    verify(root, expected_freeze_sha256)
    scopes, identities = load_scopes(root)
    result = {"schema": "hepta.acquired-feedback.results.v6", "freeze_sha256": expected_freeze_sha256,
              "independent_confirmation_trajectories": len(SEEDS) * len(DOMAINS) * 128,
              "arm_executions": len(SEEDS) * len(DOMAINS) * 128 * len(ARMS),
              "scope_identities": identities, "domains": {}, "primary": {},
              "codec_noninferiority": {}, "secondary": {}, "ood": {},
              "equivalence": {}, "production_promotion": False,
              "statistical_scope": "Five training clusters; nominal hierarchical percentile intervals, no finite-sample guarantee"}
    cost_keys = ("utility", "cost", "squared_error", "wall_ns", "cpu_ns", "packet_bytes",
                 "native_requests", "native_ticks", "native_roundtrip_ns", "evidence_archive_wall_ns")
    for domain in DOMAINS:
        result["domains"][domain] = {}
        for arm in ARMS:
            rows = [row for seed in SEEDS for row in scopes[seed, domain][arm]]
            metrics = {key: {"mean": float(np.mean([row[key] for row in rows])),
                             "sum": float(np.sum([row[key] for row in rows]))} for key in cost_keys}
            metrics["actions"] = dict(Counter("/".join(row["actions"]) for row in rows))
            metrics["calibration"] = first_stage_metrics(rows)
            metrics["per_seed_utility"] = [float(np.mean([row["utility"]
                for row in scopes[seed, domain][arm]])) for seed in SEEDS]
            result["domains"][domain][arm] = metrics

    sequence = 0
    def compare(candidate, baseline, domain, alpha):
        nonlocal sequence
        matrix = []
        for seed in SEEDS:
            a, b = scopes[seed, domain][candidate], scopes[seed, domain][baseline]
            if [row["index"] for row in a] != [row["index"] for row in b]:
                raise ValueError("Unpaired trajectories")
            matrix.append([left["utility"] - right["utility"] for left, right in zip(a, b)])
        summary = paired_interval(matrix, REG["bootstrap_replicates"], REG["bootstrap_seed"] + sequence, alpha)
        sequence += 1
        return {**summary, "candidate": candidate, "baseline": baseline, "domain": domain}

    for candidate, baseline in REG["primary_utility_comparisons"]:
        item = compare(candidate, baseline, "nominal", .025)
        item["passes_registered_superiority"] = bool(
            item["mean_difference"] >= REG["primary_minimum_mean_utility_gain"]
            and item["interval"][0] > 0 and min(item["per_seed_mean_difference"]) > 0)
        result["primary"][candidate + "-" + baseline] = item
    for candidate, baseline in REG["codec_noninferiority"]:
        item = compare(candidate, baseline, "nominal", .025)
        margin = REG["codec_noninferiority_margin"]
        item["passes_noninferiority"] = bool(item["interval"][0] > -margin
            and min(item["per_seed_mean_difference"]) > -margin)
        result["codec_noninferiority"][candidate + "-" + baseline] = item
    for candidate, baseline in REG["secondary_comparisons"]:
        result["secondary"][candidate + "-" + baseline] = {
            **compare(candidate, baseline, "nominal", .05), "descriptive_only": True}
    for domain in DOMAINS[1:]:
        for candidate, baseline in REG["primary_utility_comparisons"]:
            result["ood"][domain + ":" + candidate + "-" + baseline] = {
                **compare(candidate, baseline, domain, .05), "descriptive_only": True}

    for candidate, baseline in (("event", "direct"), ("gaussian", "probit")):
        action_mismatches, maximum_output_error, maximum_probability_error = 0, 0.0, 0.0
        decoded_mismatches = 0
        for seed in SEEDS:
            for domain in DOMAINS:
                for a, b in zip(scopes[seed, domain][candidate], scopes[seed, domain][baseline]):
                    action_mismatches += int(a["actions"] != b["actions"])
                    maximum_output_error = max(maximum_output_error, abs(a["delivered"] - b["delivered"]))
                    for left, right in zip(a["stages"], b["stages"]):
                        maximum_probability_error = max(maximum_probability_error, max(abs(x - y) for x, y in zip(
                            left["runtime"]["law"]["probabilities"], right["runtime"]["law"]["probabilities"])))
                        dl, dr = left["runtime"]["decoder"], right["runtime"]["decoder"]
                        # Transport mode/header differ by design; compare received law coordinates.
                        decoded_mismatches += int(any(dl[key] != dr[key]
                            for key in ("components", "values", "sequence", "time")))
        tolerance = 0.0 if candidate == "event" else REG["gaussian_probit_equivalence_tolerance"]
        result["equivalence"][candidate + "-" + baseline] = {
            "action_mismatches": action_mismatches, "maximum_output_error": maximum_output_error,
            "maximum_probability_error": maximum_probability_error,
            "decoded_coordinate_mismatches": decoded_mismatches,
            "tolerance": tolerance,
            "passes_equivalence": bool(action_mismatches == 0
                and maximum_output_error <= tolerance and maximum_probability_error <= tolerance
                and (candidate != "event" or decoded_mismatches == 0))}
    result["all_primary_gates_pass"] = all(item["passes_registered_superiority"] for item in result["primary"].values())
    result["analytic_nominal_calibration_pass"] = result["domains"]["nominal"]["analytic"]["calibration"]["calibration_pass"]
    result["joint_research_gate_pass"] = result["all_primary_gates_pass"] and result["analytic_nominal_calibration_pass"]
    result["summary_wall_ns"] = time.perf_counter_ns() - started
    result["summary_parent_cpu_ns"] = time.process_time_ns() - cpu
    result["timing_scope"] = "source/data/row checks, metrics and bootstrap; excludes final JSON write; not total experiment cost"
    write_json(root / "RESULTS.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    args = parser.parse_args()
    outcome = summarize(args.run_dir, args.expected_freeze_sha256)
    print(json.dumps({"primary": outcome["primary"], "joint_research_gate_pass": outcome["joint_research_gate_pass"]}))
