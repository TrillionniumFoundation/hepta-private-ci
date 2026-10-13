"""Model-free Cell Head matrix with a sealed external-observation boundary."""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
import random

SCHEMA = "hepta.shared-stem-head-matrix.v1"
ARMS = ("linear", "gated", "lora", "sparse_expert")
OPTIONAL_METRICS = (
    "negative_transfer",
    "old_task_retention",
    "calibration_ece",
    "calibration_brier",
    "ood_false_acceptance",
)


class ExperimentError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def finite(value, name, minimum=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < minimum:
        raise ExperimentError(f"{name} must be finite and >= {minimum}")
    return float(value)


PROFILES = {
    "linear": {"params_m": 1.0, "memory_mb": 8.0, "flops_g": 0.006, "quality": 0.68, "penalty": 0.020},
    "gated": {"params_m": 1.5, "memory_mb": 10.0, "flops_g": 0.009, "quality": 0.73, "penalty": 0.012},
    "lora": {"params_m": 0.6, "memory_mb": 6.0, "flops_g": 0.008, "quality": 0.71, "penalty": 0.015},
    "sparse_expert": {"params_m": 4.0, "memory_mb": 24.0, "flops_g": 0.012, "quality": 0.77, "penalty": 0.008},
}


def _quantile(values, q):
    values = sorted(values)
    return values[max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))] if values else None


def _load_external(path):
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExperimentError(f"invalid JSON at line {line_no}") from error
        rows.append(row)
    if not rows:
        raise ExperimentError("external observations are empty")
    return rows


def run(tasks=tuple(f"task-{i:03d}" for i in range(16)), cells=32, active_cells=1, training_budget=1000, seed=20261013, observations=None):
    if not isinstance(cells, int) or cells < 1 or not isinstance(active_cells, int) or not 1 <= active_cells <= cells:
        raise ExperimentError("invalid cells/active_cells")
    if not isinstance(training_budget, int) or training_budget < 1:
        raise ExperimentError("training_budget must be positive")
    rows = {}
    if observations is not None:
        for row in observations:
            arm, task = row.get("arm_id"), row.get("task_id")
            if arm not in ARMS or task not in tasks or (arm, task) in rows:
                raise ExperimentError("invalid or duplicate external observation")
            metadata = (row.get("cells"), row.get("active_cells"), row.get("training_budget"), row.get("seed"))
            if metadata != (cells, active_cells, training_budget, seed):
                raise ExperimentError("external observation metadata drift")
            rows[(arm, task)] = {key: finite(row.get(key), key) for key in ("utility", "active_flops_g", "latency_us", "resident_memory_mb")}
        if len(rows) != len(ARMS) * len(tasks):
            raise ExperimentError("external observation set is incomplete")
    report = []
    rng = random.Random(seed)
    budget_gain = 1.0 - math.exp(-training_budget / 2000.0)
    for arm in ARMS:
        profile = PROFILES[arm]
        samples = []
        for index, task in enumerate(tasks):
            if observations is None:
                utility = max(0.0, min(1.0, profile["quality"] * budget_gain - 0.20 * ((index * 17 % 80) / 100.0) - profile["penalty"] + rng.uniform(-0.002, 0.002)))
                active_flops = active_cells * (0.012 + profile["flops_g"])
                latency = 80.0 + active_flops * 11.0 + rng.uniform(-1.0, 1.0)
                resident_memory = 1684.0 + cells * profile["memory_mb"]
            else:
                sample = rows[(arm, task)]
                utility, active_flops, latency, resident_memory = (sample[key] for key in ("utility", "active_flops_g", "latency_us", "resident_memory_mb"))
            samples.append((utility, active_flops, latency, resident_memory))
        utility = statistics.fmean(row[0] for row in samples)
        flops = statistics.fmean(row[1] for row in samples)
        report.append({"arm_id": arm, "cells": cells, "active_cells": active_cells, "utility": utility, "utility_per_active_flop": utility / flops if flops else None, "active_flops_g": flops, "latency_us": {f"p{p}": _quantile([row[2] for row in samples], p / 100) for p in (50, 95, 99)}, "resident_memory_mb": statistics.fmean(row[3] for row in samples), "incremental_parameters_m": profile["params_m"] if observations is None else None, "incremental_memory_mb": profile["memory_mb"] if observations is None else None, "negative_transfer_penalty": profile["penalty"] if observations is None else None, "optional_metric_coverage": {metric: 0 for metric in OPTIONAL_METRICS}, "old_task_retention": None, "calibration_ece": None, "calibration_brier": None, "ood_false_acceptance": None})
    profile = {"schema": "hepta.head-matrix-profile.v1", "stem_digest": digest({"stem": "frozen-shared-stem"}) if observations is None else None, "cells": cells, "active_cells": active_cells, "training_budget": training_budget, "seed": seed, "arms": PROFILES}
    return {"schema": SCHEMA, "benchmark_mode": "external_observation" if observations is not None else "synthetic_estimate", "profile": profile, "profile_digest": digest(profile), "results": report, "production_accepted": False, "model_selection_authority": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--execution-manifest", type=Path)
    parser.add_argument("--cells", type=int, default=32)
    parser.add_argument("--active-cells", type=int, default=1)
    parser.add_argument("--training-budget", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.execution_manifest is not None:
        if args.observations is not None:
            parser.error("real execution and imported observations are distinct modes")
        from experiments.shared_stem_cell.execution import run as execute
        execute(args.execution_manifest, args.output)
        return 0
    report = run(cells=args.cells, active_cells=args.active_cells, training_budget=args.training_budget, seed=args.seed, observations=_load_external(args.observations) if args.observations else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
