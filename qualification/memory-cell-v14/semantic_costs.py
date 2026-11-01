"""Measured local service costs, including every calibration alternative."""

import time

import numpy as np

from semantic_data import TASKS


def query_timings(rows, predict):
    samples, cpu = [], []
    chosen = rows[::max(1, len(rows) // 16)][:16]
    for _ in range(3):
        for row in chosen:
            wall, process = time.perf_counter(), time.process_time()
            label = int(predict([row["text"]])[0])
            try:
                TASKS.execute(label, row["payload"])
                error = None
            except (ValueError, TypeError, ArithmeticError, OverflowError, TASKS.csv.Error) as exc:
                error = type(exc).__name__
            samples.append({"seconds": time.perf_counter() - wall, "error": error})
            cpu.append(time.process_time() - process)
    return {"wall_samples": samples, "cpu_samples_seconds": cpu, "count": len(samples),
            "mean_seconds": float(np.mean([x["seconds"] for x in samples])),
            "p95_seconds": float(np.quantile([x["seconds"] for x in samples], .95)),
            "scope": "Sequential request including tokenizer/encoder when required and the shared executor, including errors."}


def assess(results, prior_costs):
    arms = results["arms"]
    baselines = [name for name in arms if name not in ("bert_lora", "bert_mlp", "bert_fast_weights")]
    for name, arm in arms.items():
        cost = arm["cost"]
        cost["startup_write_seconds"] = sum(cost[x] for x in ("model_acquisition_load_seconds", "prepare_seconds", "all_training_and_selection_seconds", "serialization_seconds", "restore_seconds"))
        cost["retained_bytes"] = sum(cost[x] for x in ("base_files_bytes", "source_bytes", "all_candidate_checkpoint_bytes"))
        accuracy = arm["holdout"]["task_success"]
        arm["utility_by_reads"] = {str(n): accuracy - .01 * (cost["startup_write_seconds"] / n + arm["query_timings"]["mean_seconds"])
                                  - .001 * (cost["retained_bytes"] / 2**30) / n for n in (1, 10, 100, 1000, 10000)}
    baseline_quality = max(arms[k]["holdout"]["task_success"] for k in baselines)
    baseline_utility = max(arms[k]["utility_by_reads"]["1000"] for k in baselines)
    known_prior = sum(item["wall_seconds"] for item in prior_costs if isinstance(item.get("wall_seconds"), (int, float)))
    missing_prior = [item for item in prior_costs if item.get("wall_seconds") is None]
    current_search = results["physical_run_wall_seconds"]
    results["exploration_cost"] = {"known_previous_wall_seconds": known_prior, "previous_unknown_entries": missing_prior,
                                   "current_physical_run_wall_seconds": current_search,
                                   "current_sum_of_deployment_arm_cost_seconds": sum(arm["cost"]["startup_write_seconds"] for arm in arms.values()),
                                   "note": "Physical run cost includes all candidates and evaluation. Deployment arm sums charge shared encoders separately.",
                                   "all_current_candidate_training_and_calibration_included": True,
                                   "prior_entries": prior_costs}
    for name, arm in arms.items():
        arm["qualification"] = {"quality_delta_vs_best_implementation": arm["holdout"]["task_success"] - baseline_quality,
                                 "net_utility_delta_vs_best_at_1000_reads": arm["utility_by_reads"]["1000"] - baseline_utility,
                                 "stable_three_seed_claim": None, "unknown_energy_dollars_are_not_added_quality_gates": True}
        arm["research_amortized_utility_1000_known_costs_only"] = arm["utility_by_reads"]["1000"] - .01 * (known_prior + current_search) / 1000
        arm["research_amortized_cost_complete"] = not missing_prior
    for name, arm in arms.items():
        references = {}
        for other in baselines:
            extra = arm["cost"]["startup_write_seconds"] - arms[other]["cost"]["startup_write_seconds"]
            savings = arms[other]["query_timings"]["mean_seconds"] - arm["query_timings"]["mean_seconds"]
            references[other] = {"extra_write_seconds": extra, "read_seconds_saved": savings,
                                  "time_only_break_even_reads": max(0., extra / savings) if savings > 0 else None}
        arm["break_even_against_baselines"] = references
