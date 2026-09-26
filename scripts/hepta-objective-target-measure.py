#!/usr/bin/env python3
"""Record objective.compiler target-host latency evidence for one exact source."""

import argparse
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
PREFIX = "OBJECTIVE_MEASUREMENT="
PRODUCT_PREFIX = "OBJECTIVE_PRODUCT_MEASUREMENT="
SCHEMA = "hepta.objective-target-host-evidence.v1"
PRODUCT_SCHEMA = "hepta.objective-product-target-measurement.v1"


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
    rows = [line.split(PREFIX, 1)[1] for line in output.splitlines() if PREFIX in line]
    if len(rows) != 1:
        fail(
            f"expected exactly one measurement row for {expected_path}, received {len(rows)}"
        )
    try:
        value = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid measurement JSON for {expected_path}: {error}")
    if not isinstance(value, dict):
        fail("measurement JSON must be an object")
    if type(value.get("samples")) is not int or value["samples"] <= 0:
        fail("invalid measurement sample count")
    if expected_path == "maximum_conflict_extraction" and (
        type(value.get("constraintAtoms")) is not int
        or value["constraintAtoms"] != 256
        or type(value.get("oracleCallsPerSample")) is not int
        or value["oracleCallsPerSample"] != 257
    ):
        fail("conflict measurement must cover 256 atoms and 257 oracle calls")
    if value.get("schema") != "hepta.objective-target-measurement.v1":
        fail(f"unexpected measurement schema for {expected_path}")
    if value.get("path") != expected_path:
        fail(f"unexpected measurement path: {value.get('path')!r}")
    latency = value.get("latencyNanoseconds")
    if not isinstance(latency, dict):
        fail(f"missing latency distribution for {expected_path}")
    ordered = [latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail(f"invalid latency percentiles for {expected_path}")
    if ordered != sorted(ordered):
        fail(f"non-monotone latency percentiles for {expected_path}")
    return value


def parse_product_measurement(output: str) -> dict[str, Any]:
    rows = [
        line.split(PRODUCT_PREFIX, 1)[1]
        for line in output.splitlines()
        if PRODUCT_PREFIX in line
    ]
    if len(rows) != 1:
        fail(f"expected exactly one product measurement row, received {len(rows)}")
    try:
        value = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid product measurement JSON: {error}")
    if not isinstance(value, dict):
        fail("product measurement JSON must be an object")
    if value.get("schema") != PRODUCT_SCHEMA:
        fail("unexpected product measurement schema")
    if value.get("path") != "signed_objective_daemon_round_trip":
        fail(f"unexpected product measurement path: {value.get('path')!r}")
    samples = value.get("samples")
    if type(samples) is not int or samples <= 0:
        fail("invalid product measurement sample count")
    latency = value.get("latencyNanoseconds")
    if not isinstance(latency, dict):
        fail("missing product latency distribution")
    ordered = [latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail("invalid product latency percentiles")
    if ordered != sorted(ordered):
        fail("non-monotone product latency percentiles")
    execution_samples = value.get("executionSamples")
    if type(execution_samples) is not int or execution_samples <= 0:
        fail("invalid product execution sample count")
    execution_latency = value.get("executionLatencyNanoseconds")
    if not isinstance(execution_latency, dict):
        fail("missing product execution latency distribution")
    execution_ordered = [execution_latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in execution_ordered):
        fail("invalid product execution latency percentiles")
    if execution_ordered != sorted(execution_ordered):
        fail("non-monotone product execution latency percentiles")
    for field in (
        "exactReplayNanoseconds",
        "executionExactReplayNanoseconds",
        "restartReadyNanoseconds",
    ):
        if type(value.get(field)) is not int or value[field] < 0:
            fail(f"invalid product measurement field: {field}")
    for field in (
        "physicalProviderSends",
        "terminalObservations",
        "durableCheckpointSequence",
    ):
        if type(value.get(field)) is not int:
            fail(f"invalid product measurement counter: {field}")
    if value.get("physicalProviderSends") != execution_samples:
        fail("product execution did not preserve one physical send per run")
    if value.get("terminalObservations") != execution_samples:
        fail("product execution did not observe every terminal")
    if value.get("durableCheckpointSequence") != samples + execution_samples:
        fail("product checkpoint sequence does not cover every measured request")
    return value


def run_product_fixture(samples: int, execution_samples: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["HEPTA_OBJECTIVE_PRODUCT_MEASUREMENT_SAMPLES"] = str(samples)
    env["HEPTA_OBJECTIVE_PRODUCT_EXECUTION_SAMPLES"] = str(execution_samples)
    started = time.monotonic_ns()
    output = command(
        "cargo",
        "test",
        "--locked",
        "--release",
        "-p",
        "codex-hepta-agentd",
        "--test",
        "objective_product_e2e",
        "measurement_signed_objective_daemon_round_trip",
        "--",
        "--ignored",
        "--exact",
        "--nocapture",
        cwd=CARGO_ROOT,
        env=env,
    )
    harness_ns = time.monotonic_ns() - started
    measurement = parse_product_measurement(output)
    if (
        measurement["samples"] != samples
        or measurement["executionSamples"] != execution_samples
    ):
        fail("product fixture sample count differs from requested measurement")
    measurement["harnessWallNanoseconds"] = harness_ns
    return measurement


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
    if measurement["samples"] != samples:
        fail("fixture sample count differs from requested measurement")
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
    product_fixture = (
        'OBJECTIVE_PRODUCT_MEASUREMENT={"schema":"hepta.objective-product-target-measurement.v1",'
        '"path":"signed_objective_daemon_round_trip","samples":3,'
        '"latencyNanoseconds":{"p50":100,"p95":200,"p99":300},'
        '"exactReplayNanoseconds":80,"executionSamples":2,'
        '"executionLatencyNanoseconds":{"p50":150,"p95":250,"p99":350},'
        '"executionExactReplayNanoseconds":90,"physicalProviderSends":2,'
        '"terminalObservations":2,"restartReadyNanoseconds":400,'
        '"durableCheckpointSequence":5}'
    )
    product = parse_product_measurement(product_fixture)
    if product["restartReadyNanoseconds"] != 400:
        fail("product self-test parse mismatch")
    print("PASS_HEPTA_OBJECTIVE_TARGET_MEASUREMENT_SELF_TEST")
    return 0


def filesystem_context(root: Path, mountinfo: str) -> dict:
    """Describe the actual fixture filesystem without claiming storage acceptance."""
    root = root.resolve()
    selected = None
    for line in mountinfo.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
            if separator < 6 or len(fields) <= separator + 1:
                continue
            encoded = fields[4]
            for escape, decoded in (
                ("\\040", " "),
                ("\\011", "\t"),
                ("\\012", "\n"),
                ("\\134", "\\"),
            ):
                encoded = encoded.replace(escape, decoded)
            mount = Path(encoded)
            if not root.is_relative_to(mount):
                continue
            entry = {
                "mountPoint": str(mount),
                "filesystemType": fields[separator + 1],
                "deviceId": fields[2],
            }
            if selected is None or len(mount.parts) > len(
                Path(selected["mountPoint"]).parts
            ):
                selected = entry
        except (ValueError, IndexError):
            continue
    result = {
        "temporaryRoot": str(root),
        "mountIdentityAvailable": selected is not None,
    }
    if selected is not None:
        result.update(selected)
        result["memoryBacked"] = selected["filesystemType"] in {"tmpfs", "ramfs"}
    result["storageQualificationProved"] = False
    return result


def current_filesystem_context() -> dict:
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        mountinfo = ""
    return filesystem_context(Path(tempfile.gettempdir()), mountinfo)


def measure(args: argparse.Namespace) -> int:
    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source_sha != args.expected_sha:
        fail(
            f"source identity mismatch: expected {args.expected_sha}, observed {source_sha}"
        )
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
    product = run_product_fixture(args.product_samples, args.execution_samples)

    # A concurrent checkout or edit during the fixtures invalidates this receipt.
    if (
        git("rev-parse", "HEAD") != source_sha
        or git("rev-parse", "HEAD^{tree}") != source_tree
    ):
        fail("source identity changed during measurement")
    if git("status", "--porcelain"):
        fail("working tree changed during measurement")

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
            "fixtureFilesystem": current_filesystem_context(),
        },
        "buildProfile": "release",
        "measurements": [ordinary, conflict, product],
        "interpretation": {
            "ordinaryAndConflictAreSeparate": True,
            "productIncludesSignedIngressSocketFsyncAndRestart": True,
            "productExecutionIncludesFinalUsePhysicalSendAndTerminal": True,
            "ciRunnerIsNotProductionEvidence": True,
            "controlledModelProviderAndContextFixture": True,
            "storageQualificationProved": False,
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
    parser.add_argument("--product-samples", type=int, default=32)
    parser.add_argument("--execution-samples", type=int, default=4)
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
    if not (1 <= args.product_samples <= 1_000):
        parser.error("--product-samples must be in 1..=1000")
    if not (1 <= args.execution_samples <= 64):
        parser.error("--execution-samples must be in 1..=64")
    return measure(args)


if __name__ == "__main__":
    sys.exit(main())
