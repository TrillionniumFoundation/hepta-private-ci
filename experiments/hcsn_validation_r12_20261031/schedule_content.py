"""Meter independent content workers without changing frozen science code."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

from .process_meter import measured, write_json


REPO = Path(__file__).resolve().parents[2]
MODULE = "experiments.hcsn_validation_r12_20261031.content.study"


def run_stage(protocol, root, jobs, command, workers, attempt):
    """Each worker has its own PID, log, and wait4 receipt; failures persist."""
    status = []
    destination = root / "process_receipts" / command

    def execute(job):
        receipt = destination / f"{job['id']}_attempt{attempt:03d}.json"
        argv = [sys.executable, "-m", MODULE, command,
                "--protocol", str(protocol), "--job", job["id"]]
        if command == "worker":
            argv.extend(["--attempt", str(attempt)])
        try:
            result = measured(argv, receipt, REPO)
            return dict(job=job["id"], ok=True, receipt=str(receipt.relative_to(root)),
                        cpu_seconds=result["cpu_seconds"], wall_seconds=result["wall_seconds"])
        except Exception as error:
            return dict(job=job["id"], ok=False, error=repr(error),
                        receipt=str(receipt.relative_to(root)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            status.append(row)
            print(json.dumps(row, allow_nan=False), flush=True)
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "evaluate", "profile"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    protocol = args.protocol.resolve()
    root = protocol.parent
    record = json.loads(protocol.read_text())
    stamp = root / "schedules" / f"{args.stage}_attempt{args.attempt:03d}"
    stamp.mkdir(parents=True, exist_ok=False)
    workers = 1 if args.stage == "profile" else args.workers
    if workers < 1:
        raise ValueError("workers must be positive")
    begin = time.time()
    write_json(stamp / "START.json", dict(created_unix=begin, stage=args.stage,
        workers=workers, argv=sys.argv, source_commit=args.source_commit,
        protocol_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest(),
        scheduler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python=platform.python_version(), host_cpu_count=os.cpu_count(),
        parent_scope="Scheduling only; all complete subprocess receipts are exclusive PID wait4 measurements.",
        parallel_wall_scope="Concurrent workers overlap. Do not sum worker wall seconds as study makespan.",
        energy_joules=None))
    if args.stage == "train":
        donor = [job for job in record["jobs"] if job["kind"] == "donor"]
        rows = run_stage(protocol, root, donor, "worker", workers, args.attempt)
        if all(row["ok"] for row in rows):
            fits = [job for job in record["jobs"] if job["kind"] == "fit"]
            rows += run_stage(protocol, root, fits, "worker", workers, args.attempt)
    else:
        fits = [job for job in record["jobs"] if job["kind"] == "fit"]
        rows = run_stage(protocol, root, fits, args.stage, workers, args.attempt)
    write_json(stamp / "END.json", dict(stage=args.stage, jobs=rows,
        failures=sum(not row["ok"] for row in rows), wall_seconds=time.time()-begin,
        worker_cpu_seconds=sum(row.get("cpu_seconds", 0) for row in rows),
        note="Failed-worker costs remain in individual receipts even if absent from successful-row sum."))
    if not all(row["ok"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
