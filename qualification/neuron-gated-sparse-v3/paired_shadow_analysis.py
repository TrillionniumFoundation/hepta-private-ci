#!/usr/bin/env python3
"""Independent, signed, paired A1-A4 SHADOW evidence analysis.

Requires an independently provisioned Ed25519 evaluator key, preregistered
budget/splits and joined case-level outcomes for every arm. This reports observed
paired statistics only. It never chooses a model or grants production authority.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import math
import json
from pathlib import Path
import sys
from typing import Any

from a0_deployment_evidence import (
    EvidenceError,
    hex_digest,
    load_public_key,
    need,
    positive_int,
    verify_signed,
)

SCHEMA = "hepta.neuron.paired-shadow-evaluation.v1"
ALLOWED_SPLITS = {"heldout", "future", "ood"}
MAX_SAMPLES = 65_536
SCALE_CELLS = (64, 256, 1024, 4096)


def utc(raw: Any, label: str) -> datetime:
    need(isinstance(raw, str) and raw.endswith("Z"), f"{label} must be UTC")
    try:
        date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label} invalid ISO8601") from exc
    need(date.tzinfo is not None and date.utcoffset().total_seconds() == 0,
         f"{label} requires UTC timezone")
    return date


def exact(obj: Any, fields: set[str], label: str) -> dict:
    need(isinstance(obj, dict) and set(obj) == fields,
         f"{label}: unexpected or missing fields")
    return obj


def outcome(value: Any, label: str) -> dict:
    fields = {
        "utility_micro", "long_reward_micro", "future_retained",
        "negative_transfer", "ood_false_accept",
        "cpu_micros", "peak_rss_bytes", "latency_micros",
    }
    binary = {"binary_probability_ppm", "binary_label"}
    need(isinstance(value, dict) and (set(value) == fields or set(value) == fields | binary),
         f"{label}: unexpected fields or partial binary calibration outcome")
    obj = value
    if binary <= set(obj):
        need(type(obj["binary_probability_ppm"]) is int
             and 0 <= obj["binary_probability_ppm"] <= 1_000_000,
             f"{label}: probability not in [0,1] ppm")
        need(type(obj["binary_label"]) is bool,
             f"{label}: binary_label must be Boolean")
    for key in ("utility_micro", "long_reward_micro"):
        need(type(obj[key]) is int and -10**12 <= obj[key] <= 10**12,
             f"{label}.{key}: invalid micro utility")
    for key in ("future_retained", "negative_transfer", "ood_false_accept"):
        need(type(obj[key]) is bool, f"{label}.{key}: expected bool")
    for key in ("cpu_micros", "peak_rss_bytes", "latency_micros"):
        positive_int(obj[key], f"{label}.{key}")
    return obj


def nearest_rank(values: list[int], percentile: int) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) * percentile + 99) // 100 - 1]


def clustered_mean_ci(delta_by_cell: dict[str, list[int]]) -> dict[str, Any]:
    # Cases sharing a Cell are correlated; never treat their count as the
    # number of independent observations. Equal-weight one Cell = one unit.
    values = [sum(samples) / len(samples)
              for _, samples in sorted(delta_by_cell.items())]
    count = len(values)
    if count < 2:
        return {
            "independent_cell_count": count,
            "cluster_mean_delta_micro": values[0] if values else None,
            "cluster_mean_95ci_micro": None,
            "uncertainty": "INSUFFICIENT_INDEPENDENT_CELLS",
        }
    mean = math.fsum(values) / count
    variance = math.fsum((value - mean) ** 2 for value in values) / (count - 1)
    # Conservative fixed t critical values for 1..30 df; 1.96 beyond 30.
    # This is an approximate unadjusted interval, NOT proof of causal effect.
    critical = (
        12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
        2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
        2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052,
        2.048, 2.045, 2.042
    )[(count - 2)] if count <= 31 else 2.042
    margin = critical * math.sqrt(variance / count)
    return {
        "independent_cell_count": count,
        "cluster_mean_delta_micro": mean,
        "cluster_mean_95ci_micro": [mean - margin, mean + margin],
        "uncertainty": "UNADJUSTED_CELL_CLUSTER_T_APPROX",
    }


def calibration_metrics(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        raise EvidenceError("calibration requires a nonempty sample")
    present = sum("binary_probability_ppm" in row for row in rows)
    need(present in (0, len(rows)), "selective or incomplete binary calibration coverage")
    if present == 0:
        return {
            "brier_ppm": None,
            "ece_ppm": None,
            "calibration_sample_count": 0,
            "calibration_status": "NOT_OBSERVED",
        }
    n = len(rows)
    squared_errors = 0
    bins = [[0, 0, 0] for _ in range(10)]
    for row in rows:
        probability = row["binary_probability_ppm"]
        label = int(row["binary_label"])
        squared_errors += (probability - label * 1_000_000) ** 2
        index = min(9, probability // 100_000)
        bins[index][0] += 1
        bins[index][1] += probability
        bins[index][2] += label * 1_000_000
    # Equal-width 10-bin expected calibration error; signed integers prevent
    # accidental float rounding and the result remains descriptive only.
    return {
        "brier_ppm": squared_errors / (n * 1_000_000),
        "ece_ppm": sum(abs(predictions - positives) for count, predictions, positives
                       in bins if count > 0) / n,
        "calibration_sample_count": n,
        "calibration_status": "DESCRIPTIVE_10_BIN_BINARY_ONLY",
    }


def metrics(baseline: list[dict], candidate: list[dict],
            cell_ids: list[str]) -> dict:
    n = len(baseline)
    need(n > 0 and len(candidate) == n and len(cell_ids) == n,
         "paired metric sample count mismatch")
    delta_by_cell = defaultdict(list)
    for cell, b, c in zip(cell_ids, baseline, candidate):
        delta_by_cell[cell].append(c["utility_micro"] - b["utility_micro"])
    baseline_calibration = calibration_metrics(baseline)
    candidate_calibration = calibration_metrics(candidate)
    need(baseline_calibration["calibration_sample_count"]
         == candidate_calibration["calibration_sample_count"],
         "baseline and candidate have different binary calibration coverage")
    if candidate_calibration["calibration_sample_count"] == n:
        need(all(b["binary_label"] == c["binary_label"]
                 for b, c in zip(baseline, candidate)),
             "candidate and frozen baseline disagree on binary ground truth labels")
    return {**clustered_mean_ci(delta_by_cell),
        "candidate_calibration": candidate_calibration,
        "baseline_calibration": baseline_calibration,
        "paired_count": n,
        "mean_utility_delta_micro": sum(
            c["utility_micro"] - b["utility_micro"] for b, c in zip(baseline, candidate)
        ) / n,
        "mean_long_reward_delta_micro": sum(
            c["long_reward_micro"] - b["long_reward_micro"]
            for b, c in zip(baseline, candidate)
        ) / n,
        "negative_transfer_rate": sum(
            c["negative_transfer"] or c["utility_micro"] < b["utility_micro"]
            for b, c in zip(baseline, candidate)
        ) / n,
        "retention_rate": sum(c["future_retained"] for c in candidate) / n,
        "ood_false_accept_rate": sum(c["ood_false_accept"] for c in candidate) / n,
        "cpu_micros_sum": sum(c["cpu_micros"] for c in candidate),
        "maximum_peak_rss_bytes": max(c["peak_rss_bytes"] for c in candidate),
        "p50_latency_micros": nearest_rank([c["latency_micros"] for c in candidate], 50),
        "p95_latency_micros": nearest_rank([c["latency_micros"] for c in candidate], 95),
        "p99_latency_micros": nearest_rank([c["latency_micros"] for c in candidate], 99),
        "baseline_p99_latency_micros": nearest_rank(
            [b["latency_micros"] for b in baseline], 99
        ),
    }


def analyze(payload: dict, evaluator_fingerprint: str) -> dict:
    exact(payload, {
        "schema", "experiment_id", "phase", "evaluator_key_id", "executor_key_id",
        "selector_key_id", "preregistered_at_utc", "training_cutoff_utc",
        "evaluation_asof_utc",
        "host_profile_digest", "a0_registry_sha256", "frozen_baseline",
        "no_change_arm", "arms", "candidate_optimizer_steps", "training_dataset_digest",
        "total_parameter_ceiling",
        "total_state_bytes_ceiling", "samples", "scale_receipts",
    }, "experiment")
    need(payload["schema"] == SCHEMA, "invalid experiment schema")
    need(payload["phase"] in {"A1", "A2", "A3", "A4"}, "unknown phase")
    need(isinstance(payload["experiment_id"], str) and bool(payload["experiment_id"].strip()),
         "missing experiment identity")
    for name in ("evaluator_key_id", "executor_key_id", "selector_key_id"):
        hex_digest(payload[name], name)
    need(payload["evaluator_key_id"] == evaluator_fingerprint,
         "evaluator key does not match the trusted signature")
    need(len({payload["evaluator_key_id"], payload["executor_key_id"],
              payload["selector_key_id"]}) == 3,
         "Evaluator, Selector and Executor must have different owners")
    registration = utc(payload["preregistered_at_utc"], "preregistration")
    cutoff = utc(payload["training_cutoff_utc"], "train cutoff")
    asof = utc(payload["evaluation_asof_utc"], "evaluation as-of")
    need(registration < cutoff < asof,
         "preregistration, train cutoff and evaluation as-of must be ordered")
    hex_digest(payload["host_profile_digest"], "host profile")
    hex_digest(payload["a0_registry_sha256"], "frozen A0 registry")
    need(payload["frozen_baseline"] is True, "no-change baseline was not frozen")
    positive_int(payload["candidate_optimizer_steps"], "candidate optimizer step budget")
    hex_digest(payload["training_dataset_digest"], "preregistered training dataset")
    positive_int(payload["total_parameter_ceiling"], "total parameter ceiling")
    positive_int(payload["total_state_bytes_ceiling"], "total state ceiling")

    arms = payload["arms"]
    need(isinstance(arms, dict) and 2 <= len(arms) <= 8, "require 2-8 comparator arms")
    no_change = payload["no_change_arm"]
    need(no_change in arms, "missing no-change baseline arm")
    encoder_set, candidate_train_set, candidate_training_steps = set(), set(), set()
    for name, arm in arms.items():
        need(isinstance(name, str) and bool(name), "invalid arm name")
        exact(arm, {
            "artifact_digest", "encoder_digest", "training_data_digest",
            "parameter_count_total", "state_bytes", "optimizer_steps",
        }, f"arm {name}")
        for digest_name in ("artifact_digest", "encoder_digest", "training_data_digest"):
            hex_digest(arm[digest_name], f"{name}.{digest_name}")
        positive_int(arm["parameter_count_total"], f"{name}.parameters")
        positive_int(arm["state_bytes"], f"{name}.state_bytes")
        positive_int(arm["optimizer_steps"], f"{name}.optimizer_steps", allow_zero=True)
        need(arm["parameter_count_total"] <= payload["total_parameter_ceiling"],
             f"{name}: exceeds equal parameter budget")
        need(arm["state_bytes"] <= payload["total_state_bytes_ceiling"],
             f"{name}: exceeds equal state budget")
        encoder_set.add(arm["encoder_digest"])
        if name == no_change:
            need(arm["optimizer_steps"] == 0,
                 "no-change baseline must be frozen with zero experimental training steps")
        else:
            need(arm["optimizer_steps"] == payload["candidate_optimizer_steps"],
                 "candidate optimizer steps differ from preregistered budget")
            need(arm["training_data_digest"] == payload["training_dataset_digest"],
                 "candidate training data differ from preregistered dataset")
            candidate_train_set.add(arm["training_data_digest"])
            candidate_training_steps.add(arm["optimizer_steps"])
    need(len(encoder_set) == len(candidate_train_set) == len(candidate_training_steps) == 1,
         "candidate arms have different Encoder, training data or optimizer budget")

    samples = payload["samples"]
    need(isinstance(samples, list) and 0 < len(samples) <= MAX_SAMPLES,
         "missing or excessive paired samples")
    seen = set()
    pairs = defaultdict(lambda: defaultdict(lambda: [[], [], []]))
    split_counts = defaultdict(int)
    for sample in samples:
        exact(sample, {
            "case_id", "cell_id", "input_digest", "split",
            "event_time_utc", "label_available_at_utc", "outcomes",
        }, "paired sample")
        need(isinstance(sample["case_id"], str) and bool(sample["case_id"]),
             "missing case id")
        need(isinstance(sample["cell_id"], str) and bool(sample["cell_id"]),
             "missing cell id")
        hex_digest(sample["input_digest"], "paired original input")
        split = sample["split"]
        need(split in ALLOWED_SPLITS, "train data cannot be evaluated as held-out")
        key = (sample["cell_id"], sample["case_id"])
        need(key not in seen, "duplicate Cell/case pair")
        seen.add(key)
        event = utc(sample["event_time_utc"], "event time")
        label = utc(sample["label_available_at_utc"], "label availability")
        need(label >= event, "label before event")
        need(label <= asof, "label unavailable at signed evaluation as-of")
        if split == "future":
            need(event > cutoff and label > cutoff, "future example leaks into training window")
        else:
            need(label >= registration, "label predates preregistration")
        rows = sample["outcomes"]
        need(isinstance(rows, dict) and set(rows) == set(arms),
             "every arm must have a joined outcome on every paired input")
        validated_rows = {
            name: outcome(value, f"{name} outcome")
            for name, value in rows.items()
        }
        for arm in arms:
            if arm == no_change:
                continue
            pairs[arm][split][0].append(validated_rows[no_change])
            pairs[arm][split][1].append(validated_rows[arm])
            pairs[arm][split][2].append(sample["cell_id"])
        split_counts[split] += 1

    need(split_counts["future"] > 0 and split_counts["ood"] > 0,
         "missing future or OOD evaluation evidence")

    # Mandatory size slots for full A4; A1/A2/A3 may legitimately be incomplete.
    scale = payload["scale_receipts"]
    need(isinstance(scale, list) and len(scale) <= len(SCALE_CELLS) * len(arms),
         "invalid scale receipt count")
    scale_seen = set()
    for receipt in scale:
        exact(receipt, {
            "arm", "cell_count", "host_profile_digest", "cpu_micros",
            "peak_rss_bytes", "p95_micros", "p99_micros",
            "throughput_tasks_per_second_milli",
            "measurement_kind", "execution_receipt_digest", "recovery_receipt_digest",
        }, "scale receipt")
        need(receipt["arm"] in arms and receipt["cell_count"] in SCALE_CELLS,
             "unknown arm or Cell scale")
        need((receipt["arm"], receipt["cell_count"]) not in scale_seen,
             "duplicate scale receipt")
        scale_seen.add((receipt["arm"], receipt["cell_count"]))
        need(receipt["host_profile_digest"] == payload["host_profile_digest"],
             "scale host mismatch")
        need(receipt["measurement_kind"] == "target-host-observed",
             "scale receipt is synthetic or projected, not host observed")
        hex_digest(receipt["execution_receipt_digest"], "signed target-host execution receipt")
        hex_digest(receipt["recovery_receipt_digest"], "signed target-host recovery receipt")
        for field in ("cpu_micros", "peak_rss_bytes", "p95_micros",
                      "p99_micros", "throughput_tasks_per_second_milli"):
            positive_int(receipt[field], field)
        need(receipt["p99_micros"] >= receipt["p95_micros"],
             "invalid scale latency percentile ordering")
    complete_scale = all(
        (arm, n) in scale_seen for arm in arms for n in SCALE_CELLS
    )
    if payload["phase"] == "A4":
        need(complete_scale, "A4 requires all 64/256/1024/4096 scale receipts for all arms")

    results = {
        arm: {
            split: metrics(base, candidate, cells)
            for split, (base, candidate, cells) in sorted(splits.items())
        }
        for arm, splits in sorted(pairs.items())
    }
    return {
        "schema": "hepta.neuron.paired-shadow-report.v1",
        "experiment_id": payload["experiment_id"],
        "phase": payload["phase"],
        "evaluator_key_id": evaluator_fingerprint,
        "a0_registry_sha256": payload["a0_registry_sha256"],
        "source_claim": "signed-evaluator-shadow-evidence",
        "split_counts": dict(sorted(split_counts.items())),
        "candidate_same_encoder_data_training_budget": True,
        "no_change_frozen_with_zero_experimental_steps": True,
        "role_identifiers_distinct_but_not_independently_authenticated": True,
        "all_arms_within_registered_parameter_and_state_ceiling": True,
        "all_scale_slots_observed": complete_scale,
        "comparisons_vs_frozen_no_change": results,
        "decision": "NO_PRODUCTION_PROMOTION",
        "limitations": [
            "Trusted key validation authenticates claimed evaluator input, not real host execution.",
            "Clustered t intervals and 10-bin binary Brier/ECE are descriptive only, not causal, calibrated acceptance or multiple-testing-adjusted inference.",
            "Clock-order and dataset hash checks do not independently establish training/label non-leakage.",
            "Evaluator-signed role IDs alone do not authenticate Selector/Executor ownership; NDU final-use, CAS and migration remain external.",
            "A4 size slots do not alone prove resource claims without host attestation and replay.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed-evaluation", type=Path, required=True)
    parser.add_argument("--trusted-evaluator-public-key", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        evaluator, fingerprint = load_public_key(args.trusted_evaluator_public_key)
        payload = verify_signed(args.signed_evaluation, evaluator, fingerprint, SCHEMA)
        result = analyze(payload, fingerprint)
    except (EvidenceError, FileNotFoundError, PermissionError) as exc:
        print(json.dumps({"status": "BLOCKED_SHADOW_ANALYSIS", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
