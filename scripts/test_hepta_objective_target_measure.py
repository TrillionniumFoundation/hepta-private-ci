"""Negative evidence tests for the exact-source Objective measurement recorder."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "objective_measure", Path(__file__).with_name("hepta-objective-target-measure.py")
)
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.ordinary = {
            "schema": "hepta.objective-target-measurement.v1",
            "path": "ordinary_authenticated_admission_compile",
            "samples": 3,
            "latencyNanoseconds": {"p50": 10, "p95": 20, "p99": 30},
        }
        self.product = {
            "schema": measure.PRODUCT_SCHEMA,
            "path": "signed_objective_daemon_round_trip",
            "samples": 3,
            "executionSamples": 2,
            "latencyNanoseconds": {"p50": 10, "p95": 20, "p99": 30},
            "executionLatencyNanoseconds": {"p50": 30, "p95": 40, "p99": 50},
            "exactReplayNanoseconds": 10,
            "executionExactReplayNanoseconds": 15,
            "restartReadyNanoseconds": 60,
            "physicalProviderSends": 2,
            "terminalObservations": 2,
            "durableCheckpointSequence": 5,
        }

    def ordinary_output(self, value):
        return measure.PREFIX + json.dumps(value)

    def product_output(self, value):
        return measure.PRODUCT_PREFIX + json.dumps(value)

    def test_accepts_real_ordinary_and_product_distributions(self):
        self.assertEqual(
            measure.parse_measurement(
                self.ordinary_output(self.ordinary), self.ordinary["path"]
            ),
            self.ordinary,
        )
        self.assertEqual(
            measure.parse_product_measurement(self.product_output(self.product)),
            self.product,
        )

    def test_rejects_non_object_json_and_duplicate_records(self):
        for value in ([], None, True, 7):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                measure.parse_measurement(
                    self.ordinary_output(value), self.ordinary["path"]
                )
            with self.subTest(value=value), self.assertRaises(SystemExit):
                measure.parse_product_measurement(self.product_output(value))
        with self.assertRaises(SystemExit):
            measure.parse_product_measurement(
                self.product_output(self.product)
                + "\n"
                + self.product_output(self.product)
            )

    def test_rejects_boolean_fractional_negative_or_missing_counters(self):
        for field in (
            "samples",
            "executionSamples",
            "physicalProviderSends",
            "terminalObservations",
            "durableCheckpointSequence",
        ):
            for invalid in (True, False, 2.0, -1, None):
                value = copy.deepcopy(self.product)
                value[field] = invalid
                with (
                    self.subTest(field=field, invalid=invalid),
                    self.assertRaises(SystemExit),
                ):
                    measure.parse_product_measurement(self.product_output(value))
        for invalid in (True, False, 3.0, 0, -1, None):
            value = copy.deepcopy(self.ordinary)
            value["samples"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                measure.parse_measurement(
                    self.ordinary_output(value), self.ordinary["path"]
                )

    def test_rejects_invalid_or_non_monotone_percentiles(self):
        for field in ("latencyNanoseconds", "executionLatencyNanoseconds"):
            for invalid in (True, 0.5, -1, None, 100):
                value = copy.deepcopy(self.product)
                value[field]["p50"] = invalid
                with (
                    self.subTest(field=field, invalid=invalid),
                    self.assertRaises(SystemExit),
                ):
                    measure.parse_product_measurement(self.product_output(value))
        for field in (
            "exactReplayNanoseconds",
            "executionExactReplayNanoseconds",
            "restartReadyNanoseconds",
        ):
            value = copy.deepcopy(self.product)
            value[field] = True
            with self.subTest(field=field), self.assertRaises(SystemExit):
                measure.parse_product_measurement(self.product_output(value))

    def test_conflict_measurement_must_bind_actual_maximum_work(self):
        value = dict(
            self.ordinary,
            path="maximum_conflict_extraction",
            constraintAtoms=256,
            oracleCallsPerSample=257,
        )
        self.assertEqual(
            measure.parse_measurement(self.ordinary_output(value), value["path"]), value
        )
        for field in ("constraintAtoms", "oracleCallsPerSample"):
            bad = dict(value)
            bad[field] -= 1
            with self.subTest(field=field), self.assertRaises(SystemExit):
                measure.parse_measurement(self.ordinary_output(bad), bad["path"])

    def test_fixture_counts_must_equal_requested_counts(self):
        with patch.object(
            measure, "command", return_value=self.ordinary_output(self.ordinary)
        ):
            with self.assertRaises(SystemExit):
                measure.run_fixture("test", self.ordinary["path"], 4)
        with patch.object(
            measure, "command", return_value=self.product_output(self.product)
        ):
            with self.assertRaises(SystemExit):
                measure.run_product_fixture(4, 2)
            with self.assertRaises(SystemExit):
                measure.run_product_fixture(3, 3)

    def test_filesystem_identity_uses_longest_mount_and_marks_memory_storage(self):
        mounts = "24 1 8:1 / / rw - ext4 /dev/sda1 rw\n25 24 0:32 / /tmp rw - tmpfs tmpfs rw\n26 25 8:2 / /tmp/disk rw - ext4 /dev/sdb1 rw\n"
        memory = measure.filesystem_context(Path("/tmp/fixture"), mounts)
        disk = measure.filesystem_context(Path("/tmp/disk/fixture"), mounts)
        self.assertEqual(
            (memory["filesystemType"], memory["memoryBacked"]), ("tmpfs", True)
        )
        self.assertEqual(
            (disk["mountPoint"], disk["memoryBacked"]), ("/tmp/disk", False)
        )
        self.assertFalse(memory["storageQualificationProved"])
        self.assertFalse(disk["storageQualificationProved"])

    def test_missing_mount_identity_never_implies_storage_qualification(self):
        value = measure.filesystem_context(Path("/tmp/fixture"), "malformed\n")
        self.assertFalse(value["mountIdentityAvailable"])
        self.assertFalse(value["storageQualificationProved"])


if __name__ == "__main__":
    unittest.main()
