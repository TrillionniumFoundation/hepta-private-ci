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
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
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


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise QualificationError(f"{label} is not a JSON object")
    return value


def require_exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        raise QualificationError(f"{label} fields drifted; missing={missing}, extra={extra}")


def require_nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise QualificationError(f"{label} must be a nonnegative integer")
    return value


def require_positive_int(value: Any, label: str) -> int:
    integer = require_nonnegative_int(value, label)
    if integer == 0:
        raise QualificationError(f"{label} must be positive")
    return integer


def load_identity(path: Path) -> dict[str, Any]:
    identity = load_json_object(path, "candidate identity")
    if set(identity) != IDENTITY_FIELDS:
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


def pilot_claims(results: list[dict[str, Any]]) -> dict[str, bool]:
    expected = {case.name for case in PILOT_CASES}
    observed: dict[str, dict[str, Any]] = {}
    for result in results:
        name = result.get("name")
        if not isinstance(name, str) or name not in expected or name in observed:
            raise QualificationError("pilot case set is incomplete, unknown, or duplicated")
        if type(result.get("passed")) is not bool:
            raise QualificationError(f"pilot case {name} has no exact boolean result")
        observed[name] = result
    if set(observed) != expected:
        raise QualificationError("pilot case set is incomplete, unknown, or duplicated")

    def passed(name: str) -> bool:
        return observed[name]["passed"] is True

    return {
        "fleetPathExecuted": passed("fleet-create-restart-revoke"),
        "browserAgentdPathExecuted": passed("browser-agentd-final-use-boundary")
        and passed("agentd-effect-owner-restart-and-receipt"),
        "restartRecoveryExercised": passed("fleet-create-restart-revoke")
        and passed("agentd-effect-owner-restart-and-receipt")
        and passed("pending-revocation-crash-recovery-matrix"),
        "revocationExercised": passed("fleet-create-restart-revoke")
        and passed("pending-revocation-admission-fence")
        and passed("pending-revocation-crash-recovery-matrix"),
        "snapshotRollbackExercised": passed("external-frontier-snapshot-rollback")
        and passed("frontier-ahead-local-commit-failure"),
        "keyRotationExercised": passed("issuer-key-overlap-and-retirement"),
        "durableReceiptExercised": passed("agentd-effect-owner-restart-and-receipt"),
    }


def pilot(identity: dict[str, Any], output_dir: Path) -> int:
    results = [run_case(case, output_dir) for case in PILOT_CASES]
    claims = pilot_claims(results)
    passed = all(result["passed"] for result in results) and all(claims.values())
    receipt = {
        "schema": "hepta.kernel-authority-product-pilot.v1",
        "schemaVersion": 1,
        "candidate": identity,
        "scope": "repository-process-pilot",
        **claims,
        "passed": passed,
        "deploymentActivationProved": False,
        "productionTrustProved": False,
        "activationGranted": False,
        "releaseGranted": False,
        "cases": results,
    }
    write_json(output_dir / "product-pilot-receipt.json", receipt)
    return 0 if passed else 1


