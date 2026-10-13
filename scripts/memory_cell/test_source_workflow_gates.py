"""Research may run while an independent repository format job remains required."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class WorkflowGateTests(unittest.TestCase):
    def test_full_qwen_parity_tracks_writer_and_exact_projection_changes(self):
        path = ROOT / ".github/workflows/hepta-memory-qwen-source-parity.yml"
        workflow = yaml.safe_load(path.read_text())
        # PyYAML 1.1 parses the YAML 'on' key as boolean True.
        trigger = workflow.get("on", workflow.get(True))
        registered = set(trigger["push"]["paths"])
        required = {
            "scripts/memory_cell/source_completion_loss.py",
            "scripts/memory_cell/source_loss_admission.py",
            "scripts/memory_cell/source_pretrained_projection_receipt.py",
            "scripts/memory_cell/experience_memory.py",
            "scripts/memory_cell/experience_inference.py",
            "scripts/memory_cell/reader_reference.py",
            "scripts/memory_cell/test_source_completion_hf.py",
        }
        self.assertTrue(required <= registered)
        self.assertEqual(
            workflow["concurrency"]["group"],
            "memory-qwen-source-parity-${{ github.sha }}",
        )
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["permissions"]["contents"], "read")
        steps = str(workflow["jobs"]["real-optimizer-parity"]["steps"])
        self.assertIn("source_pretrained_projection_receipt.py", steps)
        self.assertIn("test_source_completion_hf.py", steps)
        self.assertIn("HF_HUB_OFFLINE", steps)
        self.assertIn("test -z", steps)

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

    def test_source_writer_continues_diagnostic_only_but_retains_required_full_gate(
        self,
    ):
        path = ROOT / ".github/workflows/hepta-memory-write-experiment.yml"
        jobs = yaml.safe_load(path.read_text())["jobs"]
        self.assertIn("repository-format", jobs)
        self.assertIn("just fmt --check", str(jobs["repository-format"]))
        self.assertEqual(jobs["write-and-read"]["needs"], "source-contracts")
        steps = jobs["write-and-read"]["steps"]
        install = next(
            step
            for step in steps
            if step.get("name", "").startswith("Lock dependencies")
        )
        shell = install["run"]
        self.assertIn("test_source_*.py", shell)
        self.assertIn("test_experience_*.py", shell)
        self.assertIn("test_*.py", shell)
        self.assertIn("PIPESTATUS[0]", shell)
        self.assertIn("full-regression-exit-code.txt", shell)
        self.assertIn("set +e", shell)
        self.assertIn("set -e", shell)
        model_at = next(
            i for i, step in enumerate(steps) if "Qwen2.5-3B" in step.get("name", "")
        )
        self.assertLess(steps.index(install), model_at)
        artifact_at = next(
            i
            for i, step in enumerate(steps)
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        gate_at = next(
            i
            for i, step in enumerate(steps)
            if step.get("name", "").startswith("Enforce full regression and every optional diagnostic")
        )
        self.assertLess(model_at, artifact_at)
        self.assertLess(artifact_at, gate_at)
        self.assertEqual(steps[gate_at].get("if"), "always()")
        self.assertIn("exit 1", steps[gate_at]["run"])
        self.assertIn("full-regression-exit-code.txt", steps[gate_at]["run"])
        self.assertNotIn("|| true", steps[gate_at]["run"])


if __name__ == "__main__":
    unittest.main()
