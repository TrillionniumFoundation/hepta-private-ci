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
    if not workload:
        raise ValueError("empty workload")
    scenario = workload[0].get("scenario") if type(workload[0]) is dict else None
    fields = {"logical_cells", "active_fraction", "input_repeat_fraction", "task_similarity"}
    if type(scenario) is not dict or set(scenario) != fields:
        raise ValueError("invalid workload scenario")
    size, active = scenario["logical_cells"], scenario["active_fraction"]
    repeat, similarity = scenario["input_repeat_fraction"], scenario["task_similarity"]
    if (type(size) is not int or size not in SIZES or
            type(active) not in (int, float) or active not in FRACTIONS or
            type(repeat) not in (int, float) or repeat not in REPEATS or
            similarity not in SIMILARITIES):
        raise ValueError("unregistered workload scenario")
    # Never let seven observed calls masquerade as a 4096-Cell full-load
    # benchmark. This remains source self-consistency, not target attestation.
    if len(workload) != math.ceil(size * active):
        raise ValueError("workload scenario requested-count mismatch")
    requests, cells = {}, set()
    for job in workload:
        if (type(job) is not dict or job.get("scenario") != scenario or
                type(job.get("cell_id")) is not int or
                not 0 <= job["cell_id"] < size or job["cell_id"] in cells or
                type(job.get("request_id")) is not str or not job["request_id"] or
                type(job.get("input_key")) is not str or
                not 0 < len(job["input_key"]) <= 256 or
                type(job.get("scope")) is not str or not job["scope"] or
                type(job.get("generation")) is not int or job["generation"] < 1):
            raise ValueError("inconsistent workload identity or scenario")
        require_digest(job.get("model_digest"), "model_digest")
        if job["request_id"] in requests:
            raise ValueError("duplicate workload request")
        cells.add(job["cell_id"])
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
            # The workload contains synthetic arrival OFFSETS. Never compare
            # them to the worker's actual monotonic clock! All three measured
            # timestamps must originate from the same native clock domain.
            times = (event["enqueued_us"], event["start_us"], event["end_us"])
            if any(type(value) is not int or value < 0 for value in times):
                raise ValueError("unregistered native request clock values")
            if not (times[0] <= times[1] <= times[2]):
                raise ValueError("non-monotone native request timing")
            if event["path"] not in ("cold_encoder", "cache_hit_head"):
                raise ValueError("unseparated request path")
            if event["status"] not in ("ok", "rejected", "failed"):
                raise ValueError("unknown status")
            if any(type(event[key]) is not int or event[key] < 0
                   for key in ("rss_bytes", "cpu_us")):
                raise ValueError("invalid resource counters")
            requests_trace[rid] = event
        elif kind == "backend_batch":
            bid = event["batch_id"]
            batch_size = event.get("batch_size")
            if (type(bid) is not str or not bid or bid in backend_batches or
                    type(batch_size) is not int or not 1 <= batch_size <= 32):
                raise ValueError("invalid or duplicate backend batch")
            if event.get("backend") != "native_hepta":
                raise ValueError("non-native backend cannot claim a native batch")
            # Batch-wide owner identity, exact membership and a same-clock
            # backend interval are mandatory for *diagnostic consistency*.
            # These self-reported values are never cryptographic attestation.
            declared = event.get("member_request_ids")
            if (type(event.get("scope")) is not str or not event["scope"] or
                    type(event.get("generation")) is not int or event["generation"] < 1 or
                    type(declared) is not list or len(declared) != batch_size or
                    any(type(item) is not str or not item for item in declared) or
                    len(set(declared)) != len(declared)):
                raise ValueError("missing or duplicate backend batch ownership/membership")
            start, end = event.get("backend_started_us"), event.get("backend_ended_us")
            if (type(start) is not int or type(end) is not int or
                    start < 0 or end < start):
                raise ValueError("unbound native backend clock interval")
            backend_batches[bid] = event
        elif kind == "wal_fsync":
            duration = event.get("latency_us")
            if type(duration) is not int or duration < 0:
                raise ValueError("invalid WAL fsync counter")
            wal.append(duration / 1000)
        elif kind == "restart":
            recovery = event.get("recovery_ms")
            if (type(recovery) not in (int, float) or
                    not math.isfinite(recovery) or recovery < 0 or
                    type(event.get("checksum_verified")) is not bool):
                raise ValueError("invalid recovery observation")
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
        batch = backend_batches[bid]
        if len(members) != batch["batch_size"]:
            raise ValueError("batch size is not actual member count")
        if {m["request_id"] for m in members} != set(batch["member_request_ids"]):
            raise ValueError("backend batch member identity mismatch")
        if any(m["model_digest"] != batch["model_digest"] for m in members):
            raise ValueError("mixed-model backend batch")
        if (len({m["scope"] for m in members}) != 1 or
                len({m["generation"] for m in members}) != 1 or
                any(m["scope"] != batch["scope"] or
                    m["generation"] != batch["generation"] for m in members)):
            raise ValueError("mixed-scope/generation backend batch")
        if any(not (m["start_us"] <= batch["backend_started_us"] <=
                    batch["backend_ended_us"] <= m["end_us"]) for m in members):
            raise ValueError("backend batch interval not covered by every member")
    # A cache-hit claim without an already completed, exactly in-scope cold
    # feature source can fabricate almost-free 4096-Cell inference. Warm caches
    # from before this workload are deliberately unsupported without a
    # separately authenticated owner receipt and a new protocol revision.
    # Retain the earliest completed cold source per exact scoped input.
    # A list scan for every cache hit is quadratic for one heavily repeated
    # input (up to 4,096 logical Cells). This map is linear in trace size,
    # preserves the same-clock ordering check, and cannot widen cache reuse.
    earliest_cold_completion = {}
    for request in requests_trace.values():
        if request["status"] == "ok" and request["path"] == "cold_encoder":
            key = (request["scope"], request["generation"], request["model_digest"],
                   requests[request["request_id"]]["input_key"])
            prior = earliest_cold_completion.get(key)
            if prior is None or request["end_us"] < prior:
                earliest_cold_completion[key] = request["end_us"]
    for request in requests_trace.values():
        if request["status"] == "ok" and request["path"] == "cache_hit_head":
            key = (request["scope"], request["generation"], request["model_digest"],
                   requests[request["request_id"]]["input_key"])
            completed_at = earliest_cold_completion.get(key)
            if completed_at is None or completed_at > request["start_us"]:
                raise ValueError("cache hit lacks a completed same-scope cold source")
    ok = [r for r in requests_trace.values() if r["status"] == "ok"]
    lat = {}
    for path in ("cold_encoder", "cache_hit_head"):
        matched = [r for r in ok if r["path"] == path]
        values = [(r["end_us"] - r["enqueued_us"]) / 1000 for r in matched]
        execution = [(r["end_us"] - r["start_us"]) / 1000 for r in matched]
        queue = [(r["start_us"] - r["enqueued_us"]) / 1000 for r in matched]
        lat[path] = {"count": len(values), "p50_ms": quantile(values, 0.5),
                     "p95_ms": quantile(values, 0.95), "p99_ms": quantile(values, 0.99),
                     "execution_p99_ms": quantile(execution, 0.99),
                     "queue_p99_ms": quantile(queue, 0.99)}
    return {"schema": "hepta.stem-cell-scale-observation.v2", "authority": "read_only_diagnostic",
            "trust": "unverified_trace_not_production_attestation",
            "logical_cells": workload[0]["scenario"]["logical_cells"],
            "requested": len(workload), "completed": len(ok),
            "rejected_or_failed": len(requests_trace) - len(ok),
            "cold_and_cached_latency": lat,
            "backend_batches": len(backend_batches),
            "batch_size_p95": quantile([b["batch_size"] for b in backend_batches.values()], 0.95),
            "trace_claimed_multi_request_batches": sum(
                b["batch_size"] > 1 for b in backend_batches.values()),
            "independently_verified_backend_multi_request_batches": None,
            "batch_evidence": "exact_members_scope_generation_clock_self_reported_unattested",
            "backend_execution_p99_ms_unattested": quantile(
                [(b["backend_ended_us"] - b["backend_started_us"]) / 1000
                 for b in backend_batches.values()], 0.99),
            "cache_hit_fraction": sum(r["path"] == "cache_hit_head" for r in ok) / len(ok) if ok else None,
            "cache_hit_evidence": "prior_same_scope_generation_model_input_cold_completion_unattested",
            "independently_verified_cache_hit_fraction": None,
            "request_attributed_cpu_seconds": sum(r["cpu_us"] for r in requests_trace.values()) / 1e6,
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
