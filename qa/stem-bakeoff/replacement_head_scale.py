"""Measure *actual* trained task-Head replicas on one previously encoded source.

This is a CPU-only, single-event, sequential shadow experiment, not an active
4096-Cell production proof, GPU benchmark, independent learning or Final-use.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

SCALES = (64, 256, 1024, 4096)
SAMPLES = 100
SCHEMA = "hepta.neuron.physical-head-fanout-shadow.v1"


def _rss() -> tuple[int, int]:
    try:
        status = Path("/proc/self/status").read_text()
    except OSError as exc:
        raise ValueError("Linux physical RSS receipt is required") from exc
    values = {}
    for line in status.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            parts = line.split()
            if len(parts) != 3 or parts[2] != "kB":
                raise ValueError("unexpected physical RSS record")
            values[parts[0][:-1]] = int(parts[1]) * 1024
    if "VmRSS" not in values or "VmHWM" not in values:
        raise ValueError("physical process RSS and high-water observations required")
    return values["VmRSS"], values["VmHWM"]


def _quantile_nearest_rank(samples: list[float], p: float) -> float:
    if len(samples) < SAMPLES or any(
        type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in samples
    ):
        raise ValueError("100 genuine positive finite raw latency samples required")
    ordered = sorted(samples)
    return ordered[math.ceil(p * len(ordered)) - 1]


def _feature_digest(feature) -> str:
    import torch

    data = feature.detach().cpu().contiguous()
    return hashlib.sha256(
        json.dumps([list(data.shape), str(data.dtype)], separators=(",", ":")).encode()
        + memoryview(data.view(torch.uint8).numpy()).tobytes()
    ).hexdigest()


def measure_trained_head_fanout(
    trained_head, source_feature, *, scales=SCALES, samples=SAMPLES
) -> dict:
    """Execute per-scale distinct physical Head allocations and 100 full batches.

    One feature from the real frozen Encoder is reused. All 4096 Heads are
    invoked sequentially, so 'active' here never implies parallel execution.
    """
    import torch

    if (
        type(scales) is not tuple or scales != SCALES
        or type(samples) is not int or samples != SAMPLES
    ):
        raise ValueError("fixed 64/256/1024/4096 x 100 pilot contract required")
    if not isinstance(trained_head, torch.nn.Linear):
        raise ValueError("original frozen trained Linear task Head required")
    if trained_head.training or any(
        p.requires_grad or p.grad is not None for p in trained_head.parameters()
    ):
        raise ValueError("trained Head must be evaluation-only and frozen")
    if not isinstance(source_feature, torch.Tensor) or source_feature.device.type != "cpu":
        raise ValueError("physical CPU source feature required")
    if (
        source_feature.ndim != 2 or source_feature.shape[0] != 1
        or source_feature.shape[1] != trained_head.in_features
        or source_feature.dtype != torch.float32
        or not bool(torch.isfinite(source_feature).all().item())
    ):
        raise ValueError("one finite original-width preencoded feature required")

    source_feature = source_feature.detach().contiguous()
    feature_sha256 = _feature_digest(source_feature)
    base_pointers = {p.untyped_storage().data_ptr() for p in trained_head.parameters()}
    before_rss, before_hwm = _rss()
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    measurements = []
    try:
        for count in scales:
            replicas = [copy.deepcopy(trained_head) for _ in range(count)]
            storages = [
                p.untyped_storage() for replica in replicas
                for p in replica.parameters()
            ]
            pointers = [storage.data_ptr() for storage in storages]
            if (
                len(pointers) != len(set(pointers))
                or base_pointers.intersection(pointers)
                or len(pointers) != 2 * count
            ):
                raise ValueError("private task Head storage aliased across Cells")
            if any(replica.training or any(
                p.requires_grad for p in replica.parameters()
            ) for replica in replicas):
                raise ValueError("private Head replicas changed frozen state")

            allocated_rss, allocated_hwm = _rss()
            timing = []
            checksum = 0.0
            with torch.inference_mode():
                for iteration in range(samples + 2):
                    started = time.perf_counter()
                    for replica in replicas:
                        output = replica(source_feature)
                        if output.shape != (1, 4) or not bool(
                            torch.isfinite(output).all().item()
                        ):
                            raise ValueError("non-finite or wrong-shaped trained Head output")
                        checksum += float(output[0, 0])
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if iteration >= 2:
                        if not math.isfinite(elapsed_ms) or elapsed_ms <= 0:
                            raise ValueError("invalid physical fanout duration")
                        timing.append(elapsed_ms)
            current_rss, high_water = _rss()
            if not math.isfinite(checksum):
                raise ValueError("physical Head inference checksum is nonfinite")
            measurements.append({
                "logical_cells": count,
                "head_calls_per_batch": count,
                "simultaneously_executing_heads": 1,
                "private_head_instances": len(replicas),
                "unique_parameter_storages": len(pointers),
                "actual_private_head_tensor_bytes": sum(s.nbytes() for s in storages),
                "source_feature_sha256": feature_sha256,
                "raw_full_fanout_latency_ms": timing,
                "full_batch_p50_ms": statistics.median(timing),
                "full_batch_p95_ms": _quantile_nearest_rank(timing, 0.95),
                "full_batch_p99_ms": _quantile_nearest_rank(timing, 0.99),
                "head_outputs_per_second": count * samples / (sum(timing) / 1000),
                "observed_rss_after_allocation_bytes": allocated_rss,
                "observed_rss_after_execution_bytes": current_rss,
                "process_high_water_rss_bytes": high_water,
                "previous_process_high_water_rss_bytes": allocated_hwm,
            })
            del replicas, storages, pointers
    finally:
        torch.set_num_threads(previous_threads)

    after_rss, after_hwm = _rss()
    return {
        "schema": SCHEMA,
        "source_feature_sha256": feature_sha256,
        "measurements": measurements,
        "model_encoder_forwards_within_probe": 0,
        "source_events": 1,
        "independent_input_event_scaling_measured": False,
        "target_device_qualified": False,
        "gpu_observed": False,
        "power_energy_observed": False,
        "process_before_rss_bytes": before_rss,
        "process_before_high_water_bytes": before_hwm,
        "process_after_rss_bytes": after_rss,
        "process_after_high_water_bytes": after_hwm,
        "mode": "SHADOW_ONLY",
        "authority": "DENY_ALL",
        "production_activation_allowed": False,
    }
