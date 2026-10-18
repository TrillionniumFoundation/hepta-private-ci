#!/usr/bin/env python3
"""Run and validate the target-host Cell Split qualification matrix.

The matrix is deliberately four-dimensional and therefore has exactly sixteen
rows.  Every row receives the same frozen workload digest.  A row is accepted
only after the workload emits measured metrics and an independent observer
returns a receipt binding the case, source commit, workload and metric digest.
This harness never grants execution authority; the report is DENY_ALL evidence
for a later human/host gate.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Resolve this repository-owned verifier when invoked as an absolute script
# or imported through spec_from_file_location by the exact-head test suite.
SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)
from hepta_cell_split_observer_crypto import verify_observer_receipt_signature


SCHEMA = "hepta.cell-split.target-matrix.v1"
AUTHORITY = "DENY_ALL"
FACTORS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("encoder_topology", ("shared", "replicated")),
    ("execution", ("scalar", "batch")),
    ("feature_materialization", ("rematerialize", "snapshot_reuse")),
    ("persistence", ("full_snapshot", "incremental_wal")),
)
REQUIRED_METRICS = (
    "p50Micros",
    "p95Micros",
    "p99Micros",
    "throughputPerSecond",
    "cpuMicros",
    "rssBytes",
    "communicationBytes",
    "fsyncCount",
    "lockWaitMicros",
    "recoveryMicros",
    "negativeMigrationQ32",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    """Bound hash verification RSS regardless of frozen workload file size."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def matrix_cases() -> list[dict[str, str]]:
    names = [name for name, _ in FACTORS]
    choices = [values for _, values in FACTORS]
    cases: list[dict[str, str]] = []
    for index, values in enumerate(itertools.product(*choices), start=1):
        case = {"caseId": f"cell-split-{index:02d}"}
        case.update(dict(zip(names, values, strict=True)))
        cases.append(case)
    return cases


def _number(value: Any, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric {name} must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"metric {name} must be finite")
    if isinstance(value, int) and value.bit_length() > 64:
        raise ValueError(f"metric {name} exceeds the bounded counter range")
    if value < 0:
        raise ValueError(f"metric {name} must be non-negative")
    if integer and not isinstance(value, int):
        raise ValueError(f"metric {name} must be an integer")
    return value


def validate_metrics(metrics: dict[str, Any]) -> dict[str, int | float]:
    missing = [name for name in REQUIRED_METRICS if name not in metrics]
    if missing:
        raise ValueError(f"missing metrics: {','.join(missing)}")
    normalized: dict[str, int | float] = {}
    for name in REQUIRED_METRICS:
        normalized[name] = _number(metrics[name], name, integer=name in {"fsyncCount", "rssBytes", "negativeMigrationQ32"})
    if not (normalized["p50Micros"] <= normalized["p95Micros"] <= normalized["p99Micros"]):
        raise ValueError("latency quantiles are not monotonic")
    if normalized["throughputPerSecond"] <= 0:
        raise ValueError("throughput must be positive")
    return normalized


