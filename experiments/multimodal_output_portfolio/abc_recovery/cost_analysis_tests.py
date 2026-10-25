"""Synthetic timing-only fixtures and exact random-cost risk counterexamples."""

import copy
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .cost_analysis import _method, _quality_summary, _reports, _timing_arrays, price_curve
from .statistics import crossed_bootstrap


WEIGHTS = {"text_fact": .30, "relation": .15, "image_fact": .35, "crossmodal_disagreement": .10, "pixel_mse": .10}


def fixture():
    conditions = tuple(("output_ndu", p) for p in ("fixed", "feedback", "independent_random_stream_MPC"))
    axes = {"seeds": (17, 29), "cases": (608, 609), "views": ("clean", "both_missing"), "scenarios": (0, 1), "rounds": (0, 1), "conditions": conditions}
    pairs = {608: ("synthetic-a", "synthetic-b"), 609: ("synthetic-c", "synthetic-d")}
    rows = []
    for seed, case, view, scenario, timing_round, condition in itertools.product(*(axes[k] for k in ("seeds", "cases", "views", "scenarios", "rounds", "conditions"))):
        fixed = condition[1] == "fixed"
        scores = {}
        for observer in ("primary", "secondary"):
            fields = {"text_fact": 0., "relation": 0., "image_fact": .5 * (observer == "secondary"),
                      "crossmodal_disagreement": .5 * (observer == "secondary"), "pixel_mse": (.1 if fixed else .05) + .01 * scenario}
            loss = sum(WEIGHTS[k] * fields[k] for k in WEIGHTS)
            scores[observer] = {**fields, "joint_loss": loss, "utility": 1 - 2 * loss, "caption_valid": True,
                                "joint_fact_correct": observer == "primary", "required_output_complete": True}
        wall = (2_000_000 if fixed else 3_000_000 if condition[1] == "feedback" else 10_000_000) + 1000 * (case - 608 + timing_round) + 10000 * scenario
        rows.append({"seed": seed, "case": case, "view": view, "scenario": scenario, "round": timing_round,
                     "arm": condition[0], "policy": condition[1], "source_ids": pairs[case], "actual_stream_key": [seed, case, view, scenario],
                     "path": ["refine_image", "refine_text"] if fixed else [], "wall_ns": wall, "cpu_ns": wall * 2,
                     "status": "completed", "score_origin": "decoded_actual_output_offline_observer", "observer_scores": scores,
                     "required_output_complete": True, "work": {"planner_state_transition_calls": 16 if condition[1].endswith("MPC") else 0},
                     "raw": [{"image_sha256": f"synthetic:{seed}:{case}:{view}:{scenario}:{condition}", "text_sha256": "synthetic-caption"}]})
    return rows, axes, pairs


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class CostAnalysisTests(unittest.TestCase):
    def test_method_is_frozen_before_any_outcome_access(self):
        method, sha = _method()
        self.assertEqual(len(sha), 64)
        self.assertFalse(method["price_sensitivity"]["external_calibration"])
        self.assertEqual(method["quality"]["canonical_round"], 0)

    def test_round0_quality_all_round_costs_and_no_proxy_planner_double_count(self):
        rows, axes, pairs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl"
            write_rows(path, reversed(rows))
            quality, costs, eligible, _ = _timing_arrays(path, axes, pairs, WEIGHTS)
        fixed, _, mpc = axes["conditions"]
        self.assertEqual(costs[fixed]["wall_ms"].shape, (2, 2, 2, 2, 2))
        self.assertTrue(all(eligible.values()))
        q = _quality_summary(quality["primary"][mpc])
        self.assertEqual(q["raw_utility"]["counts"]["within_source_shape"], [2, 2])
        self.assertEqual(q["raw_utility"]["counts"]["source_pairs"], 2)
        np.testing.assert_allclose(quality["primary"][mpc]["net_utility"] - quality["primary"][fixed]["net_utility"], .014)
        curve = price_curve(quality["primary"][mpc]["utility"][..., 0], quality["primary"][fixed]["utility"][..., 0],
                            costs[mpc]["wall_ms"], costs[fixed]["wall_ms"], crossed_bootstrap(2, 2, replicates=29, seed=4))
        for point in curve["curve"]:
            expected = .01 - 8 * point["utility_units_per_wall_ms"]
            np.testing.assert_allclose([point["priced_ce_gain"]["gain"], *point["priced_ce_gain"]["interval"]], [expected] * 3, atol=1e-12)
        self.assertEqual(curve["strict_grid_sign_change_brackets"], [[.001, .003]])
        self.assertFalse(curve["external_price_calibration"] or curve["unique_break_even_threshold_claim"] or curve["proxy_action_cost_also_subtracted"])

    def test_random_cost_stays_inside_exponential_not_after_mean_quality(self):
        utility = np.zeros((1, 1, 1, 1))
        variable = np.array([0., 2.]).reshape(1, 1, 1, 1, 2)
        constant = np.ones_like(variable)
        result = price_curve(utility, utility, variable, constant, crossed_bootstrap(1, 1, replicates=7), prices=(1.,))
        expected = -math.log((1 + math.exp(4)) / 2) / 2 + 1
        self.assertAlmostEqual(result["curve"][0]["priced_ce_gain"]["gain"], expected)
        self.assertLess(expected, -.6)
        self.assertEqual(float(variable.mean() - constant.mean()), 0.)

    def test_failure_and_missing_score_do_not_become_success_or_zero_action_cost(self):
        rows, axes, pairs = fixture()
        failed = next(i for i, r in enumerate(rows) if r["policy"].endswith("MPC") and r["round"] == 0)
        rows[failed] = {**rows[failed], "status": "generation_failed", "path": None, "raw": None, "required_output_complete": False,
                        "score_origin": "registered_generation_failure_penalty", "observer_scores": {name: {"utility": -1., "joint_loss": 1., "joint_fact_correct": False, "required_output_complete": False} for name in ("primary", "secondary")}}
        missing = next(i for i, r in enumerate(rows) if r["policy"] == "feedback" and r["round"] == 0)
        rows[missing] = copy.deepcopy(rows[missing])
        rows[missing]["status"], rows[missing]["observer_scores"]["primary"] = "offline_scoring_failed", None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl"
            write_rows(path, rows)
            data = _timing_arrays(path, axes, pairs, WEIGHTS)
        quality, costs, eligible, _ = data
        mpc, feedback = axes["conditions"][2], axes["conditions"][1]
        summary = _quality_summary(quality["primary"][mpc])
        self.assertIsNotNone(summary["raw_utility"])
        self.assertIsNone(summary["proxy_net_utility"])
        self.assertEqual(summary["missing_counts"]["net_utility"], 1)
        self.assertFalse(eligible[("primary", mpc)])
        self.assertFalse(eligible[("primary", feedback)])
        self.assertTrue(eligible[("secondary", feedback)])
        self.assertTrue(np.isfinite(costs[mpc]["wall_ms"]).all())
        report = _reports(*data, axes)
        contrast = report["comparisons"]["feedback_vs_independent_random_stream_MPC"]
        self.assertIsNone(contrast["observers"]["primary"]["price_sensitivity"])
        self.assertEqual(contrast["cost_increase"]["wall_ms"]["counts"]["source_pairs"], 2)

    def test_duplicate_missing_and_mismatched_replays_cannot_inflate_census(self):
        rows, axes, pairs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl"
            for invalid, message in ((rows + [dict(rows[0], replay=10)], "Duplicate"), (rows[1:], "Incomplete"),
                                     ([dict(rows[0], source_ids=pairs[609]), *rows[1:]], "unpaired")):
                write_rows(path, invalid)
                with self.assertRaisesRegex(ValueError, message):
                    _timing_arrays(path, axes, pairs, WEIGHTS)
            changed = copy.deepcopy(rows)
            changed[0]["raw"][0]["image_sha256"] = "different-realized-output"
            write_rows(path, changed)
            _, _, eligible, replay = _timing_arrays(path, axes, pairs, WEIGHTS)
            self.assertFalse(replay[axes["conditions"][0]]["output_and_path_replay_complete"])
            self.assertFalse(eligible[("primary", axes["conditions"][0])])


if __name__ == "__main__":
    unittest.main()
