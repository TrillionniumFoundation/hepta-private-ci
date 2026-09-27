#!/usr/bin/env python3
"""Negative and positive tests for candidate-bound runtime receipt validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("runtime_qualification.py")
SPEC = importlib.util.spec_from_file_location("kernel_authority_runtime_qualification", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def distribution(count: int = 128) -> dict[str, int]:
    return {
        "count": count,
        "minUs": 1,
        "meanUs": 3,
        "p50Us": 2,
        "p95Us": 4,
        "p99Us": 5,
        "maxUs": 6,
    }


def benchmark_receipt(samples: int = 128) -> dict[str, object]:
    return {
        "schema": "hepta.kernel-authority-benchmark.v1",
        "schemaVersion": 1,
        "qualificationOnly": True,
        "productionSloGranted": False,
        "samples": samples,
        "state": {
            "snapshotBytes": 4_096,
            "leases": samples + 1,
            "revocations": samples,
            "retiredLeaseIds": 0,
            "reopenUs": 10,
        },
        "operations": {
            "durableLeasePut": distribution(samples),
            "dispatchEntry": distribution(samples),
            "durableLeaseRevoke": distribution(samples),
            "contendedDispatchEntry": distribution(256),
        },
        "contention": {"threads": 4, "iterationsPerThread": 64},
        "throughputMilliOperationsPerSecond": 1_000,
        "totalMeasuredUs": 10_000,
    }


def storage_receipt(operations: int = 512) -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema": "hepta.kernel-authority-storage-model.v2",
        "schemaVersion": 2,
        "qualificationOnly": True,
        "prototypeOnly": True,
        "productionImplementation": False,
        "activationGranted": False,
        "releaseGranted": False,
        "operations": operations,
        "checkpointInterval": 128,
        "externalFrontier": {
            "schema": "hepta.kernel-authority-storage-frontier.v1",
            "sequence": operations,
            "headRecordSha256": digest,
            "rollbackIndependent": True,
            "qualificationOnly": True,
        },
        "recovered": {
            "discardedPartialTail": False,
            "externalFrontierMatched": True,
            "headRecordSha256": digest,
            "sequence": operations,
        },
        "crashRollbackAndCorruptionDrills": {
            "baselineRecovery": True,
            "committedRecordCorruptionRejected": True,
            "corruptedCheckpointRejected": True,
            "externalFrontierAheadFences": True,
            "partialTailDiscarded": True,
            "staleExternalFrontierRejected": True,
            "validOlderLocalSnapshotRejected": True,
        },
        "sharding": {"deterministic": True},
        "capacityLifetime": {},
        "passed": True,
    }


def pilot_results(passed: set[str]) -> list[dict[str, object]]:
    return [
        {"name": case.name, "passed": case.name in passed}
        for case in RUNTIME.PILOT_CASES
    ]


class RuntimeQualificationReceiptTests(unittest.TestCase):
    def write(self, root: Path, name: str, value: dict[str, object]) -> Path:
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_pilot_claims_require_the_exact_supporting_cases(self) -> None:
        all_cases = {case.name for case in RUNTIME.PILOT_CASES}
        claims = RUNTIME.pilot_claims(pilot_results(all_cases))
        self.assertTrue(all(claims.values()))

        only_fleet = RUNTIME.pilot_claims(
            pilot_results({"fleet-create-restart-revoke"})
        )
        self.assertTrue(only_fleet["fleetPathExecuted"])
        self.assertFalse(only_fleet["restartRecoveryExercised"])
        self.assertFalse(only_fleet["revocationExercised"])
        self.assertFalse(only_fleet["browserAgentdPathExecuted"])

    def test_pilot_claims_reject_missing_and_duplicate_cases(self) -> None:
        results = pilot_results({case.name for case in RUNTIME.PILOT_CASES})
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.pilot_claims(results[:-1])
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.pilot_claims(results + [dict(results[0])])

    def test_benchmark_receipt_is_strict_and_rejects_slo_overclaim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = benchmark_receipt()
            path = self.write(root, "benchmark.json", value)
            RUNTIME.validate_benchmark_receipt(path, 128)

            value["productionSloGranted"] = True
            path = self.write(root, "benchmark-overclaim.json", value)
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_benchmark_receipt(path, 128)

    def test_storage_receipt_requires_external_frontier_rollback_drill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = storage_receipt()
            path = self.write(root, "storage.json", value)
            RUNTIME.validate_storage_model_receipt(path, 512)

            drills = value["crashRollbackAndCorruptionDrills"]
            assert isinstance(drills, dict)
            drills["validOlderLocalSnapshotRejected"] = False
            path = self.write(root, "storage-regressed.json", value)
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_storage_model_receipt(path, 512)

    def test_storage_receipt_rejects_activation_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = storage_receipt()
            value["activationGranted"] = True
            path = self.write(root, "storage-overclaim.json", value)
            with self.assertRaises(RUNTIME.QualificationError):
                RUNTIME.validate_storage_model_receipt(path, 512)


if __name__ == "__main__":
    unittest.main()
