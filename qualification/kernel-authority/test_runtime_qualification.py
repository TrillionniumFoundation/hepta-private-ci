#!/usr/bin/env python3
"""Negative and positive tests for candidate-bound runtime receipt validation."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

MODULE_PATH = Path(__file__).with_name("runtime_qualification.py")
SPEC = importlib.util.spec_from_file_location("kernel_authority_runtime_qualification", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def distribution(count: int = 128) -> dict[str, int]:
    return {"count": count, "minUs": 1, "meanUs": 3, "p50Us": 2, "p95Us": 4, "p99Us": 5, "maxUs": 6}


def benchmark_receipt(samples: int = 128) -> dict[str, object]:
    return {
        "schema": "hepta.kernel-authority-benchmark.v1", "schemaVersion": 1,
        "qualificationOnly": True, "productionSloGranted": False, "samples": samples,
        "state": {"snapshotBytes": 4096, "leases": samples + 1, "revocations": samples,
                  "retiredLeaseIds": 0, "reopenUs": 10},
        "operations": {"durableLeasePut": distribution(samples), "dispatchEntry": distribution(samples),
                       "durableLeaseRevoke": distribution(samples), "contendedDispatchEntry": distribution(256)},
        "contention": {"threads": 4, "iterationsPerThread": 64},
        "throughputMilliOperationsPerSecond": 1000, "totalMeasuredUs": 10000,
    }


def storage_receipt(operations: int = 512) -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema": "hepta.kernel-authority-storage-model.v2", "schemaVersion": 2,
        "qualificationOnly": True, "prototypeOnly": True, "productionImplementation": False,
        "activationGranted": False, "releaseGranted": False, "operations": operations,
        "checkpointInterval": 128,
        "externalFrontier": {"schema": "hepta.kernel-authority-storage-frontier.v1",
                             "sequence": operations, "headRecordSha256": digest,
                             "rollbackIndependent": True, "qualificationOnly": True},
        "recovered": {"discardedPartialTail": False, "externalFrontierMatched": True,
                      "headRecordSha256": digest, "sequence": operations},
        "crashRollbackAndCorruptionDrills": {
            "baselineRecovery": True, "committedRecordCorruptionRejected": True,
            "corruptedCheckpointRejected": True, "externalFrontierAheadFences": True,
            "partialTailDiscarded": True, "staleExternalFrontierRejected": True,
            "validOlderLocalSnapshotRejected": True,
        },
        "sharding": {"deterministic": True}, "capacityLifetime": {}, "passed": True,
    }


def execution_log(names) -> str:
    return "\n".join([
        *(f"test {name} ... ok" for name in names),
        f"test result: ok. {len(names)} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s",
    ])


def pilot_results(passed: set[str]) -> list[dict[str, object]]:
    result = []
    for case in RUNTIME.PILOT_CASES:
        expected = RUNTIME.EXECUTION.EXPECTED_TESTS[case.name]
        result.append({"name": case.name, "passed": case.name in passed,
                       "exitCode": 0 if case.name in passed else 1,
                       "testExecution": RUNTIME.EXECUTION.validate_output(execution_log(expected), expected)
                       if case.name in passed else None})
    return result


class RuntimeQualificationReceiptTests(unittest.TestCase):
    def write(self, root: Path, name: str, value: dict[str, object]) -> Path:
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_pilot_claims_require_the_exact_supporting_cases(self):
        all_cases = {case.name for case in RUNTIME.PILOT_CASES}
        self.assertTrue(all(RUNTIME.pilot_claims(pilot_results(all_cases)).values()))
        only_fleet = RUNTIME.pilot_claims(pilot_results({"fleet-create-restart-revoke"}))
        self.assertTrue(only_fleet["fleetPathExecuted"])
        self.assertFalse(only_fleet["restartRecoveryExercised"])
        self.assertFalse(only_fleet["revocationExercised"])
        self.assertFalse(only_fleet["browserAgentdPathExecuted"])

    def test_pilot_claims_reject_missing_and_duplicate_cases(self):
        results = pilot_results({case.name for case in RUNTIME.PILOT_CASES})
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.pilot_claims(results[:-1])
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.pilot_claims(results + [dict(results[0])])

    def test_pass_boolean_cannot_replace_execution(self):
        results = pilot_results({case.name for case in RUNTIME.PILOT_CASES})
        results[0]["testExecution"] = None
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.pilot_claims(results)

    def test_successful_exit_with_zero_tests_fails_run_case(self):
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(execution_log(()).encode())
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory, patch.object(RUNTIME.subprocess, "run", side_effect=fake_run):
            result = RUNTIME.run_case(RUNTIME.PILOT_CASES[0], Path(directory))
            self.assertEqual(result["exitCode"], 0)
            self.assertFalse(result["passed"])
            self.assertIsNotNone(result["validationError"])

    def test_run_case_binds_real_execution_and_actual_command(self):
        case = RUNTIME.PILOT_CASES[0]
        expected = RUNTIME.EXECUTION.EXPECTED_TESTS[case.name]
        def fake_run(command, **kwargs):
            self.assertNotIn("--nocapture", command)
            kwargs["stdout"].write(execution_log(expected).encode())
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory, patch.object(RUNTIME.subprocess, "run", side_effect=fake_run):
            result = RUNTIME.run_case(case, Path(directory))
            self.assertTrue(result["passed"])
            self.assertEqual(result["testExecution"]["passedCount"], 1)
            self.assertEqual(len(result["logSha256"]), 64)

    def test_benchmark_receipt_is_strict_and_rejects_slo_overclaim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = benchmark_receipt()
            RUNTIME.validate_benchmark_receipt(self.write(root, "benchmark.json", value), 128)
            value["productionSloGranted"] = True
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_benchmark_receipt(self.write(root, "benchmark-overclaim.json", value), 128)

    def test_storage_receipt_requires_external_frontier_rollback_drill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = storage_receipt()
            RUNTIME.validate_storage_model_receipt(self.write(root, "storage.json", value), 512)
            value["crashRollbackAndCorruptionDrills"]["validOlderLocalSnapshotRejected"] = False
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_storage_model_receipt(self.write(root, "storage-regressed.json", value), 512)

    def test_storage_receipt_rejects_activation_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            value = storage_receipt()
            value["activationGranted"] = True
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_storage_model_receipt(self.write(Path(directory), "storage-overclaim.json", value), 512)

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"passed":false,"passed":true}')
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.load_json_object(path, "fixture")


if __name__ == "__main__":
    unittest.main()
