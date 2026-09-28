"""Negative and positive tests for the Objective target-host recorder."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "objective_measure", Path(__file__).with_name("hepta-objective-target-measure.py")
)
assert SPEC is not None and SPEC.loader is not None
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


def distribution() -> dict[str, int]:
    return {"p50": 10, "p95": 20, "p99": 30}


def resources() -> dict:
    return {
        "schema": measure.RESOURCE_SCHEMA,
        "scope": "one isolated fixture command process tree",
        "peakResidentSetBytes": 4096,
        "userCpuNanoseconds": 20,
        "systemCpuNanoseconds": 10,
        "wallNanoseconds": 40,
        "minorPageFaults": 2,
        "majorPageFaults": 0,
        "voluntaryContextSwitches": 1,
        "involuntaryContextSwitches": 0,
    }


class MeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ordinary = {
            "schema": "hepta.objective-target-measurement.v1",
            "path": "ordinary_authenticated_admission_compile",
            "samples": 3,
            "latencyNanoseconds": distribution(),
            "phaseLatencyNanoseconds": {
                "coldProfileValidation": distribution(),
                "warmAuthenticatedAdmission": distribution(),
                "nativeCompile": distribution(),
                "protocolEncode": distribution(),
                "protocolDecode": distribution(),
            },
            "staticProfileReuseKey": {
                "profileDigest": "profile",
                "profileRevision": 1,
                "compilerContractDigest": "contract",
            },
            "dynamicAuthorizationCached": False,
        }
        self.product = {
            "schema": measure.PRODUCT_SCHEMA,
            "path": "signed_objective_daemon_round_trip",
            "samples": 3,
            "executionSamples": 2,
            "latencyNanoseconds": distribution(),
            "phaseLatencyNanoseconds": {
                "signedIngressCompileDurableAppendCheckpointAndAgentdHandoff": distribution(),
                "compiledPublicationAndAgentdHandoff": distribution(),
                "contextAttachment": distribution(),
                "currentFinalUseProviderAndTerminalObservation": distribution(),
            },
            "atomicOwnerBoundaryNotSplit": True,
            "executionLatencyNanoseconds": distribution(),
            "exactReplayNanoseconds": 10,
            "executionExactReplayNanoseconds": 15,
            "restartReadyNanoseconds": 60,
            "physicalProviderSends": 2,
            "terminalObservations": 2,
            "durableCheckpointSequence": 5,
        }

    def ordinary_output(self, value: object) -> str:
        return measure.PREFIX + json.dumps(value)

    def product_output(self, value: object) -> str:
        return measure.PRODUCT_PREFIX + json.dumps(value)

    def test_accepts_real_ordinary_and_product_distributions(self) -> None:
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
        self.assertEqual(
            measure.process_resource_observation(resources()), resources()
        )

    def test_rejects_non_object_json_and_duplicate_records(self) -> None:
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

    def test_rejects_boolean_fractional_negative_or_missing_counters(self) -> None:
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

    def test_rejects_missing_phase_or_authorization_boundary(self) -> None:
        value = copy.deepcopy(self.ordinary)
        del value["phaseLatencyNanoseconds"]["protocolDecode"]
        with self.assertRaises(SystemExit):
            measure.parse_measurement(self.ordinary_output(value), value["path"])

        value = copy.deepcopy(self.ordinary)
        value["dynamicAuthorizationCached"] = True
        with self.assertRaises(SystemExit):
            measure.parse_measurement(self.ordinary_output(value), value["path"])

        value = copy.deepcopy(self.product)
        value["atomicOwnerBoundaryNotSplit"] = False
        with self.assertRaises(SystemExit):
            measure.parse_product_measurement(self.product_output(value))

    def test_rejects_invalid_or_non_monotone_percentiles(self) -> None:
        for field in ("latencyNanoseconds", "executionLatencyNanoseconds"):
            for invalid in (True, 0.5, -1, None, 100):
                value = copy.deepcopy(self.product)
                value[field]["p50"] = invalid
                with (
                    self.subTest(field=field, invalid=invalid),
                    self.assertRaises(SystemExit),
                ):
                    measure.parse_product_measurement(self.product_output(value))
        value = copy.deepcopy(self.ordinary)
        value["phaseLatencyNanoseconds"]["nativeCompile"] = {
            "p50": 3,
            "p95": 2,
            "p99": 1,
        }
        with self.assertRaises(SystemExit):
            measure.parse_measurement(self.ordinary_output(value), value["path"])

    def test_conflict_measurement_must_bind_actual_maximum_work(self) -> None:
        value = {
            "schema": "hepta.objective-target-measurement.v1",
            "path": "maximum_conflict_extraction",
            "samples": 3,
            "latencyNanoseconds": distribution(),
            "constraintAtoms": 256,
            "oracleCallsPerSample": 257,
        }
        self.assertEqual(
            measure.parse_measurement(self.ordinary_output(value), value["path"]), value
        )
        for field in ("constraintAtoms", "oracleCallsPerSample"):
            bad = dict(value)
            bad[field] -= 1
            with self.subTest(field=field), self.assertRaises(SystemExit):
                measure.parse_measurement(self.ordinary_output(bad), bad["path"])

    def test_fixture_counts_and_isolated_resources_are_bound(self) -> None:
        with patch.object(
            measure,
            "run_isolated_command",
            return_value=(self.ordinary_output(self.ordinary), resources()),
        ):
            with self.assertRaises(SystemExit):
                measure.run_fixture("test", self.ordinary["path"], 4)
            measured = measure.run_fixture("test", self.ordinary["path"], 3)
            self.assertEqual(measured["fixtureProcessResources"], resources())
            self.assertEqual(measured["harnessWallNanoseconds"], 40)
        with patch.object(
            measure,
            "run_isolated_command",
            return_value=(self.product_output(self.product), resources()),
        ):
            with self.assertRaises(SystemExit):
                measure.run_product_fixture(4, 2)
            with self.assertRaises(SystemExit):
                measure.run_product_fixture(3, 3)

    def test_resource_observation_rejects_boolean_or_missing_fields(self) -> None:
        for field in (
            "peakResidentSetBytes",
            "userCpuNanoseconds",
            "systemCpuNanoseconds",
            "wallNanoseconds",
            "minorPageFaults",
            "majorPageFaults",
            "voluntaryContextSwitches",
            "involuntaryContextSwitches",
        ):
            value = resources()
            value[field] = True
            with self.subTest(field=field), self.assertRaises(SystemExit):
                measure.process_resource_observation(value)
        value = resources()
        value["wallNanoseconds"] = 0
        with self.assertRaises(SystemExit):
            measure.process_resource_observation(value)

    def test_filesystem_identity_uses_longest_mount_and_marks_memory_storage(self) -> None:
        mounts = (
            "24 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "25 24 0:32 / /tmp rw - tmpfs tmpfs rw\n"
            "26 25 8:2 / /tmp/disk rw - ext4 /dev/sdb1 rw\n"
        )
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

    def test_missing_mount_identity_never_implies_storage_qualification(self) -> None:
        value = measure.filesystem_context(Path("/tmp/fixture"), "malformed\n")
        self.assertFalse(value["mountIdentityAvailable"])
        self.assertFalse(value["storageQualificationProved"])


if __name__ == "__main__":
    unittest.main()
