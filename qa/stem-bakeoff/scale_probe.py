#!/usr/bin/env python3
"""CPU fan-out probe of a tiny, RANDOM shared Stem and lightweight Cell heads.

This is an executable **synthetic shadow probe**.  It cannot establish
pretrained-model quality, hardware kernel counts, meaningful multimodal
ability, energy efficiency, or production readiness.  In particular its
latencies MUST NOT be submitted as real-teacher bake-off evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import statistics
import time
from typing import Any

from native_latent import (
    CellRequest, LightCellHead, SharedStemServer, StemContractError,
    StemSpec, build_encoder,
)

SCALES = (1, 8, 64, 256, 1024, 4096)
PROBE_SCHEMA = "hepta.shared-stem-tiny-fanout-probe.v1"


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples or not all(math.isfinite(x) and x >= 0 for x in samples):
        raise StemContractError("latency samples must be finite nonnegative numbers")
    ordered = sorted(samples)
    position = (len(ordered) - 1) * percentile / 100.0
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _peak_rss_bytes() -> int:
    # CI runs on Linux. On Linux ru_maxrss is kibibytes. Never silently
    # pretend this is a per-batch RSS or GPU-memory measurement.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def probe(*, scales: tuple[int, ...] = SCALES, repeats: int = 3,
          seed: int = 20261021) -> dict[str, Any]:
    """Measure a tiny 32d frozen CPU encoder + active Cell fan-out only.

    All Cell heads are freshly constructed once per scale; only the evaluate
    call is timed. Hence this is a request-serving, not a lifecycle benchmark.
    """
    if (not isinstance(scales, tuple) or not scales or
            any(type(n) is not int or n not in SCALES for n in scales) or
            list(scales) != sorted(set(scales)) or
            type(repeats) is not int or not 1 <= repeats <= 8 or
            type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise StemContractError("invalid scale/repeat/seed experiment plan")
    import torch

    torch.manual_seed(seed)
    torch.set_num_threads(1)
    width = 32
    encoder = build_encoder(StemSpec("tiny_random_probe_only", width, 1, 4),
                            device="cpu", trainable=False)
    server = SharedStemServer(encoder, generation=1, width=width,
                              encoder_sha256="0" * 64)
    model_hooks = [0]

    def observed_forward(_module: Any, _args: Any, _result: Any) -> None:
        model_hooks[0] += 1

    handle = encoder.register_forward_hook(observed_forward)
    rows = []
    try:
        slots = torch.randn(1, 4, width)
        for count in scales:
            heads = [LightCellHead(width).eval().requires_grad_(False)
                     for _ in range(count)]
            cell_param_counts = [sum(p.numel() for p in head.parameters()) for head in heads]
            if len(set(cell_param_counts)) != 1:
                raise StemContractError("heterogeneous Cell head sizes in toy probe")
            requests = [
                CellRequest(f"cell.{i:04d}", 1, head, torch.zeros(1, head.state_width),
                            "1" * 64)
                for i, head in enumerate(heads)
            ]
            timings = []
            prior_hook_calls = model_hooks[0]
            prior_owner_calls = server.owner_forward_calls
            for _ in range(repeats):
                start = time.perf_counter()
                answer = server.evaluate(slots, requests)
                timings.append((time.perf_counter() - start) * 1000)
                if (answer["owner_forward_calls_for_this_batch"] != 1 or
                        len(answer["cell_results"]) != count or
                        answer["authority"] != "DENY_ALL" or
                        answer["production_activation_allowed"] is not False):
                    raise StemContractError("toy fan-out violated the shadow boundary")
            if (model_hooks[0] - prior_hook_calls != repeats or
                    server.owner_forward_calls - prior_owner_calls != repeats):
                raise StemContractError("encoder owner was not invoked once per batch")
            rows.append({
                "cells": count,
                "measured_batches": repeats,
                "module_forward_hook_calls": model_hooks[0] - prior_hook_calls,
                "owner_forward_calls": server.owner_forward_calls - prior_owner_calls,
                "private_backbone_instances_detected": 0,
                "per_cell_head_parameters": cell_param_counts[0],
                "per_cell_head_fp32_weight_bytes_estimate": cell_param_counts[0] * 4,
                "p50_ms": round(statistics.median(timings), 6),
                "p95_ms": round(_percentile(timings, 95), 6),
                "p99_ms": round(_percentile(timings, 99), 6),
                "process_lifetime_peak_rss_bytes": _peak_rss_bytes(),
            })
            # Release per-scale heads to measure only the active cohort; note
            # ru_maxrss is a lifetime peak and therefore never resets here.
            del requests, heads, cell_param_counts
    finally:
        handle.remove()
    plan = {"schema": PROBE_SCHEMA, "seed": seed,
            "repeats": repeats, "scales": list(scales),
            "architecture": "tiny_random_32d_1layer_cpu_only"}
    plan_bytes = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return {
        **plan,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "measurements": rows,
        "model_pretrained": False,
        "real_model_quality_qualified": False,
        "physical_gpu_kernel_count_attested": False,
        "energy_measured": False,
        "independent_evidence_attested": False,
        "may_satisfy_real_model_bakeoff_gate": False,
        "runtime_posture": {"mode": "SHADOW_ONLY", "authority": "DENY_ALL",
                            "release": "HOLD_NO_GO"},
        "production_activation_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--scales", default=",".join(map(str, SCALES)))
    args = parser.parse_args()
    try:
        scales = tuple(int(item) for item in args.scales.split(","))
        outcome = probe(scales=scales, repeats=args.repeats, seed=args.seed)
    except (StemContractError, ValueError, RuntimeError, MemoryError) as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error),
                          "authority": "DENY_ALL",
                          "production_activation_allowed": False}))
        return 2
    print(json.dumps(outcome, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
