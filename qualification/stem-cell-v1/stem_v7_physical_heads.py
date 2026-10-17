"""Physical CPU FP32 gated-Head-only fleet probe. NO pretrained Encoder or Cell task learning."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SHAPE = (384, 8)
SIZE_LEVELS = (64, 256, 1024, 4096)
SEED = 7347
WARMUPS = 8
TRIALS = 64
SCHEMA = "hepta.stem.v7.physical-gated-heads.v1"


def gated_head_count(d=384, r=8):
    if type(d) is not int or type(r) is not int or d <= 0 or r <= 0:
        raise ValueError("positive integer feature and rank dimensions required")
    return 2 * d * r + 2 * d + 2


def vmrss_kib():
    """Only Linux process resident pages, not tensor size or GPU memory."""
    for row in Path("/proc/self/status").read_text().splitlines():
        if row.startswith("VmRSS:"):
            parts = row.split()
            if len(parts) == 3 and parts[2] == "kB":
                return int(parts[1])
    raise RuntimeError("Linux /proc VmRSS not available")


def pct(sorted_values, fraction):
    if not sorted_values or not 0 <= fraction <= 1:
        raise ValueError("nonempty metric and supported percentile")
    return sorted_values[min(len(sorted_values) - 1, int((len(sorted_values) - 1) * fraction + .999999))]


def _tensors(n, d=384, r=8):
    import torch
    torch.set_num_threads(1)
    gen = torch.Generator(device="cpu").manual_seed(SEED)
    weights = {
        "up": torch.randn((n, d, r), generator=gen, dtype=torch.float32) * .015,
        "down": torch.randn((n, r, d), generator=gen, dtype=torch.float32) * .015,
        "gate": torch.randn((n, d), generator=gen, dtype=torch.float32) * .015,
        "readout": torch.randn((n, d), generator=gen, dtype=torch.float32) * .015,
        "biases": torch.zeros((n, 2), dtype=torch.float32),
    }
    actual = sum(t.numel() for t in weights.values())
    assert actual == n * gated_head_count(d, r)
    return weights


def head_forward(weights, feature, ids):
    import torch
    if feature.ndim != 1 or feature.dtype != torch.float32 or ids.dtype != torch.int64:
        raise ValueError("one immutable, shared FP32 feature and Int64 active indexes required")
    n, d, r = weights["up"].shape
    if feature.shape != (d,) or ids.ndim != 1 or not 1 <= len(ids) <= min(n, 32):
        raise ValueError("active bounded feature batch required")
    if ids.min().item() < 0 or ids.max().item() >= n or len(set(ids.tolist())) != len(ids):
        raise ValueError("duplicate or out-of-range physical Head index")
    batch = feature.expand(len(ids), d).unsqueeze(-1)
    compressed = torch.relu(torch.bmm(weights["down"][ids], batch))
    residual = torch.bmm(weights["up"][ids], compressed).squeeze(-1)
    gate = torch.sigmoid((weights["gate"][ids] * feature).sum(dim=-1) + weights["biases"][ids, 0])
    hidden = feature + gate.unsqueeze(-1) * residual
    return (hidden * weights["readout"][ids]).sum(-1) + weights["biases"][ids, 1]


def measured_child(n):
    import torch
    if n not in SIZE_LEVELS:
        raise ValueError("one pinned fleet size required")
    torch.set_num_threads(1)
    process_cpu_start, wall_start = time.process_time(), time.perf_counter()
    before = vmrss_kib()
    weights = _tensors(n)
    actual = sum(t.numel() for t in weights.values())
    after = vmrss_kib()
    feature = torch.linspace(-1, 1, 384, dtype=torch.float32)
    active = min(n, 32)
    ids = torch.arange(active, dtype=torch.int64)
    with torch.no_grad():
        for _ in range(WARMUPS):
            head_forward(weights, feature, ids)
        ms = []
        digest = None
        for i in range(TRIALS):
            t0 = time.perf_counter_ns()
            output = head_forward(weights, feature, ids)
            ms.append((time.perf_counter_ns() - t0) / 1_000_000)
            if i == 0:
                digest = hashlib.sha256(output.contiguous().numpy().tobytes()).hexdigest()
    ms.sort()
    script = Path(__file__).read_bytes()
    return {
        "schema": SCHEMA, "model_material": "synthetic_frozen_feature_not_pretrained",
        "real_torch_cpu_forward": True, "real_pretrained_encoder_forward": False,
        "actual_pretrained_model_loaded": False, "model_task_learning_claim": False,
        "size": n, "active_heads_per_call": active,
        "per_head_params": gated_head_count(), "actual_allocated_head_params": actual,
        "actual_head_tensors": len(weights), "weight_dtype": "fp32", "torch_version": torch.__version__,
        "script_sha256": hashlib.sha256(script).hexdigest(), "feature_dimension": 384, "rank": 8,
        "source_feature_buffers": 1, "head_forward_calls": TRIALS,
        "warmup_calls": WARMUPS, "output_sha256": digest,
        "rss_before_allocation_kib": before, "rss_after_allocation_kib": after,
        "rss_after_trials_kib": vmrss_kib(),
        "wall_total_process_inside_seconds": time.perf_counter() - wall_start,
        "cpu_total_process_inside_seconds": time.process_time() - process_cpu_start,
        "latency_ms": {"p50": statistics.median(ms), "p95": pct(ms, .95),
                       "p99": pct(ms, .99), "max": max(ms)},
        "energy_joules": None, "gpu_vram_bytes": None, "encoder_forward_calls": 0,
        "production_authorized": False, "head_quality_verified": False,
        "target_dot_host_verified": False,
    }


def validate_physical_receipt(row, *, expected_script_sha256=None):
    if not isinstance(row, dict) or row.get("schema") != SCHEMA or row.get("size") not in SIZE_LEVELS:
        raise ValueError("known original physical fleet receipt required")
    n = row["size"]
    if (row.get("actual_allocated_head_params") != n * gated_head_count() or
            row.get("per_head_params") != gated_head_count() or
            row.get("feature_dimension") != 384 or row.get("rank") != 8 or
            row.get("actual_head_tensors") != 5 or row.get("weight_dtype") != "fp32" or
            row.get("head_forward_calls") != TRIALS or row.get("warmup_calls") != WARMUPS or
            row.get("active_heads_per_call") != min(n, 32) or
            row.get("source_feature_buffers") != 1 or row.get("encoder_forward_calls") != 0 or
            row.get("real_pretrained_encoder_forward") is not False or
            row.get("actual_pretrained_model_loaded") is not False or
            row.get("real_torch_cpu_forward") is not True or
            row.get("production_authorized") is not False or
            row.get("head_quality_verified") is not False or
            row.get("target_dot_host_verified") is not False or
            row.get("energy_joules") is not None or row.get("gpu_vram_bytes") is not None):
        raise ValueError("receipt overclaims model ability or changes physical Head counts")
    for name in ("script_sha256", "output_sha256"):
        value = row.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("complete digest required")
    if expected_script_sha256 is not None and row["script_sha256"] != expected_script_sha256:
        raise ValueError("source script changed")
    for field in ("rss_before_allocation_kib", "rss_after_allocation_kib", "rss_after_trials_kib"):
        if type(row.get(field)) is not int or row[field] <= 0:
            raise ValueError("measured Linux RSS required")
    for field in ("cpu_total_process_inside_seconds", "wall_total_process_inside_seconds"):
        value = row.get(field)
        if type(value) not in (int, float) or not 0 < value < float("inf"):
            raise ValueError("measured process cost required")
    metrics = row.get("latency_ms")
    if not isinstance(metrics, dict) or set(metrics) != {"p50", "p95", "p99", "max"}:
        raise ValueError("complete latency quantiles required")
    vals = [metrics[x] for x in ("p50", "p95", "p99", "max")]
    if any(type(v) not in (int, float) or not 0 < v < float("inf") for v in vals) or vals != sorted(vals):
        raise ValueError("finite ordered latency distribution required")
    return True


def run_suite(output):
    target = Path(output)
    if target.exists():
        raise FileExistsError("create-only original physical receipt; never replace results")
    rows = []
    with tempfile.TemporaryDirectory(prefix="stem-v7-heads-") as td:
        for n in SIZE_LEVELS:
            subpath = Path(td) / f"{n}.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--size", str(n),
                            "--output", str(subpath)], check=True, timeout=180,
                           env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
            row = json.loads(subpath.read_text())
            validate_physical_receipt(row, expected_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            rows.append(row)
    result = {"schema": SCHEMA, "kind": "locally_executed_synthetic_head_fleet",
              "size_levels": list(SIZE_LEVELS), "rows": rows,
              "physical_pretrained_encoder": False, "independent_task_quality": None,
              "production_authorized": False, "host_class": platform.system() + "_cpu_not_user_dot"}
    # The receipt is not a signed original source provenance claim.
    with target.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--size", type=int, choices=SIZE_LEVELS)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if args.size:
        out = measured_child(args.size)
        validate_physical_receipt(out, expected_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        target = Path(args.output)
        with target.open("x", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
    else:
        run_suite(args.output)


if __name__ == "__main__":
    main()
