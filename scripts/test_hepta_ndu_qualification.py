#!/usr/bin/env python3
"""Synthetic validator tests; these fixtures are never host qualification evidence."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "ndu_qualification", Path(__file__).with_name("hepta-ndu-qualification.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ReceiptValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.json"
        self.fixture = {
            "schema": "hepta.ndu.named-host-qualification.v3",
            "sourceSha": "a" * 40,
            "sourceTree": "b" * 40,
            "lane": "source-head",
            "hostId": runner.platform.node(),
            "journal": {
                "recordCapacity": 4096,
                "liveProjectionCapacity": 2048,
                "ordinaryOverflowRejected": True,
                "fullEnvelopeRevocation": True,
                "restartRecovery": True,
            },
            "durability": {
                "restartReopen": True,
                "revocationNonResurrection": True,
                "backupRestore": True,
                "fullCapacityDiskRecovery": True,
                "oversizedImageBoundedReject": True,
                "oversizedSparseBytes": 1 << 40,
            },
            "hotPath": {
                "runs": 100,
                "candidates": 32,
                "organs": 8,
                "p50Micros": 500,
                "p95Micros": 1000,
                "p99Micros": 2000,
                "targetPass": True,
            },
        }

    def validate(self, receipt):
        self.path.write_text(json.dumps(receipt))
        return runner.validate_host_receipt(
            self.path, "a" * 40, "b" * 40, "source-head"
        )

    def test_valid_measurement_and_honest_performance_failure(self):
        self.assertTrue(self.validate(self.fixture)["performancePassed"])
        self.fixture["hotPath"].update(p99Micros=6000, targetPass=False)
        self.assertFalse(self.validate(self.fixture)["performancePassed"])

    def test_changed_source_host_lane_and_missing_observations_reject(self):
        for key, value in [
            ("sourceSha", "c" * 40),
            ("sourceTree", "d" * 40),
            ("lane", "synthetic-merge"),
            ("hostId", "other-host"),
        ]:
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.fixture)
                receipt[key] = value
                with self.assertRaises(ValueError):
                    self.validate(receipt)
        for section, key in [
            ("journal", "fullEnvelopeRevocation"),
            ("journal", "restartRecovery"),
            ("durability", "fullCapacityDiskRecovery"),
            ("durability", "oversizedImageBoundedReject"),
        ]:
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.fixture)
                receipt[section][key] = False
                with self.assertRaises(ValueError):
                    self.validate(receipt)

    def test_reduced_workload_invalid_latencies_and_false_green_reject(self):
        for change in [
            {"runs": 1},
            {"candidates": 1},
            {"organs": 1},
            {"p50Micros": -1},
            {"p95Micros": True},
            {"p50Micros": 3000},
            {"p99Micros": 6000},
        ]:
            with self.subTest(change=change):
                receipt = copy.deepcopy(self.fixture)
                receipt["hotPath"].update(change)
                with self.assertRaises(ValueError):
                    self.validate(receipt)


if __name__ == "__main__":
    unittest.main()
