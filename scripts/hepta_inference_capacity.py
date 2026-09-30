#!/usr/bin/env python3
"""Evaluate explicit host workload assumptions; never activates a deployment.

A service-time assumption is not a measured or enforced filesystem bound.
The output is a capacity-planning calculation, not a production pass receipt.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def evaluate(profile: dict) -> dict:
    required = {"host", "peak_commands_per_second", "assumed_service_bound_ms",
                "ordinary_burst", "terminal_burst", "queue_wait_budget_ms",
                "reply_budget_ms", "shutdown_budget_ms", "maximum_utilization"}
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    if set(profile) != required or not isinstance(profile["host"], str) or not profile["host"].strip():
        raise ValueError("provide the exact host workload profile schema")
    for key in required - {"host"}:
        value = profile[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a finite positive number")
    for key in ("ordinary_burst", "terminal_burst"):
        if not isinstance(profile[key], int):
            raise ValueError(f"{key} must be an integer")
    if profile["maximum_utilization"] >= 1:
        raise ValueError("maximum_utilization must leave headroom below one")
    total = profile["ordinary_burst"] + profile["terminal_burst"]
    if total > 65536:
        raise ValueError("total queue capacity exceeds the writer's hard bound")
    utilization = profile["peak_commands_per_second"] * profile["assumed_service_bound_ms"] / 1000
    # At most total-1 queued predecessors plus one already applying command.
    wait_ms = total * profile["assumed_service_bound_ms"]
    drain_ms = (total + 1) * profile["assumed_service_bound_ms"]
    if not all(math.isfinite(value) for value in (utilization, wait_ms, drain_ms)):
        raise ValueError("capacity calculation overflowed")
    checks = {
        "utilization": utilization <= profile["maximum_utilization"],
        "queue_wait": wait_ms <= profile["queue_wait_budget_ms"],
        "reply": drain_ms <= profile["reply_budget_ms"],
        "shutdown": drain_ms <= profile["shutdown_budget_ms"],
    }
    return {
        "schema": "hepta.inference-control-capacity-planning.v1",
        "host": profile["host"], "assumptions": profile,
        "ordinary_queue_capacity": profile["ordinary_burst"],
        "terminal_queue_capacity": profile["terminal_burst"],
        "calculated_utilization": utilization,
        "conditional_queue_wait_ms": wait_ms,
        "conditional_drain_ms": drain_ms,
        "checks": checks, "assumptions_feasible": all(checks.values()),
        "production_qualified": False,
        "limitations": [
            "service bound is operator-supplied, not enforced or established by this calculator",
            "include storage, compaction and scheduler contention in service qualification",
            "provider/vault latency and external publication are separate measurements",
            "an accepted response deadline never authorizes effect replay",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    try:
        with args.profile.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("profile exceeds 64 KiB")
        report = evaluate(json.loads(raw))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"invalid capacity profile: {error}\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if not report["assumptions_feasible"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
