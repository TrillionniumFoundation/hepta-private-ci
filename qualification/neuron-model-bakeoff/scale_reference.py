#!/usr/bin/env python3
"""Weight-backed REFERENCE Python occupancy/load probe (not native Cell proof)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

from evaluate import HEX40, EvidenceError, require, rows, sha256, validate_plan
from run_models import question, statement, verify_snapshot, verify_source_head


def percentile(values, pct):
    require(values and all(x >= 0 for x in values), "invalid latency set")
    ordered = sorted(values)
    v = (len(ordered) - 1) * pct / 100
    left = int(v)
    return ordered[left] + (ordered[min(left + 1, len(ordered) - 1)] - ordered[left]) * (v - left)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("plan", "dataset", "model", "output"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--active-cells", type=int, default=8)
    parser.add_argument("--sampled-cells", type=int, default=128)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    require(args.active_cells > 0 and args.sampled_cells > 0, "invalid requested concurrency")
    plan = validate_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    verify_source_head(plan["source_sha"])
    require(sha256(args.dataset) == plan["dataset_sha256"], "dataset drifted")
    info = plan["models"][args.model]
    require(isinstance(info["revision"], str) and HEX40.fullmatch(info["revision"]), "model revision not frozen")
    from huggingface_hub import snapshot_download
    snapshot = Path(snapshot_download(repo_id=info["repo"], revision=info["revision"], local_files_only=args.offline))
    verify_snapshot(snapshot, info["file_sha256"])
    import psutil
    import torch
    start_load = time.perf_counter()
    if info["kind"] == "laya":
        import laya
        agent = laya.load(str(snapshot), device=args.device, expected_sha256=info["file_sha256"])
        def infer(row):
            return agent.predict(row["state"], {"decision": question(row)})
    else:
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(str(snapshot), device=args.device, trust_remote_code=False)
        def infer(row):
            return encoder.encode([statement(row)], normalize_embeddings=True, show_progress_bar=False)
    load_ms = 1000 * (time.perf_counter() - start_load)
    samples = [r for r in rows(args.dataset) if r["split"] == "test"]
    require(samples, "no test inputs")
    if torch.cuda.is_available() and args.device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    process = psutil.Process()
    data = []
    for logical in plan["logical_cell_scales"]:
        n = min(args.sampled_cells, logical)
        active = min(args.active_cells, n)
        logical_ids = [f"cell:{i}" for i in range(logical)]
        assert len(logical_ids) == logical
        tasks = [(i, samples[i % len(samples)]) for i in range(n)]
        times = []
            def invoke(item):
            _, row = item
            begin = time.perf_counter()
            infer(row)
            return (time.perf_counter() - begin) * 1000
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=active) as pool:
            for future in pool.map(invoke, tasks):
                times.append(future)
        wall = max(time.perf_counter() - t0, 1e-9)
        gpu_peak = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() and args.device.startswith("cuda") else None
        data.append({"model": args.model, "logical_cells": logical, "sampled_distinct_cells": n, "active_cells": active, "execution_kind": "reference_python_only_not_target_host", "source_sha": plan["source_sha"], "observed_load_ms": load_ms, "throughput_rps": n / wall, "p50_ms": percentile(times, 50), "p95_ms": percentile(times, 95), "p99_ms": percentile(times, 99), "rss_sample_bytes": process.memory_info().rss, "gpu_runtime_peak_bytes": gpu_peak, "failed_requests": 0})
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as out:
        for item in data:
            out.write(json.dumps(item, sort_keys=True) + "\n")
    print(f"Four REFERENCE scaling profiles captured in {dest}; none qualify native-host resources")


if __name__ == "__main__":
    try:
        main()
    except (EvidenceError, ValueError, KeyError, OSError) as exc:
        print(f"FAILED CLOSED: {exc}", file=sys.stderr)
        sys.exit(2)