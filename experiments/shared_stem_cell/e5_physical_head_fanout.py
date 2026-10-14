#!/usr/bin/env python3
"""Real CPU 9,744-param Cell Head work on ONE synthetic Q24 feature.

Unlike the production Worker, this isolated process has no authenticated
pretrained Encoder, permission checks, training utility or hardware power meter.
Run each cell count/mode in a new OS process: /proc RSS is process-wide.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import time

CELLS = (64, 256, 1024, 4096)
MODES = ("shared", "cloned")
SCHEMA = "hepta.e5-local-cpu-head-fanout.v1"
PARAMETERS_PER_HEAD = 9744

class Invalid(ValueError):
    pass


def percentile(items, probability):
    if not items:
        raise Invalid("empty latency distribution")
    data = sorted(items)
    i = (len(data) - 1) * probability
    lo, hi = math.floor(i), math.ceil(i)
    return data[lo] + (data[hi] - data[lo]) * (i - lo)


def make_head(torch):
    nn = torch.nn

    class StateGatedHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.down = nn.Linear(384, 8, bias=False)
            self.gate = nn.Linear(64, 8)
            self.up = nn.Linear(8, 384, bias=False)
            self.output = nn.Linear(384, 8)
            nn.init.zeros_(self.up.weight)

        def forward(self, feature, state):
            common = feature.detach()
            local = state.detach()
            residual = self.up(torch.nn.functional.silu(self.down(common)) * torch.sigmoid(self.gate(local)))
            return self.output(common + residual)

    result = StateGatedHead()
    if sum(p.numel() for p in result.parameters()) != PARAMETERS_PER_HEAD:
        raise Invalid("unregistered Head geometry")
    return result


def _weight_sha(head):
    h = hashlib.sha256(b"hepta.e5.cpu-head-weights.v1")
    for name, tensor in sorted(head.state_dict().items()):
        h.update(name.encode() + b"\0")
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def run(*, logical_cells, active_cells, mode, train_steps=1, repeats=2, seed=20261014):
    if logical_cells not in CELLS or type(active_cells) is not int or not 1 <= active_cells <= logical_cells:
        raise Invalid("unregistered logical/active Cell cohort")
    if mode not in MODES or type(train_steps) is not int or not 0 <= train_steps <= 4:
        raise Invalid("unregistered clone/training configuration")
    if type(repeats) is not int or not 1 <= repeats <= 100 or type(seed) is not int or seed < 0:
        raise Invalid("invalid repeat/seed")
    import torch
    import psutil
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    process = psutil.Process()
    start_cpu = time.process_time_ns()
    start_wall = time.perf_counter_ns()
    heads = [make_head(torch) for _ in range(logical_cells)]
    real_head_parameters = sum(sum(p.numel() for p in h.parameters()) for h in heads)
    if real_head_parameters != logical_cells * PARAMETERS_PER_HEAD:
        raise Invalid("Head inventory missing")
    # This is an engineered, SYNTHETIC feature, NOT a physical Encoder forward.
    common = torch.round(torch.linspace(-1, 1, 384, dtype=torch.float32) * (1 << 24)) / (1 << 24)
    common = common.reshape(1, -1).detach()
    features = [common] * active_cells if mode == "shared" else [common.clone().detach() for _ in range(active_cells)]
    unique_buffers = len({v.data_ptr() for v in features})
    expected = 1 if mode == "shared" else active_cells
    if unique_buffers != expected or any(not torch.equal(v, common) for v in features):
        raise Invalid("shared/clone tensor identity broken")
    states = [torch.full((1, 64), ((i % 23) - 11) / 20, dtype=torch.float32) for i in range(active_cells)]
    encoded_bytes_per_value = common.numel() * common.element_size()
    resident_shared_bytes = encoded_bytes_per_value * unique_buffers
    rss_ready = process.memory_info().rss
    order = tuple(range(active_cells))
    for idx in order[:min(8, active_cells)]:
        with torch.inference_mode():
            v = heads[idx](features[idx], states[idx])
            if not bool(torch.isfinite(v).all()):
                raise Invalid("nonfinite pre-warmup Head")
    latencies = []
    digest = hashlib.sha256(b"hepta.e5.cpu-forward-v1")
    inference_started = time.perf_counter_ns()
    with torch.inference_mode():
        for _ in range(repeats):
            for idx in order:
                tick = time.perf_counter_ns()
                value = heads[idx](features[idx], states[idx])
                latencies.append((time.perf_counter_ns() - tick) / 1e6)
                digest.update(value.contiguous().numpy().tobytes())
    serve_ms = (time.perf_counter_ns() - inference_started) / 1e6
    before = [_weight_sha(heads[i]) for i in order] if train_steps else []
    train_start = time.perf_counter_ns()
    # A genuine per-Head SGD parameter update; no label/outcome from real tasks.
    for _ in range(train_steps):
        for idx in order:
            head = heads[idx]
            head.zero_grad(set_to_none=True)
            logits = head(features[idx], states[idx])
            label = torch.tensor([idx % 8], dtype=torch.long)
            loss = torch.nn.functional.cross_entropy(logits, label)
            if not bool(torch.isfinite(loss)):
                raise Invalid("nonfinite train loss")
            loss.backward()
            with torch.no_grad():
                for weight in head.parameters():
                    if weight.grad is None or not bool(torch.isfinite(weight.grad).all()):
                        raise Invalid("missing/nonfinite gradient")
                    weight.add_(weight.grad, alpha=-0.01)
    train_ms = (time.perf_counter_ns() - train_start) / 1e6
    after = [_weight_sha(heads[i]) for i in order] if train_steps else []
    learned = sum(x != y for x, y in zip(before, after))
    if train_steps and learned != active_cells:
        raise Invalid("not all active Cell parameters updated")
    if common.requires_grad or any(v.requires_grad for v in features):
        raise Invalid("backpropagation entered shared features")
    finish_wall = (time.perf_counter_ns() - start_wall) / 1e6
    rss_finish = process.memory_info().rss
    return {
        "schema": SCHEMA,
        "authority": "DENY_ALL", "production_promotion_permitted": False,
        "real_pytorch_cpu_head_forward": True, "actual_pretrained_encoder_forward": False,
        "synthetic_input_and_labels": True, "production_worker_or_ndu_verified": False,
        "final_use_or_scope_fence_implemented": False,
        "hardware_energy_joules": None, "physical_gpu_time_ms": None,
        "logical_cells": logical_cells, "active_cells": active_cells, "mode": mode,
        "seed": seed, "train_steps_per_active_cell": train_steps, "serving_repeats": repeats,
        "physical_cell_head_parameters": real_head_parameters,
        "per_head_parameters": PARAMETERS_PER_HEAD, "heads_with_changed_weights": learned,
        "synthetic_feature_producer_count": 1,
        "physical_feature_buffer_count": unique_buffers,
        "resident_feature_tensor_payload_bytes": resident_shared_bytes,
        "synthetic_feature_q24_sha256": hashlib.sha256(common.numpy().tobytes()).hexdigest(),
        "sampled_f32_prediction_sha256": digest.hexdigest(),
        "raw_sample_count": len(latencies),
        "observed_per_head_forward_latency_ms": {
            "p50": percentile(latencies, .50), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99)
        },
        "measured_serving_loop_wall_ms": serve_ms,
        "measured_training_loop_wall_ms": train_ms,
        "measured_process_wall_ms": finish_wall,
        "measured_process_cpu_ms": (time.process_time_ns() - start_cpu) / 1e6,
        "observed_process_rss_ready_bytes": rss_ready,
        "observed_process_rss_after_bytes": rss_finish,
        "observed_process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "observed_throughput_outputs_per_second": len(latencies) / (serve_ms / 1000),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=int, choices=CELLS, required=True)
    parser.add_argument("--active", type=int, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--train-steps", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("observed receipt must be create-only")
    result = run(logical_cells=args.cells, active_cells=args.active, mode=args.mode,
                 train_steps=args.train_steps, repeats=args.repeats)
    with args.output.open("x", encoding="utf8") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
