#!/usr/bin/env python3
"""Validate measured managed-wire results; never issue lifecycle acceptance."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

SCHEMA = "hepta.platform-wire.managed-profile.v1"
PAIRS = {(payload, chunk) for payload in (1, 64, 4096) for chunk in (1, 37, 512)}
NONCLAIMS = (
    "independent_acceptance", "authenticated_network_ingress", "host_rss_measured",
    "allocator_calls_measured", "queue_wait_measured",
)


def integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def validate(report: Any, iterations: int = 256) -> None:
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("wrong managed profile schema")
    if report.get("profile") != "release":
        raise ValueError("qualification requires an actual release build")
    if any(report.get(field) is not False for field in NONCLAIMS):
        raise ValueError("measurement must not claim unmeasured host/acceptance properties")
    rows = report.get("scenarios")
    if not isinstance(rows, list) or len(rows) != len(PAIRS):
        raise ValueError("exactly nine measured scenarios are required")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("scenario must be an object")
        payload = integer(row.get("payload_bytes"), "payload_bytes", 1)
        chunk = integer(row.get("chunk_bytes"), "chunk_bytes", 1)
        pair = (payload, chunk)
        if pair not in PAIRS or pair in seen:
            raise ValueError("unexpected or duplicate scenario")
        seen.add(pair)
        count = integer(row.get("iterations"), "iterations", 64)
        delivered = integer(row.get("delivered_frames"), "delivered_frames", 1)
        if count != iterations or delivered != count:
            raise ValueError("missing, duplicated or insufficient measured frames")
        if integer(row.get("max_feed_bytes"), "max_feed_bytes", 1) != 37 or integer(row.get("max_records_per_feed"), "max_records_per_feed", 1) != 1:
            raise ValueError("work budgets differ from the qualification profile")
        calls = integer(row.get("feed_calls"), "feed_calls", count)
        yields = integer(row.get("budget_yields"), "budget_yields")
        growths = integer(row.get("record_buffer_growth_events"), "growths", 1)
        if yields > calls or growths > calls or (chunk > 37 and yields == 0):
            raise ValueError("invalid progress, yield or capacity-growth accounting")
        wire_bytes = integer(row.get("wire_bytes"), "wire_bytes", count)
        capacity = integer(row.get("record_buffer_capacity_peak_bytes"), "capacity", 1)
        buffered = integer(row.get("record_buffer_length_observed_peak_bytes"), "buffered")
        retained_capacity = integer(
            row.get("record_buffer_capacity_after_workload_bytes"),
            "retained capacity",
        )
        retained_length = integer(
            row.get("record_buffer_length_after_workload_bytes"),
            "retained length",
        )
        if wire_bytes % count or wire_bytes // count <= payload:
            raise ValueError("wire accounting omits authenticated framing")
        if buffered > capacity or capacity > 2 * (wire_bytes // count):
            raise ValueError("record buffer capacity is inconsistent with measured input")
        if retained_capacity > capacity or retained_length != 0:
            raise ValueError("post-workload record buffer accounting is inconsistent")
        if integer(row.get("returned_payload_bytes_per_frame"), "returned payload", 1) != payload:
            raise ValueError("returned payload accounting mismatch")
        integer(row.get("decode_and_delivery_total_ns"), "decode total", 1)
        for stage in ("seal", "decode_and_delivery"):
            values = row.get(stage)
            if not isinstance(values, dict):
                raise ValueError(f"missing timing stage: {stage}")
            percentiles = [integer(values.get(f"p{p}_ns"), f"{stage}.p{p}", 1) for p in (50, 95, 99)]
            if percentiles != sorted(percentiles):
                raise ValueError("percentiles must be ordered")
    if seen != PAIRS:
        raise ValueError("scenario coverage is incomplete")


def fixture() -> dict[str, Any]:
    """Synthetic validator input, never a performance measurement or receipt."""
    rows = []
    for payload, chunk in sorted(PAIRS):
        rows.append(dict(
            payload_bytes=payload, chunk_bytes=chunk, iterations=256,
            delivered_frames=256, max_feed_bytes=37, max_records_per_feed=1,
            feed_calls=65536, budget_yields=256 if chunk > 37 else 0,
            record_buffer_growth_events=8, wire_bytes=256 * (payload + 160),
            record_buffer_capacity_peak_bytes=payload + 160,
            record_buffer_length_observed_peak_bytes=payload,
            record_buffer_capacity_after_workload_bytes=payload + 160,
            record_buffer_length_after_workload_bytes=0,
            returned_payload_bytes_per_frame=payload,
            decode_and_delivery_total_ns=256000,
            seal=dict(p50_ns=100, p95_ns=150, p99_ns=200),
            decode_and_delivery=dict(p50_ns=1000, p95_ns=1500, p99_ns=2000),
        ))
    return dict(schema=SCHEMA, profile="release", scenarios=rows,
                **{field: False for field in NONCLAIMS})


class ProfileTests(unittest.TestCase):
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

    def test_rejects_zero_bool_and_missing_frame_counts(self) -> None:
        for field in ("delivered_frames", "payload_bytes", "max_records_per_feed", "returned_payload_bytes_per_frame"):
            for value in (0, True, None):
                report = fixture()
                report["scenarios"][0][field] = value
                with self.assertRaises(ValueError):
                    validate(report)
        for count in (255, 257):
            report = fixture()
            report["scenarios"][0]["delivered_frames"] = count
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_unmeasured_acceptance_claims(self) -> None:
        for field in NONCLAIMS:
            for value in (True, None):
                report = fixture()
                report[field] = value
                with self.assertRaises(ValueError):
                    validate(report)

    def test_rejects_debug_build_and_wrong_schema(self) -> None:
        for field, value in (("profile", "debug"), ("schema", "old")):
            report = fixture()
            report[field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_invalid_timing(self) -> None:
        for field, value in (("p50_ns", 0), ("p99_ns", 1), ("p95_ns", True)):
            report = fixture()
            report["scenarios"][0]["seal"][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_missing_stage_and_unbounded_capacity(self) -> None:
        for field, value in (("seal", None), ("record_buffer_capacity_peak_bytes", 1 << 30)):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_invalid_post_workload_buffer_accounting(self) -> None:
        for field, value in (
            ("record_buffer_capacity_after_workload_bytes", 1 << 30),
            ("record_buffer_length_after_workload_bytes", 1),
            ("record_buffer_capacity_after_workload_bytes", True),
        ):
            report = fixture()
            report["scenarios"][0][field] = value
            with self.assertRaises(ValueError):
                validate(report)

    def test_rejects_missing_required_yields(self) -> None:
        report = fixture()
        for row in report["scenarios"]:
            row["budget_yields"] = 0
        with self.assertRaises(ValueError):
            validate(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--iterations", type=int, default=256)
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ProfileTests)
        )
        return 0 if result.wasSuccessful() else 1
    if args.input is None or not 64 <= args.iterations <= 4096:
        parser.error("--input and iterations in 64..4096 are required")
    try:
        validate(json.loads(args.input.read_text(encoding="utf-8")), args.iterations)
    except (OSError, ValueError) as error:
        print(f"managed profile rejected: {error}", file=sys.stderr)
        return 1
    print("managed profile validated: nine measured scenarios; no host or acceptance claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
