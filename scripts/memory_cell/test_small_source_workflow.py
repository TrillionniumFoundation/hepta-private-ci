"""Protocol regression for a bounded real small-model source-before-task run.

The real model executes only in CI; these checks assert its unchanged controls.
"""

from pathlib import Path
import unittest

import yaml


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-memory-small-source-trial.yml"
)


class SmallSourceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text())
        cls.jobs = cls.workflow["jobs"]

    def test_original_source_only_and_exact_commit_trigger(self):
        trigger = self.workflow.get("on", self.workflow.get(True))
        self.assertEqual(
            trigger["push"]["branches"],
            ["codex/memory-cell-evidence-20261008"],
        )
        self.assertIn(
            ".github/workflows/hepta-memory-small-source-trial.yml",
            trigger["push"]["paths"],
        )
        self.assertIn("workflow_dispatch", trigger)
        self.assertEqual(self.workflow["permissions"]["contents"], "read")
        self.assertEqual(self.workflow["permissions"]["actions"], "read")
        self.assertFalse(self.workflow["concurrency"]["cancel-in-progress"])
        self.assertIn("github.sha", self.workflow["concurrency"]["group"])

    def test_strict_dependencies_and_budget_but_no_qwen_effect(self):
        self.assertIn("repository-format", self.jobs)
        self.assertIn("just fmt --check --base", str(self.jobs["repository-format"]))
        reader = self.jobs["small-source-write-and-read"]
        self.assertEqual(reader["needs"], "source-contracts")
        self.assertEqual(reader["timeout-minutes"], 180)
        payload = str(reader)
        for item in (
            "torch==2.5.1",
            "test_*.py",
            "11669174727",
            "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
            "35756b456f75718cc422d8678ec7ae97790ca36ced625501d24884698fddab24",
            "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897",
            "smol-135m",
            "--loss-backend full",
            "--curriculum single_hop",
            "experience_write_trial.py write",
            "experience_write_trial.py read",
            "source_write_effects.py",
            "source-effects.json",
        ):
            with self.subTest(item=item):
                self.assertIn(item, payload)
        self.assertNotIn("supervised_positions", payload)
        self.assertNotIn("qwen-3b", payload)

    def test_write_is_committed_before_evaluation_questions(self):
        steps = self.jobs["small-source-write-and-read"]["steps"]
        names = [item.get("name", "") for item in steps]
        write = next(
            i for i, name in enumerate(names) if name.startswith("Write source")
        )
        read = next(
            i for i, name in enumerate(names) if name.startswith("Fresh process")
        )
        replay = next(
            i for i, name in enumerate(names) if name.startswith("Replay original")
        )
        self.assertLess(write, read)
        self.assertLess(read, replay)
        shell = steps[write]["run"]
        self.assertNotIn("/observations/labels.json", shell)
        self.assertNotIn("/plan", shell)
        self.assertIn("snapshot-pin.txt", shell)
        self.assertIn("source", self.workflow["name"].lower())

    def test_failure_denominator_and_independent_claims_remain_false(self):
        steps = self.jobs["small-source-write-and-read"]["steps"]
        text = str(steps)
        for item in (
            "raw-answers.jsonl",
            "small-reader-diagnostic.json",
            "production_accepted",
            "semantic_citation_precision",
            "previously_exposed_authored_tasks",
            "significance_established",
        ):
            self.assertIn(item, text)
        preservation = next(
            item
            for item in steps
            if item.get("name", "").startswith("Preserve original")
        )
        self.assertEqual(preservation.get("if"), "always()")
        artifact = next(
            item
            for item in steps
            if item.get("uses", "").startswith("actions/upload-artifact@")
        )
        self.assertEqual(artifact.get("if"), "always()")


if __name__ == "__main__":
    unittest.main()
