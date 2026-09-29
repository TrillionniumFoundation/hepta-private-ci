#!/usr/bin/env python3
"""Offline tests for qualification evidence parsing; not native qualification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("qualify", Path(__file__).with_name("hepta-prompt-registry-qualify.py"))
qualify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualify)


class EvidenceTests(unittest.TestCase):
    def test_inventory_is_not_execution(self):
        self.assertEqual(qualify.completed_tests("tests::required: test\n0 tests, 0 benchmarks"), set())

    def test_ignored_and_failed_tests_are_not_passes(self):
        text = "test a::first ... ignored\ntest a::second ... FAILED\ntest a::third ... ok\n"
        self.assertEqual(qualify.completed_tests(text), {"a::third"})

    def test_profile_parser_ignores_noise_and_invalid_json(self):
        text = 'noise\n{"schema":"other"}\n{"bad\ntest prefix {"schema":"hepta.prompt-registry.x","count":1}\n'
        self.assertEqual(qualify.profile_rows(text), [{"schema": "hepta.prompt-registry.x", "count": 1}])

    def test_missing_profiles_fail_closed(self):
        self.assertTrue(qualify.check_measurements("operational-profiles", []))
        self.assertTrue(qualify.check_measurements("pipeline-profile", []))

    def rows(self):
        scale = [{"schema": "hepta.prompt-registry.operational-scale.v2", "logicalRecords": n,
                  "inPlaceGc": {"collectedPayloadRecords": 1, "cleanupPending": False},
                  "snapshot": {"samples": 31}, "dereference": {"samples": 31}} for n in (1000, 8000, 16384)]
        fsync = [{"schema": "hepta.prompt-registry.fsync-profile.v2", "bytes": n, "total": {"samples": 31}} for n in (4096, 65536, 1048576)]
        writers = [{"schema": "hepta.prompt-registry.writer-profile.v1", "finalLogicalRecords": n,
                    "registration": {"samples": 31}, "retirement": {"samples": 31}} for n in (1000, 8000, 16384)]
        return scale + fsync + writers

    def test_complete_bounded_profiles(self):
        self.assertEqual(qualify.check_measurements("operational-profiles", self.rows()), [])
        self.assertEqual(qualify.check_measurements("pipeline-profile", [{"schema": "hepta.prompt-registry.pipeline-profile.v1"}] * 31), [])

    def test_duplicates_or_unfinished_collection_cannot_pass(self):
        rows = self.rows()
        self.assertTrue(qualify.check_measurements("operational-profiles", rows + rows[:1]))
        rows[0]["inPlaceGc"]["cleanupPending"] = True
        self.assertTrue(qualify.check_measurements("operational-profiles", rows))

    def test_missing_sample_count_cannot_pass(self):
        rows = self.rows()
        rows[1]["snapshot"]["samples"] = 0
        self.assertTrue(qualify.check_measurements("operational-profiles", rows))


aggregate_spec = importlib.util.spec_from_file_location("aggregate", Path(__file__).with_name("hepta-prompt-registry-aggregate.py"))
summary = importlib.util.module_from_spec(aggregate_spec)
aggregate_spec.loader.exec_module(summary)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.receipts = []
        for profile, lane in sorted(summary.LANES):
            directory = self.root / (profile + "-" + lane)
            directory.mkdir()
            checks = []
            for name in sorted(summary.REQUIRED[profile]):
                log = b"actual fixture log\n"
                (directory / (name + ".log")).write_bytes(log)
                checks.append({"name": name, "state": "passed", "exitCode": 0,
                               "postconditionFailures": [], "logSha256": hashlib.sha256(log).hexdigest()})
            receipt = {
                "schema": "hepta.prompt-registry.qualification-receipt.v2",
                "profile": profile,
                "lane": lane,
                "sourceSha": "a" * 40,
                "baseSha": "b" * 40,
                "testedSha": ("a" if lane == "exact-head" else "c") * 40,
                "testedTree": "d" * 40,
                "runId": "1",
                "runAttempt": "1",
                "workflowSha": "e" * 40,
                "workflowRef": "TrillionniumFoundation/hepta-private-ci/.github/workflows/qualification.yml@refs/pull/1/merge",
                "dependencyLockSha256": "f" * 64,
                "targetTriple": "x86_64-unknown-linux-gnu",
                "runner": {"system": "test", "machine": "x86_64", "name": "runner", "os": "Linux", "arch": "X64", "environment": "github-hosted", "targetTriple": "x86_64-unknown-linux-gnu"},
                "checks": checks,
                "allRequiredChecksPassed": True,
                "sourceFiles": {"file": "0" * 64},
                "qualified": False,
                "productionReady": False,
                "productActivated": False,
                "accepted": False,
                "released": False,
            }
            receipt_path = directory / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            self.receipts.append((receipt_path, receipt))

    def run_aggregate(self):
        return summary.aggregate(self.root, "a" * 40, "b" * 40, "1", "1")

    def rewrite(self, index=0, **values):
        receipt_path, receipt = self.receipts[index]
        receipt.update(values)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_four_lane_success_is_not_acceptance(self):
        result = self.run_aggregate()
        self.assertEqual(result["schema"], "hepta.prompt-registry.qualification-summary.v2")
        self.assertTrue(result["sourceQualified"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["released"])
        self.assertEqual(len(result["receiptSha256"]), 4)
        self.assertEqual(len(result["laneArtifactContentSha256"]), 4)

    def test_missing_lane_rejected(self):
        self.receipts[0][0].unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_wrong_candidate_or_historical_attempt_rejected(self):
        self.rewrite(runAttempt="2")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_raw_log_tampering_rejected(self):
        (self.receipts[0][0].parent / "map.log").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_zero_or_skipped_check_cannot_hide_in_success_receipt(self):
        receipt_path, receipt = self.receipts[0]
        receipt["checks"][0]["state"] = "not_run"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_different_tested_tree_rejected(self):
        self.rewrite(testedTree="1" * 40)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_workflow_or_lock_mismatch_rejected(self):
        self.rewrite(index=1, workflowSha="2" * 40)
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.rewrite(index=1, workflowSha="e" * 40, dependencyLockSha256="3" * 64)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_missing_target_identity_rejected(self):
        self.rewrite(targetTriple="")
        with self.assertRaises(ValueError):
            self.run_aggregate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
