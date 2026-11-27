"""Real Git/subprocess controls; fixtures do not establish research benefit."""

import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .compare import ARMS, compare
from .contracts import load
from .memory import initial_state
from .runner import run


class ComparisonControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "counter.txt").write_text("0")
        for args in (
            ["init", "-q"],
            ["add", "counter.txt"],
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
                ["git", *args], cwd=self.source, check=True, capture_output=True
            )
        head, tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD", "HEAD^{tree}"],
            cwd=self.source,
            text=True,
        ).splitlines()
        self.corpus = {
            "schema": "hepta.repo-mdv.corpus.v1",
            "documents": [
                {
                    "id": name,
                    "text": "compiler repair",
                    "exposure": "development",
                    "source": {"sha256": name * 64, "reference": "control-only"},
                }
                for name in ("a", "b")
            ],
        }
        before = hashlib.sha256(b"0").hexdigest()
        self.task = {
            "schema": "hepta.repo-mdv.dev-task.v1",
            "task_id": "fixture/train",
            "lineage_group": "control-only",
            "split": "development",
            "query": "compiler repair",
            "workspace": str(self.source),
            "origin": {
                "kind": "declared_development_followup",
                "evidence_sha256": "c" * 64,
            },
            "source": {
                "head": head,
                "tree": tree,
                "before_pins": {"counter.txt": before},
                "after_pins": {"counter.txt": before},
            },
            "recipes": {
                name: [
                    {
                        "kind": "verify",
                        "argv": [sys.executable, "-c", "print('verified')"],
                        "timeout_seconds": 5,
                    }
                ]
                for name in ("a", "b")
            },
            "budget": {"wall_seconds": 20, "tool_calls": 8},
            "learn_on_success": True,
        }
        self.parent = initial_state(self.corpus)
        trained = self.root / "training"
        self.receipt = run(
            self.task,
            self.corpus,
            trained,
            policy={"kind": "fixed", "document_id": "b"},
        )
        self.assertEqual(self.receipt["terminal"], "proved")
        self.candidate = load(trained / "state.json")
        self.task["task_id"] = "fixture/successor"
        self.task["learn_on_success"] = False
        self.task["source"].update(
            after_status=" M counter.txt\n",
            after_pins={"counter.txt": hashlib.sha256(b"1").hexdigest()},
        )
        for name, steps in self.task["recipes"].items():
            steps[0]["argv"] = [
                sys.executable,
                "-c",
                "from pathlib import Path; p=Path('counter.txt'); assert p.read_text()=='0'; p.write_text('1'); print('"
                + name
                + "')",
            ]

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, *, task=None, parent=None, candidate=None, order=ARMS):
        return compare(
            task or self.task,
            self.corpus,
            self.root / "comparison",
            parent=self.parent if parent is None else parent,
            candidate=self.candidate if candidate is None else candidate,
            candidate_receipt=self.receipt,
            fixed_document="a",
            arm_order=order,
        )

    def test_four_arms_execute_terminal_recipes_on_isolated_sources(self):
        result = self.execute(order=tuple(reversed(ARMS)))
        self.assertTrue(result["terminal_comparison_complete"], result)
        self.assertEqual(result["registered_arms"], list(reversed(ARMS)))
        self.assertEqual(result["unstarted_arms"], [])
        self.assertEqual(
            {
                arm: row["result"]["selected_document"]
                for arm, row in result["arms"].items()
            },
            {"candidate": "b", "no_update": "a", "bm25": "a", "fixed_expert": "a"},
        )
        for arm, row in result["arms"].items():
            self.assertEqual(row["terminal"], "proved")
            self.assertEqual(row["result"]["training_updates_consumed"], 0)
            self.assertEqual(
                row["result"]["state_before_digest"],
                row["result"]["state_after_digest"],
            )
            self.assertEqual(
                (
                    self.root / "comparison" / arm / "workspace" / "counter.txt"
                ).read_text(),
                "1",
            )
            self.assertGreater(row["costs"]["wall_seconds"], 0)
        self.assertEqual((self.source / "counter.txt").read_text(), "0")
        self.assertTrue(result["source_unchanged_verified"])
        self.assertFalse(result["scientific_qualified"])
        self.assertIsNone(result["costs"]["energy_joules"])
        self.assertIsNone(result["formal_adoption_receipt"])

    def test_actual_checker_failure_remains_in_comparison(self):
        self.task["recipes"]["b"][0]["argv"][-1] += "; raise SystemExit(7)"
        result = self.execute()
        self.assertTrue(result["terminal_comparison_complete"], result)
        self.assertEqual(result["arms"]["candidate"]["terminal"], "refuted")
        self.assertEqual(result["arms"]["bm25"]["terminal"], "proved")
        self.assertGreater(result["arms"]["candidate"]["costs"]["wall_seconds"], 0)

    def test_unresolved_source_pins_do_not_count_as_terminal_results(self):
        self.task["source"]["before_pins"]["counter.txt"] = "f" * 64
        result = self.execute()
        self.assertFalse(result["terminal_comparison_complete"])
        self.assertEqual(
            {row["terminal"] for row in result["arms"].values()}, {"unknown"}
        )
        self.assertEqual(len(result["arms"]), 4)

    def test_invalid_lineage_or_initial_state_rejected_before_output(self):
        wrong = copy.deepcopy(self.candidate)
        wrong["parent_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.execute(candidate=wrong)
        wrong_parent = copy.deepcopy(self.parent)
        wrong_parent["weights"][0][0] = 1
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            self.execute(parent=wrong_parent)
        self.assertFalse((self.root / "comparison").exists())

    def test_exposed_tasks_cannot_become_confirmation_by_declaration(self):
        self.task["split"] = "confirmation"
        self.task["independent_evaluation"] = True
        with self.assertRaisesRegex(ValueError, "HOLD"):
            self.execute()
        self.assertFalse((self.root / "comparison").exists())

    def test_duplicate_arms_or_reused_training_task_rejected_before_output(self):
        with self.assertRaisesRegex(ValueError, "every arm"):
            self.execute(order=("candidate",) * 4)
        self.task["task_id"] = self.receipt["task_id"]
        with self.assertRaisesRegex(ValueError, "different successor"):
            self.execute()
        self.assertFalse((self.root / "comparison").exists())

    def test_original_workspace_reference_is_rejected_before_execution(self):
        self.task["recipes"]["a"][0]["argv"].append(str(self.source))
        with self.assertRaisesRegex(ValueError, "original workspace"):
            self.execute()
        self.assertFalse((self.root / "comparison").exists())


if __name__ == "__main__":
    unittest.main()