def validate_distribution(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise QualificationError(f"{label} must be an object")
    require_exact_fields(
        value,
        {"count", "minUs", "meanUs", "p50Us", "p95Us", "p99Us", "maxUs"},
        label,
    )
    count = require_positive_int(value["count"], f"{label}.count")
    points = [
        require_nonnegative_int(value[name], f"{label}.{name}")
        for name in ("minUs", "p50Us", "meanUs", "p95Us", "p99Us", "maxUs")
    ]
    minimum, p50, mean, p95, p99, maximum = points
    if not minimum <= p50 <= p95 <= p99 <= maximum:
        raise QualificationError(f"{label} percentile ordering is invalid")
    if not minimum <= mean <= maximum:
        raise QualificationError(f"{label}.meanUs is outside the observed range")
    if count < 16:
        raise QualificationError(f"{label} has too few samples")


def validate_benchmark_receipt(path: Path, requested_samples: int) -> dict[str, Any]:
    value = load_json_object(path, "authority benchmark receipt")
    require_exact_fields(
        value,
        {
            "schema",
            "schemaVersion",
            "qualificationOnly",
            "productionSloGranted",
            "samples",
            "state",
            "operations",
            "contention",
            "throughputMilliOperationsPerSecond",
            "totalMeasuredUs",
        },
        "authority benchmark receipt",
    )
    if value["schema"] != "hepta.kernel-authority-benchmark.v1":
        raise QualificationError("authority benchmark schema mismatch")
    if value["schemaVersion"] != 1:
        raise QualificationError("authority benchmark schema version mismatch")
    if value["qualificationOnly"] is not True or value["productionSloGranted"] is not False:
        raise QualificationError("authority benchmark overclaims production SLO authority")
    if value["samples"] != requested_samples:
        raise QualificationError("authority benchmark sample count mismatch")
    state = value["state"]
    if not isinstance(state, dict):
        raise QualificationError("authority benchmark state must be an object")
    require_exact_fields(
        state,
        {"snapshotBytes", "leases", "revocations", "retiredLeaseIds", "reopenUs"},
        "authority benchmark state",
    )
    for name in state:
        require_nonnegative_int(state[name], f"authority benchmark state.{name}")
    operations = value["operations"]
    if not isinstance(operations, dict):
        raise QualificationError("authority benchmark operations must be an object")
    require_exact_fields(
        operations,
        {
            "durableLeasePut",
            "dispatchEntry",
            "durableLeaseRevoke",
            "contendedDispatchEntry",
        },
        "authority benchmark operations",
    )
    for name, distribution in operations.items():
        validate_distribution(distribution, f"authority benchmark operations.{name}")
    contention = value["contention"]
    if not isinstance(contention, dict):
        raise QualificationError("authority benchmark contention must be an object")
    require_exact_fields(contention, {"threads", "iterationsPerThread"}, "contention")
    require_positive_int(contention["threads"], "contention.threads")
    require_positive_int(contention["iterationsPerThread"], "contention.iterationsPerThread")
    require_positive_int(
        value["throughputMilliOperationsPerSecond"],
        "throughputMilliOperationsPerSecond",
    )
    require_positive_int(value["totalMeasuredUs"], "totalMeasuredUs")
    return value


def validate_storage_model_receipt(path: Path, expected_operations: int) -> dict[str, Any]:
    value = load_json_object(path, "storage model receipt")
    require_exact_fields(
        value,
        {
            "schema",
            "schemaVersion",
            "qualificationOnly",
            "prototypeOnly",
            "productionImplementation",
            "activationGranted",
            "releaseGranted",
            "operations",
            "checkpointInterval",
            "externalFrontier",
            "recovered",
            "crashRollbackAndCorruptionDrills",
            "sharding",
            "capacityLifetime",
            "passed",
        },
        "storage model receipt",
    )
    if value["schema"] != "hepta.kernel-authority-storage-model.v2":
        raise QualificationError("storage model schema mismatch")
    if value["schemaVersion"] != 2:
        raise QualificationError("storage model schema version mismatch")
    if (
        value["qualificationOnly"] is not True
        or value["prototypeOnly"] is not True
        or value["productionImplementation"] is not False
        or value["activationGranted"] is not False
        or value["releaseGranted"] is not False
        or value["passed"] is not True
    ):
        raise QualificationError("storage model qualification boundary is invalid")
    if value["operations"] != expected_operations:
        raise QualificationError("storage model operation count mismatch")
    require_positive_int(value["checkpointInterval"], "storage model checkpointInterval")

    frontier = value["externalFrontier"]
    if not isinstance(frontier, dict):
        raise QualificationError("storage model externalFrontier must be an object")
    require_exact_fields(
        frontier,
        {
            "schema",
            "sequence",
            "headRecordSha256",
            "rollbackIndependent",
            "qualificationOnly",
        },
        "storage model externalFrontier",
    )
    if frontier["schema"] != "hepta.kernel-authority-storage-frontier.v1":
        raise QualificationError("storage model external frontier schema mismatch")
    if frontier["sequence"] != expected_operations:
        raise QualificationError("storage model external frontier sequence mismatch")
    if (
        not isinstance(frontier["headRecordSha256"], str)
        or DIGEST_PATTERN.fullmatch(frontier["headRecordSha256"]) is None
    ):
        raise QualificationError("storage model external frontier digest is invalid")
    if frontier["rollbackIndependent"] is not True or frontier["qualificationOnly"] is not True:
        raise QualificationError("storage model external frontier overclaims deployment")

    recovered = value["recovered"]
    if not isinstance(recovered, dict):
        raise QualificationError("storage model recovered state must be an object")
    require_exact_fields(
        recovered,
        {
            "discardedPartialTail",
            "externalFrontierMatched",
            "headRecordSha256",
            "sequence",
        },
        "storage model recovered",
    )
    if recovered["sequence"] != expected_operations:
        raise QualificationError("storage model recovered sequence mismatch")
    if recovered["headRecordSha256"] != frontier["headRecordSha256"]:
        raise QualificationError("storage model recovered digest mismatch")
    if recovered["externalFrontierMatched"] is not True:
        raise QualificationError("storage model did not bind recovery to the external frontier")
    if recovered["discardedPartialTail"] is not False:
        raise QualificationError("storage model baseline unexpectedly had a torn tail")

    drills = value["crashRollbackAndCorruptionDrills"]
    if not isinstance(drills, dict):
        raise QualificationError("storage model drill results must be an object")
    require_exact_fields(
        drills,
        {
            "baselineRecovery",
            "committedRecordCorruptionRejected",
            "corruptedCheckpointRejected",
            "externalFrontierAheadFences",
            "partialTailDiscarded",
            "staleExternalFrontierRejected",
            "validOlderLocalSnapshotRejected",
        },
        "storage model drills",
    )
    failed_drills = sorted(name for name, result in drills.items() if result is not True)
    if failed_drills:
        raise QualificationError(f"storage model drills failed: {failed_drills}")
    if not isinstance(value["sharding"], dict) or value["sharding"].get("deterministic") is not True:
        raise QualificationError("storage model sharding proof is invalid")
    if not isinstance(value["capacityLifetime"], dict):
        raise QualificationError("storage model capacity lifetime is invalid")
    return value


def validation_error(error: Exception | None) -> str | None:
    return None if error is None else str(error)


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
    benchmark_error: Exception | None = None
    try:
        if completed.returncode != 0:
            raise QualificationError(f"benchmark command exited {completed.returncode}")
        validate_benchmark_receipt(raw_benchmark, samples)
    except (OSError, QualificationError) as error:
        benchmark_error = error
    benchmark_result = {
        "name": benchmark_case.name,
        "command": list(benchmark_case.command),
        "exitCode": completed.returncode,
        "durationMs": duration_ms,
        "logPath": log_path.relative_to(output_dir).as_posix(),
        "logBytes": log_path.stat().st_size,
        "logSha256": sha256_file(log_path),
        "receiptValidated": benchmark_error is None,
        "validationError": validation_error(benchmark_error),
        "passed": benchmark_error is None,
    }

    model_operations = max(512, samples * 4)
    model_command = (
        sys.executable,
        str(ROOT / "qualification/kernel-authority/storage_model.py"),
        "--output",
        str(model_receipt),
        "--operations",
        str(model_operations),
    )
    model_case = Case("wal-checkpoint-sharding-model", "kernel.authority", model_command)
    model_result = run_case(model_case, output_dir)
    model_result["command"] = [
        "python3",
        "qualification/kernel-authority/storage_model.py",
        "--output",
        model_receipt.relative_to(output_dir).as_posix(),
        "--operations",
        str(model_operations),
    ]
    model_error: Exception | None = None
    try:
        if model_result["exitCode"] != 0:
            raise QualificationError(f"storage model exited {model_result['exitCode']}")
        validate_storage_model_receipt(model_receipt, model_operations)
    except (OSError, QualificationError) as error:
        model_error = error
    model_result["receiptValidated"] = model_error is None
    model_result["validationError"] = validation_error(model_error)
    model_result["passed"] = model_error is None

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
