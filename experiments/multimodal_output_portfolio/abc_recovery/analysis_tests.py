"""Streaming census fixtures and analytic nonlinear contrasts; no real outcomes."""

import copy
import gzip
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .analysis import (COMPONENTS, CONDITIONS, METRICS, PLANS, PRIMARY, _census,
                       _observer_report, _observer_rows, _support_flags, ce_interaction)
from .statistics import crossed_bootstrap, rows_to_cube


WEIGHTS = dict(zip(COMPONENTS, (.30, .15, .35, .10, .10)))


def fixture():
    axes = {"seeds": (17, 29), "cases": (608, 609), "views": ("clean", "both_missing"), "scenarios": (0, 1),
            "conditions": (("output_ndu", "fixed"), ("sft_continuation", "fixed")), "metrics": METRICS}
    pairs = {608: ("synthetic-a", "synthetic-b"), 609: ("synthetic-c", "synthetic-d")}
    rows = []
    for seed, case, view, scenario, condition in itertools.product(*(axes[k] for k in ("seeds", "cases", "views", "scenarios", "conditions"))):
        scores = {}
        for observer in ("primary", "secondary"):
            fields = {"text_fact": 0., "relation": 0., "image_fact": float(observer == "secondary"),
                      "crossmodal_disagreement": float(observer == "secondary"), "pixel_mse": .1 + .01 * (case - 608) + .02 * scenario}
            loss = sum(WEIGHTS[k] * fields[k] for k in COMPONENTS)
            scores[observer] = {**fields, "joint_loss": loss, "utility": 1 - 2 * loss, "net_utility": 1 - 2 * loss - .004,
                                "joint_fact_correct": float(observer == "primary"), "required_output_complete": 1.}
        path = ("refine_image", "refine_text")
        rows.append({"seed": seed, "case": case, "view": view, "scenario": scenario, "arm": condition[0], "policy": condition[1],
                     "source_ids": pairs[case], "path": path, "plan_index": PLANS.index(path), "continuation_actions": 2,
                     "tree_row_index": (axes["views"].index(view) * 2 + case - 608) * 2 + scenario,
                     "selection_is_privileged_offline_oracle": False, "observers": scores})
    return rows, axes, pairs


