"""Synthetic tests of pairing, immutable choices, strict gates and evidence IO."""

import copy
import unittest

import numpy as np

from .qualification_analysis import METHODS, OBSERVERS, analyze_panels, panel_from_flat, validate_protocol


def fixture(task_pairs=6, clean_pairs=8):
    rng, result = np.random.default_rng(73), {}
    task_offsets = {"ordinary_0": 0., "ordinary_1": .0625, "ordinary_2": .125,
                    "ordinary_3": .125, "raw_field": .1875, "origin_field": .5,
                    "origin_generic": .3125, "origin_richer": .25, "origin_h7": .375}
    for panel, pairs, conditions in (("task", task_pairs, 4), ("clean", clean_pairs, 1)):
        baseline = rng.integers(-5, 5, size=(3, 4, pairs, conditions)).astype(np.float64)
        result[panel] = {}
        for observer in OBSERVERS:
            result[panel][observer] = {method: baseline + (task_offsets[method] if panel == "task" else 0.)
                                       for method in METHODS}
            result[panel][observer]["frozen"] = baseline.copy()
    return result


class StatisticsTests(unittest.TestCase):
    def test_common_path_and_pair_noise_cancel_without_independent_arm_draws(self):
        result = analyze_panels(fixture())
        self.assertTrue(result["passed"])
        for item, effect in zip(result["comparisons"], (.125, .375, .25, 0., 0., 0.)):
            for observer in item["observers"].values():
                self.assertEqual(observer["interval"], [effect, effect])

    def test_methods_cannot_be_reselected_from_qualification_outcomes(self):
        panel = fixture()
        for observer in OBSERVERS:
            panel["task"][observer]["ordinary_1"] += 100
            panel["task"][observer]["origin_generic"] -= 100
            panel["task"][observer]["origin_h7"] += 100
            panel["task"][observer]["raw_field"] += 100
        result = analyze_panels(panel)
        self.assertTrue(result["passed"])
        self.assertEqual([row["observers"]["reward"]["mean"] for row in result["comparisons"][:3]],
                         [.125, .375, .25])

    def test_reward_only_success_fails_observer_conjunction(self):
        panel = fixture()
        panel["task"]["audit"]["origin_field"] = panel["task"]["audit"]["origin_richer"].copy()
        result = analyze_panels(panel)
        self.assertFalse(result["passed"])
        self.assertTrue(result["comparisons"][2]["observers"]["reward"]["passed"])
        self.assertFalse(result["comparisons"][2]["observers"]["audit"]["passed"])

    def test_pooled_positive_cannot_hide_a_nonpositive_fixed_model(self):
        panel = fixture()
        for observer in OBSERVERS:
            ordinary = panel["task"][observer]["ordinary_2"]
            panel["task"][observer]["origin_field"][0] = ordinary[0] - .125
            panel["task"][observer]["origin_field"][1:] += 1
        row = analyze_panels(panel)["comparisons"][1]["observers"]["reward"]
        self.assertTrue(row["lower_pass"])
        self.assertFalse(row["model_signs_pass"])
        self.assertFalse(row["passed"])

    def test_clean_ni_allows_small_negative_effect_but_not_margin_equality(self):
        for effect, expected in ((-.005, True), (-.01, False), (-.02, False)):
            panel = fixture()
            for observer in OBSERVERS:
                for method in (*METHODS, "frozen"):
                    panel["clean"][observer][method].fill(effect if method != "frozen" else 0.)
            result = analyze_panels(panel)
            self.assertEqual(result["passed"], expected, effect)

    def test_whole_rollout_variation_survives_many_duplicate_source_rows(self):
        panel = fixture()
        variation = np.array([-.75, -.75, .75, .75])[None, :, None, None]
        for observer in OBSERVERS:
            panel["task"][observer]["origin_field"] += variation
        row = analyze_panels(panel)["comparisons"][1]["observers"]["reward"]
        self.assertLess(row["interval"][0], 0)
        self.assertGreater(row["interval"][1], .375)

    def test_shared_sources_across_fixed_models_cancel_opposite_source_effects(self):
        panel = fixture(task_pairs=4)
        variation = np.array([-1., -.5, .5, 1.])[None, :, None]
        for observer in OBSERVERS:
            panel["task"][observer]["origin_field"][0] += variation
            panel["task"][observer]["origin_field"][1] -= variation
        interval = analyze_panels(panel)["comparisons"][1]["observers"]["reward"]["interval"]
        np.testing.assert_allclose(interval, [.375, .375], rtol=0, atol=1e-15)

    def test_models_and_conditions_are_fixed_equal_weights(self):
        panel = fixture()
        for observer in OBSERVERS:
            panel["task"][observer]["origin_field"] += np.array([.25, .5, .75])[:, None, None, None]
            panel["task"][observer]["origin_field"] += np.array([-.5, -.25, .25, .5])
        interval = analyze_panels(panel)["comparisons"][1]["observers"]["reward"]["interval"]
        self.assertEqual(interval, [.875, .875])

    def test_no_missing_nonfinite_or_unpaired_outcomes_can_be_dropped(self):
        for change in ("nan", "missing", "shape", "observer"):
            panel = fixture()
            if change == "nan":
                panel["task"]["audit"]["origin_h7"][0, 0, 0, 0] = np.nan
            elif change == "missing":
                del panel["task"]["reward"]["raw_field"]
            elif change == "shape":
                panel["task"]["audit"]["ordinary_0"] = panel["task"]["audit"]["ordinary_0"][:, :, :-1]
            else:
                del panel["clean"]["audit"]
            with self.assertRaises(ValueError, msg=change):
                analyze_panels(panel)

    def test_deterministic_draws_and_result_for_identical_inputs(self):
        first = fixture()
        self.assertEqual(analyze_panels(first), analyze_panels(copy.deepcopy(first)))

    def test_task_and_clean_use_identical_whole_rollout_draws(self):
        panel = fixture()
        variation = np.array([-.125, 0., .25, .375])[None, :, None, None]
        for observer in OBSERVERS:
            panel["task"][observer]["origin_field"] = panel["task"][observer]["ordinary_2"] + variation
            panel["clean"][observer]["origin_field"] = panel["clean"][observer]["frozen"] + variation
        comparisons = analyze_panels(panel)["comparisons"]
        self.assertEqual(comparisons[1]["observers"]["reward"]["interval"],
                         comparisons[4]["observers"]["reward"]["interval"])


