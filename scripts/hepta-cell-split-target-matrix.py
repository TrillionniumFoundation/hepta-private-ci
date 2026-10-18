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
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


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
        normalized[name] = _number(
            metrics[name], name, integer=name in {"fsyncCount", "rssBytes"}
        )
    if not (
        normalized["p50Micros"] <= normalized["p95Micros"] <= normalized["p99Micros"]
    ):
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
) -> dict[str, Any]:
    if len(workload_digest) != 64 or any(
        char not in "0123456789abcdef" for char in workload_digest
    ):
        raise ValueError("workload digest must be a lowercase sha256")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be a lowercase 40-character commit")
    if workload_path is not None:
        actual_workload_digest = hashlib.sha256(workload_path.read_bytes()).hexdigest()
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
        row: dict[str, Any] = {
            **case,
            "workloadDigest": workload_digest,
            "status": "blocked",
        }
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
        env.update(
            {
                "HEPTA_MATRIX_CASE_ID": case["caseId"],
                "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
                "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
                "HEPTA_MATRIX_WORKLOAD_PATH": str(workload_path),
                **{
                    f"HEPTA_MATRIX_{key.upper()}": value
                    for key, value in case.items()
                    if key != "caseId"
                },
            }
        )
        try:
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
            if result.returncode != 0:
                raise ValueError(
                    f"workload exited {result.returncode}: {result.stderr[-512:]}"
                )
            emitted = parse_workload_output(result.stdout)
            if (
                emitted.get("caseId") != case["caseId"]
                or emitted.get("workloadDigest") != workload_digest
                or emitted.get("workloadSourceDigest") != workload_digest
            ):
                raise ValueError("workload identity does not bind the requested case")
            metrics = validate_metrics(emitted["metrics"])
            row.update(
                {
                    "metrics": metrics,
                    "status": "measured",
                    "metricsDigest": digest(metrics),
                }
            )
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
    metrics_digest = digest(
        [
            {"caseId": row["caseId"], "metricsDigest": row.get("metricsDigest")}
            for row in rows
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(provisional, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    observer_receipt: dict[str, Any] | None = None
    if observer_command is None:
        blocked.append("independent-observer")
    else:
        env = os.environ.copy()
        env.update(
            {
                "HEPTA_MATRIX_REPORT": str(output),
                "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
                "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
                "HEPTA_MATRIX_PROVISIONAL_DIGEST": provisional_digest,
                "HEPTA_MATRIX_METRICS_DIGEST": metrics_digest,
            }
        )
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
                raise ValueError(
                    f"observer exited {result.returncode}: {result.stderr[-512:]}"
                )
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
            observer_receipt["receiptDigest"] = digest(
                {
                    key: value
                    for key, value in observer_receipt.items()
                    if key != "receiptDigest"
                }
            )
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
    output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return report


def validate_report(report: dict[str, Any]) -> None:
    if report.get("schema") != SCHEMA or report.get("authority") != AUTHORITY:
        raise ValueError("invalid report schema or authority posture")
    cases = report.get("cases")
    expected = {case["caseId"] for case in matrix_cases()}
    if (
        not isinstance(cases, list)
        or {case.get("caseId") for case in cases} != expected
    ):
        raise ValueError("report must contain exactly the sixteen matrix cases")
    workload = report.get("workloadDigest")
    source = report.get("sourceCommit")
    for case in cases:
        if case.get("workloadDigest") != workload:
            raise ValueError("case workload binding mismatch")
        if case.get("status") == "measured":
            metrics = validate_metrics(case.get("metrics", {}))
            if case.get("metricsDigest") != digest(metrics):
                raise ValueError("metric digest mismatch")
    if report.get("status") == "qualified":
        if any(case.get("status") != "measured" for case in cases):
            raise ValueError("qualified report contains an unmeasured case")
        observer = report.get("observer")
        if not isinstance(observer, dict) or observer.get("verified") is not True:
            raise ValueError("qualified report lacks an independent observer receipt")
        if (
            observer.get("sourceCommit") != source
            or observer.get("workloadDigest") != workload
        ):
            raise ValueError("observer binding mismatch")
        provisional = {
            key: report[key]
            for key in (
                "schema",
                "authority",
                "sourceCommit",
                "workloadDigest",
                "workloadSourceDigest",
                "host",
                "cases",
            )
        }
        if observer.get("reportDigest") != digest(provisional):
            raise ValueError("observer report digest mismatch")
        metrics_digest = digest(
            [
                {"caseId": case["caseId"], "metricsDigest": case.get("metricsDigest")}
                for case in cases
            ]
        )
        if (
            observer.get("metricsDigest") != metrics_digest
            or not isinstance(observer.get("observerId"), str)
            or not observer["observerId"].strip()
        ):
            raise ValueError("observer metrics or identity binding mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workload-command", help="argv template; {caseId} may be interpolated"
    )
    parser.add_argument("--observer-command", help="independent observer argv")
    parser.add_argument("--workload-digest", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--workload-path", type=Path, help="path to the frozen workload bytes"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-id")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_report(json.loads(args.output.read_text(encoding="utf-8")))
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
    )
    print(
        json.dumps(
            {"status": report["status"], "blockingCases": report["blockingCases"]},
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
