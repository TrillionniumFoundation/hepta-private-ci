#!/usr/bin/env python3
"""Measured Jina v5 text-backend batch/Cell-head/WAL scale probe.

Never reports production worker conformance, crash recovery or NDU impact.
The Cell weights here are initialized (not trained): this probes resources
only. Preserves scope isolation and records actual, not scheduled, batch size.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import sqlite3
import time

from hf_trial import make_head
from jina_v5 import FrozenJinaV5, research_environment, sha256_record
from jina_v5_trial import render_case
from qualified_eval import SCALES, audit_dataset, read_jsonl, scale_summary, write_json
from q24_bridge import Q24, quantize_q24


def run(args):
    import psutil
    import torch
    from torch import nn
    if args.model not in ("jina-v5-text-nano", "jina-v5-text-small"):
        raise ValueError("scale probe only supports text models")
    if args.cells not in SCALES or args.requests < 1 or args.batch_size < 1:
        raise ValueError("invalid requested scale")
    if not 0 < args.active_fraction <= 1 or not 0 <= args.repeat_fraction <= 1:
        raise ValueError("invalid activity and repeat fractions")
    if args.similarity not in ("low", "medium", "high"):
        raise ValueError("invalid task similarity")
    if args.output.exists() or args.db.exists():
        raise ValueError("do not overwrite qualification evidence")
    data = read_jsonl(args.dataset)
    audit = audit_dataset(data)
    pool = [r for r in data if r["split"] == "test"]
    tasks = sorted({r["task_id"] for r in pool})
    if args.similarity == "high":
        tasks = tasks[:1]
    elif args.similarity == "medium":
        tasks = tasks[:max(1, math.ceil(len(tasks) / 2))]
    pool = sorted((r for r in pool if r["task_id"] in tasks),
                  key=lambda r: r["case_id"])
    if not pool:
        raise ValueError("no independently held-out test rows")
    # Repeat fraction is a workload knob, not a falsely asserted hit rate.
    pool = pool[:max(1, math.ceil(len(pool) * (1 - args.repeat_fraction)))]
    classes = {len(row["options"]) for row in pool}
    if len(classes) != 1:
        raise ValueError("inconsistent option count across probe tasks")
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    active_count = max(1, math.ceil(args.cells * args.active_fraction))
    active_ids = sorted(rng.sample(range(args.cells), active_count))
    stem = FrozenJinaV5(
        args.model, args.revision, task="classification",
        dimension=args.dimension, max_tokens=args.max_tokens,
        device=args.device, allow_pinned_remote_code=args.allow_pinned_remote_code,
        allow_download=args.allow_model_download, cache_entries=args.cache_entries,
        snapshot_dir=args.snapshot, store_root=args.store_root,
        expected_snapshot_digest=args.expected_snapshot_digest)
    heads = {}
    for cid in active_ids:
        h, _ = make_head(torch, nn, args.head, args.dimension, next(iter(classes)), args.budget)
        heads[cid] = h.to(args.device).eval()
    process = psutil.Process()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE checkpoints(cell INTEGER PRIMARY KEY, tick INTEGER NOT NULL, digest TEXT NOT NULL)")
    db.commit()
    start_all = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    ticks = {}
    observations = []
    visited = set()
    try:
        for batch_start in range(0, args.requests, args.batch_size):
            started = time.perf_counter_ns()
            prepared = []
            size = min(args.batch_size, args.requests - batch_start)
            for offset in range(size):
                index = batch_start + offset
                cid = active_ids[index % active_count] if args.round_robin else rng.choice(active_ids)
                row = rng.choice(pool)
                prepared.append((cid, row))
                visited.add(cid)
            by_scope = defaultdict(list)
            for index, (_, row) in enumerate(prepared):
                by_scope[row["scope_id"]].append(index)
            features = [None] * size
            traces = []
            for scope, positions in sorted(by_scope.items()):
                inputs = [render_case(prepared[i][1], args.representation) for i in positions]
                encoded, trace = stem.encode_batch(
                    inputs, scope_id=scope, principal_id=args.principal_id,
                    generation=args.generation, authority_epoch=args.authority_epoch,
                    batch_size=args.batch_size)
                for i, feature in zip(positions, encoded):
                    features[i] = feature
                traces.append(trace)
            encoder_done = time.perf_counter_ns()
            checkpoint_events = []
            for (cid, row), vector in zip(prepared, features):
                with torch.inference_mode():
                    _ = heads[cid](torch.tensor(
                        [v / Q24 for v in quantize_q24(vector)],
                        dtype=torch.float32, device=args.device))
                tick = ticks.get(cid, 0) + 1
                ticks[cid] = tick
                checkpoint_events.append((cid, tick, row["case_id"]))
            heads_done = time.perf_counter_ns()
            with db:
                for cid, tick, case_id in checkpoint_events:
                    db.execute(
                        "INSERT INTO checkpoints(cell,tick,digest) VALUES(?,?,?) "
                        "ON CONFLICT(cell) DO UPDATE SET tick=excluded.tick,digest=excluded.digest",
                        (cid, tick, sha256_record([cid, tick, case_id])))
            committed = time.perf_counter_ns()
            duration_ms = (committed - started) / 1e6
            example_count = sum(t["encoder_examples"] for t in traces)
            backend_calls = sum(t["encoder_batch_calls"] for t in traces)
            for (cid, row), (_, tick, _) in zip(prepared, checkpoint_events):
                observations.append({
                    "measurement_origin": "real_backend",
                    "logical_cells": args.cells, "active_fraction": args.active_fraction,
                    "input_repeat_fraction": args.repeat_fraction,
                    "task_similarity": args.similarity,
                    "cell_id": cid, "scope_id": row["scope_id"],
                    "case_id": row["case_id"],
                    "execution_path": "backend_batch" if example_count else "cache_hit_head",
                    "latency_ms": duration_ms,
                    "batch_wall_ms": duration_ms,
                    "encoder_batch_wall_ms": (encoder_done - started) / 1e6,
                    "head_wall_ms": (heads_done - encoder_done) / 1e6,
                    "wal_wall_ms": (committed - heads_done) / 1e6,
                    "requested_batch_size": size,
                    "actual_encoder_examples_in_batch": example_count,
                    "observed_encoder_calls_in_batch": backend_calls,
                    "backend_batch_size": example_count,
                    "rss_bytes": process.memory_info().rss,
                    "checkpoint_tick": tick,
                })
    finally:
        db.close()
    total_wall = (time.perf_counter_ns() - start_all) / 1e9
    process_cpu = (time.process_time_ns() - cpu_start) / 1e9
    reopened = sqlite3.connect(args.db)
    try:
        quick = reopened.execute("PRAGMA quick_check").fetchone()[0]
        rows = reopened.execute("SELECT cell,tick FROM checkpoints").fetchall()
    finally:
        reopened.close()
    if quick != "ok" or {cid: tick for cid, tick in rows} != ticks:
        raise RuntimeError("clean-reopen WAL checkpoint mismatch")
    args.output.write_text("".join(json.dumps(v, sort_keys=True) + "\n"
                                   for v in observations), encoding="utf-8")
    summary = scale_summary(observations)
    summary.update({
        "schema": "hepta.jina-v5-shadow-scale-probe.v1",
        "status": "real_backend_research_only",
        "production_promotion_permitted": False,
        "model": args.model, "revision": args.revision,
        "feature_manifest_digest": stem.manifest_digest,
        "local_snapshot_census_sha256": stem.snapshot_attestation["manifest_sha256"],
        "local_snapshot_attested_twice": stem.snapshot_attestation["attested_twice_around_model_load"],
        "local_snapshot_attestation_ms": stem.snapshot_attestation_ms,
        "model_code_and_adapter_bytes_hashed": True,
        "dataset": audit, "seed": args.seed,
        "head_type": args.head, "head_parameter_ceiling": args.budget,
        "feature_dimension": args.dimension,
        "context_token_budget": args.max_tokens,
        "representation": args.representation,
        "requested_batch_size": args.batch_size,
        "task_similarity": args.similarity,
        "input_repeat_fraction": args.repeat_fraction,
        "active_fraction": args.active_fraction,
        "heads_initialized_not_learned": True,
        "q24_feature_input_enforced": True,
        "production_signed_q24_receipt_verified": False,
        "total_logical_cells": args.cells,
        "actual_active_heads": active_count,
        "distinct_ticked_cells": len(visited),
        "full_active_cell_coverage": len(visited) == active_count,
        "total_requests": args.requests,
        "actual_encoder_batch_calls": stem.encoder_calls,
        "actual_encoder_examples": stem.encoder_examples,
        "cache_hits": stem.cache_hits,
        "model_load_ms": stem.load_ms,
        "process_wall_seconds": total_wall,
        "process_cpu_seconds": process_cpu,
        "environment": research_environment(),
        "observed_total_physical_ram_bytes": psutil.virtual_memory().total,
        "aggregate_throughput_rps": args.requests / total_wall,
        "max_observed_rss_bytes": max(v["rss_bytes"] for v in observations),
        "sqlite_clean_reopen_ok": True,
        "sqlite_unclean_crash_recovery_verified": False,
        "production_worker_microbatch_verified": False,
        "ndu_signed_verified": False,
        "limitations": [
            "Benchmarks a research Jina/SentenceTransformer backend, not the Rust worker",
            "Batch request latency includes entire batch and WAL; no invented queue age",
            "SQLite clean reopen is not an unclean crash/ack-loss qualification",
            "Heads are synthetic initialized weights; no learning claims",
        ],
    })
    write_json(str(args.output) + ".summary.json", summary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True, choices=("jina-v5-text-nano", "jina-v5-text-small"))
    p.add_argument("--revision", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--principal-id", required=True)
    p.add_argument("--cells", type=int, choices=(64, 256, 1024, 4096), required=True)
    p.add_argument("--active-fraction", type=float, default=.25)
    p.add_argument("--repeat-fraction", type=float, default=.5)
    p.add_argument("--similarity", choices=("low", "medium", "high"), default="medium")
    p.add_argument("--representation", choices=("joint", "state"), default="joint")
    p.add_argument("--head", choices=("linear", "film", "rank8", "rank16", "mlp", "swiglu"),
                   default="linear")
    p.add_argument("--budget", type=int, choices=(2048, 16384, 65536, 262144),
                   default=16384)
    p.add_argument("--dimension", type=int, default=256)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--requests", type=int, default=256)
    p.add_argument("--cache-entries", type=int, default=256)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=20261011)
    p.add_argument("--device", default="cpu")
    p.add_argument("--generation", type=int, default=1)
    p.add_argument("--authority-epoch", type=int, default=1)
    p.add_argument("--round-robin", action="store_true")
    p.add_argument("--store-root", type=Path, required=True,
                   help="approved models--jinaai--REPO local cache root")
    p.add_argument("--snapshot", type=Path, required=True,
                   help="exact cache snapshots/FULL40SHA directory")
    p.add_argument("--expected-snapshot-digest", required=True,
                   help="separately reviewed 64-hex full local file-census digest")
    p.add_argument("--allow-pinned-remote-code", action="store_true")
    p.add_argument("--allow-model-download", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