def parse_json_object(stdout: str) -> dict[str, Any]:
    """Read the final JSON object emitted by a worker."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("worker did not emit a JSON object")


def parse_workload_output(stdout: str) -> dict[str, Any]:
    value = parse_json_object(stdout)
    if "metrics" not in value:
        raise ValueError("workload did not emit a JSON object containing metrics")
    return value


def _command(argv: str, case: dict[str, str]) -> list[str]:
    tokens = shlex.split(argv)
    return [token.format(**case) for token in tokens]


def run_matrix(
    *,
    workload_command: str | None,
    observer_command: str | None,
    workload_digest: str,
    source_commit: str,
    output: Path,
    workload_path: Path | None = None,
    host_id: str | None = None,
    timeout_seconds: int = 1800,
    observer_public_key: Path | None = None,
    observer_key_sha256: str | None = None,
    expected_observer_id: str | None = None,
) -> dict[str, Any]:
    if len(workload_digest) != 64 or any(char not in "0123456789abcdef" for char in workload_digest):
        raise ValueError("workload digest must be a lowercase sha256")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be a lowercase 40-character commit")
    if workload_command is not None:
        # A caller-provided SHA is not proof that the measured checkout is that SHA.
        # Dry-run reports remain possible without a git checkout, but no real
        # worker can be admitted without verifying the exact local source HEAD.
        repo_root = Path(__file__).resolve().parent.parent
        try:
            checkout = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("cannot verify measured repository HEAD") from error
        if checkout.stdout.strip() != source_commit:
            raise ValueError("measured source commit does not match repository HEAD")
    if workload_path is not None:
        actual_workload_digest = sha256_file(workload_path)
        if actual_workload_digest != workload_digest:
            raise ValueError("workload path does not match the frozen workload digest")
    host = host_id or platform.node() or "unknown-host"
    host_fingerprint = {
        "hostId": host,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    cases = matrix_cases()
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    for case in cases:
        started = time.monotonic_ns()
        row: dict[str, Any] = {**case, "workloadDigest": workload_digest, "status": "blocked"}
        if workload_command is None:
            row["reason"] = "workload command not supplied"
            blocked.append(case["caseId"])
            rows.append(row)
            continue
        if workload_path is None:
            row["reason"] = "frozen workload path is required"
            blocked.append(case["caseId"])
            rows.append(row)
            continue
        env = os.environ.copy()
        env.update({
            "HEPTA_MATRIX_CASE_ID": case["caseId"],
            "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
            "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
            "HEPTA_MATRIX_WORKLOAD_PATH": str(workload_path),
            **{f"HEPTA_MATRIX_{key.upper()}": value for key, value in case.items() if key != "caseId"},
        })
        try:
            if sha256_file(workload_path) != workload_digest:
                raise ValueError("frozen workload changed before case execution")
            result = subprocess.run(
                _command(
                    workload_command,
                    {
                        **case,
                        "workloadDigest": workload_digest,
                        "sourceCommit": source_commit,
                    },
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if sha256_file(workload_path) != workload_digest:
                raise ValueError("frozen workload changed during case execution")
            if result.returncode != 0:
                raise ValueError(f"workload exited {result.returncode}: {result.stderr[-512:]}")
            emitted = parse_workload_output(result.stdout)
            if (
                emitted.get("caseId") != case["caseId"]
                or emitted.get("workloadDigest") != workload_digest
                or emitted.get("workloadSourceDigest") != workload_digest
                or emitted.get("sourceCommit") != source_commit
                or any(
                    emitted.get(name) != value
                    for name, value in case.items()
                    if name != "caseId"
                )
            ):
                raise ValueError("workload identity does not bind the requested case")
            metrics = validate_metrics(emitted["metrics"])
            row.update({"metrics": metrics, "status": "measured", "metricsDigest": digest(metrics)})
        except (KeyError, OSError, subprocess.SubprocessError, ValueError) as error:
            row["reason"] = str(error)
            blocked.append(case["caseId"])
        row["elapsedMicros"] = (time.monotonic_ns() - started) // 1_000
        rows.append(row)

    provisional = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "sourceCommit": source_commit,
        "workloadDigest": workload_digest,
        "workloadSourceDigest": workload_digest,
        "host": host_fingerprint,
        "cases": rows,
    }
    provisional_digest = digest(provisional)
    metrics_digest = digest([
        {"caseId": row["caseId"], "metricsDigest": row.get("metricsDigest")}
        for row in rows
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(provisional, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    observer_receipt: dict[str, Any] | None = None
    if (
        observer_command is None
        or observer_public_key is None
        or observer_key_sha256 is None
        or expected_observer_id is None
    ):
        # A self-asserted verified=true string is not an independent observer.
        # Operator-pinned Ed25519 trust must exist before invoking the observer.
        blocked.append("independent-observer")
    else:
        env = os.environ.copy()
        env.update({
            "HEPTA_MATRIX_REPORT": str(output),
            "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
            "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
            "HEPTA_MATRIX_PROVISIONAL_DIGEST": provisional_digest,
            "HEPTA_MATRIX_METRICS_DIGEST": metrics_digest,
        })
        try:
            result = subprocess.run(
                shlex.split(observer_command),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if result.returncode != 0:
                raise ValueError(f"observer exited {result.returncode}: {result.stderr[-512:]}")
            observer_receipt = parse_json_object(result.stdout)
            if observer_receipt.get("verified") is not True:
                raise ValueError("observer did not return verified=true")
            if (
                observer_receipt.get("sourceCommit") != source_commit
                or observer_receipt.get("workloadDigest") != workload_digest
                or observer_receipt.get("reportDigest") != provisional_digest
                or observer_receipt.get("metricsDigest") != metrics_digest
                or not isinstance(observer_receipt.get("observerId"), str)
                or not observer_receipt["observerId"].strip()
            ):
                raise ValueError("observer receipt binding mismatch")
            verify_observer_receipt_signature(
                observer_receipt,
                trusted_public_key_path=observer_public_key,
                trusted_key_sha256=observer_key_sha256,
                expected_observer_id=expected_observer_id,
            )
            observer_receipt["receiptDigest"] = digest({key: value for key, value in observer_receipt.items() if key != "receiptDigest"})
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            blocked.append("independent-observer")
            observer_receipt = {"verified": False, "reason": str(error)}

    report = {
        **provisional,
        "observer": observer_receipt,
        "blockingCases": sorted(set(blocked)),
        "status": "qualified" if not blocked else "blocked",
        "reportDigest": digest({**provisional, "observer": observer_receipt}),
    }
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def validate_report(
    report: dict[str, Any],
    *,
    observer_public_key: Path | None = None,
    observer_key_sha256: str | None = None,
    expected_observer_id: str | None = None,
) -> None:
    """Verify report integrity and qualified observer signature, never split authority."""
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    if report.get("schema") != SCHEMA or report.get("authority") != AUTHORITY:
        raise ValueError("invalid report schema or authority posture")
    source = report.get("sourceCommit")
    workload = report.get("workloadDigest")
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("invalid source commit identity")
    if not isinstance(workload, str) or not re.fullmatch(r"[0-9a-f]{64}", workload):
        raise ValueError("invalid workload digest")
    if report.get("workloadSourceDigest") != workload:
        raise ValueError("workload source digest mismatch")
    if not isinstance(report.get("host"), dict):
        raise ValueError("host fingerprint missing")

    expected = {case["caseId"]: case for case in matrix_cases()}
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != len(expected):
        raise ValueError("report must contain exactly sixteen matrix rows")
    seen: set[str] = set()
    unmeasured: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("matrix row must be an object")
        case_id = case.get("caseId")
        if not isinstance(case_id, str) or case_id not in expected or case_id in seen:
            raise ValueError("unknown or repeated matrix case ID")
        seen.add(case_id)
        if any(case.get(field) != value for field, value in expected[case_id].items()):
            raise ValueError("matrix case factor tuple does not match canonical case ID")
        if case.get("workloadDigest") != workload:
            raise ValueError("case workload binding mismatch")
        if case.get("status") == "measured":
            raw_metrics = case.get("metrics")
            if not isinstance(raw_metrics, dict):
                raise ValueError("measured row lacks metrics object")
            metrics = validate_metrics(raw_metrics)
            if case.get("metricsDigest") != digest(metrics):
                raise ValueError("metric digest mismatch")
        elif case.get("status") == "blocked":
            unmeasured.add(case_id)
            if not isinstance(case.get("reason"), str) or not case["reason"].strip():
                raise ValueError("blocked row requires a reason")
        else:
            raise ValueError("unknown matrix row status")

    observer = report.get("observer")
    if observer is not None and not isinstance(observer, dict):
        raise ValueError("observer receipt must be an object or null")
    verified = isinstance(observer, dict) and observer.get("verified") is True
    provisional = {
        key: report[key]
        for key in ("schema", "authority", "sourceCommit", "workloadDigest", "workloadSourceDigest", "host", "cases")
    }
    if report.get("reportDigest") != digest({**provisional, "observer": observer}):
        raise ValueError("final report digest mismatch")
    if verified:
        assert isinstance(observer, dict)
        if observer.get("sourceCommit") != source or observer.get("workloadDigest") != workload:
            raise ValueError("observer source/workload binding mismatch")
        if observer.get("reportDigest") != digest(provisional):
            raise ValueError("observer provisional report binding mismatch")
        metrics_digest = digest([
            {"caseId": case["caseId"], "metricsDigest": case.get("metricsDigest")}
            for case in cases
        ])
        if observer.get("metricsDigest") != metrics_digest:
            raise ValueError("observer metrics binding mismatch")
        if not isinstance(observer.get("observerId"), str) or not observer["observerId"].strip():
            raise ValueError("observer identity missing")
        if observer.get("receiptDigest") != digest({
            key: value for key, value in observer.items() if key != "receiptDigest"
        }):
            raise ValueError("observer receipt digest mismatch")

    blocked = report.get("blockingCases")
    if (not isinstance(blocked, list)
            or any(not isinstance(value, str) for value in blocked)
            or blocked != sorted(set(blocked))):
        raise ValueError("blockingCases must be sorted and unique")
    expected_blocked = unmeasured | (set() if verified else {"independent-observer"})
    if set(blocked) != expected_blocked:
        raise ValueError("blockingCases do not match measured rows and observer")

    status = report.get("status")
    if status == "qualified":
        if blocked:
            raise ValueError("qualified report contains unresolved blockers")
        if not verified:
            raise ValueError("qualified report lacks an observer receipt")
        verify_observer_receipt_signature(
            observer,
            trusted_public_key_path=observer_public_key,
            trusted_key_sha256=observer_key_sha256,
            expected_observer_id=expected_observer_id,
        )
    elif status == "blocked":
        if not blocked:
            raise ValueError("blocked report has no blocking evidence")
    else:
        raise ValueError("unknown matrix report status")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-command", help="argv template; {caseId} may be interpolated")
    parser.add_argument("--observer-command", help="independent observer argv")
    parser.add_argument("--observer-public-key", type=Path, help="host-trusted Ed25519 PEM public key file")
    parser.add_argument("--observer-key-sha256", help="independently pinned SHA256 of trusted key bytes")
    parser.add_argument("--expected-observer-id", help="host-pinned independent observer principal")
    parser.add_argument("--workload-digest", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workload-path", type=Path, help="path to the frozen workload bytes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-id")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_report(
            json.loads(args.output.read_text(encoding="utf-8")),
            observer_public_key=args.observer_public_key,
            observer_key_sha256=args.observer_key_sha256,
            expected_observer_id=args.expected_observer_id,
        )
        return 0
    report = run_matrix(
        workload_command=args.workload_command,
        observer_command=args.observer_command,
        workload_digest=args.workload_digest,
        source_commit=args.source_commit,
        output=args.output,
        workload_path=args.workload_path,
        host_id=args.host_id,
        timeout_seconds=args.timeout_seconds,
        observer_public_key=args.observer_public_key,
        observer_key_sha256=args.observer_key_sha256,
        expected_observer_id=args.expected_observer_id,
    )
    print(json.dumps({"status": report["status"], "blockingCases": report["blockingCases"]}, sort_keys=True))
    return 0 if report["status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
