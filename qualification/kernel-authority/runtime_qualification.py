#!/usr/bin/env python3
"""Produce candidate-bound kernel.authority pilot and benchmark receipts.

The harness executes repository tests and measurements in the prepared exact-head
or deterministic synthetic-merge checkout. Receipts are evidence of those local
runs only. They never grant deployment activation, production SLOs, or release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
CODEX_ROOT = ROOT / "codex-rs"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
IDENTITY_FIELDS = {
    "schema",
    "mode",
    "sourceCommit",
    "baseCommit",
    "candidateCommit",
    "candidateTree",
    "activationGranted",
    "releaseGranted",
}


class QualificationError(RuntimeError):
    """Raised when candidate identity or a required run is invalid."""


class Case(NamedTuple):
    name: str
    product: str
    command: tuple[str, ...]


PILOT_CASES = (
    Case(
        "fleet-create-restart-revoke",
        "runtime.fleet",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-fleet",
            "authority_port::tests::allocation_issue_consumes_exact_live_kernel_authority_lease",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "browser-agentd-final-use-boundary",
        "browser.servo.agentd",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "browser_servo::tests::final_use_fence_covers_exactly_the_browser_local_dispatch_boundary",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "agentd-effect-owner-restart-and-receipt",
        "automation.taskflow.agentd",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "automation_effect_host::tests::host_dispatches_exact_wire_payload_once",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "external-frontier-snapshot-rollback",
        "automation.taskflow.agentd",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "authority_trust_host::tests::restored_local_authority_snapshot_is_rejected_by_external_frontier",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "pending-revocation-admission-fence",
        "kernel.authority",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-contracts",
            "final_use::tests::pending_revocation_preserves_the_observed_head_until_commit",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "pending-revocation-crash-recovery-matrix",
        "kernel.authority",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-contracts",
            "--test",
            "final_use_pending_recovery",
            "--",
            "--nocapture",
        ),
    ),
    Case(
        "issuer-key-overlap-and-retirement",
        "kernel.authority",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-contracts",
            "final_use::tests::issuer_key_ring_supports_overlap_and_epoch_retirement",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
    Case(
        "frontier-ahead-local-commit-failure",
        "kernel.authority",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-contracts",
            "final_use::tests::external_final_use_frontier_ahead_after_local_failure_fences_reopen",
            "--",
            "--exact",
            "--nocapture",
        ),
    ),
)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_identity(path: Path) -> dict[str, Any]:
    try:
        identity = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationError(f"invalid candidate identity: {error}") from error
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise QualificationError("candidate identity fields are not exact")
    if identity["schema"] != "hepta.kernel-authority-candidate.v1":
        raise QualificationError("unsupported candidate identity schema")
    if identity["mode"] not in {"exact-head", "synthetic-merge"}:
        raise QualificationError("unsupported candidate mode")
    for field in ("sourceCommit", "baseCommit", "candidateCommit", "candidateTree"):
        value = identity[field]
        if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
            raise QualificationError(f"{field} is not an exact lowercase commit/tree id")
    if identity["activationGranted"] is not False or identity["releaseGranted"] is not False:
        raise QualificationError("candidate identity must not grant activation or release")
    if git("rev-parse", "HEAD") != identity["candidateCommit"]:
        raise QualificationError("candidate identity does not match checkout HEAD")
    if git("rev-parse", "HEAD^{tree}") != identity["candidateTree"]:
        raise QualificationError("candidate identity does not match checkout tree")
    return identity


def environment() -> dict[str, str]:
    return {
        **os.environ,
        "CARGO_INCREMENTAL": "0",
        "RUST_BACKTRACE": "1",
    }


def run_case(case: Case, output_dir: Path) -> dict[str, Any]:
    log_path = output_dir / "logs" / f"{case.name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    with log_path.open("wb") as log:
        completed = subprocess.run(
            list(case.command),
            cwd=CODEX_ROOT,
            env=environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    duration_ms = max(1, (time.monotonic_ns() - started) // 1_000_000)
    return {
        "name": case.name,
        "product": case.product,
        "command": list(case.command),
        "workingDirectory": "codex-rs",
        "exitCode": completed.returncode,
        "durationMs": duration_ms,
        "logPath": log_path.relative_to(output_dir).as_posix(),
        "logBytes": log_path.stat().st_size,
        "logSha256": sha256_file(log_path),
        "passed": completed.returncode == 0,
    }


def pilot(identity: dict[str, Any], output_dir: Path) -> int:
    results = [run_case(case, output_dir) for case in PILOT_CASES]
    passed = all(result["passed"] for result in results)
    receipt = {
        "schema": "hepta.kernel-authority-product-pilot.v1",
        "schemaVersion": 1,
        "candidate": identity,
        "scope": "repository-process-pilot",
        "fleetPathExecuted": any(
            result["product"] == "runtime.fleet" and result["passed"]
            for result in results
        ),
        "browserAgentdPathExecuted": any(
            result["product"] in {"browser.servo.agentd", "automation.taskflow.agentd"}
            and result["passed"]
            for result in results
        ),
        "restartRecoveryExercised": passed,
        "revocationExercised": passed,
        "snapshotRollbackExercised": passed,
        "keyRotationExercised": passed,
        "durableReceiptExercised": passed,
        "passed": passed,
        "deploymentActivationProved": False,
        "productionTrustProved": False,
        "activationGranted": False,
        "releaseGranted": False,
        "cases": results,
    }
    write_json(output_dir / "product-pilot-receipt.json", receipt)
    return 0 if passed else 1


def benchmark(identity: dict[str, Any], output_dir: Path, samples: int) -> int:
    raw_benchmark = output_dir / "raw" / "authority-benchmark.json"
    model_receipt = output_dir / "raw" / "storage-model.json"
    raw_benchmark.parent.mkdir(parents=True, exist_ok=True)
    benchmark_case = Case(
        "kernel-authority-latency-recovery",
        "kernel.authority",
        (
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-contracts",
            "--test",
            "kernel_authority_benchmark",
            "qualification_benchmark_emits_machine_receipt",
            "--",
            "--exact",
            "--nocapture",
        ),
    )
    benchmark_env = environment()
    benchmark_env["HEPTA_KERNEL_AUTHORITY_BENCH_OUTPUT"] = str(raw_benchmark)
    benchmark_env["HEPTA_KERNEL_AUTHORITY_BENCH_SAMPLES"] = str(samples)
    log_path = output_dir / "logs" / f"{benchmark_case.name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    with log_path.open("wb") as log:
        completed = subprocess.run(
            list(benchmark_case.command),
            cwd=CODEX_ROOT,
            env=benchmark_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    duration_ms = max(1, (time.monotonic_ns() - started) // 1_000_000)
    benchmark_result = {
        "name": benchmark_case.name,
        "command": list(benchmark_case.command),
        "exitCode": completed.returncode,
        "durationMs": duration_ms,
        "logPath": log_path.relative_to(output_dir).as_posix(),
        "logBytes": log_path.stat().st_size,
        "logSha256": sha256_file(log_path),
        "passed": completed.returncode == 0 and raw_benchmark.is_file(),
    }

    model_command = (
        sys.executable,
        str(ROOT / "qualification/kernel-authority/storage_model.py"),
        "--output",
        str(model_receipt),
        "--operations",
        str(max(512, samples * 4)),
    )
    model_case = Case("wal-checkpoint-sharding-model", "kernel.authority", model_command)
    model_result = run_case(model_case, output_dir)
    model_result["command"] = [
        "python3",
        "qualification/kernel-authority/storage_model.py",
        "--output",
        model_receipt.relative_to(output_dir).as_posix(),
        "--operations",
        str(max(512, samples * 4)),
    ]
    model_result["passed"] = model_result["passed"] and model_receipt.is_file()

    passed = benchmark_result["passed"] and model_result["passed"]
    artifacts: list[dict[str, Any]] = []
    for path, kind in (
        (raw_benchmark, "latency-recovery"),
        (model_receipt, "wal-checkpoint-sharding-prototype"),
    ):
        if path.is_file():
            artifacts.append(
                {
                    "kind": kind,
                    "path": path.relative_to(output_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    receipt = {
        "schema": "hepta.kernel-authority-performance-qualification.v1",
        "schemaVersion": 1,
        "candidate": identity,
        "requestedSamples": samples,
        "passed": passed,
        "qualificationOnly": True,
        "productionSloGranted": False,
        "walCheckpointProductionImplementation": False,
        "registryShardingProductionImplementation": False,
        "activationGranted": False,
        "releaseGranted": False,
        "runs": [benchmark_result, model_result],
        "artifacts": artifacts,
    }
    write_json(output_dir / "performance-qualification-receipt.json", receipt)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pilot")
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--samples", type=int, default=128)
    args = parser.parse_args()

    identity = load_identity(args.identity.resolve())
    output_dir = args.output_dir.resolve()
    if output_dir.is_relative_to(ROOT):
        parser.error("output-dir must live outside the source checkout")
    if args.command == "pilot":
        return pilot(identity, output_dir)
    if not 16 <= args.samples <= 2_048:
        parser.error("samples must be in 16..=2048")
    return benchmark(identity, output_dir, args.samples)


if __name__ == "__main__":
    raise SystemExit(main())
