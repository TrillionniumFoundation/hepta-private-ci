"""Finite-process checks for information ordering, selection, and MC coverage."""

import math
import unittest

import numpy as np

from .conditional_information import analyze_history, information_lattice, select_public_action


DIGEST = "a" * 64


def analyze(fit, evaluation, **kwargs):
    return analyze_history(fit, evaluation, kwargs.pop("prior", [1 / len(fit)] * len(fit)),
        public_history_digests=kwargs.pop("digests", [DIGEST] * len(fit)),
        action_names=kwargs.pop("names", ("a", "b")),
        selected_actions=kwargs.pop("selected", {"fit_choice": 0}),
        gamma=kwargs.pop("gamma", 2.0), utility_bounds=kwargs.pop("bounds", (0, 1)), **kwargs)


class InformationTests(unittest.TestCase):
    def test_hidden_target_gap_can_be_entirely_unattainable(self):
        values = np.array([[[1, 0], [1, 0]], [[0, 1], [0, 1]]], dtype=float)
        result = analyze(values, values, deterministic_actions=(0, 1))
        ce = result["empirical_information_lattice"]["CE"]
        public = -math.log((1 + math.exp(-2)) / 2) / 2
        self.assertAlmostEqual(ce["public_only"], public)
        self.assertAlmostEqual(ce["private_target_known"], 1)
        self.assertAlmostEqual(ce["full_future_table_known"], public)
        self.assertAlmostEqual(ce["target_and_future_known"], 1)
        np.testing.assert_allclose(result["causal_best_action_CE_interval"], [public, public])
        np.testing.assert_allclose(result["policies"]["fit_choice"]["finite_history_regret_interval"], [0, 0])

    def test_future_information_and_interaction_are_distinct(self):
        future = np.array([[[1, 0], [0, 1]], [[1, 0], [0, 1]]], dtype=float)
        ce = information_lattice(future, [.5, .5], gamma=2, utility_bounds=(0, 1))["CE"]
        self.assertEqual(ce["public_only"], ce["private_target_known"])
        self.assertAlmostEqual(ce["full_future_table_known"], 1)
        xor = np.array([[[1, 0], [0, 1]], [[0, 1], [1, 0]]], dtype=float)
        result = information_lattice(xor, [.5, .5], gamma=2, utility_bounds=(0, 1))
        self.assertAlmostEqual(result["CE"]["public_only"], result["CE"]["private_target_known"])
        self.assertAlmostEqual(result["CE"]["public_only"], result["CE"]["full_future_table_known"])
        self.assertGreater(result["interaction"], .7)

    def test_fit_selection_cannot_be_replaced_by_evaluation_winner(self):
        fit = np.array([[[1, 0], [1, 0]]], dtype=float)
        evaluation = 1 - fit
        action = select_public_action(fit, [1], gamma=2, utility_bounds=(0, 1))
        self.assertEqual(action, 0)
        result = analyze(fit, evaluation, selected={"frozen": action})
        self.assertEqual(result["policies"]["frozen"]["action"], "a")
        self.assertAlmostEqual(result["policies"]["frozen"]["evaluation_CE"], 0)
        self.assertGreater(result["empirical_information_lattice"]["CE"]["public_only"], .99)

    def test_weighted_moment_target_is_not_mean_log_target(self):
        utility = -np.log(np.array([1, 9])) / 2
        values = np.stack([np.repeat([[u, -math.log(4)/2]], 2, axis=0) for u in utility])
        result = analyze(values, values, bounds=(-2, 1), deterministic_actions=(0, 1),
                         predicted_moments={"correct": [5, 4], "geometric": [3, 4]})
        self.assertAlmostEqual(result["critic_predictions"]["correct"]["conditional_mean_target_MSE_estimate"], 0)
        self.assertAlmostEqual(result["critic_predictions"]["geometric"]["conditional_mean_target_MSE_estimate"], 2)
        self.assertEqual(select_public_action(values, [.5, .5], gamma=2, utility_bounds=(-2, 1)), 1)

    def test_bounded_interval_exact_binomial_coverage_with_paired_actions(self):
        n, probability, alpha, failed_mass = 32, .37, .1, 0.
        for successes in range(n + 1):
            samples = np.r_[np.ones(successes), np.zeros(n-successes)]
            values = np.stack((samples, 1-samples), axis=1)[None]
            result = analyze(values, values, gamma=0, alpha=alpha)
            bounds = np.array(result["action_simultaneous_CE_intervals"])
            true = np.array((probability, 1-probability))
            if np.any(true < bounds[:, 0]) or np.any(true > bounds[:, 1]):
                failed_mass += math.comb(n, successes) * probability**successes * (1-probability)**(n-successes)
        self.assertLessEqual(failed_mass, alpha)

    def test_invalid_information_and_false_determinism_are_rejected(self):
        fit = np.array([[[1, 0], [0, 1]], [[0, 1], [1, 0]]], dtype=float)
        with self.assertRaisesRegex(ValueError, "same|share"):
            analyze(fit, fit, digests=(DIGEST, "b"*64))
        with self.assertRaisesRegex(ValueError, "deterministic"):
            analyze(fit, fit, deterministic_actions=(0,))
        with self.assertRaisesRegex(ValueError, "normalized"):
            analyze(fit, fit, prior=(.5, .4))
        with self.assertRaisesRegex(ValueError, "bounds"):
            analyze(fit, fit+1)
        missing = np.ma.array(fit, mask=np.zeros_like(fit, dtype=bool))
        missing.mask[0, 0, 0] = True
        with self.assertRaisesRegex(ValueError, "Missing"):
            analyze(fit, missing)


if __name__ == "__main__":
    unittest.main()
