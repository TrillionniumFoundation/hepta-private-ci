"""Synthetic tests of covariance, hierarchy, strict gates and dev selection."""

import copy
import unittest
import numpy as np

from analysis_contract import bootstrap_family, select_development


def panels(left, right=None, audit_left=None):
    right = np.zeros_like(left) if right is None else right
    audit_left = left if audit_left is None else audit_left
    return {"reward": {"left": left, "right": right},
            "audit": {"left": audit_left, "right": right}}


def calculate(panel, kind="gain", margin=None, **changes):
    comparison = {"name": "left-right", "panel": "task", "left": "left", "right": "right", "kind": kind}
    if margin is not None:
        comparison["margin"] = margin
    arguments = dict(draws=120, rng_seed=1729, family_alpha=.05, family_comparisons=1,
                     expected_seeds=3, expected_rollouts=panel["reward"]["left"].shape[1])
    arguments.update(changes)
    return bootstrap_family({"task": panel}, [comparison], **arguments)


class BootstrapTests(unittest.TestCase):
    def test_constant_paired_effect_cancels_shared_path_and_source_noise(self):
        rng = np.random.default_rng(27)
        baseline = rng.integers(-30, 30, (3, 4, 9, 4)).astype(float)
        result = calculate(panels(baseline + .125, baseline))
        self.assertTrue(result["complete_family_pass"])
        for value in result["comparisons"][0]["observers"].values():
            self.assertEqual(value["interval"], [.125, .125])
            self.assertEqual(value["per_seed_mean"], [.125] * 3)

    def test_path_uncertainty_not_lost_when_pairs_are_duplicated(self):
        path = np.tile(np.array([-.5, -.5, .5, .5])[None, :, None, None], (3, 1, 8, 2))
        interval = calculate(panels(path))["comparisons"][0]["observers"]["reward"]["interval"]
        self.assertLess(interval[0], -.1)
        self.assertGreater(interval[1], .1)

    def test_fixed_models_are_not_resampled_as_new_training_replicates(self):
        values = np.broadcast_to(np.array([.125, .25, .375])[:, None, None, None], (3, 1, 9, 4))
        interval = calculate(panels(values))["comparisons"][0]["observers"]["reward"]["interval"]
        self.assertEqual(interval, [.25, .25])

    def test_source_clusters_are_shared_across_fixed_models(self):
        deviations = np.array([-3., -1., 1., 3.])
        values = np.stack([.25 + deviations, .25 - deviations, np.full(4, .25)])[:, None, :, None]
        interval = calculate(panels(values))["comparisons"][0]["observers"]["reward"]["interval"]
        np.testing.assert_allclose(interval, [.25, .25], atol=1e-15, rtol=0)

    def test_task_and_clean_share_rollout_draws_with_separate_source_panels(self):
        paths = np.array([-.5, 0., .25, .5])[None, :, None, None]
        task = panels(np.tile(paths, (3, 1, 8, 4)))
        clean = panels(np.tile(paths, (3, 1, 10, 1)))
        comparisons = [{"name": name, "panel": name, "left": "left", "right": "right", "kind": "gain"}
                       for name in ("task", "clean")]
        result = bootstrap_family({"task": task, "clean": clean}, comparisons, draws=120,
                                  rng_seed=27, family_alpha=.05, family_comparisons=2)
        first, second = result["comparisons"]
        self.assertEqual(first["observers"], second["observers"])

    def test_observer_conjunction_rejects_reward_only_success(self):
        values = np.ones((3, 4, 8, 4)) * .125
        result = calculate(panels(values, audit_left=np.zeros_like(values)))
        row = result["comparisons"][0]
        self.assertTrue(row["observers"]["reward"]["pass"])
        self.assertFalse(row["observers"]["audit"]["pass"])
        self.assertFalse(row["pass"])

    def test_model_sign_condition_rejects_positive_pooled_effect(self):
        values = np.broadcast_to(np.array([-.125, .5, .5])[:, None, None, None], (3, 4, 8, 1))
        result = calculate(panels(values))["comparisons"][0]["observers"]["reward"]
        self.assertTrue(result["lower_pass"])
        self.assertFalse(result["seed_signs_pass"])
        self.assertFalse(result["pass"])

    def test_noninferiority_equality_is_not_a_strict_pass(self):
        values = np.full((3, 4, 8, 1), -.125)
        result = calculate(panels(values), kind="noninferiority", margin=.125)
        self.assertFalse(result["comparisons"][0]["pass"])

    def test_retention_does_not_require_positive_mean_in_every_model(self):
        values = np.full((3, 4, 8, 1), -.0625)
        result = calculate(panels(values), kind="noninferiority", margin=.125)
        self.assertTrue(result["comparisons"][0]["pass"])

    def test_runtime_clean_subset_uses_same_source_panel_and_registered_condition(self):
        values = np.broadcast_to(np.array([-.5, -.5, -.5, .125]), (3, 1, 8, 4))
        comparisons = [
            {"name": "overall", "panel": "task", "left": "left", "right": "right", "kind": "gain"},
            {"name": "clean", "panel": "task", "left": "left", "right": "right",
             "kind": "noninferiority", "margin": .01, "condition_indices": [3]},
        ]
        result = bootstrap_family({"task": panels(values)}, comparisons, draws=120,
                                  rng_seed=27, family_alpha=.05, family_comparisons=2)
        self.assertFalse(result["comparisons"][0]["pass"])
        self.assertTrue(result["comparisons"][1]["pass"])
        self.assertEqual(result["comparisons"][1]["observers"]["reward"]["mean"], .125)

    def test_unrun_comparisons_keep_original_denominator_and_are_not_complete(self):
        result = calculate(panels(np.ones((3, 1, 8, 1))), family_comparisons=6)
        self.assertEqual(result["unrun_family_comparisons"], 5)
        self.assertAlmostEqual(result["interval_coverage_per_observer"], 1 - .05 / 6)
        self.assertFalse(result["complete_family_pass"])
        self.assertTrue(result["all_executed_comparisons_pass"])

    def test_no_missing_nonfinite_or_unpaired_rows_can_disappear(self):
        original = panels(np.ones((3, 4, 8, 4)))
        for value in (np.nan, np.inf):
            changed = copy.deepcopy(original)
            changed["audit"]["left"][0, 0, 0, 0] = value
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                calculate(changed)
        changed = copy.deepcopy(original)
        changed["audit"]["left"] = np.ones((3, 4, 7, 4))
        with self.assertRaisesRegex(ValueError, "Unpaired"):
            calculate(changed)

    def test_draws_and_results_reproduce_exactly(self):
        panel = panels(np.arange(3 * 4 * 8 * 4).reshape(3, 4, 8, 4).astype(float))
        self.assertEqual(calculate(panel), calculate(panel))


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        values = {"frozen": 0, "field": .04, "ordinary_0": 0, "ordinary_1": .01,
                  "ordinary_2": .01, "ordinary_3": .03, "generic": .02, "richer": .02, "h7": .015}
        self.task = {observer: {method: np.full((3, 4, 8, 4), effect) for method, effect in values.items()}
                     for observer in ("reward", "audit")}
        self.clean = {observer: {method: np.zeros((3, 4, 10, 1)) for method in values}
                      for observer in ("reward", "audit")}
        self.gate = {"each_seed_clean_delta_min": -.01, "ordinary_pooled_gain_min": .005,
                     "ordinary_each_seed_gain_min": 0., "field_over_ordinary_pooled_gain_strict_min": 0.,
                     "field_over_selected_adaptive_pooled_gain_min": 0.}

    def test_clean_ineligible_winner_excluded_and_ties_follow_registered_order(self):
        self.clean["audit"]["ordinary_3"][:] = -.02
        result = select_development(self.task, self.clean, self.gate)
        self.assertTrue(result["pass"])
        self.assertEqual(result["ordinary_choices"], ["ordinary_1"] * 3)
        self.assertEqual(result["selected_adaptive"], "generic")

    def test_no_eligible_ordinary_is_failure_without_fallback(self):
        for index in range(4):
            self.clean["reward"][f"ordinary_{index}"][1] = -.02
        result = select_development(self.task, self.clean, self.gate)
        self.assertEqual(result["reason"], "no_eligible_ordinary")
        self.assertFalse(result["pass"])

    def test_no_eligible_adaptive_is_failure_without_substitution(self):
        for method in ("generic", "richer", "h7"):
            self.clean["audit"][method][2] = -.02
        result = select_development(self.task, self.clean, self.gate)
        self.assertEqual(result["reason"], "no_eligible_adaptive")
        self.assertFalse(result["pass"])

    def test_field_representation_is_fixed_even_when_generic_wins(self):
        for observer in self.task:
            self.task[observer]["generic"][:] = .05
        result = select_development(self.task, self.clean, self.gate)
        self.assertEqual(result["selected_adaptive"], "generic")
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
