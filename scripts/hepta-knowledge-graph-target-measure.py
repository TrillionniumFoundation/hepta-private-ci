#!/usr/bin/env python3
"""Record knowledge.graph target-host performance evidence for one exact source."""

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
PREFIX = "HEPTA_KNOWLEDGE_GRAPH_PERF_RECEIPT="
BENCHMARK_SCHEMA = "hepta.knowledge-graph-perf-library.v2"
EVIDENCE_SCHEMA = "hepta.knowledge-graph-target-host-evidence.v1"
TEST_NAME = (
    "cognitive_kg_benchmark_tests::qualification_knowledge_graph_capacity_receipt"
)


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_KNOWLEDGE_GRAPH_TARGET_MEASUREMENT: " + message)


def command(
    *args: str,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> str:
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


def positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    lower = 0 if allow_zero else 1
    if not isinstance(value, int) or value < lower:
        fail(f"{field} must be an integer >= {lower}")
    return value


def latency_distribution(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    ordered = [positive_int(value.get(key), f"{field}.{key}", allow_zero=True) for key in ("p50", "p95", "p99")]
    if ordered != sorted(ordered):
        fail(f"{field} percentiles are not monotone")
    return {"p50": ordered[0], "p95": ordered[1], "p99": ordered[2]}


def parse_receipt(output: str, expected_profile_id: str) -> dict[str, Any]:
    rows = [line.split(PREFIX, 1)[1] for line in output.splitlines() if PREFIX in line]
    if len(rows) != 1:
        fail(f"expected exactly one benchmark receipt, received {len(rows)}")
    try:
        receipt = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid benchmark receipt JSON: {error}")
    if receipt.get("schema") != BENCHMARK_SCHEMA:
        fail(f"unexpected benchmark schema: {receipt.get('schema')!r}")
    if receipt.get("hostProfileId") != expected_profile_id:
        fail("benchmark receipt host profile does not match the requested profile")

    for field in ("mutationNs", "queryNs", "reopenNs"):
        latency_distribution(receipt.get(field), field)
    contention = receipt.get("contention")
    if not isinstance(contention, dict):
        fail("missing contention measurements")
    for field in ("writerNs", "readerNs", "roundNs"):
        latency_distribution(contention.get(field), f"contention.{field}")

    work = receipt.get("boundedQueryWork")
    if not isinstance(work, dict):
        fail("missing bounded-query work receipt")
    returned = positive_int(work.get("returnedEdges"), "boundedQueryWork.returnedEdges")
    omitted = positive_int(work.get("omittedEdges"), "boundedQueryWork.omittedEdges")
    cloned = positive_int(work.get("selectedEdgesCloned"), "boundedQueryWork.selectedEdgesCloned")
    if returned != 1 or cloned != 1:
        fail("bounded query must return and clone exactly one edge")
    if positive_int(work.get("matchingEdges"), "boundedQueryWork.matchingEdges") != returned + omitted:
        fail("bounded query matching-edge accounting is inconsistent")
    if positive_int(work.get("relationEdgesScanned"), "boundedQueryWork.relationEdgesScanned") < returned + omitted:
        fail("bounded query edge scan count is smaller than its match count")

    storage = receipt.get("storageBytes")
    if not isinstance(storage, dict):
        fail("missing DB/WAL storage measurements")
    positive_int(storage.get("database"), "storageBytes.database", allow_zero=True)
    positive_int(storage.get("wal"), "storageBytes.wal", allow_zero=True)

    process = receipt.get("process")
    if not isinstance(process, dict):
        fail("missing process measurements")
    if platform.system() == "Linux":
        positive_int(process.get("peakRssKiB"), "process.peakRssKiB")
    return receipt


def read_linux_host_details() -> dict[str, Any]:
    details: dict[str, Any] = {}
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                details["cpuModel"] = line.split(":", 1)[1].strip()
                break
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                details["memoryTotalKiB"] = int(line.split()[1])
                break
    loadavg = Path("/proc/loadavg")
    if loadavg.exists():
        details["loadAverageBefore"] = loadavg.read_text(encoding="utf-8").split()[:3]
    return details


def run_benchmark(args: argparse.Namespace) -> tuple[dict[str, Any], int, str]:
    env = os.environ.copy()
    env.update(
        {
            "HEPTA_KG_TARGET_PROFILE_ID": args.host_profile_id,
            "HEPTA_KG_BENCH_WRITES": str(args.writes),
            "HEPTA_KG_BENCH_QUERY_SAMPLES": str(args.query_samples),
            "HEPTA_KG_BENCH_REOPEN_SAMPLES": str(args.reopen_samples),
            "HEPTA_KG_BENCH_CONTENTION_READERS": str(args.contention_readers),
            "HEPTA_KG_BENCH_CONTENTION_ROUNDS": str(args.contention_rounds),
            "CARGO_INCREMENTAL": "0",
        }
    )
    if args.target_dir:
        env["CARGO_TARGET_DIR"] = str(Path(args.target_dir).expanduser().resolve())

    started = time.monotonic_ns()
    output = command(
        "cargo",
        "test",
        "--locked",
        "--release",
        "-p",
        "codex-hepta-memory",
        "--lib",
        TEST_NAME,
        "--",
        "--ignored",
        "--exact",
        "--nocapture",
        "--test-threads=1",
        cwd=CARGO_ROOT,
        env=env,
    )
    elapsed = time.monotonic_ns() - started
    return parse_receipt(output, args.host_profile_id), elapsed, output


def self_test() -> int:
    fixture = {
        "schema": BENCHMARK_SCHEMA,
        "hostProfileId": "self-test",
        "mutationNs": {"p50": 1, "p95": 2, "p99": 3},
        "queryNs": {"p50": 1, "p95": 2, "p99": 3},
        "reopenNs": {"p50": 1, "p95": 2, "p99": 3},
        "contention": {
            "writerNs": {"p50": 1, "p95": 2, "p99": 3},
            "readerNs": {"p50": 1, "p95": 2, "p99": 3},
            "roundNs": {"p50": 1, "p95": 2, "p99": 3},
        },
        "boundedQueryWork": {
            "returnedEdges": 1,
            "omittedEdges": 2,
            "matchingEdges": 3,
            "relationEdgesScanned": 4,
            "selectedEdgesCloned": 1,
        },
        "storageBytes": {"database": 0, "wal": 0},
        "process": {"peakRssKiB": 1},
    }
    parsed = parse_receipt(PREFIX + json.dumps(fixture), "self-test")
    if parsed["boundedQueryWork"]["omittedEdges"] != 2:
        fail("self-test parse mismatch")
    print("PASS_HEPTA_KNOWLEDGE_GRAPH_TARGET_MEASUREMENT_SELF_TEST")
    return 0


def measure(args: argparse.Namespace) -> int:
    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source_sha != args.expected_sha:
        fail(f"source identity mismatch: expected {args.expected_sha}, observed {source_sha}")
    if git("status", "--porcelain"):
        fail("working tree is not clean")

    host = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logicalCpuCount": os.cpu_count(),
        "python": platform.python_version(),
        "rustc": command("rustc", "--version").strip(),
        "cargo": command("cargo", "--version").strip(),
    }
    if platform.system() == "Linux":
        host.update(read_linux_host_details())

    receipt, harness_ns, raw_output = run_benchmark(args)
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": source_sha,
        "sourceTree": source_tree,
        "hostProfileId": args.host_profile_id,
        "host": host,
        "buildProfile": "release",
        "parameters": {
            "writes": args.writes,
            "querySamples": args.query_samples,
            "reopenSamples": args.reopen_samples,
            "contentionReaders": args.contention_readers,
            "contentionRounds": args.contention_rounds,
        },
        "benchmark": receipt,
        "harnessWallNanoseconds": harness_ns,
        "interpretation": {
            "exactSourceBound": True,
            "ciRunnerIsNotTargetHostEvidence": True,
            "measurementDoesNotGrantActivation": True,
            "measurementDoesNotGrantAcceptance": True,
            "measurementDoesNotGrantRelease": True,
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    if args.raw_output:
        raw = Path(args.raw_output)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(raw_output, encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0


def bounded(parser: argparse.ArgumentParser, name: str, value: int, lower: int, upper: int) -> None:
    if not lower <= value <= upper:
        parser.error(f"--{name.replace('_', '-')} must be in {lower}..={upper}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--host-profile-id")
    parser.add_argument("--writes", type=int, default=256)
    parser.add_argument("--query-samples", type=int, default=20)
    parser.add_argument("--reopen-samples", type=int, default=5)
    parser.add_argument("--contention-readers", type=int, default=4)
    parser.add_argument("--contention-rounds", type=int, default=10)
    parser.add_argument("--target-dir")
    parser.add_argument("--output")
    parser.add_argument("--raw-output")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.expected_sha or len(args.expected_sha) != 40:
        parser.error("--expected-sha must be the exact 40-character candidate SHA")
    if not args.host_profile_id:
        parser.error("--host-profile-id is required")
    if not args.output:
        parser.error("--output is required")
    bounded(parser, "writes", args.writes, 1, 256)
    bounded(parser, "query_samples", args.query_samples, 1, 100)
    bounded(parser, "reopen_samples", args.reopen_samples, 1, 20)
    bounded(parser, "contention_readers", args.contention_readers, 1, 16)
    bounded(parser, "contention_rounds", args.contention_rounds, 1, 50)
    return measure(args)


if __name__ == "__main__":
    sys.exit(main())
