#!/usr/bin/env python3
"""Record knowledge.graph target-host performance evidence for one exact source."""

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
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
    if type(value) is not int or value < lower:
        fail(f"{field} must be an integer >= {lower}")
    return value


def latency_distribution(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    ordered = [
        positive_int(value.get(key), f"{field}.{key}", allow_zero=True)
        for key in ("p50", "p95", "p99")
    ]
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
    if not isinstance(receipt, dict):
        fail("benchmark receipt must be an object")
    if receipt.get("schema") != BENCHMARK_SCHEMA:
        fail(f"unexpected benchmark schema: {receipt.get('schema')!r}")
    if receipt.get("hostProfileId") != expected_profile_id:
        fail("benchmark receipt host profile does not match the requested profile")

    for field in ("writes", "querySamples", "reopenSamples"):
        positive_int(receipt.get(field), field)
    for field in ("mutationNs", "queryNs", "reopenNs"):
        latency_distribution(receipt.get(field), field)
    contention = receipt.get("contention")
    if not isinstance(contention, dict):
        fail("missing contention measurements")
    for field in ("rounds", "readersPerRound"):
        positive_int(contention.get(field), f"contention.{field}")
    for field in ("writerNs", "readerNs", "roundNs"):
        latency_distribution(contention.get(field), f"contention.{field}")

    work = receipt.get("boundedQueryWork")
    if not isinstance(work, dict):
        fail("missing bounded-query work receipt")
    returned = positive_int(work.get("returnedEdges"), "boundedQueryWork.returnedEdges")
    omitted = positive_int(work.get("omittedEdges"), "boundedQueryWork.omittedEdges")
    cloned = positive_int(
        work.get("selectedEdgesCloned"), "boundedQueryWork.selectedEdgesCloned"
    )
    if returned != 1 or cloned != 1:
        fail("bounded query must return and clone exactly one edge")
    if (
        positive_int(work.get("matchingEdges"), "boundedQueryWork.matchingEdges")
        != returned + omitted
    ):
        fail("bounded query matching-edge accounting is inconsistent")
    if (
        positive_int(
            work.get("relationEdgesScanned"), "boundedQueryWork.relationEdgesScanned"
        )
        < returned + omitted
    ):
        fail("bounded query edge scan count is smaller than its match count")

    for field in (
        "validatedNodes",
        "validatedEdges",
        "validatedSupports",
        "visibilityNodesScanned",
        "visibilitySupportsInspected",
        "relationSupportsInspected",
        "selectedSupportsCloned",
    ):
        positive_int(work.get(field), f"boundedQueryWork.{field}")
    if work["relationEdgesScanned"] != work["validatedEdges"]:
        fail("bounded query must account for every canonical edge scan")
    if (
        not cloned
        <= work["selectedSupportsCloned"]
        <= work["relationSupportsInspected"]
        <= work["validatedSupports"]
    ):
        fail("bounded query support accounting is inconsistent")
    if (
        not work["visibilityNodesScanned"]
        == work["validatedNodes"]
        <= work["visibilitySupportsInspected"]
        <= work["validatedSupports"]
    ):
        fail("bounded query visibility accounting is inconsistent")

    writes = receipt["writes"]
    for field, expected in (
        ("logicalNodes", writes * 16),
        ("logicalEdges", writes * 128),
        ("revisionEntityRows", writes * 16),
        ("revisionRelationRows", writes * 128),
        ("compactGenerationWitnessRows", writes),
        ("legacySnapshotNodeRows", 0),
        ("legacySnapshotEdgeRows", 0),
    ):
        if positive_int(receipt.get(field), field, allow_zero=True) != expected:
            fail(f"benchmark storage workload mismatch: {field}")
    generation = positive_int(receipt.get("currentGeneration"), "currentGeneration")
    if (
        positive_int(
            receipt.get("postContentionGeneration"), "postContentionGeneration"
        )
        != generation + contention["rounds"]
    ):
        fail("contention did not publish exactly one generation per writer")
    total = positive_int(receipt["mutationNs"].get("total"), "mutationNs.total")
    if total < receipt["mutationNs"]["p99"]:
        fail("mutation total is below a measured latency")
    throughput = positive_int(
        receipt["mutationNs"].get("throughputMilliOpsPerSecond"),
        "mutationNs.throughputMilliOpsPerSecond",
        allow_zero=True,
    )
    if throughput != writes * 1_000_000_000_000 // total:
        fail("mutation throughput disagrees with count and elapsed time")

    storage = receipt.get("storage")
    if not isinstance(storage, dict):
        fail("missing DB/WAL storage measurements")
    positive_int(storage.get("databaseBytes"), "storage.databaseBytes")
    positive_int(storage.get("walBytes"), "storage.walBytes", allow_zero=True)

    process = receipt.get("process")
    if not isinstance(process, dict):
        fail("missing process measurements")
    if platform.system() == "Linux":
        peak = positive_int(process.get("peakRssKiB"), "process.peakRssKiB")
        for field in ("rssKiBBefore", "rssKiBAfter"):
            if positive_int(process.get(field), f"process.{field}") > peak:
                fail("peak RSS is lower than an observed resident set")
        positive_int(
            process.get("linuxCpuTicksDelta"),
            "process.linuxCpuTicksDelta",
            allow_zero=True,
        )
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
    scratch = Path(tempfile.gettempdir()).resolve()
    stat = os.statvfs(scratch)
    details["benchmarkFilesystem"] = {
        "scratchDirectory": str(scratch),
        "deviceId": os.stat(scratch).st_dev,
        "blockSize": stat.f_frsize,
        "totalBytes": stat.f_blocks * stat.f_frsize,
        "availableBytesBefore": stat.f_bavail * stat.f_frsize,
    }
    # Resolve only the actual benchmark scratch filesystem, not unrelated mounts.
    try:
        mount = subprocess.run(
            [
                "findmnt",
                "--json",
                "--target",
                str(scratch),
                "--output",
                "TARGET,SOURCE,FSTYPE,OPTIONS",
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        )
        details["benchmarkFilesystem"]["mount"] = json.loads(mount.stdout)[
            "filesystems"
        ]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        details["benchmarkFilesystem"]["mountObservationError"] = type(error).__name__
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
    invocation = [
        "just",
        "test",
        "--locked",
        "--release",
        "--profile",
        "knowledge-graph-measurement",
        "--retries",
        "0",
        "-p",
        "codex-hepta-memory",
        "--lib",
        "--run-ignored",
        "only",
        "-E",
        f"test(={TEST_NAME})",
        "--success-output",
        "immediate",
        "--failure-output",
        "immediate",
        "--no-tests",
        "fail",
    ]
    result = subprocess.run(
        invocation,
        cwd=CARGO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout
    # Preserve diagnostics even when the test or the receipt validator fails.
    raw = Path(args.raw_output or (str(args.output) + ".log"))
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        fail(f"benchmark exited {result.returncode}; raw output: {raw}")
    elapsed = time.monotonic_ns() - started
    receipt = parse_receipt(output, args.host_profile_id)
    check_parameters(receipt, args)
    return receipt, elapsed, output


def check_parameters(receipt: dict[str, Any], args: argparse.Namespace) -> None:
    for key, expected in (
        ("writes", args.writes),
        ("querySamples", args.query_samples),
        ("reopenSamples", args.reopen_samples),
    ):
        if receipt.get(key) != expected:
            fail(f"benchmark parameter mismatch: {key}")
    contention = receipt["contention"]
    for key, expected in (
        ("rounds", args.contention_rounds),
        ("readersPerRound", args.contention_readers),
    ):
        if contention.get(key) != expected:
            fail(f"contention parameter mismatch: {key}")


def self_test() -> int:
    fixture = {
        "schema": BENCHMARK_SCHEMA,
        "hostProfileId": "self-test",
        "writes": 256,
        "currentGeneration": 256,
        "postContentionGeneration": 266,
        "logicalNodes": 4096,
        "logicalEdges": 32768,
        "revisionEntityRows": 4096,
        "revisionRelationRows": 32768,
        "compactGenerationWitnessRows": 256,
        "legacySnapshotNodeRows": 0,
        "legacySnapshotEdgeRows": 0,
        "querySamples": 20,
        "reopenSamples": 5,
        "mutationNs": {
            "p50": 1,
            "p95": 2,
            "p99": 3,
            "total": 1000000,
            "throughputMilliOpsPerSecond": 256000000,
        },
        "queryNs": {"p50": 1, "p95": 2, "p99": 3},
        "reopenNs": {"p50": 1, "p95": 2, "p99": 3},
        "contention": {
            "rounds": 10,
            "readersPerRound": 4,
            "writerNs": {"p50": 1, "p95": 2, "p99": 3},
            "readerNs": {"p50": 1, "p95": 2, "p99": 3},
            "roundNs": {"p50": 1, "p95": 2, "p99": 3},
        },
        "boundedQueryWork": {
            "returnedEdges": 1,
            "validatedNodes": 4,
            "validatedEdges": 4,
            "validatedSupports": 20,
            "visibilityNodesScanned": 4,
            "visibilitySupportsInspected": 4,
            "relationSupportsInspected": 4,
            "selectedSupportsCloned": 2,
            "omittedEdges": 2,
            "matchingEdges": 3,
            "relationEdgesScanned": 4,
            "selectedEdgesCloned": 1,
        },
        "storage": {"databaseBytes": 4096, "walBytes": 0},
        "process": {
            "peakRssKiB": 1,
            "rssKiBBefore": 1,
            "rssKiBAfter": 1,
            "linuxCpuTicksDelta": 10,
        },
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
        fail(
            f"source identity mismatch: expected {args.expected_sha}, observed {source_sha}"
        )
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
    if git("rev-parse", "HEAD") != source_sha or git("status", "--porcelain"):
        fail("source changed during benchmark; raw log retained, evidence not accepted")
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": source_sha,
        "sourceTree": source_tree,
        "hostProfileId": args.host_profile_id,
        "host": host,
        "buildProfile": "release",
        "nextestProfile": "knowledge-graph-measurement",
        "measurementWatchdogSeconds": 600,
        "hostDesignation": "operator-supplied-profile-not-independent-acceptance",
        "rawLogSha256": hashlib.sha256(raw_output.encode()).hexdigest(),
        "selectedRuntimeWriter": "complete-generation-rebuild",
        "incrementalPromoted": False,
        "parameters": {
            "writes": args.writes,
            "querySamples": args.query_samples,
            "reopenSamples": args.reopen_samples,
            "contentionReaders": args.contention_readers,
            "contentionRounds": args.contention_rounds,
        },
        "benchmark": receipt,
        "hostAfter": read_linux_host_details() if platform.system() == "Linux" else {},
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
    temporary.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, output)
    if args.raw_output:
        raw = Path(args.raw_output)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(raw_output, encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0


def bounded(
    parser: argparse.ArgumentParser, name: str, value: int, lower: int, upper: int
) -> None:
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
    if (
        not args.expected_sha
        or len(args.expected_sha) != 40
        or any(character not in "0123456789abcdef" for character in args.expected_sha)
    ):
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
