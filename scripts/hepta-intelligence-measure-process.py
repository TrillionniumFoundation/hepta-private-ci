#!/usr/bin/env python3
"""Measure one Linux qualification test process from a fresh Python parent."""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


def positive_sample(value: str) -> int:
    sample = int(value)
    if sample <= 0:
        raise argparse.ArgumentTypeError("sample must be positive")
    return sample


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive and finite")
    return timeout


def kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=positive_sample)
    parser.add_argument("--timeout", required=True, type=positive_timeout)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timing", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a subject command is required")
    if sys.platform != "linux":
        parser.error("Linux resource accounting is required")
    if len({path.resolve() for path in (args.output, args.timing, args.metadata)}) != 3:
        parser.error("output, timing and metadata paths must be distinct")
    baseline = resource.getrusage(resource.RUSAGE_CHILDREN)
    if baseline.ru_utime or baseline.ru_stime or baseline.ru_maxrss:
        parser.error("each measurement requires a fresh parent with no prior children")

    # A failed rerun must not leave a prior sample looking successful.
    args.timing.unlink(missing_ok=True)
    args.metadata.unlink(missing_ok=True)
    with args.output.open("wb") as output:
        started = time.perf_counter_ns()
        process = subprocess.Popen(
            command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            process.wait(timeout=args.timeout)
        except BaseException:
            try:
                kill_process_group(process.pid)
            finally:
                process.wait()
            raise
        elapsed_ns = time.perf_counter_ns() - started
    if process.returncode:
        kill_process_group(process.pid)
        print(f"subject command failed: exit {process.returncode}", file=sys.stderr)
        return process.returncode if process.returncode > 0 else 1
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    if elapsed_ns <= 0 or usage.ru_maxrss <= 0:
        raise ValueError("invalid process measurement")
    metadata = {
        "schema": "hepta.intelligence-control.process-measurement.v1",
        "sample": args.sample,
        "elapsedNanoseconds": elapsed_ns,
        "timingMethod": {
            "wallClock": "time.perf_counter_ns",
            "clockResolutionSeconds": time.get_clock_info("perf_counter").resolution,
            "wallScope": "parent-observed process launch through wait/reap, including test fixtures, IO and wait scheduling",
            "cpuScope": "RUSAGE_CHILDREN user and system time for terminated, waited children and their waited descendants; fresh parent per sample",
            "rssScope": "RUSAGE_CHILDREN largest child peak RSS, not simultaneous process-tree RSS or wrapper RSS",
            "rssUnit": "Linux KiB",
            "cpuPercentMayExceed100": True,
        },
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")
    with args.timing.open("w", newline="") as timing:
        csv.writer(timing, lineterminator="\n").writerow(
            [
                args.sample,
                f"{elapsed_ns / 1_000_000_000:.9f}",
                f"{usage.ru_utime:.9f}",
                f"{usage.ru_stime:.9f}",
                usage.ru_maxrss,
            ]
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired:
        print(
            "subject command timed out; process group killed and child reaped",
            file=sys.stderr,
        )
        raise SystemExit(124)
