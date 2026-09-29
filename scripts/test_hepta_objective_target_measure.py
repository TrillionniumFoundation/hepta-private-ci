"""Negative and positive tests for the Objective target-host recorder."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
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
            "run_native_fixture",
            return_value=(self.ordinary_output(self.ordinary), resources(), {"test": "ordinary"}),
        ):
            with self.assertRaises(SystemExit):
                measure.run_fixture("test", self.ordinary["path"], 4)
            measured = measure.run_fixture("test", self.ordinary["path"], 3)
            self.assertEqual(measured["fixtureProcessResources"], resources())
            self.assertEqual(measured["harnessWallNanoseconds"], 40)
        with patch.object(
            measure,
            "run_native_fixture",
            return_value=(self.product_output(self.product), resources(), {"test": "product"}),
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

    def test_native_test_selection_is_exact_and_unambiguous(self) -> None:
        self.assertEqual(measure.select_exact_test("mod::work: test\nother: test", "work"), "mod::work")
        for listing in ("other: test", "a::work: test\nb::work: test", "work: benchmark"):
            with self.subTest(listing=listing), self.assertRaises(SystemExit):
                measure.select_exact_test(listing, "work")

    def test_native_artifact_identity_rejects_drift_missing_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-executable"
            path.write_bytes(b"fixture-executable-bytes-not-a-Rust-qualification")
            path.chmod(0o700)
            identity = measure.file_identity(path)
            measure.verify_native_artifacts([identity])
            path.write_bytes(b"changed")
            with self.assertRaises(SystemExit):
                measure.verify_native_artifacts([identity])
            link = Path(directory) / "substitution"
            link.symlink_to(path)
            with self.assertRaises(SystemExit):
                measure.file_identity(link)
            path.unlink()
            with self.assertRaises(SystemExit):
                measure.verify_native_artifacts([identity])

    def test_cargo_artifact_must_be_the_requested_crate_and_test_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hepta-objective/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text("// fixture\n")
            executable = root / "test-executable"
            executable.write_bytes(b"test-only artifact fixture")
            executable.chmod(0o700)
            row = {"reason": "compiler-artifact", "executable": str(executable),
                   "target": {"name": "codex_hepta_objective", "kind": ["lib"], "src_path": str(source)},
                   "profile": {"test": True}}
            with patch.object(measure, "CARGO_ROOT", root):
                selected, artifacts = measure.select_native_artifacts(json.dumps(row), "codex-hepta-objective", "codex_hepta_objective", "lib")
                self.assertEqual(selected["path"], str(executable))
                self.assertEqual(artifacts, [selected])
                for changed in ([], [row, row], [{**row, "profile": {"test": False}}]):
                    with self.subTest(changed=changed), self.assertRaises(SystemExit):
                        measure.select_native_artifacts("\n".join(map(json.dumps, changed)), "codex-hepta-objective", "codex_hepta_objective", "lib")
                row["target"]["src_path"] = str(root / "wrong-crate/lib.rs")
                with self.assertRaises(SystemExit):
                    measure.select_native_artifacts(json.dumps(row), "codex-hepta-objective", "codex_hepta_objective", "lib")

    def test_resource_sampler_executes_prebuilt_binary_not_cargo(self) -> None:
        native = {"executable": "/fixture/test", "artifacts": []}
        with patch.object(measure, "build_native_fixture", return_value=native), \
             patch.object(measure, "verify_native_artifacts") as verify, \
             patch.object(measure, "command", return_value="module::test: test\n"), \
             patch.object(measure, "run_isolated_command", return_value=("result", resources())) as run:
            output, observed, binding = measure.run_native_fixture("package", None, "test", {})
            self.assertEqual(run.call_args.args[:2], ("/fixture/test", "module::test"))
            self.assertNotIn("cargo", run.call_args.args)
            self.assertIn("--exact", run.call_args.args)
            self.assertEqual(verify.call_count, 3)
            self.assertEqual((output, observed), ("result", resources()))
            self.assertTrue(binding["artifactsUnchangedAfterExecution"])
            self.assertEqual(binding["exitCode"], 0)

    def test_filesystem_identity_uses_longest_mount_and_marks_memory_storage(self) -> None:
        # Keep this synthetic mount namespace independent of host aliases such as
        # macOS /tmp -> /private/tmp while still exercising Path.resolve().
        mount_root = "/__hepta_objective_fixture__/tmp"
        mounts = (
            "24 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            f"25 24 0:32 / {mount_root} rw - tmpfs tmpfs rw\n"
            f"26 25 8:2 / {mount_root}/disk rw - ext4 /dev/sdb1 rw\n"
        )
        memory = measure.filesystem_context(Path(f"{mount_root}/fixture"), mounts)
        disk = measure.filesystem_context(Path(f"{mount_root}/disk/fixture"), mounts)
        self.assertEqual(
            (memory["filesystemType"], memory["memoryBacked"]), ("tmpfs", True)
        )
        self.assertEqual(
            (disk["mountPoint"], disk["memoryBacked"]),
            (f"{mount_root}/disk", False),
        )
        self.assertFalse(memory["storageQualificationProved"])
        self.assertFalse(disk["storageQualificationProved"])

    def test_missing_mount_identity_never_implies_storage_qualification(self) -> None:
        value = measure.filesystem_context(Path("/tmp/fixture"), "malformed\n")
        self.assertFalse(value["mountIdentityAvailable"])
        self.assertFalse(value["storageQualificationProved"])


if __name__ == "__main__":
    unittest.main()
