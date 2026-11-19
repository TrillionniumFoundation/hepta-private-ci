"""Descriptive resource summary of the complete frozen policy benchmark.

This post-processing module does not import Torch, read task holdouts, select
checkpoints, alter measurements, or estimate population tail quantiles.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parent
VARIANTS = ("rr_full", "ctrnn_state_cpu", "alif", "resource_lif")
COUNTS = (64, 256, 1024, 4096)
SEEDS = (101, 211, 307, 401, 503)
NO_NEW_LIMIT = "no_new_cgroup_limit_event_observed"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_nonnegative(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("Resource measurements must be finite and nonnegative")
    return result


def describe(values):
    """Retain each seed; medians are across seed-specific statistics."""
    values = {str(seed): finite_nonnegative(value) for seed, value in values.items()}
    samples = list(values.values())
    return {"seed_count": len(samples), "median": median(samples) if samples else None,
            "minimum": min(samples) if samples else None,
            "maximum": max(samples) if samples else None,
            "values_by_training_seed": values}


def group_summary(rows):
    values = {}
    for row in rows:
        seed = row["identity"]["training_seed"]
        summary = row["summary"]
        metrics = {
            "batch_observation_wall_p95_ms": 1000*summary["batch_observation_wall_seconds"]["p95"],
            "batch_observation_wall_p99_ms": 1000*summary["batch_observation_wall_seconds"]["p99"],
            "batch_observation_cpu_p95_ms": 1000*summary["batch_observation_cpu_seconds"]["p95"],
            "batch_observation_cpu_p99_ms": 1000*summary["batch_observation_cpu_seconds"]["p99"],
            "batch_episode_wall_p95_ms": 1000*summary["batch_episode_wall_seconds"]["p95"],
            "batch_episode_wall_p99_ms": 1000*summary["batch_episode_wall_seconds"]["p99"],
            "full_loop_policy_observations_per_wall_second": summary["full_loop_policy_observations_per_wall_second"],
            "full_loop_policy_episodes_per_wall_second": summary["full_loop_policy_episodes_per_wall_second"],
            "model_only_policy_observations_per_wall_second": summary["model_only_policy_observations_per_wall_second"],
            "full_loop_measured_cpu_seconds": summary["measured_full_cpu_seconds"],
            "process_peak_rss_mib": row["process_peak_rss_mib"],
            "measured_internal_spikes": summary["actual_internal_spikes"],
            "measured_communication_output_pulses": summary["communication_output_pulses"],
        }
        for name, value in metrics.items():
            values.setdefault(name, {})[seed] = value
    state_bytes = sorted({value for row in rows
                          for value in row["summary"]["actual_state_bytes_per_policy"]})
    return {"training_seeds": sorted(row["identity"]["training_seed"] for row in rows),
            "conditions": len(rows), "actual_numeric_state_bytes_per_policy": state_bytes,
            "metrics": {name: describe(per_seed) for name, per_seed in values.items()},
            "resource_status_counts": dict(Counter(row["resource_quality"]["status"] for row in rows))}


def summarize_matrix(matrix_path, destination):
    matrix_path = Path(matrix_path).resolve()
    matrix = json.loads(matrix_path.read_text())
    if (matrix.get("schema") != "rrsnn-v4-policy-benchmark-matrix-1"
            or matrix.get("all_completed") is not True
            or matrix.get("expected_conditions") != 80 or matrix.get("conditions") != 80
            or matrix.get("native_cell_scale_claim") is not False
            or matrix.get("measurement_cpu") != 3 or len(matrix.get("receipts", [])) != 80):
        raise ValueError("A complete 80-condition frozen policy matrix is required")
    protocol_path = ROOT/"policy_benchmark_protocol.json"
    if matrix["protocol_sha256"] != sha(protocol_path):
        raise ValueError("Matrix protocol hash mismatch")
    rows, hashes, seen = [], {}, set()
    for receipt in matrix["receipts"]:
        path = (ROOT/receipt["path"]).resolve()
        if ROOT not in path.parents or sha(path) != receipt["sha256"]:
            raise ValueError("Result path or byte hash mismatch")
        row = json.loads(path.read_text())
        identity = row["identity"]
        key = (identity["variant"], identity["training_seed"], identity["policy_instances"])
        if (key in seen or row.get("status") != "completed" or identity != receipt["identity"]
                or identity["protocol_sha256"] != matrix["protocol_sha256"]
                or identity["cpu_affinity"] != [3]
                or row["summary"] != receipt["summary"]
                or row["resource_quality"] != receipt["resource_quality"]
                or row["process_peak_rss_mib"] != receipt["process_peak_rss_mib"]
                or row.get("holdout_task_data_opened") is not False
                or row.get("native_cell_scale_claim") is not False
                or row.get("weights_unchanged") is not True
                or len(row["warmup_records"]) != 2 or len(row["measured_records"]) != 5):
            raise ValueError(f"Inconsistent benchmark evidence: {key}")
        seen.add(key)
        hashes[receipt["path"]] = receipt["sha256"]
        rows.append(row)
    expected = {(variant, seed, count) for variant in VARIANTS for seed in SEEDS for count in COUNTS}
    if seen != expected:
        raise ValueError("Missing or additional strategy, seed, or scale condition")
    full, sensitivity = [], []
    for variant in VARIANTS:
        for count in COUNTS:
            group = [row for row in rows if row["identity"]["variant"] == variant
                     and row["identity"]["policy_instances"] == count]
            accepted = [row for row in group if row["resource_quality"]["status"] == NO_NEW_LIMIT]
            full.append({"variant": variant, "policy_instances": count, **group_summary(group)})
            sensitivity.append({"variant": variant, "policy_instances": count,
                **group_summary(accepted),
                "excluded_training_seeds": sorted(row["identity"]["training_seed"] for row in group
                                                   if row["resource_quality"]["status"] != NO_NEW_LIMIT)})
    flagged = [{"identity": row["identity"], "resource_quality": row["resource_quality"]}
               for row in rows if row["resource_quality"]["status"] != NO_NEW_LIMIT]
    result = {
        "schema": "rrsnn-v4-policy-benchmark-descriptive-summary-1",
        "all_conditions_retained": True, "conditions": 80, "training_seeds": list(SEEDS),
        "source_sha256": sha(__file__), "matrix_sha256": sha(matrix_path),
        "protocol_sha256": matrix["protocol_sha256"], "result_sha256": hashes,
        "units": "Batched policy instances sharing one selected checkpoint per condition; not native owner components, production Cells, or biological neurons.",
        "aggregation": "Every table entry is the median, minimum, and maximum across the listed training seeds of that seed's already measured statistic. A median of five empirical p95 or p99 values is not a pooled p95 or p99, a population tail estimate, or a confidence interval.",
        "sample_resolution": "Each seed has five complete measured episodes and 55 correlated inner batched-observation timings; full-episode and inner-step p95/p99 are descriptive only. Per-policy throughput is aggregate throughput, not single-request latency.",
        "timing_scope": {
            "batch_observation_and_model_only": "The inner model.step timer includes the action head, actual event propagation, and spike counts. It excludes task observation construction, legal-action argmax, queues, delivery, and budget ledger operations; batch_observation p95/p99 are not end-to-end latencies.",
            "batch_episode_and_full_loop": "Complete closed-loop episodes include model reset, task observations, legal-action decisions, queues, model steps, task transitions, deliveries, terminal settlement, and invariant checks. Scenario generation, source/checkpoint hashing, GC between episodes, state-byte inspection, and result serialization are excluded.",
        },
        "rss_scope": "Fresh measurement-process peak RSS includes Python, PyTorch, shared weights, task state, temporary allocations, warmup, measured timing arrays, and measurements. It is not numeric persistent state per policy.",
        "clean_sensitivity_scope": "Post-processing sensitivity subset excludes windows with new observed shared-cgroup max/OOM events or unknown resource status. No new limit event does not establish an exclusive or contention-free host. This subset never replaces the complete five-seed table and no condition is remeasured.",
        "energy_measured": False, "native_cell_scale_claim": False,
        "all_five_seed_table": full, "no_new_limit_event_sensitivity_table": sensitivity,
        "flagged_resource_windows": flagged,
        "resource_status_counts": dict(Counter(row["resource_quality"]["status"] for row in rows)),
    }
    encoded = (json.dumps(result, indent=2, sort_keys=True)+"\n").encode()
    destination = Path(destination)
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError("Refusing to replace a different completed resource summary")
    else:
        with destination.open("xb") as stream:
            stream.write(encoded)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=ROOT/"policy_benchmark_results"/"matrix.json")
    parser.add_argument("--output", type=Path, default=ROOT/"policy_benchmark_results"/"summary.json")
    arguments = parser.parse_args()
    result = summarize_matrix(arguments.matrix, arguments.output)
    print(json.dumps({"conditions": result["conditions"], "all_conditions_retained": True,
                      "resource_status_counts": result["resource_status_counts"],
                      "output": str(arguments.output.resolve())}))
