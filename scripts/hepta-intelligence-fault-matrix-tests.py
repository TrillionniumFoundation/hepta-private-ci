#!/usr/bin/env python3
"""Adversarial checks for a declaration gate, not process-loss evidence."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).with_name("hepta-intelligence-fault-matrix.py")
SPEC = importlib.util.spec_from_file_location("intelligence_fault_matrix", PATH)
assert SPEC is not None and SPEC.loader is not None
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


class FaultMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.value = MATRIX.load_json(MATRIX.MATRIX)

    def reject(self, value: dict) -> None:
        with self.assertRaises(ValueError):
            MATRIX.validate(value)

    def test_closed_world_matrix_keeps_all_evidence_pending(self) -> None:
        value = MATRIX.validate(self.value)
        self.assertEqual(len(value["cuts"]), 16)
        self.assertTrue(all(row["evidenceBindings"] == [] for row in value["cuts"]))

    def test_passed_or_wrong_head_claims_are_rejected(self) -> None:
        for key, value in (("executionStatus", "passed"), ("sourceIdentity", {})):
            with self.subTest(key=key):
                hostile = copy.deepcopy(self.value)
                hostile[key] = value
                self.reject(hostile)

    def test_cut_execution_and_fabricated_evidence_are_rejected(self) -> None:
        for key, value in (
            ("executionStatus", "passed"),
            ("evidenceBindings", ["fake-receipt"]),
        ):
            with self.subTest(key=key):
                hostile = copy.deepcopy(self.value)
                hostile["cuts"][0][key] = value
                self.reject(hostile)

    def test_duplicate_missing_or_reordered_cuts_are_rejected(self) -> None:
        variants = []
        duplicate = copy.deepcopy(self.value)
        duplicate["cuts"][-1] = copy.deepcopy(duplicate["cuts"][0])
        variants.append(duplicate)
        missing = copy.deepcopy(self.value)
        missing["cuts"].pop()
        variants.append(missing)
        reordered = copy.deepcopy(self.value)
        reordered["cuts"].reverse()
        variants.append(reordered)
        for hostile in variants:
            self.reject(hostile)

    def test_wrong_phase_disposition_or_boundary_are_rejected(self) -> None:
        for key, value in (
            ("phase", "unknown"),
            ("requiredDisposition", "Applied"),
            ("evidenceBoundary", "source exists"),
        ):
            with self.subTest(key=key):
                hostile = copy.deepcopy(self.value)
                hostile["cuts"][0][key] = value
                self.reject(hostile)

    def test_pre_provider_entry_cannot_claim_safe_redispatch(self) -> None:
        hostile = copy.deepcopy(self.value)
        row = next(
            row for row in hostile["cuts"] if row["id"] == "before_provider_entry"
        )
        row["requiredDisposition"] = "NotDispatched"
        self.reject(hostile)

    def test_wrong_schema_boolean_version_and_unknown_fields_reject(self) -> None:
        for key, value in (
            ("schema", "other"),
            ("schemaVersion", True),
            ("accepted", True),
        ):
            with self.subTest(key=key):
                hostile = copy.deepcopy(self.value)
                hostile[key] = value
                self.reject(hostile)

    def test_invariants_and_malformed_row_cannot_bypass_validation(self) -> None:
        for key, value in (("invariants", []), ("cuts", [None] * 16)):
            hostile = copy.deepcopy(self.value)
            hostile[key] = value
            self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["cuts"][0]["requiredInvariants"] = []
        self.reject(hostile)

    def test_json_duplicate_keys_and_repository_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "declaration.json"
            path.write_text('{"executionStatus":"pending","executionStatus":"passed"}')
            with mock.patch.object(MATRIX, "ROOT", root):
                with self.assertRaises(ValueError):
                    MATRIX.load_json(path)
                with self.assertRaises(ValueError):
                    MATRIX.load_json(root / ".." / "outside.json")

    def test_symlinked_and_oversized_declarations_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text("{}")
            linked = root / "linked.json"
            linked.symlink_to(source)
            oversized = root / "large.json"
            oversized.write_text(" " * (128 * 1024 + 1))
            with mock.patch.object(MATRIX, "ROOT", root):
                for path in (linked, oversized):
                    with self.assertRaises(ValueError):
                        MATRIX.load_json(path)


if __name__ == "__main__":
    unittest.main()
