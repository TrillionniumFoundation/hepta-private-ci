"""Physical CPU Head-only scale probe; explicitly NOT a native Encoder/Worker E5.

Uses sealed, operator-supplied pretrained feature rows (or clearly synthetic
fixture rows). No model weights load, NDU or production grant is performed.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import platform
import time

import torch
from e1_e5_trial import MODELS, ResidualCellHead, load_inputs
from execution import bound_file, decode, integer, measured, sha, write_once


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty duration set")
    return ordered[math.ceil((len(ordered) - 1) * fraction)]


def probe(plan: Path, plan_sha: str, output: Path, *, model="granite97", cells=64,
          active_fraction=1.0, reuse=0.5, budget=2048, seed=123):
    integer(cells, 64, 4096, "logical cells")
    if cells not in (64, 256, 1024, 4096) or model not in MODELS or budget not in (2048, 8192, 16384):
        raise ValueError("non-preregistered scale profile")
    if type(active_fraction) not in (float, int) or active_fraction not in (0.01, 0.1, 0.5, 1.0):
        raise ValueError("unsupported active Cell fraction")
    if type(reuse) not in (int, float) or reuse not in (0.0, 0.5, 0.9):
        raise ValueError("unsupported fixed input-repeat fraction")
    integer(seed, 0, 2**31 - 1, "seed")
    raw = bound_file(plan, plan_sha)
    config = decode(raw)
    cases, features, _, baseline = load_inputs(plan.parent, config)
    items = sorted(cases.values(), key=lambda c: c["case_id"])
    # Reuse only same-scope request inputs. This probe does not encode new text.
    scope = items[0]["scope"]
    items = [x for x in items if x["scope"] == scope]
    count = max(1, math.ceil(cells * active_fraction))
    unique_requests = max(1, math.ceil(count * (1 - reuse)))
    physical_inputs = [items[i % len(items)] for i in range(unique_requests)]
    if len({x["input_sha256"] for x in physical_inputs}) < min(unique_requests, len(items)):
        raise ValueError("bad unique feature cohort")
    # Cold-cache. Count physical borrow operations separately from encoder forwards.
    cache = OrderedDict()
    latencies = []
    checksum = 0.0
    torch.set_num_threads(1)
    sampled_peak_rss = None
    try:
        import psutil
        process = psutil.Process(os.getpid())
        sampled_peak_rss = process.memory_info().rss
    except (ImportError, OSError):
        process = None
    with measured() as meter:
        for i in range(count):
            case = physical_inputs[i % unique_requests]
            key = (scope, config["models"][model]["revision"], case["input_sha256"])
            tic = time.perf_counter_ns()
            if key not in cache:
                cache[key] = torch.tensor(features[(model, case["case_id"])]["vector"], dtype=torch.float32).unsqueeze(0)
            # Real per-Cell distinct weights, but they are untrained mechanism fixtures.
            torch.manual_seed(seed + i)
            head = ResidualCellHead(MODELS[model][0], budget, anchored=True).eval()
            s = torch.tensor(case["state"], dtype=torch.float32).unsqueeze(0)
            p = torch.tensor(baseline[case["case_id"]], dtype=torch.float32).clamp_min(1e-7).log().unsqueeze(0)
            with torch.no_grad():
                y = head(cache[key], s, p).softmax(-1)
            checksum += float(y[0, 1].item())
            latencies.append(time.perf_counter_ns() - tic)
            if process is not None and i % 32 == 0:
                try:
                    sampled_peak_rss = max(sampled_peak_rss, process.memory_info().rss)
                except OSError:
                    pass
    meter["sampled_process_rss_peak_lower_bound_bytes"] = sampled_peak_rss
    try:
        import resource
        # Linux ru_maxrss is a process-LIFETIME high-water mark, not a per-arm peak.
        meter["process_lifetime_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except (ImportError, AttributeError, OSError):
        meter["process_lifetime_peak_rss_bytes"] = None
    retained = sum(t.numel() * t.element_size() for t in cache.values())
    return write_once(output, {
        "schema": "hepta.stem-e5-head-only-physical.v1", "source_plan_sha256": plan_sha,
        "source_feature_sha256": config["files"]["features"]["sha256"],
        "model_id": model, "logical_cells": cells, "active_fraction": active_fraction,
        "active_cells": count, "requested_repeat_fraction": reuse,
        "unique_feature_keys": len(cache), "cache_hits": count - len(cache),
        "physical_head_forwards": count, "physical_encoder_forwards": 0,
        "head_parameters_each": ResidualCellHead(MODELS[model][0], budget, anchored=True).parameter_count(),
        "trained_heads": 0, "distinct_untrained_head_initializations": count,
        "physical_output_sum_diagnostic": checksum,
        "cache_retained_tensor_bytes": retained,
        "backend_latency_p50_ns": percentile(latencies, 0.5),
        "backend_latency_p95_ns": percentile(latencies, 0.95) if len(latencies) >= 20 else None,
        "backend_latency_p99_ns": percentile(latencies, 0.99) if len(latencies) >= 100 else None,
        "latency_sample_count": len(latencies),
        "process_measurement": meter,
        "runtime": {"python": platform.python_version(), "torch": torch.__version__,
                    "platform": platform.platform(), "cpu_count": os.cpu_count()},
        "native_worker": False, "pretrained_encoder_loaded": False,
        "gpu_power_energy_measured": False, "checkpoint_recovery_executed": False,
        "final_use_authorized": False, "production_promotion_permitted": False,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--model", choices=MODELS, default="granite97")
    parser.add_argument("--cells", type=int, choices=(64, 256, 1024, 4096), required=True)
    parser.add_argument("--active-fraction", type=float, choices=(0.01, 0.1, 0.5, 1.0), default=1.0)
    parser.add_argument("--reuse", type=float, choices=(0.0, 0.5, 0.9), default=0.5)
    parser.add_argument("--head-budget", type=int, choices=(2048, 8192, 16384), default=2048)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("head_only_physical_sha256=" + probe(args.plan, args.plan_sha256, args.output,
        model=args.model, cells=args.cells, active_fraction=args.active_fraction,
        reuse=args.reuse, budget=args.head_budget))
