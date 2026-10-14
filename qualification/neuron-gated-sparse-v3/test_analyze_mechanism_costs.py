"""Untrusted fixtures for five-arm mechanism-cost parser; no efficacy claims."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import analyze_mechanism_costs as audit
import run_shadow_probe_matrix as probe


DIGEST = hashlib.sha256(b"same recorded Q24 trace").hexdigest()


def report() -> dict:
    rows = []
    for scale in probe.SCALES:
        for arm_index, arm in enumerate(probe.ARMS):
            latency = (arm_index + 1) * 1000
            rows.append({
                "schema": probe.REPORT_SCHEMA,
                "evidence_kind": probe.EVIDENCE_KIND,
                "production_qualification": False,
                "ndu_eligible": False,
                "trained_model": False,
                "all_model_parameter_budgets_matched": False,
                "state_persistence_measured": False,
                "microbatch_and_gpu_measured": False,
                "artifact_provenance_verified": False,
                "arm": arm,
                "cells": scale,
                "trace_sha256": DIGEST,
                "logical_tick_count": scale * 8,
                "process_wall_micros": scale * 64,
                "p50_tick_nanos": latency,
                "p95_tick_nanos": latency + 500,
                "p99_tick_nanos": latency + 1000,
                "process_peak_rss_bytes": (arm_index + 1) * 1024 * 1024,
                "mechanism_tick_throughput_per_second_milli": 10_000_000 // (arm_index + 1),
                "frontier_digest": hashlib.sha256(f"{arm}:{scale}".encode()).hexdigest(),
                "warning": "synthetic unit fixture, no physical host source",
            })
    return {
        "schema": audit.SCHEMA,
        "source_evidence_kind": audit.EVIDENCE_KIND,
        "target_host_qualified": False,
        "trained_artifacts_qualified": False,
        "ndu_eligible": False,
        "trace_sha256": DIGEST,
        "arms": list(probe.ARMS),
        "scales": list(probe.SCALES),
        "results": rows,
        "warning": "fake CI fixture only",
    }


class MechanismCostAuditTests(unittest.TestCase):
    def test_complete_matrix_is_descriptive_never_production_authority(self) -> None:
        summary = audit.analyze(report())
        self.assertEqual(summary["total_verified_native_records"], 20)
        self.assertEqual(summary["events_per_cell"], 8)
        self.assertEqual(len(summary["comparisons"]), 4)
        self.assertEqual(summary["comparisons"][0]["arms"][0]["p99_ratio_to_v1"], "1.000000")
        self.assertEqual(summary["comparisons"][0]["arms"][4]["p99_ratio_to_v1"], "3.000000")
        self.assertFalse(summary["qualified_p99_sla"])
        self.assertFalse(summary["verified_real_training"])
        self.assertFalse(summary["ndu_eligible"])
        self.assertEqual(summary["decision"], "NO_MODEL_PROMOTION")

    def test_missing_duplicate_or_unknown_arm_reject(self) -> None:
        for change in ("missing", "duplicate", "unknown"):
            with self.subTest(change=change):
                value = report()
                if change == "missing":
                    value["results"].pop()
                elif change == "duplicate":
                    value["results"][-1] = copy.deepcopy(value["results"][0])
                else:
                    value["results"][0]["arm"] = "invented"
                with self.assertRaises(ValueError):
                    audit.analyze(value)

    def test_mixed_event_counts_and_trace_hash_reject(self) -> None:
        for name, changed in [
            ("bad_event_count", lambda v: v["results"][1].update(logical_tick_count=65)),
            ("mixed_event_count", lambda v: v["results"][1].update(logical_tick_count=128 * 16)),
            ("mixed_digest", lambda v: v["results"][1].update(trace_sha256="e" * 64)),
        ]:
            with self.subTest(case=name):
                value = report()
                changed(value)
                with self.assertRaises(ValueError):
                    audit.analyze(value)

    def test_authority_escalation_and_fake_budget_parity_reject(self) -> None:
        for where, key in [
            ("root", "target_host_qualified"),
            ("root", "ndu_eligible"),
            ("sample", "trained_model"),
            ("sample", "all_model_parameter_budgets_matched"),
            ("sample", "production_qualification"),
        ]:
            with self.subTest(field=key):
                value = report()
                obj = value if where == "root" else value["results"][0]
                obj[key] = True
                with self.assertRaises(ValueError):
                    audit.analyze(value)

    def test_zero_and_inverted_measured_costs_reject(self) -> None:
        for field, invalid in [
            ("process_wall_micros", 0),
            ("mechanism_tick_throughput_per_second_milli", 0),
            ("p99_tick_nanos", 0),
            ("p95_tick_nanos", 50_000),
            ("process_peak_rss_bytes", False),
        ]:
            with self.subTest(field=field):
                value = report()
                value["results"][0][field] = invalid
                with self.assertRaises(ValueError):
                    audit.analyze(value)

    def test_different_required_arm_or_scale_order_rejects(self) -> None:
        for key in ("arms", "scales"):
            value = report()
            value[key].reverse()
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError, "arms or scales"):
                    audit.analyze(value)

    def test_invalid_ratios_are_not_represented_as_measurements(self) -> None:
        for a, b in [(0, 1), (1, 0), (float("nan"), 3), (1, float("inf"))]:
            with self.subTest(numerator=a, denominator=b):
                with self.assertRaises(ValueError):
                    audit.ratio(a, b)

    def test_duplicate_json_key_parser_rejects_before_aggregation(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            json.loads('{"arms":[],"arms":["v1"]}', object_pairs_hook=audit.no_duplicates)


if __name__ == "__main__":
    unittest.main()
