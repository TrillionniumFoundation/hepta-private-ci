"""Adversarial unit tests; all observations here are fabricated fixtures.

No fixture is a real model, hardware or native execution result.
"""

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scale_pair as pair

D = lambda char: char * 64


def manifest(arm):
    return {
        "schema": pair.RUN_SCHEMA,
        "arm": arm,
        "hardware_digest": D("1"),
        "binary_digest": D("2"),
        "dataset_digest": D("3"),
        "model_digest": D("a" if arm == "no_change" else "b"),
        "run_id": "run-original" if arm == "no_change" else "run-candidate",
        "execution_profile": {"device": "cpu", "threads": 8, "governor": "performance",
                              "warmup_policy": "recorded", "measurement_policy": "ordered"},
        "capture_kind": "native_owner_trace_unattested",
    }


def data(arm, count=64, speed=200):
    scenario = {"logical_cells": count, "active_fraction": 1.0,
                "input_repeat_fraction": 0.0, "task_similarity": "same_family"}
    workload = []
    for i in range(count):
        workload.append({"request_id": f"r-{i}", "model_digest": D("a" if arm == "no_change" else "b"),
                         "scope": "s", "generation": 1, "input_key": f"sample-{i}",
                         "family": "decision", "cell_id": i, "scenario": scenario})
    events = []
    # Eight cold requests per declared backend group. Each batch owns one
    # interval and exact member identities; no cache-hit shortcut is assumed.
    for group_start in range(0, count, 8):
        members = workload[group_start:group_start+8]
        base = 100_000 + group_start * 500
        started = base + 200
        finished = started + speed
        batch_id = f"batch-{group_start}"
        events.append({"kind": "backend_batch", "batch_id": batch_id,
                       "backend": "native_hepta", "batch_size": len(members),
                       "model_digest": members[0]["model_digest"], "scope": "s",
                       "generation": 1, "member_request_ids": [m["request_id"] for m in members],
                       "backend_started_us": started, "backend_ended_us": finished})
        for i, m in enumerate(members):
            events.append({"kind": "request", "request_id": m["request_id"],
                           "model_digest": m["model_digest"], "scope": "s", "generation": 1,
                           "path": "cold_encoder", "status": "ok", "batch_id": batch_id,
                           "enqueued_us": base + i * 10,
                           "start_us": base + 120, "end_us": finished + 30,
                           "rss_bytes": 1_048_576, "cpu_us": speed})
    events.append({"kind": "wal_fsync", "latency_us": 250})
    events.append({"kind": "restart", "recovery_ms": 12, "checksum_verified": True})
    return workload, events


def checked_scale(workload, trace):
    # Stand-in ONLY for environments that lack the current repository v2.
    # This mock deliberately does not enforce request completeness: the
    # comparator must independently reject missing members.
    return {"schema": "hepta.stem-cell-scale-observation.v2",
            "production_authorized": False, "native_worker_attested": False,
            "all_recoveries_checksums_verified": True,
            "cold_and_cached_latency": {}, "trace_report_fixture": True}


