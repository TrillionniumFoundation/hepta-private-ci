"""Preregistered CPU service boundary and separate quality/utility routes."""

import time

import numpy as np

from language_data import execute


def sequential_reads(data, predict_texts):
    rows = data["test"][::max(1, len(data["test"]) // 16)][:16]
    samples = []
    for repeat in range(3):
        for index, row in enumerate(rows):
            started = time.perf_counter()
            label = int(predict_texts([row["query"]])[0])
            if data["task"] == "procedure_selection":
                execute(label, index - 7, 11 - index)
            samples.append(time.perf_counter() - started)
    return {"count": len(samples), "mean_seconds": float(np.mean(samples)),
            "median_seconds": float(np.median(samples)), "p95_seconds": float(np.quantile(samples, .95)),
            "first_observed_seconds": samples[0], "samples_seconds": samples,
            "includes": "tokenization/encoding when needed, memory read, and shared interpreter when applicable"}


def comparisons(arms, source_bytes, replay_bytes, base_file_bytes, base_start_seconds):
    baseline_kinds = ("exact_kv", "bm25", "lexical_ridge", "feature_nearest", "feature_ridge", "feature_linear")
    for kind, arm in arms.items():
        final = arm["phases"][-1]
        arm["cost_ledger"] = {
            "write_seconds": final["cumulative_write_seconds"],
            "qualification_seconds": sum(e["read_seconds"] for p in arm["phases"] for e in p["evaluations"].values()),
            "restore_seconds": arm["restore_seconds"],
            "base_start_seconds": base_start_seconds if arm["requires_shared_backbone"] else 0.,
            "source_bytes": source_bytes,
            "replay_bytes": replay_bytes if kind in ("feature_linear", "feature_mlp", "attention_lora", "fast_weights") else 0,
            "versioned_checkpoint_bytes": sum(p["checkpoint_bytes"] for p in arm["phases"]),
            "shared_base_file_bytes": base_file_bytes if arm["requires_shared_backbone"] else 0,
            "observed_single_query_mean_seconds": arm["sequential_reads"]["mean_seconds"],
        }
        ledger = arm["cost_ledger"]
        ledger["startup_and_write_seconds"] = sum(ledger[k] for k in ("write_seconds", "qualification_seconds", "restore_seconds", "base_start_seconds")) + arm.get("initialization_seconds", 0.)
        ledger["total_persistent_bytes"] = sum(ledger[k] for k in ("source_bytes", "replay_bytes", "versioned_checkpoint_bytes", "shared_base_file_bytes"))
        accuracy = final["evaluations"]["test"]["accuracy"]
        arm["utility_by_reads"] = {str(reads): accuracy - .01 * (ledger["startup_and_write_seconds"] / reads + ledger["observed_single_query_mean_seconds"])
            - .001 * (ledger["total_persistent_bytes"] / 2**30) / reads for reads in (1, 10, 100, 1000, 10000)}
    for kind, arm in arms.items():
        accuracy = arm["phases"][-1]["evaluations"]["test"]["accuracy"]
        best_accuracy = max(arms[k]["phases"][-1]["evaluations"]["test"]["accuracy"] for k in baseline_kinds)
        best_utility = max(arms[k]["utility_by_reads"]["1000"] for k in baseline_kinds)
        arm["qualification"] = {
            "quality_delta_vs_best_baseline": accuracy - best_accuracy,
            "single_seed_quality_candidate": accuracy > best_accuracy,
            "utility_delta_vs_best_baseline_at_1000_reads": arm["utility_by_reads"]["1000"] - best_utility,
            "single_seed_utility_candidate": arm["utility_by_reads"]["1000"] > best_utility,
            "stable_three_seed_claim": None,
            "scope": "Measured local CPU service boundary; energy/dollars/distributed transport are not claimed.",
        }
        exact = arms["exact_kv"]["cost_ledger"]
        ledger = arm["cost_ledger"]
        extra_write = ledger["startup_and_write_seconds"] - exact["startup_and_write_seconds"]
        read_saving = exact["observed_single_query_mean_seconds"] - ledger["observed_single_query_mean_seconds"]
        arm["exact_kv_comparison"] = {"accuracy_delta": accuracy - arms["exact_kv"]["phases"][-1]["evaluations"]["test"]["accuracy"],
            "extra_startup_write_seconds": extra_write, "seconds_saved_per_query": read_saving,
            "cpu_time_break_even_reads": max(0., extra_write / read_saving) if read_saving > 0 else None,
            "note": "Time break-even alone does not imply quality or utility acceptance."}
