#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

REQUIRED_SCENARIOS = {
    "healthy_256",
    "crash_wave_10_percent",
    "crash_wave_50_percent",
    "crash_wave_100_percent",
    "slow_driver",
    "slow_filesystem",
    "concurrent_drain_status_mutation",
    "supervisord_sigkill",
    "fsync_failure",
    "rename_failure",
    "disk_full",
    "lease_corruption",
    "restart_journal_corruption",
    "intent_journal_corruption",
    "signer_rotation",
    "revocation_propagation",
    "wrong_grant",
    "stale_grant",
    "authority_epoch_rollover",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(receipt: dict) -> None:
    require(receipt.get("schema") == "hepta.runtime-supervisor-qualification.v1", "schema")
    for field in ("source_commit", "binary_sha256", "host", "lock_metrics", "scenarios"):
        require(field in receipt, f"missing {field}")
    value = receipt["binary_sha256"]
    require(
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value),
        "binary_sha256",
    )
    host = receipt["host"]
    require(
        isinstance(host, dict)
        and all(key in host for key in ("identity", "os", "kernel", "runtime")),
        "host identity",
    )
    metrics = receipt["lock_metrics"]
    require(
        isinstance(metrics, dict)
        and all(key in metrics for key in ("tick", "read", "mutation")),
        "lock metrics classes",
    )
    for lock_class in ("tick", "read", "mutation"):
        item = metrics[lock_class]
        require(
            isinstance(item, dict)
            and all(
                key in item
                for key in (
                    "wait_p50_nanos",
                    "wait_p95_nanos",
                    "wait_p99_nanos",
                    "wait_max_nanos",
                    "hold_p50_nanos",
                    "hold_p95_nanos",
                    "hold_p99_nanos",
                    "hold_max_nanos",
                )
            ),
            f"{lock_class} metrics",
        )
    scenarios = receipt["scenarios"]
    require(isinstance(scenarios, list), "scenarios list")
    by_name = {item.get("name"): item for item in scenarios if isinstance(item, dict)}
    require(set(by_name) == REQUIRED_SCENARIOS, "scenario set")
    for name, item in by_name.items():
        require(item.get("passed") is True, f"{name} did not pass")
        require(isinstance(item.get("elapsed_millis"), int), f"{name} elapsed")
        require(isinstance(item.get("evidence"), dict) and item["evidence"], f"{name} evidence")
        require(
            isinstance(item.get("final_operator_outcome"), str)
            and item["final_operator_outcome"],
            f"{name} outcome",
        )


def self_test() -> None:
    scenario = {
        "passed": True,
        "elapsed_millis": 1,
        "evidence": {"receipt_sha256": hashlib.sha256(b"evidence").hexdigest()},
        "final_operator_outcome": "bounded test outcome",
    }
    receipt = {
        "schema": "hepta.runtime-supervisor-qualification.v1",
        "source_commit": "0" * 40,
        "binary_sha256": "a" * 64,
        "host": {
            "identity": "self-test",
            "os": "test",
            "kernel": "test",
            "runtime": "test",
        },
        "lock_metrics": {
            lock_class: {
                "wait_p50_nanos": 0,
                "wait_p95_nanos": 0,
                "wait_p99_nanos": 0,
                "wait_max_nanos": 0,
                "hold_p50_nanos": 0,
                "hold_p95_nanos": 0,
                "hold_p99_nanos": 0,
                "hold_max_nanos": 0,
            }
            for lock_class in ("tick", "read", "mutation")
        },
        "scenarios": [{"name": name, **scenario} for name in sorted(REQUIRED_SCENARIOS)],
    }
    verify(receipt)
    receipt["scenarios"][0]["passed"] = False
    try:
        verify(receipt)
    except ValueError:
        return
    raise AssertionError("negative self-test unexpectedly passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.receipt:
        parser.error("receipt is required unless --self-test is used")
    receipt = json.loads(pathlib.Path(args.receipt).read_text(encoding="utf-8"))
    verify(receipt)


if __name__ == "__main__":
    main()