class EndpointContractTests(unittest.TestCase):
    def test_flat_values_restore_true_source_clusters_without_axis_swaps(self):
        pairs, conditions = np.array([["a", "b"], ["c", "d"], ["e", "f"]]), ["noise", "clean"]
        values = np.arange(9 * 4 * 2 * 6).reshape(9, 4, 2, 6)
        original = np.arange(12).reshape(2, 6)
        flat = {"task_values": values, "original_task": original,
                "task_source_ids": np.tile(pairs, (2, 1)), "task_conditions": np.repeat(conditions, 3)}
        result = panel_from_flat(flat, "task", pairs, conditions)
        for oi, observer in enumerate(OBSERVERS):
            for mi, method in enumerate(METHODS):
                for rollout in range(4):
                    for pair in range(3):
                        self.assertEqual(result[observer][method][rollout, pair].tolist(),
                                         values[mi, rollout, oi, [pair, pair + 3]].tolist())
            for rollout in range(4):
                np.testing.assert_array_equal(result[observer]["frozen"][rollout], original[oi].reshape(2, 3).T)

    def test_pair_or_condition_permutation_is_rejected_instead_of_repaired(self):
        pairs, conditions = np.array([["a", "b"], ["c", "d"]]), ["noise", "clean"]
        flat = {"task_values": np.ones((9, 4, 2, 4)), "original_task": np.ones((2, 4)),
                "task_source_ids": np.tile(pairs, (2, 1)), "task_conditions": np.repeat(conditions, 2)}
        for key in ("task_source_ids", "task_conditions"):
            changed = copy.deepcopy(flat)
            changed[key][[0, 3]] = changed[key][[3, 0]]
            with self.assertRaisesRegex(ValueError, "Source-pair/condition"):
                panel_from_flat(changed, "task", pairs, conditions)

    def test_registered_family_cannot_be_weakened_or_relabel_old_failure(self):
        import json
        from pathlib import Path
        original = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
        validate_protocol(original)
        for key, value in (("comparison_family", 3), ("bootstrap_seed", 1),
                           ("gain_each_fixed_model_mean_strict_min", -.1),
                           ("clean_ci_lower_strict_min", -.02), ("adaptive_comparator", "origin_h7")):
            changed = copy.deepcopy(original)
            changed["qualification"][key] = value
            with self.assertRaises(ValueError, msg=key):
                validate_protocol(changed)
        changed = copy.deepcopy(original)
        changed["historical_boundary"]["v3_training_gate_passed"] = True
        with self.assertRaises(ValueError):
            validate_protocol(changed)


if __name__ == "__main__":
    unittest.main()
