#!/usr/bin/env python3
"""Read-only 64/256/1024/4096 Cell real loopback inference resource probe."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import mean
from typing import Any

LEVELS = (64, 256, 1024, 4096)
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))]


def rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def gpu_bytes() -> int | None:
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=3, text=True,
        )
        return sum(int(x.strip()) for x in raw.splitlines()) * 1024 * 1024
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def probe(
    endpoint: str, pid: int, cells: int, active: int, generation: int,
    model_digest: str, timeout: float,
) -> dict[str, Any]:
    url = urllib.parse.urlsplit(endpoint)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or not url.port or url.username or url.password or url.fragment):
        raise ValueError("endpoint must be explicit loopback http://127.0.0.1:port/path")
    if active > cells or active <= 0 or cells not in LEVELS:
        raise ValueError("invalid Cell/concurrency profile")
    if generation <= 0 or HEX64.fullmatch(model_digest) is None:
        raise ValueError("model digest and generation must be pinned")
    if not Path(f"/proc/{pid}/status").is_file():
        raise ValueError("serving PID required for actual RSS")
    durations: list[float] = []
    queue_ages: list[int] = []
    errors: list[str] = []
    stop = threading.Event()
    rss_peak: list[int] = []
    gpu_peak: list[int] = []
    http_inflight_lock = threading.Lock()
    client_http_inflight = 0
    client_http_inflight_peak = 0

    def monitor() -> None:
        while not stop.is_set():
            rss, gpu = rss_bytes(pid), gpu_bytes()
            if rss is not None:
                rss_peak.append(rss)
            if gpu is not None:
                gpu_peak.append(gpu)
            stop.wait(0.1)

    def request(index: int) -> tuple[float, int]:
        nonlocal client_http_inflight, client_http_inflight_peak
        request_id = f"cell-qualification-{cells}-{index}"
        cell_id = f"cell-{index}"
        data = json.dumps({
            "request_id": request_id, "cell_id": cell_id,
            "generation": generation, "model_digest": model_digest,
            "mode": "read_only_qualification",
        }).encode()
        req = urllib.request.Request(
            endpoint, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        # Never follow redirect or ambient HTTP proxy from the local inference port.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                raise ValueError("local inference endpoint redirected; refuse external calls")

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
        )
        with http_inflight_lock:
            client_http_inflight += 1
            client_http_inflight_peak = max(client_http_inflight_peak, client_http_inflight)
        try:
            with opener.open(req, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("non-200 inference response")
                payload = response.read(128 * 1024 + 1)
                if len(payload) > 128 * 1024:
                    raise ValueError("oversized inference response")
                record = json.loads(payload)
        finally:
            with http_inflight_lock:
                client_http_inflight -= 1
        elapsed = (time.perf_counter() - started) * 1000
        if (
            record.get("request_id") != request_id
            or record.get("cell_id") != cell_id
            or record.get("generation") != generation
            or record.get("model_digest") != model_digest
            or record.get("terminal_observed") is not True
            or record.get("success") is not True
            or not isinstance(record.get("output_digest"), str)
            or HEX64.fullmatch(record["output_digest"]) is None
            or type(record.get("queue_age_us")) is not int
            or record["queue_age_us"] < 0
        ):
            raise ValueError(f"indeterminate/mismatched inference for {request_id}")
        return elapsed, record["queue_age_us"]

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    started = time.perf_counter()
    monitor_thread.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=active) as workers:
            pending = [workers.submit(request, i) for i in range(cells)]
            for future in concurrent.futures.as_completed(pending):
                try:
                    elapsed, queue_age = future.result()
                    durations.append(elapsed)
                    queue_ages.append(queue_age)
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        monitor_thread.join(timeout=5)
    seconds = time.perf_counter() - started
    return {
        "schema": "hepta.neuron.model-scale.observation.v1",
        "logical_cells": cells, "configured_active_workers": active,
        "client_http_inflight_peak": client_http_inflight_peak,
        "server_active_inference_peak": None,
        "concurrently_active": None,  # not observable from client HTTP concurrency alone
        "generation": generation, "model_digest": model_digest,
        "successes": len(durations), "failures": len(errors),
        "failure_examples": errors[:5],
        "latency_ms": {
            "p50": percentile(durations, 0.5) if durations else None,
            "p95": percentile(durations, 0.95) if durations else None,
            "p99": percentile(durations, 0.99) if durations else None,
            "mean": mean(durations) if durations else None,
        },
        "queue_age_us_p99": percentile(queue_ages, 0.99) if queue_ages else None,
        "throughput_rps": len(durations) / seconds,
        "p99_at_least_100_samples": len(durations) >= 100,
        "resource_measurements_complete": bool(rss_peak),
        "measurement_scope": "client_http_timing_not_attested_server_execution",
        "server_pid": pid,
        "server_rss_peak_bytes": max(rss_peak) if rss_peak else None,
        "host_total_gpu_memory_peak_bytes": max(gpu_peak) if gpu_peak else None,
        "gpu_memory_attribution": "whole_host_not_process_attributed",
        "model_load_ms": None, "model_load_receipt": "missing_external_observation",
        "qualification": False, "authority_granted": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--server-pid", type=int, required=True)
    p.add_argument("--model-digest", required=True)
    p.add_argument("--generation", type=int, required=True)
    p.add_argument("--active", type=int, default=8)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    records = []
    try:
        for cells in LEVELS:
            records.append(probe(
                a.endpoint, a.server_pid, cells, min(a.active, cells),
                a.generation, a.model_digest, a.timeout,
            ))
        report = {
            "schema": "hepta.neuron.model-scale.series.v1",
            "profiles": records, "independent_acceptance": False,
            "all_blockers_closed": False,
        }
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 0 if all(r["failures"] == 0 and r["successes"] == r["logical_cells"] for r in records) else 2
    except (OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
