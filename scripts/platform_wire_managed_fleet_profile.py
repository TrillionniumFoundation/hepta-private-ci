#!/usr/bin/env python3
"""Validate measured managed-wire fleet results without issuing acceptance."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

SCHEMA = "hepta.platform-wire.managed-fleet-profile.v1"
SCENARIOS = {(peers, payload) for peers in (4, 16, 32) for payload in (64, 4096)}
NONCLAIMS = (
    "independent_acceptance",
    "authenticated_network_ingress",
    "target_host_measured",
    "allocator_calls_measured",
    "transport_queue_wait_measured",
    "multi_process_pressure_measured",
)


def integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def validate(report: Any, rounds: int = 32) -> None:
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("wrong managed fleet profile schema")
    if report.get("profile") != "release":
        raise ValueError("managed fleet qualification requires a release build")
    if any(report.get(field) is not False for field in NONCLAIMS):
        raise ValueError("fleet measurement must not claim unmeasured host or acceptance facts")
    rows = report.get("scenarios")
    if not isinstance(rows, list) or len(rows) != len(SCENARIOS):
        raise ValueError("exactly six measured fleet scenarios are required")
    seen: set[tuple[int, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("fleet scenario must be an object")
        peers = integer(row.get("peer_count"), "peer_count", 1)
        payload = integer(row.get("base_payload_bytes"), "base_payload_bytes", 1)
        scenario = (peers, payload)
        if scenario not in SCENARIOS or scenario in seen:
            raise ValueError("unexpected or duplicate fleet scenario")
        seen.add(scenario)
        count = integer(row.get("rounds"), "rounds", 8)
        if count != rounds:
            raise ValueError("fleet round count differs from the requested workload")
        if integer(row.get("payload_stride_bytes"), "payload_stride_bytes", 1) != 17:
            raise ValueError("fleet payload stride changed")
        if integer(row.get("max_feed_bytes"), "max_feed_bytes", 1) != 64:
            raise ValueError("fleet byte budget changed")
        if integer(row.get("max_records_per_feed"), "max_records_per_feed", 1) != 1:
            raise ValueError("fleet record budget changed")
        delivered = integer(row.get("delivered_frames"), "delivered_frames", 1)
        if delivered != peers * count:
            raise ValueError("fleet measurement lost or duplicated frames")
        calls = integer(row.get("feed_calls"), "feed_calls", delivered)
        yields = integer(row.get("budget_yields"), "budget_yields", 1)
        if yields > calls:
            raise ValueError("fleet yield accounting exceeds feed calls")
        wire_bytes = integer(row.get("wire_bytes_per_round_max"), "wire bytes", 1)
        capacity = integer(
            row.get("aggregate_record_buffer_capacity_peak_bytes"),
            "aggregate peak capacity",
            1,
        )
        buffered = integer(
            row.get("aggregate_record_buffered_peak_bytes"),
            "aggregate peak buffered bytes",
            1,
        )
        retained_capacity = integer(
            row.get("aggregate_record_buffer_capacity_after_workload_peak_bytes"),
            "aggregate retained capacity",
        )
        retained_buffered = integer(
            row.get("aggregate_record_buffered_after_workload_peak_bytes"),
            "aggregate retained buffered bytes",
        )
        after_retire = integer(
            row.get("aggregate_record_buffer_capacity_after_retire_bytes"),
            "aggregate capacity after retire",
        )
        if buffered > capacity or capacity > 2 * wire_bytes:
            raise ValueError(
                "fleet record-buffer accounting exceeds the allocator-tolerant wire bound"
            )
        if retained_capacity > capacity or retained_buffered != 0 or after_retire != 0:
            raise ValueError("fleet post-workload or retirement accounting is inconsistent")
        first = integer(
            row.get("scheduler_turns_to_first_completion_max"),
            "first completion turn",
            1,
        )
        last = integer(
            row.get("scheduler_turns_to_last_completion_max"),
            "last completion turn",
            first,
        )
        gap = integer(row.get("scheduler_fairness_gap_turns_max"), "fairness gap", 1)
        if gap != last - first:
            raise ValueError("fleet fairness-gap accounting is inconsistent")
        timing = row.get("round_elapsed")
        if not isinstance(timing, dict):
            raise ValueError("missing fleet timing stage")
        percentiles = [
            integer(timing.get(f"p{percent}_ns"), f"round_elapsed.p{percent}", 1)
            for percent in (50, 95, 99)
        ]
        if percentiles != sorted(percentiles):
            raise ValueError("fleet timing percentiles must be ordered")
    if seen != SCENARIOS:
        raise ValueError("fleet scenario coverage is incomplete")


def fixture(rounds: int = 32) -> dict[str, Any]:
    """Synthetic validator fixture; never a measurement or qualification receipt."""
    rows = []
    for peers, payload in sorted(SCENARIOS):
        wire_bytes = peers * (payload + 512)
        first = (payload + 160 + 63) // 64
        last = (payload + (peers - 1) * 17 + 160 + 63) // 64
        rows.append(
            {
                "rounds": rounds,
                "peer_count": peers,
                "base_payload_bytes": payload,
                "payload_stride_bytes": 17,
                "max_feed_bytes": 64,
                "max_records_per_feed": 1,
                "delivered_frames": rounds * peers,
                "feed_calls": rounds * peers * last,
                "budget_yields": rounds * peers * max(1, last - 1),
                "wire_bytes_per_round_max": wire_bytes,
                "aggregate_record_buffer_capacity_peak_bytes": wire_bytes // 2,
                "aggregate_record_buffered_peak_bytes": wire_bytes // 3,
                "aggregate_record_buffer_capacity_after_workload_peak_bytes": wire_bytes // 2,
                "aggregate_record_buffered_after_workload_peak_bytes": 0,
                "aggregate_record_buffer_capacity_after_retire_bytes": 0,
                "scheduler_turns_to_first_completion_max": first,
                "scheduler_turns_to_last_completion_max": last,
                "scheduler_fairness_gap_turns_max": last - first,
                "round_elapsed": {"p50_ns": 1000, "p95_ns": 1500, "p99_ns": 2000},
            }
        )
    return {
        "schema": SCHEMA,
        "profile": "release",
        "scenarios": rows,
        **{field: False for field in NONCLAIMS},
    }


class FleetProfileTests(unittest.TestCase):
    def test_valid_measurement_shape(self) -> None:
        validate(fixture())

    def test_rejects_missing_or_duplicate_scenarios(self) -> None:
        for duplicate in (False, True):
            report = fixture()
            report["scenarios"].pop()
            if duplicate:
                report["scenarios"].append(copy.deepcopy(report["scenarios"][0]))
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_unmeasured_claims(self) -> None:
        for field in NONCLAIMS:
            report = fixture()
            report[field] = True
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_wrong_rounds_and_delivery(self) -> None:
        for field, value in (("rounds", 31), ("delivered_frames", 1)):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_budget_or_progress_drift(self) -> None:
        for field, value in (
            ("max_feed_bytes", 0),
            ("max_records_per_feed", 2),
            ("budget_yields", 0),
            ("feed_calls", 1),
        ):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_unbounded_or_inconsistent_capacity(self) -> None:
        for field, value in (
            ("aggregate_record_buffer_capacity_peak_bytes", 1 << 30),
            ("aggregate_record_buffered_peak_bytes", 1 << 30),
            ("aggregate_record_buffer_capacity_after_workload_peak_bytes", 1 << 30),
            ("aggregate_record_buffered_after_workload_peak_bytes", 1),
            ("aggregate_record_buffer_capacity_after_retire_bytes", 1),
        ):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_fairness_accounting_drift(self) -> None:
        for field, value in (
            ("scheduler_turns_to_first_completion_max", 0),
            ("scheduler_turns_to_last_completion_max", 1),
            ("scheduler_fairness_gap_turns_max", 999),
        ):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_debug_profile_and_wrong_schema(self) -> None:
        for field, value in (("profile", "debug"), ("schema", "legacy")):
            report = fixture()
            report[field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_invalid_timing(self) -> None:
        for field, value in (("p50_ns", 0), ("p95_ns", True), ("p99_ns", 1)):
            report = fixture()
            report["scenarios"][0]["round_elapsed"][field] = value
            with self.assertRaises(ValueError):
                validate(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--rounds", type=int, default=32)
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(FleetProfileTests)
        )
        return 0 if result.wasSuccessful() else 1
    if args.input is None or not 8 <= args.rounds <= 256:
        parser.error("--input and rounds in 8..256 are required")
    try:
        validate(json.loads(args.input.read_text(encoding="utf-8")), args.rounds)
    except (OSError, ValueError) as error:
        print(f"managed fleet profile rejected: {error}", file=sys.stderr)
        return 1
    print("managed fleet profile validated: six measured scenarios; no host or acceptance claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
