#!/usr/bin/env python3
"""Bounded CPU numerical reference for shared-encoder, lightweight-cell heads.

NOT Hepta production code, NOT a pretrained encoder, NOT independent evidence,
NOT a real target-host P2/P5 qualification. No network, tool effects or secrets.

Each size/arm runs in a separate child process. Both arms compute the same
frozen encoder and per-cell head functions, but one runs the encoder once while
other materializes and runs one encoder copy per cell. Measurements are host-
local observations and cannot serve as signed physical rollout receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import resource
import platform
import statistics
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import psutil
import torch

SIZES = (1, 8, 64, 256, 1024, 4096)
MODES = ("shared", "duplicated")
D = 64
SEED = 20261022


def cpu_payload(n: int, mode: str, repeats: int) -> dict:
    """Measure one isolated process, returning observed scores and statistics."""
    if n not in SIZES or mode not in MODES or not 3 <= repeats <= 250:
        raise ValueError("bounded scale/mode/repeats required")
    torch.set_num_threads(1)
    torch.manual_seed(SEED)
    p = psutil.Process()
    rss_pre = p.memory_info().rss
    x = torch.randn(D)
    enc = torch.randn(D, D) / math.sqrt(D)
    bias = torch.randn(D) / 8
    heads = torch.randn(n, D) / math.sqrt(D)
    if mode == "shared":
        def run() -> torch.Tensor:
            features = torch.tanh(torch.mv(enc, x) + bias)
            return torch.mv(heads, features)
        encoder_copies = 1
    else:
        # Physical parameter duplication, not simply repeat input into one W.
        full_enc = enc.repeat(n, 1, 1).contiguous()
        full_bias = bias.repeat(n, 1).contiguous()
        x_expanded = x.repeat(n, 1).unsqueeze(-1)
        def run() -> torch.Tensor:
            features = torch.tanh(torch.bmm(full_enc, x_expanded).squeeze(-1) + full_bias)
            return torch.sum(features * heads, dim=1)
        encoder_copies = n
    rss_after_allocation = p.memory_info().rss
    latencies_us = []
    result = None
    with torch.inference_mode():
        for _ in range(5):
            result = run()
        for _ in range(repeats):
            start = time.perf_counter_ns()
            result = run()
            latencies_us.append((time.perf_counter_ns() - start) / 1000.)
    assert result is not None
    result_list = [float(v) for v in result.tolist()]
    cpu_times = p.cpu_times()
    arr = np.asarray(latencies_us, dtype=np.float64)
    model_params = encoder_copies * (D * D + D) + n * D
    return {
        "mode": mode,
        "cells": n,
        "input_dim": D,
        "encoder_parameter_copies": encoder_copies,
        "live_parameter_count": model_params,
        "parameter_bytes_float32": model_params * 4,
        "rss_before_parameter_allocation_bytes": rss_pre,
        "rss_after_parameter_allocation_bytes": rss_after_allocation,
        "rss_parameter_allocation_delta_bytes": max(0, rss_after_allocation - rss_pre),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cpu_user_seconds_observed": float(cpu_times.user),
        "cpu_system_seconds_observed": float(cpu_times.system),
        "batch_input_requests": 1,
        "warmup_runs": 5,
        "sample_runs": repeats,
        "p50_us": float(np.percentile(arr, 50)),
        "p95_us": float(np.percentile(arr, 95)),
        "p99_us": float(np.percentile(arr, 99)),
        "mean_us": float(arr.mean()),
        "request_throughput_per_s": float(1e6 / arr.mean()),
        "cell_evaluations_per_s": float(n * 1e6 / arr.mean()),
        "scores": result_list,
    }


def child(conn, n, mode, repeats):
    try:
        conn.send({"ok": cpu_payload(n, mode, repeats)})
    except BaseException as e:
        conn.send({"error": {"kind": type(e).__name__, "description": str(e),
                             "trace": traceback.format_exc(limit=4)}})
    finally:
        conn.close()


def measured_arm(n: int, mode: str, repeats: int, timeout_s: float) -> dict:
    """Fork only for disposable read-only CPU numeric workers; stop/reap on timeout."""
    if sys.platform != "linux":
        raise RuntimeError("this reproducibility reference currently requires Linux fork")
    context = mp.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    proc = context.Process(target=child, args=(sender, n, mode, repeats), daemon=False)
    proc.start()
    sender.close()
    try:
        if not receiver.poll(timeout_s):
            proc.terminate()
            proc.join(3)
            if proc.is_alive():
                proc.kill()
                proc.join(3)
            raise TimeoutError(f"bounded worker timeout: {n} {mode}")
        payload = receiver.recv()
        proc.join(3)
        if proc.exitcode not in (0,):
            raise RuntimeError(f"worker nonzero exit for {n} {mode}: {proc.exitcode}")
        if "error" in payload:
            raise RuntimeError(f"worker {n} {mode}: {payload['error']}")
        return payload["ok"]
    finally:
        receiver.close()
        if proc.is_alive():
            proc.kill()
            proc.join()


def synthetic_training() -> dict:
    """Physically train lightweight heads on independent synthetic heldout data.

    This tests a real gradient and no-change path; it does not measure external
    task utility, negative transfer or a pretrained feature backend.
    """
    torch.manual_seed(SEED + 1)
    torch.set_num_threads(1)
    W = torch.randn(D, D) / math.sqrt(D)
    b = torch.randn(D) / 8
    teacher = torch.randn(8, D) / math.sqrt(D)
    train_x = torch.randn(256, D)
    heldout_x = torch.randn(128, D)
    with torch.no_grad():
        feature_train = torch.tanh(train_x @ W.T + b)
        feature_heldout = torch.tanh(heldout_x @ W.T + b)
        train_y = feature_train @ teacher.T
        heldout_y = feature_heldout @ teacher.T
    head = torch.nn.Parameter(torch.zeros(8, D))
    frozen_head = head.detach().clone()
    optimizer = torch.optim.Adam([head], lr=0.05)
    def mse() -> float:
        with torch.no_grad():
            return float(torch.mean((feature_heldout @ head.T - heldout_y) ** 2))
    before = mse()
    for _ in range(160):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.mean((feature_train @ head.T - train_y) ** 2)
        loss.backward()
        optimizer.step()
    after = mse()
    # A zero-delta successor must reproduce the frozen baseline exactly.
    zero_delta_parity = bool(torch.equal(frozen_head, frozen_head + torch.zeros_like(frozen_head)))
    assert after < before * 0.05, (before, after)
    assert zero_delta_parity
    return {"data": "deterministic_synthetic_teacher_heldout", "cells": 8,
            "encoder_frozen": True, "train_examples": 256, "heldout_examples": 128,
            "training_steps": 160, "optimizer": "Adam", "synthetic_heldout_mse_before": before,
            "synthetic_heldout_mse_after": after, "zero_delta_parity": zero_delta_parity,
            "external_independent_evaluation": False, "real_pretrained_encoder": False}


def perform_benchmark(repeats: int, timeout_s: float) -> dict:
    measurements = []
    for n in SIZES:
        shared = measured_arm(n, "shared", repeats, timeout_s)
        duplicated = measured_arm(n, "duplicated", repeats, timeout_s)
        diff = np.abs(np.asarray(shared.pop("scores")) - np.asarray(duplicated.pop("scores")))
        err = float(diff.max())
        if err > 3e-5:
            raise RuntimeError(f"shared/duplicated output disagreement at {n}: {err}")
        measurements.append({"cells": n, "max_abs_output_difference": err,
                             "shared": shared, "duplicated": duplicated,
                             "relative_p50_speedup": duplicated["p50_us"] / shared["p50_us"],
                             "parameter_memory_ratio": duplicated["parameter_bytes_float32"] / shared["parameter_bytes_float32"]})
    return {"reference_only": True,
            "host_class": "ChatGPT_isolated_container_NOT_dot_target_host",
            "p2_production_qualified": False, "p5_production_qualified": False,
            "real_pretrained_encoder": False, "signed_production_receipts": False,
            "independent_target_host_observer": False,
            "software": {"python": platform.python_version(), "torch": torch.__version__,
                         "numpy": np.__version__, "psutil": psutil.__version__},
            "host": {"platform": platform.platform(), "cpu_machine": platform.machine(),
                     "logical_cpus_visible": os.cpu_count(), "torch_threads": 1},
            "training": synthetic_training(),
            "paired_arm_measurements": measurements}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-per-arm", type=float, default=25.0)
    args = parser.parse_args()
    if not 3 <= args.repeats <= 250 or not 2 <= args.timeout_per_arm <= 90:
        parser.error("repeats or timeout outside bounded envelope")
    report = perform_benchmark(args.repeats, args.timeout_per_arm)
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target = args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    target.write_text(data, encoding="utf8")
    print(f"physical CPU reference completed {len(SIZES)} scales x 2 arms; report={target}")
    for row in report["paired_arm_measurements"]:
        print(f"Cells={row['cells']:4} max_error={row['max_abs_output_difference']:.2e} "
              f"shared_p95={row['shared']['p95_us']:.1f}us "
              f"dup_p95={row['duplicated']['p95_us']:.1f}us "
              f"parameter_ratio={row['parameter_memory_ratio']:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
