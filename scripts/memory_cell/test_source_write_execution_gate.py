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
        self.assertIn('exit "$status"', repository)
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
        self.assertIn('exit "$status"', str(self.jobs["repository-format"]))

    def test_actual_seven_arm_census_precedes_exploratory_model_probes(self):
        steps = self.jobs["write-and-read"]["steps"]
        names = [step.get("name", "") for step in steps]

        def position(prefix):
            positions = [i for i, name in enumerate(names) if name.startswith(prefix)]
            self.assertEqual(len(positions), 1, prefix)
            return positions[0]

        task = position("New process reloads both committed modules")
        effects = position("Recompute seven-arm knowledge and policy effects")
        self.assertLess(task, effects)
        self.assertLess(position("Train a small read policy"), task)
        self.assertLess(position("Write observed source facts"), task)

        probe_positions = []
        for ident in ("kway", "recall", "decode", "likelihood", "confusion"):
            indices = [i for i, step in enumerate(steps) if step.get("id") == ident]
            self.assertEqual(len(indices), 1, ident)
            step = steps[indices[0]]
            self.assertGreater(indices[0], effects)
            probe_positions.append(indices[0])
            self.assertIs(step.get("continue-on-error"), True)
            # The separate diagnostic commands must remain blind to the task
            # plan and task output, even though they run after the task census.
            self.assertNotIn("/tmp/experience-input/plan", step["run"])
            self.assertNotIn("/tmp/experience-result/tasks", step["run"])
            self.assertIn(
                "/tmp/experience-input/observations/sources.json", step["run"]
            )

        recorded = position("Persist optional diagnostic outcomes")
        artifact = next(
            i
            for i, step in enumerate(steps)
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        final = position("Enforce full regression and every optional diagnostic")
        self.assertGreater(recorded, max(probe_positions))
        self.assertLess(recorded, artifact)
        self.assertLess(artifact, final)
        self.assertEqual(steps[recorded].get("if"), "always()")
        self.assertEqual(steps[final].get("if"), "always()")
        self.assertIn("full-regression-exit-code.txt", steps[final]["run"])
        self.assertIn("diagnostic-outcomes.json", steps[final]["run"])
        self.assertIn("exit 1", steps[final]["run"])


if __name__ == "__main__":
    unittest.main()
