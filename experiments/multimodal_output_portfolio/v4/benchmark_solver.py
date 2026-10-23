"""Named-host, cold-cache finite Bellman latency receipt (RESEARCH_ONLY).

No neural encoder, pretrained decoder or natural output is run here. Policy
costs and input-generation costs are not conflated with this pure solver timing.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import statistics
import time
import tracemalloc

from portfolio import Config, Controller, State

SAMPLES = 12
CASES = (
    ("easy", State((2, 2, 2, 2), 12)),
    ("text-gap", State((0, 2, 2, 2), 12)),
    ("all-gap", State((0, 0, 0, 0), 12)),
)


def q_ms(values: list[float], q: float) -> float:
    if not values or not 0 <= q <= 1 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid timing samples")
    ascending = sorted(values)
    return ascending[max(0, math.ceil(q * len(ascending)) - 1)]


def source_identity() -> dict:
    root = Path(__file__).resolve().parent
    paths = ("portfolio.py", "benchmark_solver.py")
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}


def run(samples: int = SAMPLES) -> dict:
    if type(samples) is not int or not 3 <= samples <= 100:
        raise ValueError("bounded replicate count required")
    cfg = Config(horizon=2, max_units_per_step=2, risk_aversion=0.5)
    cases = []
    for name, state in CASES:
        wall_ms, cpu_ms, nodes, branches = [], [], [], []
        first_action, value = None, None
        for _ in range(samples):
            gc.collect()
            controller = Controller(cfg)  # cold per-episode memo
            start_wall = time.perf_counter_ns()
            start_cpu = time.process_time_ns()
            action, current_value = controller.solve(state)
            cpu_ms.append((time.process_time_ns() - start_cpu) / 1e6)
            wall_ms.append((time.perf_counter_ns() - start_wall) / 1e6)
            work = controller.work_receipt()
            nodes.append(work["expanded_states"])
            branches.append(work["evaluated_branches"])
            if first_action is None:
                first_action, value = action.units, current_value
            elif action.units != first_action or abs(value - current_value) > 1e-12:
                raise AssertionError("different cold-solver decision on fixed state")
        tracemalloc.start()
        memory_controller = Controller(cfg)
        memory_controller.solve(state)
        _current_bytes, peak_python_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        cases.append({
            "case": name,
            "first_allocation": first_action,
            "finite_solver_value": value,
            "cold_wall_p50_ms": statistics.median(wall_ms),
            "cold_wall_p95_ms": q_ms(wall_ms, 0.95),
            "cold_wall_p99_ms": q_ms(wall_ms, 0.99),
            "cold_cpu_p50_ms": statistics.median(cpu_ms),
            "cold_cpu_p95_ms": q_ms(cpu_ms, 0.95),
            "logical_states": nodes[0],
            "logical_branches": branches[0],
            "stable_work_counts": len(set(zip(nodes, branches))) == 1,
            "peak_tracemalloc_bytes_separate_run": peak_python_bytes,
            "named_host_p95_under_2ms": q_ms(wall_ms, 0.95) <= 2.0,
        })
    return {
        "schema": "hepta.ndu-v4.bounded-solver-cost.v1",
        "scope": "RESEARCH_ONLY_DENY_ALL_SOLVER_ONLY",
        "source_sha256": source_identity(),
        "runner_name_unverified": os.getenv("RUNNER_NAME", "local"),
        "github_sha_unverified": os.getenv("GITHUB_SHA", "not-set"),
        "host": platform.platform(),
        "python": platform.python_version(),
        "samples_per_case": samples,
        "startup_encoder_decoder_and_training_excluded": True,
        "tracemalloc_timed_separately": True,
        "warmups": 0,
        "cases": cases,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
