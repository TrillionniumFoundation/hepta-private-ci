#!/usr/bin/env python3
"""Measured HF inference + SQLite WAL workload probe; NOT the production worker."""
import argparse
import json
import math
import random
import sqlite3
import time
from pathlib import Path

from hf_trial import FrozenStem, make_head
from qualified_eval import MODES, SCALES, audit_dataset, digest, read_jsonl, scale_summary, write_json


def _text(row, mode):
    options = " | ".join(f"{i}: {v}" for i, v in enumerate(row["options"]))
    condition = f"Question: {row['question']}\nOptions: {options}"
    return (f"State: {row['state']}\n{condition}" if mode == "joint"
            else f"State: {row['state']}"), condition


def run(args):
    import psutil
    import torch
    from torch import nn

    if args.cells not in SCALES or args.requests < 1:
        raise ValueError("supported counts: 64, 256, 1024, 4096; requests > 0")
    if not 0 < args.active_fraction <= 1 or not 0 <= args.repeat_fraction <= 1:
        raise ValueError("invalid fractions")
    if args.db.exists() or args.output.exists():
        raise ValueError("refusing to overwrite old WAL/measurements")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(args.dataset)
    audit = audit_dataset(rows)
    test_rows = [r for r in rows if r["split"] == "test"]
    tasks = sorted({r["task_id"] for r in test_rows})
    rng = random.Random(args.seed)
    if args.similarity == "high":
        tasks = tasks[:1]
    elif args.similarity == "medium":
        tasks = tasks[:max(1, math.ceil(len(tasks) / 2))]
    pool = [r for r in test_rows if r["task_id"] in tasks]
    if not pool:
        raise ValueError("no held-out examples for the requested task similarity")
    # An input-repeat knob, not a fabricated measured cache-hit percentage.
    pool = sorted(pool, key=lambda r: r["case_id"])
    pool = pool[:max(1, math.ceil(len(pool) * (1 - args.repeat_fraction)))]
    stem = FrozenStem(args.model, args.revision, args.device,
                      args.max_tokens, args.allow_pinned_remote_code,
                      args.cache_entries)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    project_width = stem.width if args.mode in ("joint", "sentence") else 2 * stem.width
    projection = nn.Linear(project_width, args.organ_width).to(args.device).eval()
    active_cells = max(1, math.ceil(args.cells * args.active_fraction))
    cell_ids = sorted(rng.sample(range(args.cells), active_cells))
    heads = {}
    for cell_id in cell_ids:
        head, _ = make_head(torch, nn, args.head, args.organ_width, 2, args.budget)
        heads[cell_id] = head.to(args.device).eval()
    db = sqlite3.connect(args.db)
    try:
        if db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
            raise ValueError("WAL unavailable")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE checkpoints (cell INTEGER PRIMARY KEY, tick INTEGER NOT NULL, "
                   "row_hash TEXT NOT NULL)")
        db.commit()
        process = psutil.Process()
        process_cpu_start = time.process_time_ns()
        observations = []
        next_tick = {}
        unique_inputs = set()
        total_forward_batches = 0
        total_encoder_examples = 0
        for start in range(0, args.requests, args.batch_size):
            prepared = []
            for index in range(start, min(args.requests, start + args.batch_size)):
                row = rng.choice(pool)
                cell_id = rng.choice(cell_ids)
                text, condition = _text(row, args.mode)
                key = digest([row["scope_id"], stem.model_id, stem.revision,
                              stem.max_tokens, text])
                unique_inputs.add(key)
                prepared.append((row, cell_id, condition, text, key))
            # Protect previously admitted features from eviction while this
            # batch is materialized; never look up a foreign-scope cache key.
            cached_before = {key: stem.cache[key] for _, _, _, _, key in prepared
                             if key in stem.cache}
            # Deduplicate within batch; do not reuse across different scopes.
            new_keys, pending = {}, []
            for row, cell_id, condition, text, key in prepared:
                if key not in stem.cache and key not in new_keys:
                    new_keys[key] = (text, row["scope_id"])
                    pending.append(key)
            batch_elapsed = 0.0
            if pending:
                texts = [new_keys[key][0] for key in pending]
                begin = time.perf_counter_ns()
                tokens = stem.tokenizer(texts, return_tensors="pt", padding=True,
                                        truncation=True, max_length=stem.max_tokens)
                tokens = {k: v.to(args.device) for k, v in tokens.items()}
                with torch.inference_mode():
                    raw = stem.model(**tokens).last_hidden_state.float()
                mask = tokens["attention_mask"]
                for j, key in enumerate(pending):
                    length = int(mask[j].sum().item())
                    stem.cache[key] = raw[j, :length].detach().cpu()
                    if len(stem.cache) > stem.cache_entries:
                        stem.cache.popitem(last=False)
                batch_elapsed = (time.perf_counter_ns() - begin) / 1e6
                total_forward_batches += 1
                total_encoder_examples += len(pending)
            for row, cell_id, condition, text, key in prepared:
                began = time.perf_counter_ns()
                states = cached_before.get(key)
                if states is None:
                    states = stem.cache.get(key)
                if states is None:
                    raise ValueError("missing feature during admitted batch")
                if args.mode in ("joint", "sentence"):
                    representation = states.mean(dim=0)
                else:
                    indexes = torch.linspace(0, states.shape[0] - 1,
                                             steps=min(8, states.shape[0])).long()
                    landmarks = states[indexes]
                    query = stem._query(condition)
                    if args.mode == "landmark":
                        context = landmarks.mean(dim=0)
                    else:
                        weights = torch.softmax((landmarks @ query) / math.sqrt(stem.width), dim=0)
                        context = (landmarks * weights.unsqueeze(-1)).sum(dim=0)
                    representation = torch.cat((context, query))
                with torch.inference_mode():
                    _ = heads[cell_id](projection(representation.to(args.device)))
                head_ms = (time.perf_counter_ns() - began) / 1e6
                was_new = key in new_keys
                stage = ("backend_batch" if len(pending) > 1 else "encoder_warm") if was_new else "cache_hit_head"
                elapsed = head_ms + (batch_elapsed if was_new else 0)
                tick = next_tick.get(cell_id, 0) + 1
                next_tick[cell_id] = tick
                row_hash = digest([args.cells, cell_id, tick, row["case_id"], stage])
                wal_start = time.perf_counter_ns()
                with db:
                    db.execute("INSERT INTO checkpoints(cell, tick, row_hash) VALUES(?, ?, ?) "
                               "ON CONFLICT(cell) DO UPDATE SET tick=excluded.tick, "
                               "row_hash=excluded.row_hash", (cell_id, tick, row_hash))
                wal_ms = (time.perf_counter_ns() - wal_start) / 1e6
                elapsed += wal_ms
                observations.append({
                    "measurement_origin": "real_backend",
                    "logical_cells": args.cells,
                    "active_fraction": args.active_fraction,
                    "input_repeat_fraction": args.repeat_fraction,
                    "task_similarity": args.similarity,
                    "case_id": row["case_id"], "scope_id": row["scope_id"],
                    "cell_id": cell_id, "execution_path": stage,
                    "latency_ms": elapsed, "head_ms": head_ms,
                    "wal_commit_ms": wal_ms,
                    "encoder_batch_wall_ms": batch_elapsed if was_new else 0,
                    "backend_batch_size": len(pending) if was_new else 0,
                    "rss_bytes": process.memory_info().rss,
                    "checkpoint_tick": tick, "checkpoint_hash": row_hash,
                })
        db.close()
        begin = time.perf_counter_ns()
        restarted = sqlite3.connect(args.db)
        quick_check = restarted.execute("PRAGMA quick_check").fetchone()[0]
        checkpoint_rows = restarted.execute("SELECT cell, tick, row_hash FROM checkpoints").fetchall()
        restarted.close()
        recovery_ms = (time.perf_counter_ns() - begin) / 1e6
        observed_process_cpu_ms = (time.process_time_ns() - process_cpu_start) / 1e6
        if quick_check != "ok" or len(checkpoint_rows) != len(next_tick):
            raise RuntimeError("WAL restart read-back invariant failed")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(x, sort_keys=True) + "\n"
                                       for x in observations), encoding="utf-8")
        summary = scale_summary(observations)
        summary.update({
            "schema": "hepta.neuron-stem-real-backend-scale.v1",
            "dataset": audit, "model": stem.model_id, "revision": stem.revision,
            "mode": args.mode, "head": args.head, "head_parameter_ceiling": args.budget,
            "active_cells": active_cells,
            "requested_events": args.requests,
            "unique_input_keys": len(unique_inputs),
            "observed_encoder_batch_calls": total_forward_batches,
            "observed_encoder_contexts": total_encoder_examples,
            "model_load_ms": stem.load_ms,
            "observed_process_cpu_ms": observed_process_cpu_ms,
            "checkpoint_rows_after_clean_restart": len(checkpoint_rows),
            "clean_reopen_ms": recovery_ms,
            "clean_reopen_integrity": quick_check,
            "unclean_crash_recovery_verified": False,
            "throughput_is_sequential_driver_not_worker_queue": True,
            "production_worker_microbatch_verified": False,
            "target_host_perf_qualified": False,
            "trace_digest": digest(observations),
        })
        write_json(str(args.output) + ".summary.json", summary)
        print(json.dumps({"trace": str(args.output),
                          "requests": len(observations),
                          "forward_batches": total_forward_batches,
                          "recovery_ms": recovery_ms}))
    finally:
        try:
            db.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--mode", choices=MODES, default="joint")
    parser.add_argument("--head", default="film")
    parser.add_argument("--budget", type=int, default=2048)
    parser.add_argument("--cells", type=int, required=True)
    parser.add_argument("--active-fraction", type=float, default=.25)
    parser.add_argument("--repeat-fraction", type=float, default=.5)
    parser.add_argument("--similarity", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--requests", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--cache-entries", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--organ-width", type=int, default=64)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--allow-pinned-remote-code", action="store_true")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(x < 1 for x in (args.batch_size, args.organ_width, args.threads)):
        parser.error("batch size, organ width and threads must be positive")
    if args.batch_size > args.cache_entries:
        parser.error("cache-entries must be at least batch-size")
    run(args)


if __name__ == "__main__":
    main()
