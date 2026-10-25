"""Analytic laws and correlated-group fixtures, independent of neural outcomes."""

import itertools
import math
import unittest

import numpy as np

from .statistics import cost_summary, crossed_bootstrap, fractional_tail, loss_tails, paired_comparison, registered_confidence, rows_to_cube, summarize_utility


def row_fixture():
    axes = {"seeds": (17, 29), "cases": (608, 609, 610), "views": ("clean", "missing"), "scenarios": (0, 1), "conditions": (("output_mean", "fixed"), ("output_ndu", "fixed")), "metrics": ("utility", "joint_loss", "joint_fact_correct", "required_output_complete", "net_utility")}
    rows = []
    for s, c, v, g, condition in itertools.product(*[axes[k] for k in ("seeds", "cases", "views", "scenarios", "conditions")]):
        u = 0.01 * (s - 17) + 0.03 * (c - 608) + 0.02 * g + 0.04 * (v == "clean") + 0.05 * (condition[0] == "output_ndu")
        rows.append({"seed": s, "case": c, "view": v, "scenario": g, "arm": condition[0], "policy": condition[1], "utility": u, "joint_loss": (1 - u) / 2, "joint_fact_correct": int((s + c + g) % 2 == 0), "required_output_complete": True, "net_utility": u - 0.004})
    return rows, axes


def exact_ce(values, gamma=2.0):
    values = list(values)
    return sum(values) / len(values) if gamma == 0 else -math.log(sum(math.exp(-gamma * x) for x in values) / len(values)) / gamma