class PairTests(unittest.TestCase):
    def setup(self, size=64):
        left = data("no_change", count=size, speed=400)
        right = data("candidate", count=size, speed=100)
        return (left[0], right[0], left[1], right[1],
                manifest("no_change"), manifest("candidate"))

    def evaluate(self, *args):
        with patch.object(pair, "trace_report", checked_scale):
            return pair.compare(*args, replicates=1000)

    def test_measured_numbers_are_diagnostic_never_production_admission(self):
        result = self.evaluate(*self.setup())
        self.assertEqual(result["schema"], pair.SCHEMA)
        self.assertGreater(result["p99_e2e_gain_ms_unattested"], 0)
        self.assertEqual(result["paired_bootstrap"]["source_groups"], 64)
        self.assertGreater(result["paired_bootstrap"]["bootstrap_lcb_ms"], 0)
        for prop in ("production_authorized", "shadow_eligible",
                     "hardware_observer_authenticated", "independently_verified_native_execution",
                     "independent_ndu_or_negative_transfer_available",
                     "wal_and_crash_recovery_independently_verified"):
            self.assertIs(result[prop], False)

    def test_hardware_mismatch_rejected_without_computing_any_observations(self):
        args = list(self.setup())
        args[-1]["hardware_digest"] = D("4")
        with self.assertRaisesRegex(ValueError, "incomparable"):
            self.evaluate(*args)

    def test_frozen_worker_binary_and_dataset_mismatch_rejected(self):
        for key in ("binary_digest", "dataset_digest", "execution_profile"):
            with self.subTest(key=key):
                args = list(self.setup())
                args[-1][key] = (D("f") if key != "execution_profile"
                                  else {**args[-1][key], "threads": 16})
                with self.assertRaisesRegex(ValueError, "incomparable"):
                    self.evaluate(*args)

    def test_replay_same_run_id_is_rejected(self):
        args = list(self.setup())
        args[-1]["run_id"] = args[-2]["run_id"]
        with self.assertRaisesRegex(ValueError, "same run ID"):
            self.evaluate(*args)

    def test_silent_workload_drift_or_missing_requests_cannot_show_speedup(self):
        args = list(self.setup())
        args[1][1]["input_key"] = "other-input"
        with self.assertRaisesRegex(ValueError, "workload drift"):
            self.evaluate(*args)
        args = list(self.setup())
        args[3] = [event for event in args[3] if event.get("request_id") != "r-0"]
        with self.assertRaisesRegex(ValueError, "incomplete paired"):
            self.evaluate(*args)

    def test_failed_requests_not_inferred_away(self):
        args = list(self.setup())
        bad = next(x for x in args[3] if x["kind"] == "request")
        bad["status"] = "rejected"
        with self.assertRaisesRegex(ValueError, "failed or rejected"):
            self.evaluate(*args)

    def test_untrusted_observer_cannot_advertise_production_attestation(self):
        args = self.setup()
        def lie(*_):
            report = checked_scale(*_)
            report["native_worker_attested"] = True
            return report
        with patch.object(pair, "trace_report", lie):
            with self.assertRaisesRegex(ValueError, "authority escalation"):
                pair.compare(*args, replicates=1000)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "in.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                pair._read_json(path)

    def test_host_manifest_has_bounded_utf8_and_no_nan(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "in.json"
            path.write_bytes(b"{" + b" " * (64 * 1024) + b"}")
            with self.assertRaisesRegex(ValueError, "oversized"):
                pair._read_json(path)
            path.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                pair._read_json(path)
            path.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                pair._read_json(path)

    def test_insufficient_independent_input_groups_never_has_ci(self):
        args = list(self.setup())
        for workload in (args[0], args[1]):
            for item in workload:
                item["input_key"] = "one-shared-input"
        result = self.evaluate(*args)
        self.assertFalse(result["paired_bootstrap"]["reliable_paired_ci_available"])
        self.assertIsNone(result["paired_bootstrap"]["bootstrap_lcb_ms"])

    def test_mismatched_source_model_not_accepted(self):
        args = list(self.setup())
        args[1][0]["model_digest"] = D("d")
        with self.assertRaisesRegex(ValueError, "workload model"):
            self.evaluate(*args)

    def test_256_1024_4096_logical_cells_use_bounded_group_bootstrap(self):
        for logical_cells in (256, 1024, 4096):
            with self.subTest(logical_cells=logical_cells):
                result = self.evaluate(*self.setup(size=logical_cells))
                self.assertEqual(result["scenario"]["logical_cells"], logical_cells)
                self.assertEqual(result["paired_bootstrap"]["source_groups"], logical_cells)
                self.assertGreater(result["paired_bootstrap"]["bootstrap_lcb_ms"], 0)
                self.assertFalse(result["production_authorized"])

    def test_bootstrap_is_reproducible_with_held_out_seeds(self):
        a = self.evaluate(*self.setup())
        b = self.evaluate(*self.setup())
        self.assertEqual(a, b)

    @unittest.skipUnless(importlib.util.find_spec("scale") is not None, "requires repository scale module")
    def test_actual_native_trace_v2_parser_is_exercised_when_available(self):
        import scale
        if "hepta.stem-cell-scale-observation.v2" not in scale.trace_report.__code__.co_consts:
            # The local export may have an obsolete v1 module; the GitHub CI
            # source under qualification/stem-cell-v1 has v2 and must run this.
            self.skipTest("local export lacks native v2 validator")
        result = pair.compare(*self.setup(), replicates=1000)
        self.assertIs(result["production_authorized"], False)
        self.assertEqual(result["scenario"]["logical_cells"], 64)


if __name__ == "__main__":
    unittest.main()
