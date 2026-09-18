#!/usr/bin/env python3
"""Record objective.compiler target-host latency evidence for one exact source."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARGO_ROOT = ROOT / "codex-rs"
PREFIX = "OBJECTIVE_MEASUREMENT="
SCHEMA = "hepta.objective-target-host-evidence.v1"


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_OBJECTIVE_TARGET_MEASUREMENT: " + message)


def command(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def git(*args: str) -> str:
    return command("git", *args).strip()


def parse_measurement(output: str, expected_path: str) -> dict[str, Any]:
    rows = [
        line.split(PREFIX, 1)[1]
        for line in output.splitlines()
        if PREFIX in line
    ]
    if len(rows) != 1:
        fail(f"expected exactly one measurement row for {expected_path}, received {len(rows)}")
    try:
        value = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid measurement JSON for {expected_path}: {error}")
    if value.get("schema") != "hepta.objective-target-measurement.v1":
        fail(f"unexpected measurement schema for {expected_path}")
    if value.get("path") != expected_path:
        fail(f"unexpected measurement path: {value.get('path')!r}")
    latency = value.get("latencyNanoseconds")
    if not isinstance(latency, dict):
        fail(f"missing latency distribution for {expected_path}")
    ordered = [latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(isinstance(item, int) and item >= 0 for item in ordered):
        fail(f"invalid latency percentiles for {expected_path}")
    if ordered != sorted(ordered):
        fail(f"non-monotone latency percentiles for {expected_path}")
    return value


def run_fixture(test_name: str, expected_path: str, samples: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["HEPTA_OBJECTIVE_MEASUREMENT_SAMPLES"] = str(samples)
    started = time.monotonic_ns()
    output = command(
        "cargo",
        "test",
        "--locked",
        "--release",
        "-p",
        "codex-hepta-objective",
        test_name,
        "--",
        "--ignored",
        "--nocapture",
        cwd=CARGO_ROOT,
        env=env,
    )
    harness_ns = time.monotonic_ns() - started
    measurement = parse_measurement(output, expected_path)
    measurement["harnessWallNanoseconds"] = harness_ns
    return measurement


def self_test() -> int:
    fixture = (
        'OBJECTIVE_MEASUREMENT={"schema":"hepta.objective-target-measurement.v1",'
        '"path":"ordinary_authenticated_admission_compile","samples":3,'
        '"latencyNanoseconds":{"p50":10,"p95":20,"p99":30}}'
    )
    parsed = parse_measurement(fixture, "ordinary_authenticated_admission_compile")
    if parsed["latencyNanoseconds"]["p99"] != 30:
        fail("self-test parse mismatch")
    print("PASS_HEPTA_OBJECTIVE_TARGET_MEASUREMENT_SELF_TEST")
    return 0


def measure(args: argparse.Namespace) -> int:
    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source_sha != args.expected_sha:
        fail(f"source identity mismatch: expected {args.expected_sha}, observed {source_sha}")
    if git("status", "--porcelain"):
        fail("working tree is not clean")

    rustc = command("rustc", "--version").strip()
    cargo = command("cargo", "--version").strip()
    ordinary = run_fixture(
        "measurement_ordinary_admission_compile_v1",
        "ordinary_authenticated_admission_compile",
        args.ordinary_samples,
    )
    conflict = run_fixture(
        "measurement_conflict_extraction_v1",
        "maximum_conflict_extraction",
        args.conflict_samples,
    )

    evidence = {
        "schema": SCHEMA,
        "sourceCommit": source_sha,
        "sourceTree": source_tree,
        "hostProfileId": args.host_profile_id,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "rustc": rustc,
            "cargo": cargo,
        },
        "buildProfile": "release",
        "measurements": [ordinary, conflict],
        "interpretation": {
            "ordinaryAndConflictAreSeparate": True,
            "ciRunnerIsNotProductionEvidence": True,
            "activationGranted": False,
            "releaseGranted": False,
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(json.dumps(evidence, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--host-profile-id")
    parser.add_argument("--ordinary-samples", type=int, default=1_000)
    parser.add_argument("--conflict-samples", type=int, default=64)
    parser.add_argument("--output")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.expected_sha or len(args.expected_sha) != 40:
        parser.error("--expected-sha must be the exact 40-character candidate SHA")
    if not args.host_profile_id:
        parser.error("--host-profile-id is required")
    if not args.output:
        parser.error("--output is required")
    if not (1 <= args.ordinary_samples <= 100_000):
        parser.error("--ordinary-samples must be in 1..=100000")
    if not (1 <= args.conflict_samples <= 10_000):
        parser.error("--conflict-samples must be in 1..=10000")
    return measure(args)


if __name__ == "__main__":
    sys.exit(main())