class StatisticsTests(unittest.TestCase):
    def test_frozen_census_rejects_duplicate_replays_and_missing_entire_sources(self):
        rows, axes = row_fixture()
        cubes = rows_to_cube(reversed(rows), **axes)
        self.assertEqual(cubes[("output_ndu", "fixed")]["utility"].shape, (2, 3, 2, 2))
        for extra in (rows[0], dict(rows[0], replay=999)):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                rows_to_cube(rows + [extra], **axes)
        with self.assertRaisesRegex(ValueError, "incomplete balanced"):
            rows_to_cube([r for r in rows if r["case"] != 610], **axes)
        with self.assertRaisesRegex(ValueError, "out-of-census"):
            rows_to_cube(rows + [dict(rows[0], case=999)], **axes)
        with self.assertRaisesRegex(ValueError, "unique"):
            rows_to_cube(rows, **dict(axes, cases=(608, 608, 609, 610)))

    def test_finite_complete_inputs_and_binary_success_are_required(self):
        rows, axes = row_fixture()
        with self.assertRaisesRegex(ValueError, "non-finite"):
            rows_to_cube([dict(rows[0], utility=float("nan")), *rows[1:]], **axes)
        with self.assertRaisesRegex(ValueError, "binary"):
            rows_to_cube([dict(rows[0], joint_fact_correct=0.5), *rows[1:]], **axes)
        with self.assertRaises(ValueError):
            summarize_utility(np.zeros((5, 8, 4)))
        with self.assertRaises(ValueError):
            summarize_utility(np.ma.array(np.ones((2, 2, 1, 1)), mask=True))
        with self.assertRaises(ValueError):
            paired_comparison(np.zeros((2, 3, 1, 1)), np.zeros((3, 2, 1, 1)))

    def test_risk_aggregation_keeps_training_seed_outside_ce(self):
        cube = np.array([[[[0.0, 1.0]], [[0.4, 0.4]]], [[[1.0, 1.0]], [[0.6, 0.6]]]])
        report = summarize_utility(cube)
        joint = [exact_ce(seed.ravel()) for seed in cube]
        conditional = [np.mean([exact_ce(condition) for condition in seed.reshape(-1, 2)]) for seed in cube]
        np.testing.assert_allclose(report["joint_ce_per_seed"], joint, rtol=1e-13)
        np.testing.assert_allclose(report["mean_conditional_ce_per_seed"], conditional, rtol=1e-13)
        self.assertAlmostEqual(report["joint_ce"], sum(joint) / 2)
        self.assertNotAlmostEqual(report["joint_ce"], exact_ce(cube.ravel()))
        neutral = summarize_utility(cube, gamma=0)
        self.assertAlmostEqual(neutral["joint_ce"], float(cube.mean()))
        self.assertAlmostEqual(neutral["mean_conditional_ce"], float(cube.mean()))
        a = summarize_utility(np.array([[[[0.0]], [[1.0]]]]))
        b = summarize_utility(np.full((1, 2, 1, 1), 0.4))
        self.assertGreater(a["mean_conditional_ce"], b["mean_conditional_ce"])
        self.assertLess(a["joint_ce"], b["joint_ce"])

    def test_crossed_pairing_translation_and_duplicate_within_source_blocks(self):
        base = np.arange(2 * 3 * 2 * 2).reshape(2, 3, 2, 2) / 100
        improvement = np.array([[0.02, 0.08, 0.15], [0.04, 0.10, 0.18]])[:, :, None, None]
        plan = crossed_bootstrap(2, 3, replicates=4000, seed=7)
        original = paired_comparison(base + improvement, base, bootstrap=plan)
        repeated = paired_comparison(np.tile(base + improvement, (1, 1, 2, 3)), np.tile(base, (1, 1, 2, 3)), bootstrap=plan)
        self.assertGreater(original["interval"][1], original["interval"][0])
        np.testing.assert_allclose(original["interval"], repeated["interval"], atol=1e-13)
        self.assertEqual(original["counts"]["source_pairs"], repeated["counts"]["source_pairs"])
        self.assertGreater(repeated["counts"]["observed_rows"], original["counts"]["observed_rows"])
        shift = paired_comparison(base + 0.1, base, bootstrap=plan)
        np.testing.assert_allclose(shift["interval"], (0.1, 0.1), atol=1e-13)
        self.assertEqual(original["bootstrap"]["paired_indices_sha256"], shift["bootstrap"]["paired_indices_sha256"])
        self.assertFalse(original["bootstrap"]["confirmatory_coverage_guaranteed"])
        with self.assertRaises(ValueError):
            paired_comparison(base, base, bootstrap=crossed_bootstrap(3, 3, replicates=10))

    def test_registered_family_levels_and_direction_of_gains(self):
        self.assertEqual(registered_confidence(("output_ndu", "fixed"), ("output_mean", "fixed")), 0.975)
        self.assertEqual(registered_confidence(("output_ndu", "feedback"), ("output_ndu", "fixed")), 0.975)
        self.assertEqual(registered_confidence(("output_ndu", "feedback"), ("output_ndu", "fixed"), metric="utility"), 0.95)
        self.assertEqual(registered_confidence(("output_ndu", "feedback"), ("output_ndu", "fixed"), estimand="success_rate"), 0.95)
        base = np.arange(24).reshape(2, 3, 2, 2) / 50
        narrow = paired_comparison(base * 0.8, base, estimand="loss_reduction", confidence=0.95)
        wide = paired_comparison(base * 0.8, base, estimand="loss_reduction", confidence=0.975)
        self.assertGreater(wide["gain"], 0)
        self.assertLessEqual(wide["interval"][0], narrow["interval"][0])
        self.assertGreaterEqual(wide["interval"][1], narrow["interval"][1])
        success = paired_comparison(np.ones((2, 2, 1, 1)), np.array([0, 0, 1, 1]).reshape(2, 2, 1, 1), estimand="success_rate")
        self.assertEqual((success["gain"], success["gain_percentage_points"]), (0.5, 50.0))

    def test_accelerated_bootstrap_matches_direct_output_enumeration(self):
        reference = np.array([0.0, 0.9, 0.2, 0.3, 0.5, -0.4, 0.1, 0.6]).reshape(2, 2, 1, 2)
        candidate = reference + np.array([0.2, -0.1, -0.2, 0.3]).reshape(2, 2, 1, 1)
        plan = crossed_bootstrap(2, 2, replicates=47, seed=19)
        differences = []
        for seeds, sources in zip(plan.seed_indices, plan.source_indices):
            estimates = []
            for values in (candidate, reference):
                selected = np.take(np.take(values, seeds, axis=0), sources, axis=1)
                estimates.append(sum(exact_ce(seed.ravel()) for seed in selected) / len(selected))
            differences.append(estimates[0] - estimates[1])
        report = paired_comparison(candidate, reference, bootstrap=plan, batch_size=7)
        np.testing.assert_allclose(report["interval"], np.quantile(differences, (0.025, 0.975)), atol=1e-13)

    def test_fractional_boundary_tail_and_source_averaging_are_distinct(self):
        tail = fractional_tail((0, 1, 2, 3), fraction=0.375)
        self.assertAlmostEqual(tail["cvar"], (3 + 0.5 * 2) / 1.5)
        self.assertEqual((tail["full_tail_observations"], tail["boundary_mass"]), (1, 0.5))
        self.assertAlmostEqual(tail["p95"], 2.85)
        cube = np.array([[[[0.0, 1.0]], [[0.5, 0.5]]]])
        report = loss_tails(cube, fraction=0.25)
        self.assertEqual(report["output_level"]["per_seed"][0]["cvar"], 1.0)
        self.assertEqual(report["source_mean_level"]["per_seed"][0]["cvar"], 0.5)
        different_models = loss_tails(np.array([0, 0, 1, 1]).reshape(2, 2, 1, 1))
        self.assertEqual(different_models["output_level"]["mean_across_seed_summaries"]["cvar"], 0.5)
        self.assertEqual(different_models["output_level"]["equal_seed_mixture"]["cvar"], 1.0)

    def test_cost_rounds_remain_paired_inside_source_groups(self):
        reference = 1 + np.arange(48).reshape(2, 3, 2, 2, 2) / 10
        report = cost_summary(reference + 3, reference=reference, replicates=4000, bootstrap_seed=17)
        self.assertEqual(report["counts"]["source_pairs"], 3)
        self.assertEqual(report["counts"]["within_source_shape"], [2, 2, 2])
        self.assertEqual(report["estimand"], "candidate_minus_reference_cost")
        for name in ("mean", "p50", "p95"):
            self.assertAlmostEqual(report["point_estimates"][name], 3)
            np.testing.assert_allclose(report["intervals"][name], (3, 3), atol=1e-12)
        absolute = cost_summary(reference, replicates=100)
        self.assertAlmostEqual(absolute["point_estimates"]["p95"], float(np.quantile(reference, 0.95)))
        self.assertFalse(absolute["outlier_deletion"])
        with self.assertRaises(ValueError):
            cost_summary(reference, reference=reference[:, :, :, :, :1])
        with self.assertRaises(ValueError):
            cost_summary(np.ma.array(reference, mask=True))


if __name__ == "__main__":
    unittest.main()
