"""Closed-form, nonidentifiability, and independently generated choice checks."""

from dataclasses import FrozenInstanceError
import math
import unittest

import numpy as np

from preference import (UnidentifiablePreference, evaluate_preference, fit_preference,
                        identifiability_report, pair_choice_probabilities,
                        randomized_lottery_pairs, simulate_choices)


class PreferenceTests(unittest.TestCase):
    def test_closed_form_log_odds_mle_and_information(self):
        pairs = np.repeat([[[0., 0.], [0., 2.]]], 10, axis=0)
        choices = np.array([1] * 8 + [0] * 2)
        fit = fit_preference(pairs, choices)
        self.assertAlmostEqual(fit.gamma, math.log(4), places=11)
        self.assertAlmostEqual(fit.fisher_information, 1.6, places=10)
        self.assertAlmostEqual(fit.nll, -8 * math.log(.8) - 2 * math.log(.2), places=12)
        self.assertFalse(fit.at_boundary)
        with self.assertRaises(FrozenInstanceError):
            fit.gamma = 0
        # Exhaustive bounded candidate search independently checks the optimum.
        grid = np.linspace(0, 8, 1001)
        costs = [10 * math.log1p(math.exp(gamma)) - 8 * gamma for gamma in grid]
        self.assertLessEqual(fit.nll, min(costs))

    def test_equal_variance_is_unidentified_and_scale_is_a_real_assumption(self):
        pairs = np.array([[[1., 2.], [-1., 2.]], [[.5, 1.], [.2, 1.]]])
        np.testing.assert_array_equal(pair_choice_probabilities(pairs, 0), pair_choice_probabilities(pairs, 7))
        with self.assertRaises(UnidentifiablePreference):
            fit_preference(pairs, [1, 0])
        self.assertFalse(identifiability_report(pairs, 2)['structurally_identified'])
        design = randomized_lottery_pairs(25, 12)
        scaled = design.copy()
        scaled[:, :, 0] *= 3
        scaled[:, :, 1] *= 9
        np.testing.assert_allclose(pair_choice_probabilities(design, 1.2, .7),
                                   pair_choice_probabilities(scaled, .4, 2.1), rtol=0, atol=1e-15)

    def test_independent_synthetic_train_test_and_frozen_scoring(self):
        train = randomized_lottery_pairs(6000, 31)
        labels = simulate_choices(train, 1.5, 32)
        fit = fit_preference(train, labels)
        self.assertLess(abs(fit.gamma - 1.5), 4 * fit.standard_error)
        test = randomized_lottery_pairs(3000, 41)
        test_labels = simulate_choices(test, 1.5, 42)
        before = fit.gamma
        score = evaluate_preference(test, test_labels, fit.gamma)
        baseline = evaluate_preference(test, test_labels, 0)
        self.assertLess(score['mean_nll'], baseline['mean_nll'])
        self.assertFalse(score['refitted'])
        self.assertEqual(fit.gamma, before)
        report = identifiability_report(train, fit.gamma)
        self.assertTrue(report['structurally_identified'])
        self.assertGreater(report['fisher_information'], 100)
        self.assertFalse(report['real_user_identified'])

    def test_boundary_and_input_contracts(self):
        pairs = np.repeat([[[0., 0.], [0., 2.]]], 10, axis=0)
        self.assertEqual(fit_preference(pairs, np.ones(10), bounds=(0, 3)).gamma, 3)
        self.assertTrue(fit_preference(pairs, np.zeros(10)).at_boundary)
        for kwargs in ({'temperature': 0}, {'bounds': (2, 1)}, {'bounds': (0, float('inf'))}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fit_preference(pairs, np.ones(10), **kwargs)
        with self.assertRaises(ValueError):
            fit_preference(pairs, [0, 1])
        with self.assertRaises(ValueError):
            pair_choice_probabilities(pairs, float('nan'))
        bad = pairs.copy()
        bad[0, 0, 1] = -1
        with self.assertRaises(ValueError):
            pair_choice_probabilities(bad, 2)


if __name__ == '__main__':
    unittest.main()
