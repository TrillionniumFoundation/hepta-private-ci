"""Admission decisions and actual tiny-decoder sequential source acquisition."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from growth_policy import choose_growth
from growth_reads import read_arms
from growth_runtime import train_candidates, typed_slot
from growth_trial import peak_rss
from parametric_model import SourceMemoryCell
from parametric_owner import Frontier
from parametric_trial import read_worker, write_json
from pretrained import file_inventory
import test_parametric_model as tiny


TRAIN = ["What is the {relation} of {entity}?"]
SELECT = "What {relation} of {entity}?"
FINAL = "the {relation} of {entity}?"


def costs():
    return {
        "nochange": {
            "private_parameter_bytes": 100,
            "retained_checkpoint_bytes": 200,
            "optimizer_steps": 0,
        },
        "single": {
            "private_parameter_bytes": 100,
            "retained_checkpoint_bytes": 220,
            "optimizer_steps": 8,
        },
        "split": {
            "private_parameter_bytes": 200,
            "retained_checkpoint_bytes": 440,
            "optimizer_steps": 8,
        },
    }


class GrowthCostTests(unittest.TestCase):
    def test_rss_units_and_unavailable_measurements_are_explicit(self):
        measured = SimpleNamespace(
            RUSAGE_SELF=0,
            RUSAGE_CHILDREN=1,
            getrusage=lambda kind: SimpleNamespace(ru_maxrss=(512, 256)[kind]),
        )
        for platform, multiplier in (("linux", 1024), ("darwin", 1)):
            with self.subTest(platform=platform):
                with (
                    patch("growth_trial.sys.platform", platform),
                    patch.dict("sys.modules", {"resource": measured}),
                ):
                    result = peak_rss()
                self.assertEqual(
                    result["parent_process_peak_rss_bytes"], 512 * multiplier
                )
                self.assertEqual(
                    result["child_process_peak_rss_bytes"], 256 * multiplier
                )
                self.assertIn(platform, result["peak_rss_basis"])
        for platform, module in (
            ("win32", measured),
            ("freebsd", measured),
            ("linux", None),
        ):
            with self.subTest(platform=platform, available=module is not None):
                with (
                    patch("growth_trial.sys.platform", platform),
                    patch.dict("sys.modules", {"resource": module}),
                ):
                    result = peak_rss()
                self.assertIsNone(result["parent_process_peak_rss_bytes"])
                self.assertIsNone(result["child_process_peak_rss_bytes"])
                self.assertIn("unavailable", result["peak_rss_basis"])


class GrowthPolicyTests(unittest.TestCase):
    def test_ties_keep_parent_and_split_requires_two_over_eligible_cheaper(self):
        parent = {"old": [True, True], "new": [False] * 4}
        cases = [
            (parent, parent, "nochange"),
            (
                {"old": [True, True], "new": [True, False, False, False]},
                {"old": [True, True], "new": [True, True, False, False]},
                "single",
            ),
            (
                {"old": [True, True], "new": [True, False, False, False]},
                {"old": [True, True], "new": [True, True, True, False]},
                "split",
            ),
            (
                {"old": [False, True], "new": [True] * 4},
                {"old": [False, True], "new": [True] * 4},
                "nochange",
            ),
            (
                {"old": [False, True], "new": [True] * 4},
                {"old": [True, True], "new": [True, True, False, False]},
                "split",
            ),
        ]
        for single, split, expected in cases:
            with self.subTest(expected=expected, single=single, split=split):
                selection = choose_growth(
                    {"nochange": parent, "single": single, "split": split}, costs()
                )
                self.assertEqual(selection["chosen_arm"], expected)
                self.assertEqual(
                    selection["additional_private_bytes_over_parent"],
                    100 if expected == "split" else 0,
                )
                self.assertFalse(selection["final_scores_used"])

    def test_unmatched_costs_nonboolean_or_final_scores_are_rejected(self):
        source = {arm: {"old": [True], "new": [False]} for arm in costs()}
        with self.assertRaises(TypeError):
            choose_growth(source, costs(), final_scores={"split": 1})
        malformed = copy.deepcopy(source)
        malformed["split"]["new"] = [1]
        with self.assertRaises(ValueError):
            choose_growth(malformed, costs())
        mismatched = costs()
        mismatched["split"]["optimizer_steps"] = 4
        with self.assertRaises(ValueError):
            choose_growth(source, mismatched)
        with self.assertRaises(ValueError):
            typed_slot("split", "unknown")


class GrowthDecoderTests(unittest.TestCase):
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
        self.old = [tiny.fact("one", "red", "a"), tiny.fact("two", "blue", "b")]
        self.incoming = [
            tiny.fact("one", "green", "c") | {"relation": "shape"},
            tiny.fact("two", "red", "d") | {"relation": "shape"},
        ]
        self.cell = SourceMemoryCell(tiny.SourceMemoryCellTests.base, rank=8)
        self.cell.reset("alpha")
        self.cell.fit_sources(self.old, 2, 0.001, TRAIN)
        parent = self.root / "parent"
        manifest = self.cell.save(parent)
        self.parent = {
            "directory": str(parent),
            "manifest_sha256": manifest,
            "roots": ["a" * 64, "b" * 64],
        }
        self.frontier = Frontier("alpha", 1, ("f" * 64,))

    def arguments(self):
        return {
            "old": self.old,
            "incoming": self.incoming,
            "parent": self.parent,
            "frontier": self.frontier,
            "output": self.root / "candidates",
            "single_steps": 8,
            "learning_rate": 0.001,
            "templates": TRAIN,
            "selection_template": SELECT,
            "final_template": FINAL,
            "write_json": write_json,
        }

    def test_actual_arrivals_preserve_ancestry_and_execute_closed_fresh_readers(self):
        before = file_inventory(Path(self.parent["directory"]))
        report = train_candidates(self.cell, **self.arguments())
        self.assertEqual(file_inventory(Path(self.parent["directory"])), before)
        self.assertEqual(report["costs"]["single"]["optimizer_steps"], 8)
        self.assertEqual(report["costs"]["split"]["optimizer_steps"], 8)
        self.assertEqual(
            report["costs"]["split"]["private_parameter_bytes"],
            2 * report["costs"]["single"]["private_parameter_bytes"],
        )
        old_roots = {"a" * 64, "b" * 64}
        all_roots = old_roots | {"c" * 64, "d" * 64}
        for arm, slot, roots in (
            ("single", 0, all_roots),
            ("split", 0, old_roots),
            ("split", 1, all_roots),
        ):
            version = report["versions"][arm][slot]
            manifest = json.loads(
                (Path(version["directory"]) / "lineage.json").read_text()
            )
            self.assertEqual(set(manifest["roots"]), roots)
            self.assertEqual(set(manifest["training"]["inherited_roots"]), old_roots)
            self.assertEqual(
                manifest["training"]["learned_parent_manifest_sha256"],
                self.parent["manifest_sha256"],
            )
            self.assertTrue(
                all(value > 0 for value in manifest["training"]["fact_visits"])
            )
        selection = (self.root / "candidates/precommitted-selection.json").read_bytes()
        final = read_arms(
            model=tiny.SourceMemoryCellTests.base,
            report=report,
            old=self.old,
            incoming=self.incoming,
            frontier=self.frontier,
            output=self.root / "final",
            final_template=FINAL,
            read_worker=read_worker,
            write_json=write_json,
        )
        self.assertEqual(final["fresh_worker_processes"], 4)
        self.assertTrue(report["revoked_ancestry_disjoint"])
        self.assertTrue(
            all(
                call["owner_admitted_before_and_after"]
                for call in final["routed_calls"]
            )
        )
        self.assertEqual(
            final["routed_calls"][0]["unwritten_diagnostic_indices"], [2, 3]
        )
        self.assertTrue(
            all(
                not call["unwritten_diagnostic_indices"]
                for call in final["routed_calls"][1:]
            )
        )
        self.assertEqual(final["source_frontier"]["epoch"], 1)
        self.assertGreater(final["owner_database_bytes"], 0)
        self.assertEqual(
            final["chosen_before_final_read"], report["selection"]["chosen_arm"]
        )
        self.assertEqual(
            (self.root / "candidates/precommitted-selection.json").read_bytes(),
            selection,
        )
        for arm in costs():
            self.assertEqual(final["metrics"][arm]["old"]["total"], 2)
            self.assertEqual(final["metrics"][arm]["new"]["total"], 2)
        for path in (self.root / "final").glob("*.request.json"):
            request = json.loads(path.read_text())
            self.assertEqual(
                set(request),
                {
                    "model",
                    "snapshot",
                    "manifest_sha256",
                    "scope",
                    "allowed_roots",
                    "questions",
                    "rank",
                    "seed",
                    "control",
                },
            )
            self.assertTrue(
                all(
                    not any(
                        value in question.split() for value in ("red", "blue", "green")
                    )
                    for question in request["questions"]
                )
            )
        self.assertEqual(
            report["training_loss_by_relation"]["single"][0]["color"]["updates"], 4
        )
        self.assertEqual(
            report["training_loss_by_relation"]["single"][0]["shape"]["updates"], 4
        )

    def test_new_sources_must_be_distinct_and_rejected_before_any_model_call(self):
        invalid = [
            {"incoming": [self.incoming[0] | {"scope": "other"}, self.incoming[1]]},
            {
                "incoming": [
                    self.incoming[0] | {"source_digest": "a" * 64},
                    self.incoming[1],
                ]
            },
            {"incoming": [self.incoming[0] | {"gold": "red"}, self.incoming[1]]},
            {"single_steps": 3},
            {"parent": self.parent | {"roots": self.parent["roots"] + ["c" * 64]}},
        ]
        for change in invalid:
            with self.subTest(change=change):
                cell = Mock()
                with self.assertRaises(ValueError):
                    train_candidates(cell, **(self.arguments() | change))
                cell.load.assert_not_called()
                self.assertFalse((self.root / "candidates").exists())

    def test_revoked_old_or_new_sources_are_rejected_before_model_load_or_fit(self):
        for root in ("a" * 64, "c" * 64):
            with self.subTest(root=root):
                cell = Mock()
                frontier = Frontier("alpha", 2, ("f" * 64, root))
                with self.assertRaisesRegex(ValueError, "withdrawn source"):
                    train_candidates(
                        cell, **(self.arguments() | {"frontier": frontier})
                    )
                cell.load.assert_not_called()
                cell.fit_sources.assert_not_called()
                self.assertFalse((self.root / "candidates").exists())


if __name__ == "__main__":
    unittest.main()
