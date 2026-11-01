"""Behavior checks against the pinned original CI receipts, with deliberate corruption."""

import copy
import hashlib
import json
from pathlib import Path
import unittest

from dependency_receipt_audit import audit


class DependencyReceiptAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent / "evidence"
        choices = [root / "ci-41259326679-1/readable/v14-routing-41259326679-1/isolation/seed-713/RESULTS.json",
                   root / "structural-admission/ci-isolation/seed-713/RESULTS.json"]
        path = next((p for p in choices if p.is_file()), None)
        if path is None:
            raise FileNotFoundError("the pinned original CI isolation report is required")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != "8d427a0495fbb2cf1f317f51908a0a27b34980f640455a455491149531d9944b":
            raise ValueError("test evidence does not match the original CI artifact")
        cls.original = json.loads(raw)

    def test_original_receipts_pass_with_exact_counts(self):
        result = audit(self.original)
        self.assertEqual(result["candidate_single_source_cuts_checked"], 10)
        self.assertEqual(result["read_receipts_checked"], {"learned": 1120, "fallback": 36, "refused": 8})

    def test_wrong_revision_is_rejected(self):
        report = copy.deepcopy(self.original)
        report["stages"][0]["traces"][0]["receipt"]["source_revision"] += 1
        with self.assertRaisesRegex(ValueError, "mismatching source cut"):
            audit(report)

    def test_mixed_fitted_dependencies_are_rejected(self):
        report = copy.deepcopy(self.original)
        report["candidates"][0]["source_cut"]["records"].append({"source_id": "project:unrelated"})
        with self.assertRaisesRegex(ValueError, "single-source"):
            audit(report)


if __name__ == "__main__":
    unittest.main()
