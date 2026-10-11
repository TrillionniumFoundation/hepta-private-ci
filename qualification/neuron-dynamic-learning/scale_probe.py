"""Bounded real CPU numeric-head stress, *not* an end-to-end Encoder benchmark.

Physical Encoder, final-use, CAS, WAL, CPU-normalized target-host budgets and
production recovery remain required. No synthetic workload is promotable.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import time

import numpy as np

from cell_learning import DynamicCell, LearningContractError

CELL_SCALES = (64, 256, 1024, 4096)
ACTIVE_FRACTIONS = (0.05, 0.25, 1.0)
REUSE_FRACTIONS = (0.0, 0.5, 0.9)


def _resident_rss_bytes() -> int:
    try:
        # Linux current VmRSS (not maxrss); fallback below is process peak.
        with open("/proc/self/status", encoding="ascii") as source:
            for line in source:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(max_rss) * (1 if os.uname().sysname == "Darwin" else 1024)


def run_head_probe(
    logical_cells: int, active_fraction: float, input_reuse: float, *,
    feature_width: int = 384, seed: int = 17,
) -> dict:
    if (
        logical_cells not in CELL_SCALES or active_fraction not in ACTIVE_FRACTIONS
        or input_reuse not in REUSE_FRACTIONS or not 1 <= feature_width <= 512
    ):
        raise LearningContractError("non-preregistered scale scenario")
    n_active = max(1, round(logical_cells * active_fraction))
    n_unique = max(1, round(n_active * (1.0 - input_reuse)))
    rng = np.random.default_rng(seed)
    # All Cells belong to one admitted synthetic scope/principal/purpose.
    # Distinct scopes MUST NOT use this deduplication pool.
    unique = rng.normal(0.0, 0.35, (n_unique, feature_width))
    unique.setflags(write=False)
    shared_views = [unique[index % n_unique] for index in range(n_active)]
    heads = [
        DynamicCell.initialize(
            f"cell.{i}", "a" * 64, feature_width,
            min(16, feature_width), 8, seed + i,
        )
        for i in range(logical_cells)
    ]
    durations = []
    output_checksum = 0.0
    rss_before = _resident_rss_bytes()
    started = time.perf_counter_ns()
    for cell, feature in zip(heads, shared_views):
        tick = time.perf_counter_ns()
        prediction = cell.predict(feature.reshape(1, feature_width))
        durations.append((time.perf_counter_ns() - tick) / 1000)
        output_checksum += float(prediction[0])
    total_seconds = (time.perf_counter_ns() - started) / 1e9
    rss_after = _resident_rss_bytes()
    if not np.isfinite(output_checksum) or total_seconds <= 0:
        raise LearningContractError("invalid actual CPU numeric result")
    return {
        "evidence_type": "synthetic_inputs_real_numpy_head_arithmetic",
        "production_promotion": "DENY_ALL",
        "physical_pretrained_encoder_executed": False,
        "encoder_forward_calls": None,
        "logical_cells": logical_cells,
        "active_cells": n_active,
        "active_fraction": active_fraction,
        "input_reuse_fraction": input_reuse,
        "distinct_synthetic_inputs": n_unique,
        "feature_width": feature_width,
        "head_parameter_bytes": sum(head.parameter_count() * 8 for head in heads),
        "logical_feature_buffer_bytes": n_unique * feature_width * 8,
        "measured_rss_before_bytes": rss_before,
        "measured_rss_after_bytes": rss_after,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            * (1 if os.uname().sysname == "Darwin" else 1024),
        "p50_head_micros": float(np.percentile(durations, 50)),
        "p95_head_micros": float(np.percentile(durations, 95)),
        "p99_head_micros": float(np.percentile(durations, 99)),
        "head_throughput_per_second": n_active / total_seconds,
        "checksum": output_checksum,
        "missing_production_evidence": [
            "real_pretrained_encoder", "real_worker_batch", "target_host",
            "peak_rss_under_workload", "wal_fsync", "unclean_recovery",
            "signed_final_use", "future_ndu", "cold_wake_model_load",
        ],
    }


def full_matrix() -> list[dict]:
    return [
        run_head_probe(n, active, reuse)
        for n in CELL_SCALES
        for active in ACTIVE_FRACTIONS
        for reuse in REUSE_FRACTIONS
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="36 actual numeric CPU stress scenarios")
    args = parser.parse_args()
    result = full_matrix() if args.full else [
        run_head_probe(64, 0.25, 0.5)
    ]
    print(json.dumps(result, indent=2, sort_keys=True))
