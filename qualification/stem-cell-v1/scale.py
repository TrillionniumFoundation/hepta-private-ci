"""Deterministic Cell workload generator and strictly observational trace analyzer.

Never claims that a generated workload is a measured backend batch. A native
worker MUST execute the workload and export independent, generation-bound traces.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from study import load_jsonl, quantile, require_digest

SIZES = (64, 256, 1024, 4096)
FRACTIONS = (0.01, 0.1, 0.5, 1.0)
REPEATS = (0.0, 0.5, 0.9)
SIMILARITIES = ("same_family", "mixed_family", "disjoint_family")


def generate(size, active, repeat, similarity, model_digest, seed=7347):
    if size not in SIZES or active not in FRACTIONS or repeat not in REPEATS or similarity not in SIMILARITIES:
        raise ValueError("scenario not in pre-registered experiment 3 matrix")
    require_digest(model_digest, "model_digest")
    rng = random.Random(seed)
    active_count = math.ceil(size * active)
    shared_inputs = round(active_count * repeat)
    result = []
    arrival_us = 0
    for i in range(active_count):
        arrival_us += rng.randint(0, 50)
        family = ("decision" if similarity == "same_family" else
                  ("decision", "predictor", "memory", "value")[i % 4] if similarity == "mixed_family" else
                  f"private_task_{i}")
        # Repetitions are admitted inside ONE tenant/scope. Never dedupe across scope.
        input_id = "shared_input" if i < shared_inputs else f"unique_input_{i}"
        request_id = hashlib.sha256(f"{seed}:{size}:{active}:{repeat}:{similarity}:{i}".encode()).hexdigest()
        result.append({"request_id": request_id, "cell_id": i,
                       "scope": "qualification_shard_0", "generation": 1,
                       "model_digest": model_digest, "input_key": input_id,
                       "family": family, "submitted_at_us": arrival_us,
                       "scenario": {"logical_cells": size, "active_fraction": active,
                                    "input_repeat_fraction": repeat, "task_similarity": similarity}})
    # Task identity and input repetition are separate axes; no synthetic result claims.
    return result


def trace_report(workload, events):
    requests = {}
    if not workload:
        raise ValueError("empty workload")
    for job in workload:
        if job["request_id"] in requests:
            raise ValueError("duplicate workload request")
        requests[job["request_id"]] = job
    requests_trace, backend_batches, wal, restarts = {}, {}, [], []
    for event in events:
        kind = event["kind"]
        if kind == "request":
            rid = event["request_id"]
            if rid in requests_trace or rid not in requests:
                raise ValueError("missing/duplicate/extraneous request")
            job = requests[rid]
            if (event.get("model_digest") != job["model_digest"] or
                    event.get("generation") != job["generation"] or
                    event.get("scope") != job["scope"]):
                raise ValueError("stale/cross-scope model or generation")
            if event["start_us"] < job["submitted_at_us"] or event["end_us"] < event["start_us"]:
                raise ValueError("non-monotone request timing")
            if event["path"] not in ("cold_encoder", "cache_hit_head"):
                raise ValueError("unseparated request path")
            if event["status"] not in ("ok", "rejected", "failed"):
                raise ValueError("unknown status")
            if event["rss_bytes"] < 0 or event["cpu_us"] < 0:
                raise ValueError("invalid resource counters")
            requests_trace[rid] = event
        elif kind == "backend_batch":
            bid = event["batch_id"]
            if bid in backend_batches or event.get("batch_size", 0) <= 0:
                raise ValueError("invalid or duplicate backend batch")
            if event.get("backend") != "native_hepta":
                raise ValueError("non-native backend cannot claim a native batch")
            backend_batches[bid] = event
        elif kind == "wal_fsync":
            if event["latency_us"] < 0:
                raise ValueError("negative fsync")
            wal.append(event["latency_us"] / 1000)
        elif kind == "restart":
            if event["recovery_ms"] < 0:
                raise ValueError("negative recovery")
            restarts.append(event)
        else:
            raise ValueError("unregistered trace kind")
    if set(requests_trace) != set(requests):
        raise ValueError("native execution trace incomplete")
    used_batches = defaultdict(list)
    for request in requests_trace.values():
        if request["status"] == "ok" and request["path"] == "cold_encoder":
            if "batch_id" not in request or request["batch_id"] not in backend_batches:
                raise ValueError("cold request lacks actual native backend batch")
            used_batches[request["batch_id"]].append(request)
        elif request.get("batch_id") is not None:
            raise ValueError("only cold encoder requests may bind native batch")
    if set(used_batches) != set(backend_batches):
        raise ValueError("orphan backend batch")
    for bid, members in used_batches.items():
        if len(members) != backend_batches[bid]["batch_size"]:
            raise ValueError("batch size is not actual member count")
        if any(m["model_digest"] != backend_batches[bid]["model_digest"] for m in members):
            raise ValueError("mixed-model backend batch")
    ok = [r for r in requests_trace.values() if r["status"] == "ok"]
    lat = {}
    for path in ("cold_encoder", "cache_hit_head"):
        matched = [r for r in ok if r["path"] == path]
        values = [(r["end_us"] - r["start_us"]) / 1000 for r in matched]
        queue = [(r["start_us"] - requests[r["request_id"]]["submitted_at_us"]) / 1000 for r in matched]
        lat[path] = {"count": len(values), "p50_ms": quantile(values, 0.5),
                     "p95_ms": quantile(values, 0.95), "p99_ms": quantile(values, 0.99),
                     "queue_p99_ms": quantile(queue, 0.99)}
    return {"schema": "hepta.stem-cell-scale-observation.v1", "authority": "read_only_diagnostic",
            "trust": "unverified_trace_not_production_attestation",
            "logical_cells": workload[0]["scenario"]["logical_cells"],
            "requested": len(workload), "completed": len(ok),
            "rejected_or_failed": len(requests_trace) - len(ok),
            "cold_and_cached_latency": lat,
            "backend_batches": len(backend_batches),
            "batch_size_p95": quantile([b["batch_size"] for b in backend_batches.values()], 0.95),
            "actual_backend_multi_request_batches": sum(b["batch_size"] > 1 for b in backend_batches.values()),
            "cache_hit_fraction": sum(r["path"] == "cache_hit_head" for r in ok) / len(ok) if ok else None,
            "cpu_seconds": sum(r["cpu_us"] for r in requests_trace.values()) / 1e6,
            "peak_rss_bytes": max(r["rss_bytes"] for r in requests_trace.values()),
            "wal_fsync_p99_ms": quantile(wal, 0.99),
            "crash_recovery_p99_ms": quantile([r["recovery_ms"] for r in restarts], 0.99),
            "all_recoveries_checksums_verified": bool(restarts) and all(r.get("checksum_verified") is True for r in restarts),
            "longitudinal_retention": None,
            "negative_transfer_rate": None,
            "native_worker_attested": False, "production_authorized": False}


def main():
    parser = argparse.ArgumentParser(description="Generate Cell intents or summarize real native trace")
    sub = parser.add_subparsers(dest="action", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--logical-cells", type=int, required=True, choices=SIZES)
    gen.add_argument("--active-fraction", type=float, required=True, choices=FRACTIONS)
    gen.add_argument("--input-repeat", type=float, required=True, choices=REPEATS)
    gen.add_argument("--task-similarity", required=True, choices=SIMILARITIES)
    gen.add_argument("--model-digest", required=True)
    gen.add_argument("--output", required=True)
    ana = sub.add_parser("analyze")
    ana.add_argument("--workload", required=True)
    ana.add_argument("--trace", required=True)
    ana.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.action == "generate":
        jobs = generate(args.logical_cells, args.active_fraction, args.input_repeat,
                        args.task_similarity, args.model_digest)
        with Path(args.output).open("w", encoding="utf-8") as handle:
            for row in jobs:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"generated {len(jobs)} input intents; no model executed")
    else:
        result = trace_report(list(load_jsonl(args.workload)), list(load_jsonl(args.trace)))
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("native trace diagnostic emitted; no production attestation")


if __name__ == "__main__":
    main()
