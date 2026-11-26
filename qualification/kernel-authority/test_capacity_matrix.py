#!/usr/bin/env python3
"""Regression tests for the strict target capacity collector."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).with_name("capacity_matrix.py")
SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_capacity_matrix",
    MODULE,
)
assert SPEC is not None and SPEC.loader is not None
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


class CapacityMatrixTests(unittest.TestCase):
    def plan(self) -> dict[str, object]:
        return MATRIX.validate_plan(
            MATRIX.plan(
                "a" * 40,
                "b" * 40,
                "target-profile",
                100,
            )
        )

    def test_exact_inventory_and_nonclaims(self) -> None:
        selected = self.plan()
        self.assertEqual(
            (
                len(selected["measurements"]),
                len(selected["faults"]),
                len(selected["hotPathDiagnostics"]),
            ),
            (55, 8, 25),
        )
        self.assertFalse(selected["productionEvidence"])
        self.assertFalse(selected["activationGranted"])
        self.assertFalse(selected["releaseGranted"])

    def test_missing_duplicate_and_boolean_samples_fail(self) -> None:
        baseline = MATRIX.plan(
            "a" * 40,
            "b" * 40,
            "target-profile",
            100,
        )
        missing = copy.deepcopy(baseline)
        missing["measurements"].pop()
        with self.assertRaises(MATRIX.Invalid):
            MATRIX.validate_plan(missing)

        duplicate = copy.deepcopy(baseline)
        duplicate["measurements"].append(
            copy.deepcopy(duplicate["measurements"][0])
        )
        with self.assertRaises(MATRIX.Invalid):
            MATRIX.validate_plan(duplicate)

        wrong = copy.deepcopy(baseline)
        wrong["samplesPerRow"] = True
        with self.assertRaises(MATRIX.Invalid):
            MATRIX.validate_plan(wrong)

    def test_synthetic_measurement_rejected_for_real_collection(self) -> None:
        selected = self.plan()
        row = selected["measurements"][0]
        raw = {
            "schema": MATRIX.SCHEMAS["measurement"],
            "schemaVersion": 1,
            "candidate": selected["candidate"],
            "profileId": selected["profileId"],
            "host": MATRIX.fake_host(),
            "synthetic": True,
            **row,
            "p50Ms": 1,
            "p95Ms": 2,
            "p99Ms": 3,
            "latencyBudgetMs": 4,
            "bytesWritten": 1,
            "fsyncP99Ms": 1,
            "peakRssBytes": 1,
        }
        with self.assertRaises(MATRIX.Invalid):
            MATRIX.validate_row(raw, "measurement", selected)

    def test_uncertain_fault_cannot_reopen_success(self) -> None:
        selected = self.plan()
        raw = {
            "schema": MATRIX.SCHEMAS["fault"],
            "schemaVersion": 1,
            "candidate": selected["candidate"],
            "profileId": selected["profileId"],
            "host": MATRIX.fake_host(),
            "synthetic": True,
            "case": "during_prune",
            "outcome": "reopen_succeeds",
            "indeterminatePreserved": True,
            "stateResetAttempted": False,
        }
        with self.assertRaises(MATRIX.Invalid):
            MATRIX.validate_row(raw, "fault", selected, True)

    def test_self_test_is_never_production_evidence(self) -> None:
        result = MATRIX.synthetic(self.plan())
        self.assertTrue(result["passed"])
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["productionEvidenceAdmissible"])
        self.assertFalse(result["productionSloGranted"])
        self.assertFalse(result["activationGranted"])
        self.assertFalse(result["releaseGranted"])


if __name__ == "__main__":
    unittest.main()
