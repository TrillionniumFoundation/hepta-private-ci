#!/usr/bin/env python3
"""Check actual retention measurements without manufacturing host acceptance."""

import argparse
import copy
import json
from pathlib import Path
import sys
import unittest

from platform_wire_performance_gate import integer, p99, read_json

SCHEMA = "hepta.platform-wire.retention-profile.v1"
CASES = {(feed, pattern, policy) for feed in (4096, 65536)
         for pattern in ("small", "large", "alternating")
         for policy in ("default", "none", "large")}
NONCLAIMS = (
    "authenticated_network_ingress", "allocator_calls_measured", "host_rss_measured",
    "transport_queue_wait_measured", "five_path_grpc_qualified", "independent_acceptance",
    "activation", "release",
)


def validate(report, iterations=64):
    integer(iterations, "iterations", 16)
    if iterations > 1024 or iterations % 2:
        raise ValueError("iterations must be even and in 16..1024")
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("wrong retention profile schema")
    if report.get("profile") != "release":
        raise ValueError("retention measurements require a release build")
    if any(report.get(field) is not False for field in NONCLAIMS):
        raise ValueError("unmeasured production or allocation claim")
    rows = report.get("scenarios")
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise ValueError("all eighteen measured scenarios required")
    seen, summaries = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid scenario")
        feed = integer(row.get("max_feed_bytes"), "max_feed_bytes")
        pattern, policy = row.get("pattern"), row.get("retention")
        if not isinstance(pattern, str) or not isinstance(policy, str):
            raise ValueError("invalid scenario labels")
        case = feed, pattern, policy
        if case not in CASES or case in seen:
            raise ValueError("unknown or duplicate scenario")
        seen.add(case)
        count = integer(row.get("iterations"), "iterations", 16)
        if count != iterations or integer(row.get("delivered_frames"), "frames") != count:
            raise ValueError("lost, duplicated or unexpected sample count")
        if integer(row.get("chunk_bytes"), "chunk_bytes") != 32768:
            raise ValueError("transport fragment workload drift")
        expected_payload = count * {"small": 128, "large": 131072,
                                    "alternating": (128 + 131072) // 2}[pattern]
        if integer(row.get("delivered_payload_bytes"), "payload bytes") != expected_payload:
            raise ValueError("payload workload drift")
        wire = integer(row.get("wire_bytes"), "wire bytes", expected_payload + count)
        maximum = integer(row.get("maximum_record_bytes"), "maximum record")
        ceiling = integer(row.get("record_ceiling_bytes"), "record ceiling", maximum)
        # These examples use the protocol's 1 MiB payload ceiling, not a supplied
        # arbitrary heap limit. Allow only bounded framing metadata above it.
        if not 1048576 <= ceiling <= 1048576 + 1024:
            raise ValueError("record ceiling outside the managed protocol envelope")
        if maximum > wire or maximum <= (128 if pattern == "small" else 131072):
            raise ValueError("invalid maximum record accounting")
        expected_limit = {"default": min(feed, ceiling), "none": 0, "large": ceiling}[policy]
        limit = integer(row.get("idle_limit_bytes"), "idle limit", 0)
        if limit != expected_limit:
            raise ValueError("retention policy drift")
        calls = integer(row.get("feed_calls"), "feed calls", count * 2)
        yields = integer(row.get("budget_yields"), "yields", 0)
        if yields > calls or calls > wire:
            raise ValueError("unbounded or inconsistent progress")
        if feed == 4096 and pattern != "small" and yields == 0:
            raise ValueError("small-budget large records never yielded")
        capacity = integer(row.get("observed_capacity_peak_bytes"), "capacity")
        buffered = integer(row.get("observed_buffered_peak_bytes"), "buffered")
        if buffered > capacity or capacity > 2 * maximum:
            raise ValueError("unbounded observed staging capacity")
        if integer(row.get("peak_returned_frames"), "returned frames") != 1:
            raise ValueError("consumer did not drain one-record batches")
        idle = row.get("idle_capacity_bytes")
        latency = row.get("decode_and_delivery_latency_ns")
        if not isinstance(idle, list) or not isinstance(latency, list):
            raise ValueError("raw per-record observations missing")
        if len(idle) != count or len(latency) != count:
            raise ValueError("raw observation count drift")
        for index, (held, elapsed) in enumerate(zip(idle, latency)):
            integer(held, "idle capacity", 0)
            integer(elapsed, "latency")
            if held > limit or held > capacity:
                raise ValueError("idle retention exceeds its bound")
            is_large = pattern == "large" or (pattern == "alternating" and index % 2 == 1)
            if (policy == "none" or (policy == "default" and is_large)) and held != 0:
                raise ValueError("completed large buffer was not reclaimed")
            if policy == "large" and held == 0:
                raise ValueError("explicit reusable-buffer workload was not retained")
        if integer(row.get("pressure_released_capacity_bytes"), "pressure release", 0) != idle[-1]:
            raise ValueError("pressure release did not account for the retained capacity")
        if integer(row.get("capacity_after_pressure_bytes"), "post-pressure capacity", 0) != 0:
            raise ValueError("pressure did not release empty staging")
        summaries.append({"max_feed_bytes": feed, "pattern": pattern, "retention": policy,
                          "sample_count": count, "p99_ns": p99(latency),
                          "idle_capacity_peak_bytes": max(idle),
                          "observed_capacity_peak_bytes": capacity})
    return summaries


def fixture(iterations=64):
    """Synthetic validator input only. Never output this as measured evidence."""
    rows = []
    for feed, pattern, policy in sorted(CASES):
        sizes = [128 if pattern == "small" or (pattern == "alternating" and i % 2 == 0)
                 else 131072 for i in range(iterations)]
        maximum = max(sizes) + 192
        capacity = maximum
        limit = {"default": feed, "none": 0, "large": 1048912}[policy]
        held = 0
        idle = []
        for size in sizes:
            held = max(held, size + 192)
            if held > limit:
                held = 0
            idle.append(held)
        rows.append(dict(
            max_feed_bytes=feed, pattern=pattern, retention=policy, iterations=iterations,
            chunk_bytes=32768, delivered_frames=iterations, delivered_payload_bytes=sum(sizes),
            wire_bytes=sum(sizes) + 192 * iterations, maximum_record_bytes=maximum,
            record_ceiling_bytes=1048912, idle_limit_bytes=limit,
            feed_calls=iterations * 40, budget_yields=iterations,
            observed_capacity_peak_bytes=capacity, observed_buffered_peak_bytes=1,
            peak_returned_frames=1, idle_capacity_bytes=idle,
            pressure_released_capacity_bytes=idle[-1], capacity_after_pressure_bytes=0,
            decode_and_delivery_latency_ns=[1000] * iterations,
        ))
    return dict(schema=SCHEMA, profile="release", scenarios=rows,
                **{field: False for field in NONCLAIMS})


class RetentionContractTests(unittest.TestCase):
    report = None
    iterations = 64

    def checked(self, change=None):
        report = copy.deepcopy(self.report)
        if change:
            change(report)
        return validate(report, self.iterations)

    def test_actual_or_synthetic_baseline(self):
        self.assertEqual(len(self.checked()), 18)

    def test_missing_duplicate_or_foreign_scenarios(self):
        changes = [lambda r: r["scenarios"].pop(),
                   lambda r: r["scenarios"].__setitem__(1, r["scenarios"][0]),
                   lambda r: r["scenarios"][0].__setitem__("pattern", "other")]
        for change in changes:
            with self.assertRaises(ValueError):
                self.checked(change)

    def test_unmeasured_claims_reject(self):
        for field in NONCLAIMS:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.checked(lambda r: r.__setitem__(field, True))

    def test_sample_and_delivery_drift_reject(self):
        for field in ("iterations", "delivered_frames", "delivered_payload_bytes"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.checked(lambda r: r["scenarios"][0].__setitem__(field, 1))

    def test_policy_and_fragment_drift_reject(self):
        for field in ("idle_limit_bytes", "chunk_bytes", "max_feed_bytes"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.checked(lambda r: r["scenarios"][0].__setitem__(field, 7))

    def test_invalid_or_missing_raw_latency_reject(self):
        for bad in (True, 0, -1, 1.5, None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.checked(lambda r: r["scenarios"][0]["decode_and_delivery_latency_ns"].__setitem__(0, bad))
        with self.assertRaises(ValueError):
            self.checked(lambda r: r["scenarios"][0]["decode_and_delivery_latency_ns"].pop())

    def test_excessive_idle_capacity_rejects(self):
        with self.assertRaises(ValueError):
            self.checked(lambda r: r["scenarios"][0]["idle_capacity_bytes"].__setitem__(0, 1 << 30))

    def test_pressure_and_output_accounting_reject(self):
        for field in ("capacity_after_pressure_bytes", "pressure_released_capacity_bytes", "peak_returned_frames"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.checked(lambda r: r["scenarios"][0].__setitem__(field, 1 << 30))

    def test_unbounded_staging_rejects(self):
        with self.assertRaises(ValueError):
            self.checked(lambda r: r["scenarios"][0].__setitem__("observed_capacity_peak_bytes", 1 << 30))

    def test_debug_or_wrong_schema_rejects(self):
        for field in ("profile", "schema"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.checked(lambda r: r.__setitem__(field, "wrong"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--iterations", type=int, default=64)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    if args.self_test and (args.input or args.contract):
        parser.error("synthetic self-test cannot be combined with measured input")
    if not args.self_test and not args.input:
        parser.error("a real --input is required; no fixture fallback")
    try:
        report = fixture(args.iterations) if args.self_test else read_json(args.input, 4 * 1024 * 1024)[0]
        summaries = validate(report, args.iterations)
        if args.self_test or args.contract:
            RetentionContractTests.report = report
            RetentionContractTests.iterations = args.iterations
            result = unittest.TextTestRunner(verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(RetentionContractTests))
            return 0 if result.wasSuccessful() else 1
        print(json.dumps({"scope": "retention measurement validation only", "scenarios": summaries,
                          **{field: False for field in NONCLAIMS}}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"retention profile rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
