"""Research may run while an independent repository format job remains required."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class WorkflowGateTests(unittest.TestCase):
    def test_pretrained_parity_retains_its_separate_format_gate(self):
        path = ROOT / ".github/workflows/hepta-memory-pretrained-projection.yml"
        jobs = yaml.safe_load(path.read_text())["jobs"]
        self.assertIn("repository-format", jobs)
        self.assertIn("just fmt --check", str(jobs["repository-format"]))
        self.assertEqual(
            jobs["pinned-pretrained-step"]["needs"], "qwen2-peft-contracts"
        )
        self.assertNotIn(
            "repository-format", str(jobs["qwen2-peft-contracts"].get("needs", ""))
        )
        self.assertIn("test_source_completion_qwen", str(jobs["qwen2-peft-contracts"]))
        self.assertIn("test_*.py", str(jobs["qwen2-peft-contracts"]))

    def test_source_preflight_retains_full_suite_and_independent_format_gate(self):
        path = ROOT / ".github/workflows/hepta-memory-source-preflight.yml"
        jobs = yaml.safe_load(path.read_text())["jobs"]
        self.assertIn("repository-format", jobs)
        self.assertIn("just fmt --check", str(jobs["repository-format"]))
        self.assertIn("test_*.py", str(jobs["preflight"]))
        self.assertIn("source_write_schedule.py", str(jobs["preflight"]))
        self.assertIsNone(jobs["preflight"].get("needs"))


if __name__ == "__main__":
    unittest.main()
