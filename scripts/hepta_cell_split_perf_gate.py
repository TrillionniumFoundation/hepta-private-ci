#!/usr/bin/env python3
"""Read-only, provenance-honest comparison of four Hepta CellSplit workloads.

This compares supplied measurements; it does not run models, authenticate
hardware, verify signatures, or issue production/activation authorization.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

SCOPES = (64, 256, 1024, 4096)
MODES = ("no_split", "logical_split", "optimized_logical_split", "physical_split")
INTEGER_FIELDS = frozenset((
    "attempted", "completed", "communication_bytes", "native_backend_calls",
    "native_batch_requests", "fsync_count", "failed_requests",
))
FIELDS = (
    "attempted", "completed", "elapsed_seconds", "p50_ms", "p95_ms", "p99_ms",
    "cpu_seconds", "rss_peak_bytes", "communication_bytes",
    "native_backend_calls", "native_batch_requests", "fsync_count",
    "lock_wait_ms", "recovery_ms", "failed_requests", "negative_transfer_rate",
)


class InvalidEvidence(ValueError):
    """Input does not supply an exact, comparable measurement matrix."""


def positive_number(value: Any, field: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidEvidence(f"{field}: expected numeric measurement")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise InvalidEvidence(f"{field}: non-finite or invalid measurement")
    return value


def exact_counter(value: Any, field: str, *, allow_zero: bool = True) -> int:
    # Float conversion loses integer precision above 2**53 and can falsely
    # qualify two different request/byte/fsync counts as an equal workload.
    if type(value) is not int or value < 0 or value > (2**63 - 1):
        raise InvalidEvidence(f"{field}: expected exact bounded integer")
    if not allow_zero and value == 0:
        raise InvalidEvidence(f"{field}: expected positive integer")
    return value


def analyze(packet: dict[str, Any], max_p99_regression: float = 0.0) -> dict[str, Any]:
    if packet.get("schema") != "hepta.cell-split.performance.v1":
        raise InvalidEvidence("unsupported schema")
    if not isinstance(packet.get("source_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", packet["source_sha"]):
        raise InvalidEvidence("missing exact 40-character source SHA")
    for field in ("hardware_id", "model_digest", "workload_digest"):
        if not isinstance(packet.get(field), str) or not packet[field]:
            raise InvalidEvidence(f"missing {field}")
    if not 0 <= max_p99_regression < 1:
        raise InvalidEvidence("p99 regression limit must be in [0,1)")
    raw = packet.get("runs")
    if not isinstance(raw, list) or len(raw) != len(SCOPES) * len(MODES):
        raise InvalidEvidence("requires exactly four modes at each of four scope counts")

    measurements: dict[tuple[int, str], dict[str, float]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise InvalidEvidence("each run must be an object")
        scope = entry.get("scopes")
        mode = entry.get("mode")
        if type(scope) is not int or scope not in SCOPES or mode not in MODES:
            raise InvalidEvidence("invalid mode or scope")
        key = (scope, mode)
        if key in measurements:
            raise InvalidEvidence(f"duplicate run {key}")
        vals = {
            field: (
                exact_counter(entry.get(field), f"{scope}/{mode}/{field}",
                              allow_zero=field not in ("attempted", "completed"))
                if field in INTEGER_FIELDS
                else positive_number(entry.get(field), f"{scope}/{mode}/{field}",
                                     allow_zero=field != "elapsed_seconds")
            )
            for field in FIELDS
        }
        if vals["completed"] + vals["failed_requests"] != vals["attempted"]:
            raise InvalidEvidence(f"{key}: inconsistent terminal request accounting")
        if not vals["p50_ms"] <= vals["p95_ms"] <= vals["p99_ms"]:
            raise InvalidEvidence(f"{key}: percentiles out of order")
        if vals["native_batch_requests"] > vals["completed"]:
            raise InvalidEvidence(f"{key}: impossible native batch accounting")
        if vals["native_batch_requests"] and not vals["native_backend_calls"]:
            raise InvalidEvidence(f"{key}: native batch requests without a backend call")
        if vals["native_batch_requests"] and (
            vals["native_batch_requests"] < 2 * vals["native_backend_calls"]
        ):
            raise InvalidEvidence(f"{key}: native batch density below two requests per call")
        if vals["rss_peak_bytes"] == 0:
            raise InvalidEvidence(f"{key}: missing peak resident memory measurement")
        if vals["negative_transfer_rate"] > 1:
            raise InvalidEvidence(f"{key}: negative-transfer rate is not a fraction")
        vals["throughput_rps"] = vals["completed"] / vals["elapsed_seconds"]
        vals["cpu_per_request_s"] = vals["cpu_seconds"] / vals["completed"]
        vals["communication_per_request_bytes"] = vals["communication_bytes"] / vals["completed"]
        vals["fsync_per_request"] = vals["fsync_count"] / vals["completed"]
        vals["lock_wait_per_request_ms"] = vals["lock_wait_ms"] / vals["completed"]
        vals["failure_rate"] = vals["failed_requests"] / vals["attempted"]
        vals["native_batch_requests_per_call"] = (
            vals["native_batch_requests"] / vals["native_backend_calls"]
            if vals["native_backend_calls"] else 0.0
        )
        measurements[key] = vals
    if len(measurements) != 16:
        raise InvalidEvidence("missing mode/scope combination")
    # Equal workload digests alone do not ensure that each ablation actually
    # attempted the same number of requests. Reject unmatched cohorts rather
    # than presenting their throughput as a comparable split experiment.
    for scope in SCOPES:
        attempted = {measurements[(scope, mode)]["attempted"] for mode in MODES}
        if len(attempted) != 1:
            raise InvalidEvidence(f"{scope}: unmatched attempted-request counts across modes")

    comparisons = []
    violations = []
    for scope in SCOPES:
        baseline = measurements[(scope, "no_split")]
        logical = measurements[(scope, "logical_split")]
        optimized = measurements[(scope, "optimized_logical_split")]
        physical = measurements[(scope, "physical_split")]
        physical_eligible = (
            physical["throughput_rps"] >= baseline["throughput_rps"]
            and physical["p99_ms"] <= baseline["p99_ms"] * (1 + max_p99_regression)
            and physical["rss_peak_bytes"] <= baseline["rss_peak_bytes"]
            and physical["cpu_per_request_s"] <= baseline["cpu_per_request_s"]
            and physical["communication_per_request_bytes"] <= baseline["communication_per_request_bytes"]
            and physical["fsync_per_request"] <= baseline["fsync_per_request"]
            and physical["lock_wait_per_request_ms"] <= baseline["lock_wait_per_request_ms"]
            and physical["recovery_ms"] <= baseline["recovery_ms"]
            and physical["failure_rate"] <= baseline["failure_rate"]
            and physical["negative_transfer_rate"] <= baseline["negative_transfer_rate"]
        )
        comparisons.append({
            "scopes": scope,
            "physical_split_resource_eligible": physical_eligible,
            "no_split": baseline,
            "logical_split": logical,
            "optimized_logical_split": optimized,
            "physical_split": physical,
            "optimized_throughput_ratio": optimized["throughput_rps"] / logical["throughput_rps"],
            "physical_throughput_ratio": physical["throughput_rps"] / baseline["throughput_rps"],
        })
        # Tighten against the logical-split control, not a different workload.
        if optimized["throughput_rps"] < logical["throughput_rps"]:
            violations.append(f"{scope}: optimized throughput below logical split")
        if optimized["p99_ms"] > logical["p99_ms"] * (1 + max_p99_regression):
            violations.append(f"{scope}: optimized p99 regressed")
        for key in ("cpu_per_request_s", "communication_per_request_bytes",
                    "fsync_per_request", "lock_wait_per_request_ms"):
            if optimized[key] > logical[key]:
                violations.append(f"{scope}: optimized {key} regressed")
        if optimized["rss_peak_bytes"] > logical["rss_peak_bytes"]:
            violations.append(f"{scope}: optimized peak RSS regressed")
        if optimized["recovery_ms"] > logical["recovery_ms"]:
            violations.append(f"{scope}: optimized recovery time regressed")
        if optimized["failure_rate"] > logical["failure_rate"]:
            violations.append(f"{scope}: optimized failure rate regressed")
        if optimized["negative_transfer_rate"] > logical["negative_transfer_rate"]:
            violations.append(f"{scope}: optimized negative transfer regressed")

    return {
        "schema": "hepta.cell-split.performance.comparison.v1",
        "source_sha": packet["source_sha"],
        "hardware_id": packet["hardware_id"],
        "workload_digest": packet["workload_digest"],
        "model_digest": packet["model_digest"],
        "comparative_gate_passed": not violations,
        "violations": violations,
        "comparisons": comparisons,
        # Signatures, target-host origin and future-window receipts must be
        # verified by an independently controlled production acceptance owner.
        "production_evidence_verified": False,
        "production_activation_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-p99-regression", type=float, default=0.0)
    args = parser.parse_args()
    try:
        packet = json.loads(args.input.read_text(encoding="utf-8"))
        result = analyze(packet, args.max_p99_regression)
    except (InvalidEvidence, ValueError, OSError, TypeError) as exc:
        parser.error(str(exc))
    output = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0 if result["comparative_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
