"""Strict raw-resource trace checks for NEU-1 research; never production authority."""
from __future__ import annotations

import math
import re

HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class TraceEvidenceError(ValueError):
    """Workload summary lacks valid raw backing evidence."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise TraceEvidenceError(reason)


def number(v: object, *, positive: bool = False) -> bool:
    return type(v) in (int, float) and math.isfinite(v) and (v > 0 if positive else v >= 0)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    x = (len(ordered) - 1) * p / 100
    a, b = math.floor(x), math.ceil(x)
    return ordered[a] + (ordered[b] - ordered[a]) * (x - a)


def near(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=.02, abs_tol=1e-5)


def audit_trace(summary: dict, samples: list[dict]) -> dict:
    """Recompute observed end-to-end latency, throughput, concurrency, Cell coverage.

    Nanosecond clocks originate with the worker. A self-reported trace is NOT an
    independent attestation: target-host custody/signatures must be verified later.
    """
    scale, active = summary.get("logical_cells"), summary.get("active_cells")
    require(type(scale) is int and scale in (64, 256, 1024, 4096), "unregistered Cell scale")
    require(type(active) is int and 1 <= active <= scale, "invalid active Cell count")
    require(type(summary.get("requests")) is int and summary["requests"] == len(samples),
            "request count must equal raw trace length")
    require(len(samples) >= max(100, scale), "insufficient raw requests or Cell coverage for p99")
    require(summary.get("device") in ("cpu", "cuda", "mps", "xpu"), "target device identity required")
    digest = summary.get("model_weights_sha256")
    require(type(digest) is str and HEX64.fullmatch(digest) is not None,
            "workload must bind selected model weights")
    require(type(summary.get("host_id")) is str and bool(summary["host_id"]), "host required")
    require(type(summary.get("arm")) is str and bool(summary["arm"]), "arm required")
    require(type(summary.get("load_started_ns")) is int and summary["load_started_ns"] >= 0,
            "observed load start required")
    require(type(summary.get("load_completed_ns")) is int and
            summary["load_completed_ns"] > summary["load_started_ns"],
            "observed load end required")
    ids, cells = set(), set()
    spans, durations, rss_samples, gpu_samples = [], [], [], []
    first, last = None, 0
    for i, row in enumerate(samples):
        require(type(row) is dict, f"raw sample {i} is not an object")
        rid, cid = row.get("request_id"), row.get("cell_id")
        require(type(rid) is str and rid and rid not in ids, "duplicate or empty request id")
        require(type(cid) is str and cid, "missing Cell identity")
        ids.add(rid)
        cells.add(cid)
        for key in ("submitted_ns", "started_ns", "completed_ns"):
            require(type(row.get(key)) is int and row[key] >= 0,
                    f"non-monotonic/invalid {key}")
        sub, start, end = (row[k] for k in ("submitted_ns", "started_ns", "completed_ns"))
        require(summary["load_completed_ns"] <= sub <= start < end,
                "negative/invalid queue, inference or load ordering")
        require(row.get("host_id") == summary["host_id"] and row.get("arm") == summary["arm"] and
                row.get("device") == summary["device"] and
                row.get("model_weights_sha256") == digest,
                "raw observation does not bind host/device/model identity")
        rss = row.get("rss_bytes")
        require(type(rss) is int and rss > 0, "missing observed RSS sample")
        gpu = row.get("gpu_peak_bytes")
        if summary["device"] == "cuda":
            require(type(gpu) is int and gpu > 0, "CUDA requires observed GPU memory")
            gpu_samples.append(gpu)
        else:
            require(gpu is None or (type(gpu) is int and gpu >= 0),
                    "invalid non-CUDA memory observation")
        spans.append((start, end))
        durations.append((end - sub) / 1_000_000)
        rss_samples.append(rss)
        first = sub if first is None else min(first, sub)
        last = max(last, end)
    require(len(cells) == scale, "not all declared logical Cells produced real request spans")
    events = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans],
                    key=lambda item: (item[0], item[1]))
    in_flight = peak = 0
    for _, delta in events:
        in_flight += delta
        require(in_flight >= 0, "broken in-flight interval")
        peak = max(peak, in_flight)
    require(in_flight == 0 and peak == active, "active concurrency not backed by raw spans")
    elapsed = (last - first) / 1e9
    require(elapsed > 0, "invalid workload wallclock interval")
    calculated = {
        "requests": len(samples), "active_cells": peak, "distinct_logical_cells": len(cells),
        "p95_ms": percentile(durations, 95), "p99_ms": percentile(durations, 99),
        "throughput_per_sec": len(samples) / elapsed,
        "load_ms": (summary["load_completed_ns"] - summary["load_started_ns"]) / 1e6,
        "peak_rss_bytes": max(rss_samples),
        "peak_gpu_bytes": max(gpu_samples) if gpu_samples else None,
    }
    for field in ("p95_ms", "p99_ms", "throughput_per_sec", "load_ms"):
        require(number(summary.get(field), positive=True) and
                near(float(summary[field]), calculated[field]), f"raw trace disagrees with {field}")
    require(type(summary.get("peak_rss_bytes")) is int and
            summary["peak_rss_bytes"] == calculated["peak_rss_bytes"],
            "RSS peak not backed by raw samples")
    require(summary.get("peak_gpu_bytes") == calculated["peak_gpu_bytes"],
            "GPU peak not backed by raw samples")
    return calculated
