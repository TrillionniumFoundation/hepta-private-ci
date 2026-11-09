"""Actual subprocess controls; these tiny fixtures are not research tasks."""

import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .contracts import load
from .runner import run
from .test_memory import corpus


class RunnerControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.source = self.workspace / "source.txt"
        self.source.write_text("control fixture\n")
        for args in (
            ["init", "-q"],
            ["add", "source.txt"],
            [
                "-c",
                "user.name=Control",
                "-c",
                "user.email=control@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
        ):
            subprocess.run(
                ["git", *args], cwd=self.workspace, check=True, capture_output=True
            )
        self.head, self.tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=self.workspace, text=True
        ).splitlines()
        self.bank = corpus()

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, number, *, learn, returncode=0):
        pin = hashlib.sha256(self.source.read_bytes()).hexdigest()
        step = {
            "kind": "verify",
            "argv": [
                sys.executable,
                "-c",
                f"from pathlib import Path; assert Path('source.txt').read_text() == 'control fixture\\n'; raise SystemExit({returncode})",
            ],
            "timeout_seconds": 5,
        }
        return {
            "schema": "hepta.repo-mdv.dev-task.v1",
            "task_id": "control/" + str(number),
            "lineage_group": "unit-control",
            "split": "development",
            "query": "compiler repair",
            "workspace": str(self.workspace),
            "origin": {
                "kind": "declared_development_followup",
                "evidence_sha256": "a" * 64,
            },
            "source": {
                "head": self.head,
                "tree": self.tree,
                "before_pins": {"source.txt": pin},
                "after_pins": {"source.txt": pin},
            },
            "recipes": {
                row["id"]: [copy.deepcopy(step)] for row in self.bank["documents"]
            },
            "budget": {"wall_seconds": 20, "tool_calls": 8},
            "learn_on_success": learn,
        }

    def test_verified_update_and_new_task_consume_real_checkpoint(self):
        first_path = self.root / "first"
        first = run(self.task(1, learn=True), self.bank, first_path)
        self.assertEqual(
            (first["terminal"], first["training_updates_consumed"]), ("proved", 1)
        )
        second = run(
            self.task(2, learn=False),
            self.bank,
            self.root / "second",
            state=load(first_path / "state.json"),
            state_receipt=load(first_path / "result.json"),
        )
        self.assertEqual(
            (second["terminal"], second["training_updates_consumed"]), ("proved", 0)
        )
        self.assertEqual(second["state_before_digest"], first["state_after_digest"])
        self.assertTrue(second["development_state_consumed"])
        self.assertGreater(second["ranking"][0]["learned_association"], 0)
        self.assertEqual(
            [x["returncode"] for x in second["operations"]], [0, 0, 0, 0, 0]
        )
        self.assertIsNone(second["formal_adoption_receipt"])

    def test_failed_actual_checker_does_not_update(self):
        result = run(
            self.task(1, learn=True, returncode=7), self.bank, self.root / "failed"
        )
        self.assertEqual(
            (result["terminal"], result["state_updated"]), ("refuted", False)
        )
        self.assertEqual(result["operations"][2]["returncode"], 7)
        self.assertGreater(result["costs"]["envelope_wall_seconds"], 0)

    def test_holdout_rejected_before_output_or_processes(self):
        task = self.task(1, learn=False)
        task["split"] = "confirmation"
        output = self.root / "holdout"
        with self.assertRaisesRegex(ValueError, "HOLD"):
            run(task, self.bank, output)
        self.assertFalse(output.exists())

    def test_failed_parent_cannot_release_state_to_successor(self):
        first_path = self.root / "first"
        first = run(self.task(1, learn=True), self.bank, first_path)
        first["terminal"] = "unknown"
        output = self.root / "must-not-start"
        with self.assertRaisesRegex(ValueError, "unreleased"):
            run(
                self.task(2, learn=False),
                self.bank,
                output,
                state=load(first_path / "state.json"),
                state_receipt=first,
            )
        self.assertFalse(output.exists())

    def test_wrong_source_pin_blocks_recipe(self):
        task = self.task(1, learn=True)
        task["source"]["before_pins"]["source.txt"] = "f" * 64
        result = run(task, self.bank, self.root / "wrong-source")
        self.assertEqual(result["terminal"], "unknown")
        self.assertFalse(result["state_updated"])
        self.assertEqual(
            [x["kind"] for x in result["operations"]], ["identity", "identity"]
        )


if __name__ == "__main__":
    unittest.main()
