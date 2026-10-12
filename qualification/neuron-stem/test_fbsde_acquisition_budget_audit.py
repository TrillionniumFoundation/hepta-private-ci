"""Read-only budget auditor regressions; no pretrained or timing assumptions."""
import json
from pathlib import Path
import tempfile
import unittest

from fbsde_acquisition_budget_audit import summarize_attempts
from four_gate_common import digest


class BudgetAuditTests(unittest.TestCase):
    def write(self, root, status, cpu):
        r = {"split": "test", "sequence": 0, "previous_sha256": None,
            "arm": "test", "id": "a", "view": 0, "text_sha256": digest("text"),
            "head_sha256": digest("head"), "status": status,
            "cpu_ns": cpu, "wall_ns": cpu, "limit_ns": 100_000_000,
            "prediction_returned": status == "returned",
            "phase_cpu_ns": {"encoder_cpu_ns": cpu}}
        path = root / "test-view-attempts.jsonl"
        path.write_text(json.dumps({**r, "attempt_sha256": digest(r)}) + "\n")
        return path

    def test_failure_retained(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.write(p, "budget_exceeded", 100_000_001)
            r = summarize_attempts(p)
            self.assertFalse(r["no_rejected_attempts_observed"])
            self.assertEqual(r["failures"][0]["dominant_measured_phase"], "encoder_cpu_ns")
            self.assertFalse(r["failures"][0]["cause_established"])

    def test_budget_inclusive_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.write(p, "returned", 100_000_000)
            r = summarize_attempts(p)
            self.assertTrue(r["no_rejected_attempts_observed"])
            self.assertFalse(r["budget_stability_established"])

    def test_rehashed_overbudget_return_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.write(p, "returned", 100_000_001)
            with self.assertRaisesRegex(ValueError, "contradiction"):
                summarize_attempts(p)

    def test_partial_journal_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            f = self.write(p, "returned", 1)
            f.write_bytes(f.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "partial"):
                summarize_attempts(p)


if __name__ == "__main__":
    unittest.main()
