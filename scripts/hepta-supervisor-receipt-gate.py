#!/usr/bin/env python3
"""Fail closed unless a physical Supervisor host receipt satisfies the named SLOs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def latency_summary(
    value: Any,
    *,
    label: str,
    p99_limit_ms: float,
    max_limit_ms: float,
) -> dict[str, float | int]:
    require(isinstance(value, dict), f"{label} must be an object")
    samples = value.get("samples")
    p50 = value.get("p50")
    p95 = value.get("p95")
    p99 = value.get("p99")
    maximum = value.get("max")
    require(isinstance(samples, int) and samples > 0, f"{label}.samples must be positive")
    metrics = (p50, p95, p99, maximum)
    require(
        all(isinstance(metric, (int, float)) and metric >= 0 for metric in metrics),
        f"{label} latency metrics must be non-negative numbers",
    )
    require(p50 <= p95 <= p99 <= maximum, f"{label} percentiles are not monotone")
    require(p99 <= p99_limit_ms, f"{label} p99 {p99}ms exceeds {p99_limit_ms}ms")
    require(
        maximum <= max_limit_ms,
        f"{label} max {maximum}ms exceeds {max_limit_ms}ms",
    )
    return {
        "samples": samples,
        "p50": float(p50),
        "p95": float(p95),
        "p99": float(p99),
        "max": float(maximum),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--platform", choices=("linux", "darwin"), required=True)
    parser.add_argument("--instances", type=int, choices=(8, 64, 256), required=True)
    parser.add_argument("--p99-limit-ms", type=float, default=1000.0)
    parser.add_argument("--max-limit-ms", type=float, default=2000.0)
    args = parser.parse_args()

    require(args.p99_limit_ms > 0, "p99 limit must be positive")
    require(args.max_limit_ms >= args.p99_limit_ms, "max limit must cover p99")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    require(isinstance(receipt, dict), "physical host receipt must be an object")
    require(receipt.get("schema_version") == 1, "unsupported physical host receipt schema")
    require(
        receipt.get("backend") == "native_agentd_protocol_fixture",
        "unexpected physical host backend",
    )
    require(receipt.get("source_commit") == args.expected_sha, "source commit mismatch")
    require(receipt.get("source_dirty") is False, "qualification source was dirty")
    require(receipt.get("status") == "passed", "physical host qualification did not pass")
    require(receipt.get("error") is None, "physical host receipt retained an error")
    require(receipt.get("instances") == args.instances, "instance count mismatch")
    require(
        receipt.get("peak_observed_live_instances") == args.instances,
        "not every configured instance became live",
    )
    require(bool(receipt.get("supervisord_sha256")), "missing supervisord artifact digest")
    require(
        receipt.get("deployment_qualified") is False,
        "repository-hosted receipt must not self-assert deployment qualification",
    )
    require(
        receipt.get("independent_acceptance") is False,
        "repository-hosted receipt must not self-assert independent acceptance",
    )

    measured: dict[str, Any] = {}
    measured["warm_snapshot_latency_ms"] = latency_summary(
        receipt.get("warm_snapshot_latency_ms"),
        label="warm_snapshot_latency_ms",
        p99_limit_ms=args.p99_limit_ms,
        max_limit_ms=args.max_limit_ms,
    )

    checks = receipt.get("checks")
    require(isinstance(checks, list), "checks must be an array")
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for raw in checks:
        require(isinstance(raw, dict), "every check must be an object")
        kind = raw.get("kind")
        if isinstance(kind, str):
            by_kind.setdefault(kind, []).append(raw)

    waves = by_kind.get("physical_crash_wave", [])
    percents = [check.get("percent") for check in waves]
    require(all(isinstance(percent, int) for percent in percents), "crash wave percent must be an integer")
    require(sorted(percents) == [10, 50, 100], "physical crash waves must cover 10%, 50%, and 100%")
    for wave in waves:
        percent = wave["percent"]
        require(wave.get("all_replaced") is True, f"{percent}% wave did not replace every victim")
        require(
            wave.get("unrelated_pids_unchanged") is True,
            f"{percent}% wave changed an unrelated pid",
        )
        measured[f"physical_crash_wave_{percent}_snapshot_latency_ms"] = latency_summary(
            wave.get("snapshot_latency_ms"),
            label=f"physical_crash_wave_{percent}.snapshot_latency_ms",
            p99_limit_ms=args.p99_limit_ms,
            max_limit_ms=args.max_limit_ms,
        )

    required_once = {
        "fourth_crash_exhausted",
        "supervisord_sigkill_adoption",
        "filesystem_permission_failure",
        "malformed_drain_ignores_sigterm",
        "trickled_drain_ignores_sigterm",
    }
    if args.platform == "linux":
        required_once |= {"fsync_eio", "write_enospc"}
    for kind in sorted(required_once):
        require(len(by_kind.get(kind, [])) == 1, f"expected exactly one {kind} check")

    for kind in ("malformed_drain_ignores_sigterm", "trickled_drain_ignores_sigterm"):
        check = by_kind[kind][0]
        require(check.get("terminated") is True, f"{kind} did not terminate")
        measured[f"{kind}_peer_snapshot_latency_ms"] = latency_summary(
            check.get("peer_snapshot_latency_during_drain_ms"),
            label=f"{kind}.peer_snapshot_latency_during_drain_ms",
            p99_limit_ms=args.p99_limit_ms,
            max_limit_ms=args.max_limit_ms,
        )

    if args.platform == "linux":
        for kind in ("fsync_eio", "write_enospc"):
            check = by_kind[kind][0]
            require(check.get("trigger_observed") is True, f"{kind} injection did not trigger")
            require(
                check.get("no_unwitnessed_replacement") is True,
                f"{kind} allowed an unwitnessed replacement",
            )

    unmeasured = receipt.get("unmeasured_faults")
    require(isinstance(unmeasured, list), "unmeasured_faults must be an array")
    unmeasured_set = set(unmeasured)
    require("hardware power loss" in unmeasured_set, "hardware power loss must remain external")
    if args.platform == "linux":
        require("fsync EIO" not in unmeasured_set, "Linux fsync EIO was not measured")
        require("ENOSPC" not in unmeasured_set, "Linux ENOSPC was not measured")
    else:
        require("fsync EIO" in unmeasured_set, "macOS receipt must disclose unmeasured fsync EIO")
        require("ENOSPC" in unmeasured_set, "macOS receipt must disclose unmeasured ENOSPC")

    summary = {
        "schema_version": 1,
        "status": "passed",
        "source_commit": args.expected_sha,
        "platform": args.platform,
        "instances": args.instances,
        "p99_limit_ms": args.p99_limit_ms,
        "max_limit_ms": args.max_limit_ms,
        "measured_latency": measured,
        "unmeasured_faults": unmeasured,
        "deployment_qualified": False,
        "independent_acceptance": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"supervisor receipt gate failed: {error}", file=sys.stderr)
        sys.exit(1)
