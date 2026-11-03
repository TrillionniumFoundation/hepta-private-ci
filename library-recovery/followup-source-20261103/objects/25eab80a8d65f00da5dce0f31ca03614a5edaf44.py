#!/usr/bin/env python3
"""Repeated, SINGLE-REQUEST Laya CPU diagnostic; no user data or production authority.

Requires immutable publisher-pinned, fully materialized weights and a pinned
installed Laya SDK. Runs one identical synthetic prompt with a fixed 512/192
context budget. Reports process RSS and exact serial-forward timing samples.
This is NOT backend batch throughput, p99 SLA evidence, efficacy or NDU gain.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import statistics
import time

from hepta_neuron_artifact_preflight import inspect_local, verify_catalog
from hepta_neuron_model_trials import (
    InvalidTrial, MODEL_IDS, checked_probabilities, is_sha,
    read_json, require, sha_file, sha_tree, write_new,
)

SCHEMA = "hepta.neuron.serial-cpu-benchmark.diagnostic.v1"
EXPECTED_PARAMETERS = {"laya": 421293827, "typed": 421293827, "multilingual": 321908995}
STATE = "Synthetic record: invoice total requires a standard payment receipt."
QUESTION = {"type": "choice", "instructions": "Which queue handles a routine invoice?",
            "criteria": {"billing": "invoice and payment queries",
                         "safety": "urgent incident reports"}}
OPTIONS = ("billing", "safety")


def nearest_rank(values: list[float], percentile: int) -> float:
    require(bool(values) and percentile in (50, 95, 99) and
            all(type(x) in (float, int) and math.isfinite(x) and x > 0 for x in values),
            "finite positive timing samples required")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered) / 100) - 1)]


def memory_bytes() -> dict[str, int]:
    """Linux process-resident current/peak; fail closed on unsupported hosts."""
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    entries = {}
    for line in status.splitlines():
        key, _, rest = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            words = rest.strip().split()
            require(len(words) == 2 and words[1] == "kB" and words[0].isdigit(),
                    "invalid Linux RSS sample")
            entries[key] = int(words[0]) * 1024
    require(set(entries) == {"VmRSS", "VmHWM"} and
            0 < entries["VmRSS"] <= entries["VmHWM"], "RSS values missing or inconsistent")
    return {"rss_bytes": entries["VmRSS"], "peak_rss_bytes": entries["VmHWM"]}


def validate_options(arm: str, sdk_sha: str, device: str,
                     warmup: int, samples: int, threads: int) -> None:
    require(arm in EXPECTED_PARAMETERS and is_sha(sdk_sha),
            "supported model and exact SDK source digest required")
    require(device == "cpu", "repeated diagnostic is CPU-only; no implicit fallback")
    require(type(warmup) is int and 2 <= warmup <= 20 and
            type(samples) is int and 100 <= samples <= 256 and
            type(threads) is int and 1 <= threads <= 8,
            "explicit bounded warmup/sample/thread counts required")


def run_benchmark(catalog_path: Path, arm: str, artifact_dir: Path,
                  sdk_sha: str, *, device: str = "cpu", warmup: int = 5,
                  samples: int = 100, threads: int = 2) -> dict:
    validate_options(arm, sdk_sha, device, warmup, samples, threads)
    catalog = verify_catalog(read_json(catalog_path))
    require(arm in catalog["variants"], "variant not present in immutable catalog")
    artifact_dir = Path(artifact_dir)
    require(artifact_dir.is_absolute() and artifact_dir.is_dir() and not artifact_dir.is_symlink(),
            "new absolute local artifact directory required")
    physical = inspect_local(catalog, arm, artifact_dir)
    require(physical["local_weight_bytes_verified"] is True, "local weights not physically verified")
    require(sha_file(artifact_dir / "model.safetensors") == catalog["variants"][arm]["weights_sha256"],
            "physical model weights mismatch")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["USE_TF"] = "0"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    import laya
    require(sha_tree(Path(laya.__file__).parent, only_python=True) == sdk_sha,
            "installed Laya SDK source differs from pinned checkout")
    torch.set_num_threads(threads)
    require(torch.get_num_threads() == threads, "torch CPU thread cap ignored")
    before_load = memory_bytes()
    load_start = time.perf_counter_ns()
    agent = laya.load(str(artifact_dir), device=device)
    load_ms = (time.perf_counter_ns() - load_start) / 1e6
    require(str(agent.device) == "cpu", "model switched execution device")
    parameter_count = sum(p.numel() for p in agent.model.parameters())
    require(parameter_count == EXPECTED_PARAMETERS[arm], "checkpoint parameter inventory drift")
    require(type(agent.cfg.get("max_len")) is int and agent.cfg["max_len"] >= 512,
            "model cannot support matched input token budget")
    require(type(agent.cfg.get("head_max_len", 192)) is int and
            agent.cfg.get("head_max_len", 192) >= 192,
            "model cannot support matched option token budget")
    agent.cfg["max_len"] = 512
    agent.cfg["head_max_len"] = 192
    after_load = memory_bytes()

    def one_forward() -> tuple[float, int]:
        start = time.perf_counter_ns()
        result = agent.predict(STATE, {"q": QUESTION})
        elapsed_ms = (time.perf_counter_ns() - start) / 1e6
        require(str(agent.device) == "cpu", "model silently changed device")
        response = result["answers"]["q"]["probabilities"]
        require(isinstance(response, dict) and list(response) == list(OPTIONS),
                "model reordered synthetic options")
        checked_probabilities([response[k] for k in OPTIONS], len(OPTIONS))
        n_tokens = result["usage"]["input_tokens"]
        require(type(n_tokens) is int and 0 < n_tokens <= 512,
                "invalid effective input token count")
        require(math.isfinite(elapsed_ms) and elapsed_ms > 0, "invalid physical latency")
        return elapsed_ms, n_tokens

    for _ in range(warmup):
        one_forward()
    timings: list[float] = []
    token_counts: list[int] = []
    for _ in range(samples):
        dt, n = one_forward()
        timings.append(dt)
        token_counts.append(n)
    after_run = memory_bytes()
    require(len(set(token_counts)) == 1, "identical fixed input changed token count")
    require(sha_tree(artifact_dir) == physical["artifact_tree_sha256"],
            "artifact bytes changed during benchmark")
    runtime = {
        "schema": SCHEMA, "arm": arm, "model_id": MODEL_IDS[arm],
        "source_revision": catalog["revision"], "source_catalog_sha256": sha_file(catalog_path),
        "weights_sha256": catalog["variants"][arm]["weights_sha256"],
        "physical_artifact_tree_sha256": physical["artifact_tree_sha256"],
        "installed_sdk_python_sha256": sdk_sha,
        "device": device, "torch_version": torch.__version__, "cpu_threads": threads,
        "parameters": parameter_count, "effective_context": 512, "effective_head_budget": 192,
        "warmup_count": warmup, "sample_count": samples,
        "input_tokens": token_counts[0], "load_ms": round(load_ms, 6),
        "p50_ms": round(nearest_rank(timings, 50), 6),
        "p95_ms": round(nearest_rank(timings, 95), 6),
        "p99_ms": round(nearest_rank(timings, 99), 6),
        "mean_ms": round(statistics.mean(timings), 6),
        "serial_invocations_per_second": round(1000 / statistics.mean(timings), 5),
        "timing_samples_ms": [round(t, 6) for t in timings],
        "rss_before_model_load": before_load,
        "rss_after_model_load": after_load,
        "rss_after_forwards": after_run,
        "measurement_scope": "serial single CPU process, synthetic repeated identical prompt",
        "backend_batch_throughput_measured": False,
        "actual_hepta_data_used": False, "independent_host_attestation": False,
        "production_p99_sla_established": False,
        "future_window_effectiveness_evaluated": False,
        "ndu_net_gain_verified": False,
        "ndu_selection_authorized": False,
        "production_evidence_verified": False,
        "promotion_authorized": False,
    }
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--arm", choices=tuple(EXPECTED_PARAMETERS), required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--sdk-python-sha256", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(args.output.is_absolute() and not args.output.exists(),
                "diagnostic output must be fresh absolute file")
        report = run_benchmark(args.catalog, args.arm, args.artifact_dir,
                               args.sdk_python_sha256, device=args.device,
                               warmup=args.warmup, samples=args.samples, threads=args.threads)
        write_new(args.output, report)
    except (InvalidTrial, OSError, TypeError, KeyError, ValueError, ImportError) as e:
        parser.exit(2, f"blocked: {e}\n")

if __name__ == "__main__":
    main()
