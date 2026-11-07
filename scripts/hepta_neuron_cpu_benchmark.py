#!/usr/bin/env python3
"""Pinned three-arm serial CPU benchmark. Diagnostic ONLY; never model selection."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import statistics
import time

from hepta_neuron_artifact_preflight import inspect_local, verify_catalog
from hepta_neuron_model_trials import (
    MODEL_IDS,
    InvalidTrial,
    checked_probabilities,
    is_sha,
    read_json,
    require,
    sha_file,
    sha_tree,
    write_new,
)

SCHEMA = "hepta.neuron.serial-cpu-benchmark.diagnostic.v1"
EXPECTED_PARAMETERS = {"laya": 421293827, "typed": 421293827, "multilingual": 321908995}
STATE = "Synthetic record: invoice total requires a standard payment receipt."
QUESTION = {
    "type": "choice",
    "instructions": "Which queue handles a routine invoice?",
    "criteria": {
        "billing": "invoice and payment queries",
        "safety": "urgent incident reports",
    },
}
OPTIONS = ("billing", "safety")


def nearest_rank(values, percentile):
    require(
        bool(values)
        and percentile in (50, 95, 99)
        and all(type(x) in (float, int) and math.isfinite(x) and x > 0 for x in values),
        "positive finite latency samples required",
    )
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered) / 100) - 1)]


def process_memory():
    """Actual Linux process VmRSS and VmHWM in bytes. No synthetic fallback."""
    values = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            parts = value.strip().split()
            require(
                len(parts) == 2 and parts[1] == "kB" and parts[0].isdigit(),
                "malformed Linux RSS sample",
            )
            values[key] = int(parts[0]) * 1024
    require(
        set(values) == {"VmRSS", "VmHWM"} and 0 < values["VmRSS"] <= values["VmHWM"],
        "missing/inconsistent physical RSS",
    )
    return {"rss_bytes": values["VmRSS"], "peak_rss_bytes": values["VmHWM"]}


def validate_config(arm, sdk_sha, warmup, samples, threads):
    require(
        arm in EXPECTED_PARAMETERS and is_sha(sdk_sha),
        "frozen model and SDK identity required",
    )
    require(
        type(warmup) is int
        and 2 <= warmup <= 20
        and type(samples) is int
        and 100 <= samples <= 256
        and type(threads) is int
        and 1 <= threads <= 8,
        "bounded warmups, samples and CPU threads required",
    )


def benchmark(
    catalog_path, arm, artifact_dir, sdk_sha, warmup=5, samples=100, threads=2
):
    validate_config(arm, sdk_sha, warmup, samples, threads)
    catalog = verify_catalog(read_json(catalog_path))
    require(arm in catalog["variants"], "unknown catalog variant")
    artifact_dir = Path(artifact_dir)
    require(
        artifact_dir.is_absolute()
        and artifact_dir.is_dir()
        and not artifact_dir.is_symlink(),
        "model requires physical absolute directory",
    )
    physical = inspect_local(catalog, arm, artifact_dir)
    require(
        physical["local_weight_bytes_verified"] is True
        and sha_file(artifact_dir / "model.safetensors")
        == catalog["variants"][arm]["weights_sha256"],
        "model weights not verified",
    )
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "USE_TF": "0",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    import torch
    import laya

    require(
        sha_tree(Path(laya.__file__).parent, only_python=True) == sdk_sha,
        "installed Laya SDK differs from pinned source",
    )
    torch.set_num_threads(threads)
    require(torch.get_num_threads() == threads, "CPU thread cap ignored")
    before = process_memory()
    start = time.perf_counter_ns()
    agent = laya.load(str(artifact_dir), device="cpu")
    load_ms = (time.perf_counter_ns() - start) / 1e6
    require(str(agent.device) == "cpu", "unexpected model device")
    parameters = sum(p.numel() for p in agent.model.parameters())
    require(parameters == EXPECTED_PARAMETERS[arm], "model parameter inventory drift")
    require(
        type(agent.cfg.get("max_len")) is int
        and agent.cfg["max_len"] >= 512
        and type(agent.cfg.get("head_max_len", 192)) is int
        and agent.cfg.get("head_max_len", 192) >= 192,
        "unsupported matched token budgets",
    )
    agent.cfg["max_len"] = 512
    agent.cfg["head_max_len"] = 192
    after_load = process_memory()

    def forward():
        t0 = time.perf_counter_ns()
        result = agent.predict(STATE, {"q": QUESTION})
        elapsed = (time.perf_counter_ns() - t0) / 1e6
        require(str(agent.device) == "cpu", "model switched device")
        p = result["answers"]["q"]["probabilities"]
        require(
            isinstance(p, dict) and list(p) == list(OPTIONS),
            "synthetic option order drift",
        )
        checked_probabilities([p[k] for k in OPTIONS], len(OPTIONS))
        tokens = result["usage"]["input_tokens"]
        require(
            type(tokens) is int
            and 0 < tokens <= 512
            and math.isfinite(elapsed)
            and elapsed > 0,
            "invalid physical observation",
        )
        return elapsed, tokens

    for _ in range(warmup):
        forward()
    measured = [forward() for _ in range(samples)]
    times = [x[0] for x in measured]
    token_counts = [x[1] for x in measured]
    require(len(set(token_counts)) == 1, "repeated input changed token count")
    after_run = process_memory()
    require(
        sha_tree(artifact_dir) == physical["artifact_tree_sha256"],
        "model bytes changed during forward execution",
    )
    mean = statistics.mean(times)
    return {
        "schema": SCHEMA,
        "arm": arm,
        "model_id": MODEL_IDS[arm],
        "source_revision": catalog["revision"],
        "source_catalog_sha256": sha_file(catalog_path),
        "weights_sha256": catalog["variants"][arm]["weights_sha256"],
        "physical_artifact_tree_sha256": physical["artifact_tree_sha256"],
        "installed_sdk_python_sha256": sdk_sha,
        "device": "cpu",
        "torch_version": torch.__version__,
        "cpu_threads": threads,
        "parameters": parameters,
        "effective_context": 512,
        "effective_head_budget": 192,
        "warmup_count": warmup,
        "sample_count": samples,
        "input_tokens": token_counts[0],
        "load_ms": round(load_ms, 6),
        "p50_ms": round(nearest_rank(times, 50), 6),
        "p95_ms": round(nearest_rank(times, 95), 6),
        "p99_ms": round(nearest_rank(times, 99), 6),
        "mean_ms": round(mean, 6),
        "serial_invocations_per_second": round(1000 / mean, 5),
        "timing_samples_ms": [round(t, 6) for t in times],
        "rss_before_model_load": before,
        "rss_after_model_load": after_load,
        "rss_after_forwards": after_run,
        "measurement_scope": "serial single CPU process, synthetic repeated identical prompt",
        "backend_batch_throughput_measured": False,
        "actual_hepta_data_used": False,
        "independent_host_attestation": False,
        "production_p99_sla_established": False,
        "future_window_effectiveness_evaluated": False,
        "ndu_net_gain_verified": False,
        "ndu_selection_authorized": False,
        "production_evidence_verified": False,
        "promotion_authorized": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--arm", choices=tuple(EXPECTED_PARAMETERS), required=True)
    ap.add_argument("--artifact-dir", type=Path, required=True)
    ap.add_argument("--sdk-python-sha256", required=True)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        require(
            args.output.is_absolute() and not args.output.exists(),
            "diagnostic output must be new absolute file",
        )
        write_new(
            args.output,
            benchmark(
                args.catalog,
                args.arm,
                args.artifact_dir,
                args.sdk_python_sha256,
                warmup=args.warmup,
                samples=args.samples,
                threads=args.threads,
            ),
        )
    except (InvalidTrial, ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        ap.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()
