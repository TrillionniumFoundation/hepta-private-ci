#!/usr/bin/env python3
"""Measure a bounded runtime.codex qualification command without source mutation."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentiles require at least one sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_time_file(path: Path) -> dict[str, float | int]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ": " in line:
            key, value = line.strip().split(": ", 1)
            fields[key] = value
    return {
        "maximumResidentSetKiB": int(fields.get("Maximum resident set size (kbytes)", "0")),
        "userSeconds": float(fields.get("User time (seconds)", "0")),
        "systemSeconds": float(fields.get("System time (seconds)", "0")),
        "voluntaryContextSwitches": int(fields.get("Voluntary context switches", "0")),
        "involuntaryContextSwitches": int(fields.get("Involuntary context switches", "0")),
    }


def run(args: argparse.Namespace) -> None:
    if not (1 <= args.iterations <= 100):
        raise ValueError("iterations must be 1..=100")
    if not args.command:
        raise ValueError("a benchmark command is required")
    before = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain", "--untracked-files=normal"),
    }
    if before["status"]:
        raise ValueError("benchmark checkout is not clean")
    samples = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index in range(args.iterations):
            resource = root / f"time-{index}.txt"
            log = args.output.parent / f"benchmark-{index}.log"
            started = time.monotonic()
            with log.open("xb") as stream:
                completed = subprocess.run(
                    ["/usr/bin/time", "-v", "-o", str(resource), *args.command],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=args.timeout_seconds,
                    check=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            elapsed = time.monotonic() - started
            if completed.returncode != 0:
                raise subprocess.CalledProcessError(completed.returncode, args.command)
            samples.append({
                "iteration": index,
                "elapsedSeconds": elapsed,
                "log": log.name,
                **parse_time_file(resource),
            })
    after = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain", "--untracked-files=normal"),
    }
    if after != before:
        raise ValueError("benchmark mutated the tested source identity")
    elapsed = [float(sample["elapsedSeconds"]) for sample in samples]
    rss = [int(sample["maximumResidentSetKiB"]) for sample in samples]
    result = {
        "schema": "hepta.runtime-codex-performance.v1",
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "testedSha": before["commit"],
        "testedTree": before["tree"],
        "iterations": args.iterations,
        "command": args.command,
        "samples": samples,
        "latencySeconds": {
            "minimum": min(elapsed),
            "mean": statistics.fmean(elapsed),
            "p50": percentile(elapsed, 0.50),
            "p95": percentile(elapsed, 0.95),
            "p99": percentile(elapsed, 0.99),
            "maximum": max(elapsed),
        },
        "maximumResidentSetKiB": {
            "p50": percentile([float(value) for value in rss], 0.50),
            "p95": percentile([float(value) for value in rss], 0.95),
            "p99": percentile([float(value) for value in rss], 0.99),
            "maximum": max(rss),
        },
        "claimBoundary": {
            "sourceCandidateBaseline": True,
            "productionCapacityClaim": False,
        },
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    run(args)


if __name__ == "__main__":
    main()
