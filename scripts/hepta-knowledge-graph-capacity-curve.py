#!/usr/bin/env python3
"""Record the knowledge.graph kernel/local-incremental target-host capacity curve."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARGO_ROOT = ROOT / "codex-rs"
TEST_SOURCE = CARGO_ROOT / "hepta-kg/tests/capacity_curve.rs"
TEST_NAME = "qualification_knowledge_graph_capacity_curve"
MATRIX_PREFIX = "HEPTA_KG_CAPACITY_MATRIX="
EVIDENCE_SCHEMA = "hepta.knowledge-graph-capacity-evidence.v1"
MATRIX_SCHEMA = "hepta.knowledge-graph-capacity-matrix.v1"
EXPECTED_POINTS = {
    "baseline-4k-32k": (4_096, 32_768),
    "kernel-32k-262k": (32_768, 262_144),
}
EXPECTED_REJECTIONS = {
    "requested-100k-nodes": (100_000, None, "kernel-node-policy"),
    "requested-1m-edges": (None, 1_000_000, "kernel-edge-policy"),
}


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_KNOWLEDGE_GRAPH_CAPACITY_CURVE: " + message)


def command(
    *args: str,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        output = error.stdout or ""
        if output:
            print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
        fail(f"command failed with exit {error.returncode}: {' '.join(args)}")
    return result.stdout


def git(*args: str) -> str:
    return command("git", *args).strip()


def strict_json(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        fail(f"invalid {label} JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def exact_nonnegative_int(value: Any, label: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or value < minimum:
        fail(f"{label} must be an integer >= {minimum}")
    return value


def parse_output(output: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    points: list[dict[str, Any]] = []
    matrix_rows: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(MATRIX_PREFIX):
            matrix_rows.append(stripped.split(MATRIX_PREFIX, 1)[1])
            continue
        if stripped.startswith('{"name":') and '"localWork"' in stripped:
            points.append(strict_json(stripped, "capacity point"))
    if len(matrix_rows) != 1:
        fail(f"expected exactly one capacity matrix, received {len(matrix_rows)}")
    matrix = strict_json(matrix_rows[0], "capacity matrix")
    if matrix.get("schema") != MATRIX_SCHEMA:
        fail(f"unexpected matrix schema: {matrix.get('schema')!r}")
    if matrix.get("hostIndependentThresholdsClaimed") is not False:
        fail("capacity matrix must deny host-independent threshold claims")
    if matrix.get("changesResourcePolicy") is not False:
        fail("capacity measurement must not change the resource policy")

    by_name: dict[str, dict[str, Any]] = {}
    for point in points:
        name = point.get("name")
        if not isinstance(name, str) or name in by_name:
            fail("capacity point names must be unique strings")
        by_name[name] = point
    if set(by_name) != set(EXPECTED_POINTS):
        fail(f"unexpected measured point set: {sorted(by_name)}")
    for name, (nodes, edges) in EXPECTED_POINTS.items():
        point = by_name[name]
        if point.get("nodes") != nodes or point.get("edges") != edges:
            fail(f"{name} cardinality does not match the frozen matrix")
        for field in (
            "buildNs",
            "queryViewNs",
            "queryNs",
            "recoveryIndexNs",
            "localPrepareNs",
            "localApplyNs",
        ):
            exact_nonnegative_int(point.get(field), f"{name}.{field}", positive=True)
        work = point.get("localWork")
        if not isinstance(work, dict):
            fail(f"{name}.localWork must be an object")
        if work.get("predecessorNodesRead") != 1:
            fail(f"{name} must read exactly one predecessor node for the local replacement")
        if work.get("predecessorEdgesRead") != 0 or work.get("fullEntriesScanned") != 0:
            fail(f"{name} local preparation must not scan predecessor edges or the full graph")
        exact_nonnegative_int(
            work.get("treapLeafUpdates"), f"{name}.localWork.treapLeafUpdates", positive=True
        )
        exact_nonnegative_int(
            work.get("treapNodesRehashed"),
            f"{name}.localWork.treapNodesRehashed",
            positive=True,
        )

    rejected = matrix.get("rejectedPoints")
    if not isinstance(rejected, list):
        fail("capacity matrix rejectedPoints must be an array")
    rejected_by_name = {
        row.get("name"): row for row in rejected if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    if set(rejected_by_name) != set(EXPECTED_REJECTIONS):
        fail(f"unexpected rejected point set: {sorted(rejected_by_name)}")
    for name, (nodes, edges, reason) in EXPECTED_REJECTIONS.items():
        row = rejected_by_name[name]
        if nodes is not None and row.get("nodes") != nodes:
            fail(f"{name} node request changed")
        if edges is not None and row.get("edges") != edges:
            fail(f"{name} edge request changed")
        if row.get("reason") != reason:
            fail(f"{name} rejection reason changed")
    return [by_name[name] for name in EXPECTED_POINTS], matrix


def host_observation() -> dict[str, Any]:
    observation: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logicalCpuCount": os.cpu_count(),
        "python": platform.python_version(),
        "temporaryRoot": str(Path(tempfile.gettempdir()).resolve(strict=True)),
    }
    if platform.system() == "Linux":
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("model name"):
                    observation["cpuModel"] = line.split(":", 1)[1].strip()
                    break
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    observation["memoryTotalKiB"] = int(line.split()[1])
                    break
        loadavg = Path("/proc/loadavg")
        if loadavg.exists():
            observation["loadAverageBefore"] = loadavg.read_text(encoding="utf-8").split()[:3]
    return observation


def run_curve(args: argparse.Namespace) -> tuple[str, int]:
    env = os.environ.copy()
    env["CARGO_INCREMENTAL"] = "0"
    if args.target_dir:
        env["CARGO_TARGET_DIR"] = str(Path(args.target_dir).expanduser().resolve())
    started = time.monotonic_ns()
    output = command(
        "cargo",
        "test",
        "--locked",
        "--release",
        "-p",
        "codex-hepta-kg",
        "--test",
        "capacity_curve",
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
    if not re.search(r"test result: ok\. 1 passed; 0 failed; 0 ignored;", output):
        fail("capacity curve did not execute exactly one successful non-skipped test")
    return output, elapsed


def write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def self_test() -> int:
    fixture_points = [
        {
            "name": name,
            "nodes": nodes,
            "edges": edges,
            "buildNs": 1,
            "queryViewNs": 1,
            "queryNs": 1,
            "recoveryIndexNs": 1,
            "localPrepareNs": 1,
            "localApplyNs": 1,
            "localWork": {
                "predecessorNodesRead": 1,
                "predecessorEdgesRead": 0,
                "treapLeafUpdates": 1,
                "treapNodesRehashed": 1,
                "fullEntriesScanned": 0,
            },
        }
        for name, (nodes, edges) in EXPECTED_POINTS.items()
    ]
    matrix = {
        "schema": MATRIX_SCHEMA,
        "kernelPolicy": {"maximumNodes": 65_536, "maximumEdges": 262_144},
        "measuredPoints": list(EXPECTED_POINTS),
        "rejectedPoints": [
            {"name": "requested-100k-nodes", "nodes": 100_000, "reason": "kernel-node-policy"},
            {"name": "requested-1m-edges", "edges": 1_000_000, "reason": "kernel-edge-policy"},
        ],
        "hostIndependentThresholdsClaimed": False,
        "changesResourcePolicy": False,
    }
    output = "\n".join(
        [json.dumps(point, separators=(",", ":")) for point in fixture_points]
        + [MATRIX_PREFIX + json.dumps(matrix, separators=(",", ":"))]
    )
    parse_output(output)
    print("PASS_HEPTA_KNOWLEDGE_GRAPH_CAPACITY_CURVE_SELF_TEST")
    return 0


def measure(args: argparse.Namespace) -> int:
    source_commit = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source_commit != args.expected_sha:
        fail(f"source identity mismatch: expected {args.expected_sha}, observed {source_commit}")
    if git("status", "--porcelain"):
        fail("working tree is not clean")
    if not TEST_SOURCE.is_file():
        fail(f"missing capacity test source: {TEST_SOURCE.relative_to(ROOT)}")

    output, wall_ns = run_curve(args)
    points, matrix = parse_output(output)
    if source_commit != git("rev-parse", "HEAD") or source_tree != git("rev-parse", "HEAD^{tree}"):
        fail("source identity changed during capacity measurement")
    if git("status", "--porcelain"):
        fail("working tree changed during capacity measurement")

    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "cargoLockSha256": hashlib.sha256((CARGO_ROOT / "Cargo.lock").read_bytes()).hexdigest(),
        "testSourceSha256": hashlib.sha256(TEST_SOURCE.read_bytes()).hexdigest(),
        "hostProfileId": args.host_profile_id,
        "host": host_observation(),
        "buildProfile": "release",
        "testName": TEST_NAME,
        "points": points,
        "matrix": matrix,
        "rawOutputSha256": hashlib.sha256(output.encode()).hexdigest(),
        "harnessWallNanoseconds": wall_ns,
        "interpretation": {
            "exactSourceBound": True,
            "targetHostSpecific": True,
            "doesNotChangeResourcePolicy": True,
            "doesNotSelectIncrementalWriter": True,
            "doesNotGrantAcceptance": True,
            "doesNotGrantActivation": True,
            "doesNotGrantRelease": True,
        },
    }
    payload = json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    write_atomic(Path(args.output), payload)
    if args.raw_output:
        write_atomic(Path(args.raw_output), output)
    print(json.dumps(evidence, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--host-profile-id")
    parser.add_argument("--target-dir")
    parser.add_argument("--output")
    parser.add_argument("--raw-output")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.expected_sha or not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        parser.error("--expected-sha must be the exact 40-character candidate SHA")
    if not args.host_profile_id:
        parser.error("--host-profile-id is required")
    if not args.output:
        parser.error("--output is required")
    return measure(args)


if __name__ == "__main__":
    raise SystemExit(main())
