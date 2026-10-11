"""Keep exact-source model execution separate from the full PR style gate."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hepta-memory-write-experiment.yml"


class SourceWriteExecutionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]

    def test_required_repository_format_remains_unmodified(self):
        self.assertIn("repository-format", self.jobs)
        repository = str(self.jobs["repository-format"])
        self.assertIn("just fmt --check --base", repository)
        self.assertIn("exit \"$status\"", repository)
        self.assertIn("memory-source-write-format", repository)

    def test_actual_writer_does_not_depend_on_unrelated_pr_formatting(self):
        self.assertEqual(self.jobs["write-and-read"]["needs"], "source-contracts")
        self.assertNotIn("repository-format", str(self.jobs["write-and-read"]))
        scoped = str(self.jobs["source-contracts"])
        self.assertIn("ruff format --check", scoped)
        self.assertIn("python3 -m compileall -q scripts/memory_cell", scoped)
        self.assertIn("test_source_write_execution_gate.py", scoped)
        self.assertIn("test_source_workflow_gates.py", scoped)
        self.assertNotIn("just fmt --check", scoped)

    def test_expensive_model_still_requires_original_pins_and_full_regressions(self):
        execution = str(self.jobs["write-and-read"])
        for original in (
            "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
            "35756b456f75718cc422d8678ec7ae97790ca36ced625501d24884698fddab24",
            "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897",
            "torch==2.5.1",
            "test_*.py",
            "source_pretrained_projection_receipt.py",
            "--loss-backend supervised_positions",
            "--parity-receipt",
            "source_write_effects.py",
            "memory-source-only-write",
        ):
            with self.subTest(guard=original):
                self.assertIn(original, execution)
        self.assertEqual(self.jobs["write-and-read"]["timeout-minutes"], 330)
        self.assertEqual(self.jobs["repository-format"]["timeout-minutes"], 15)

    def test_format_job_does_not_claim_a_model_success(self):
        self.assertNotIn("write-and-read", self.jobs["repository-format"])
        self.assertNotIn("source-contracts", self.jobs["repository-format"])
        self.assertIn("fail", str(self.jobs["repository-format"]).lower())


if __name__ == "__main__":
    unittest.main()
