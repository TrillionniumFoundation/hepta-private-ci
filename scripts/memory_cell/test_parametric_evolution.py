"""Actual tiny decoder evolution and value-free routing boundaries."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from parametric_evolution import cluster_questions, route_questions, run_evolution
from parametric_model import SourceMemoryCell
from pretrained import file_inventory
import test_parametric_model as tiny


TRAIN = ["What is the {relation} of {entity}?"]
SELECT = "What {relation} for {entity}?"


class ParametricEvolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        tiny.SourceMemoryCellTests.tearDownClass()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.facts = [
            tiny.fact("one", "red", "a"),
            tiny.fact("two", "blue", "b"),
            tiny.fact("three", "green", "c"),
            tiny.fact("four", "red", "d"),
        ]
        self.cell = SourceMemoryCell(tiny.SourceMemoryCellTests.base, rank=2)
        self.cell.reset("alpha")
        self.cell.fit_sources(self.facts, 4, 0.001, TRAIN)
        self.parent = self.root / "parent"
        self.parent_sha = self.cell.save(self.parent)

    def arguments(self):
        return dict(
            parent_dir=self.parent,
            parent_sha=self.parent_sha,
            facts=self.facts,
            output=self.root / "evolution",
            steps=4,
            learning_rate=0.001,
            templates=TRAIN,
            selection_template=SELECT,
        )

    def test_actual_two_slot_descendants_match_budget_and_preserve_parent(self):
        before = file_inventory(self.parent)
        with patch.object(self.cell, "generate", wraps=self.cell.generate) as calls:
            report = run_evolution(self.cell, **self.arguments())
        self.assertEqual(file_inventory(self.parent), before)
        self.assertEqual(set(report["partition"]["slots"]), {0, 1})
        for key in ("optimizer_steps", "parameter_bytes", "saved_adapter_bytes"):
            self.assertEqual(
                report["arms"]["continue"][key], report["arms"]["split"][key]
            )
        self.assertEqual(report["arms"]["continue"]["optimizer_steps"], 8)
        all_roots = sorted(f["source_digest"] for f in self.facts)
        for arm in ("continue", "split"):
            for version in report["arms"][arm]["cells"]:
                manifest = json.loads(
                    (Path(version["directory"]) / "lineage.json").read_text()
                )
                self.assertEqual(manifest["roots"], all_roots)
                self.assertEqual(
                    manifest["training"]["learned_parent_manifest_sha256"],
                    self.parent_sha,
                )
                self.assertTrue(all(v > 0 for v in manifest["training"]["fact_visits"]))
                self.assertEqual(manifest["training"]["steps"], 4)
        for call in calls.call_args_list:
            self.assertTrue(
                all(
                    all(f["value"] not in q.split() for f in self.facts)
                    for q in call.args[0]
                )
            )
        baseline = report["arms"]["continue"]["selection"]
        split = report["arms"]["split"]["selection"]
        if report["chosen_arm"] == "split":
            self.assertGreaterEqual(split["correct"], baseline["correct"] + 2)
            self.assertTrue(
                all(
                    not old or new
                    for old, new in zip(
                        baseline["correct_by_source"], split["correct_by_source"]
                    )
                )
            )
        self.assertEqual(
            report["chosen_cells"], report["arms"][report["chosen_arm"]]["cells"]
        )

    def test_routing_does_not_change_when_only_adapter_or_values_change(self):
        questions = [
            TRAIN[0].format(entity=f["entity"], relation=f["relation"])
            for f in self.facts
        ]
        before = cluster_questions(self.cell, questions)
        altered = copy.deepcopy(self.facts)
        for fact in altered:
            fact["value"] = "green"
        self.cell.fit_sources(altered, 4, 0.01, TRAIN)
        after = cluster_questions(self.cell, questions)
        self.assertEqual(after, before)
        self.assertEqual(
            route_questions(self.cell, questions, before)["slots"], before["slots"]
        )
        wrong_scope = before | {"scope": "other"}
        with self.assertRaisesRegex(ValueError, "router identity"):
            route_questions(self.cell, questions, wrong_scope)

    def test_selection_keeps_parent_when_candidates_regress(self):
        cases = [
            (
                [True, True, True, True],
                [True, True, True, True],
                [True, True, True, True],
                "nochange",
            ),
            (
                [True, True, True, True],
                [True, False, False, False],
                [True, True, True, False],
                "nochange",
            ),
            (
                [True, False, False, False],
                [False, True, False, False],
                [False, True, True, False],
                "nochange",
            ),
            (
                [True, False, False, False],
                [True, True, False, False],
                [True, True, True, False],
                "continue",
            ),
            (
                [True, False, False, False],
                [True, False, False, False],
                [True, True, True, False],
                "split",
            ),
        ]
        for index, (parent, continued, split, expected) in enumerate(cases):
            assessments = [
                (
                    {
                        "correct": sum(correct),
                        "count": len(correct),
                        "correct_by_source": correct,
                    },
                    [{"input_tokens": 1, "generated_tokens": 1} for _ in correct],
                )
                for correct in (parent, continued, split)
            ]
            with (
                self.subTest(expected=expected, index=index),
                patch("parametric_evolution._assess", side_effect=assessments),
            ):
                report = run_evolution(
                    self.cell,
                    **(self.arguments() | {"output": self.root / f"selection-{index}"}),
                )
            self.assertEqual(report["chosen_arm"], expected)
            self.assertEqual(report["chosen_cells"], report["arms"][expected]["cells"])
            if expected == "nochange":
                self.assertEqual(
                    [v["manifest_sha256"] for v in report["chosen_cells"]],
                    [self.parent_sha] * 2,
                )

    def test_final_targets_and_unbounded_or_nonheldout_inputs_never_execute(self):
        invalid = [
            dict(steps=3),
            dict(steps=4097),
            dict(steps=True),
            dict(learning_rate=float("nan")),
            dict(selection_template=TRAIN[0]),
            dict(selection_template="{entity} {relation} {value}"),
            dict(facts=[self.facts[0] | {"final_answer": "red"}, *self.facts[1:]]),
        ]
        for change in invalid:
            cell = Mock()
            with self.subTest(change=change), self.assertRaises(ValueError):
                run_evolution(cell, **(self.arguments() | change))
            cell.load.assert_not_called()
            self.assertFalse((self.root / "evolution").exists())
        with self.assertRaises(TypeError):
            run_evolution(Mock(), **self.arguments(), finaltest=["forbidden"])


if __name__ == "__main__":
    unittest.main()