def write_rows(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def exact_ce(values):
    values = list(values)
    return -math.log(sum(math.exp(-2 * x) for x in values) / len(values)) / 2


class AnalysisTests(unittest.TestCase):
    def test_two_stream_passes_keep_observers_and_frozen_source_axes_separate(self):
        rows, axes, pairs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl.gz"
            write_rows(path, reversed(rows))
            cubes = {name: rows_to_cube(_observer_rows(path, name, pairs, WEIGHTS, axes["views"], axes["scenarios"]), **axes)
                     for name in ("primary", "secondary")}
        self.assertEqual(cubes["primary"][("output_ndu", "fixed")]["utility"].shape, (2, 2, 2, 2))
        np.testing.assert_allclose(cubes["primary"][("output_ndu", "fixed")]["utility"] - cubes["secondary"][("output_ndu", "fixed")]["utility"], .9)

    def test_duplicate_replay_missing_source_and_wrong_identity_are_rejected(self):
        rows, axes, pairs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl.gz"
            for invalid, message in ((rows + [dict(rows[0], replay=99)], "duplicate"),
                                     ([r for r in rows if r["case"] != 609], "incomplete"),
                                     ([dict(rows[0], source_ids=pairs[609]), *rows[1:]], "Unpaired")):
                write_rows(path, invalid)
                with self.assertRaisesRegex(ValueError, message):
                    rows_to_cube(_observer_rows(path, "primary", pairs, WEIGHTS, axes["views"], axes["scenarios"]), **axes)

    def test_path_oracle_and_action_penalty_cannot_be_relabelled(self):
        rows, axes, pairs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl.gz"
            wrong_penalty = copy.deepcopy(rows[0])
            wrong_penalty["observers"]["primary"]["net_utility"] += .008
            for row in (dict(rows[0], policy="oracle_primary"), dict(rows[0], plan_index=0), wrong_penalty):
                write_rows(path, [row])
                with self.assertRaises(ValueError):
                    list(_observer_rows(path, "primary", pairs, WEIGHTS, axes["views"], axes["scenarios"]))

    def test_exact_registered_census_and_disjoint_source_pairs(self):
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        manifest = {"roles": {"development": {"source_ids": [f"synthetic-{i}" for i in range(1500)]}}}
        axes, pairs = _census(protocol, manifest)
        self.assertEqual((len(axes["conditions"]), len(pairs)), (24, 128))
        self.assertEqual(math.prod(len(axes[k]) for k in ("seeds", "cases", "views", "scenarios", "conditions")), 491520)
        manifest["roles"]["development"]["source_ids"][1217] = "synthetic-1216"
        with self.assertRaisesRegex(ValueError, "disjoint"):
            _census(protocol, manifest)

    def test_interaction_is_four_ces_not_ce_of_output_differences(self):
        a = np.array([1., 0.]).reshape(1, 2, 1, 1)
        zero, c = np.zeros_like(a), 1 - a
        plan = crossed_bootstrap(1, 2, replicates=47, seed=19)
        report = ce_interaction(a, zero, c, zero, bootstrap=plan, batch_size=7)
        self.assertAlmostEqual(report["gain"], 0.)
        self.assertLess(exact_ce((a - c).ravel()), -.6)
        differences = []
        for sources in plan.source_indices:
            cells = [exact_ce(values[0, sources].ravel()) for values in (a, zero, c, zero)]
            differences.append(cells[0] - cells[1] - cells[2] + cells[3])
        np.testing.assert_allclose(report["interval"], np.quantile(differences, (.025, .975)), atol=1e-13)

    def test_interaction_keeps_all_four_cells_on_same_crossed_draw(self):
        ndu = np.arange(24).reshape(2, 3, 2, 2) / 100
        sft = ndu[::-1, ::-1] - .4
        report = ce_interaction(ndu + .2, ndu, sft + .05, sft,
                                bootstrap=crossed_bootstrap(2, 3, replicates=41, seed=5))
        np.testing.assert_allclose([report["gain"], *report["interval"]], (.15, .15, .15), atol=1e-13)
        with self.assertRaises(ValueError):
            ce_interaction(ndu, ndu, sft[:, :2], sft)

    def test_primary_family_secondary_checks_and_support_flags_stay_separate(self):
        reports = {}
        for observer in ("primary", "secondary"):
            cubes = {}
            for condition in CONDITIONS:
                utility = .7 if condition == ("output_mean", "fixed") else .6
                if condition == ("output_ndu", "fixed"):
                    utility = .8 if observer == "primary" else .5
                if condition == ("output_ndu", "feedback"):
                    utility = .9 if observer == "primary" else .4
                if observer == "primary" and condition[1].startswith("oracle_"):
                    utility = .99
                loss = (1 - utility) / 2
                metrics = {k: np.full((2, 2, 2, 2), loss) for k in COMPONENTS}
                metrics.update({"utility": np.full((2, 2, 2, 2), utility), "net_utility": np.full((2, 2, 2, 2), utility - .004),
                                "joint_loss": np.full((2, 2, 2, 2), loss), "joint_fact_correct": np.zeros((2, 2, 2, 2)),
                                "required_output_complete": np.ones((2, 2, 2, 2))})
                cubes[condition] = metrics
            reports[observer] = _observer_report(cubes, ("clean", "both_missing"), observer,
                                                crossed_bootstrap(2, 2, replicates=19, seed=3))
            for name, result in reports[observer]["comparisons"].items():
                self.assertEqual(result["net_ce"]["confidence"], .975 if observer == "primary" and name in PRIMARY else .95)
                self.assertEqual(result["raw_ce"]["confidence"], .95)
        flags = _support_flags(reports)
        self.assertTrue(flags["nominal_support_for_both_registered_primary_comparisons"])
        self.assertTrue(all(not value["direction_positive"] for value in flags["secondary_descriptive_checks"].values()))
        self.assertFalse(flags["confirmatory_coverage_guaranteed"] or flags["production_approved"] or flags["all_blockers_closed"])
        self.assertIn("not a secondary upper bound", reports["secondary"]["comparisons"]["output_ndu_oracle_vs_fixed"]["oracle_interpretation"])


if __name__ == "__main__":
    unittest.main()
