"""A discontinuous outcome law checks the estimator independently of training."""

import math
import unittest

import torch

from .actor import antithetic_gradient, terminal_state
from ...v6.data import Target


class ActualOutcomeGradientTests(unittest.TestCase):
    def test_threshold_delivery_matches_integrated_gaussian_derivative(self):
        # The decoder emits one of two discrete artifacts at a threshold.
        # Integrating their actual costs gives an independent analytic oracle.
        mu, sigma, gamma = .18, .6, 2.
        generator = torch.Generator().manual_seed(71923)
        eps = torch.randn(800000, 1, 1, generator=generator, dtype=torch.float64)
        good, bad = math.expm1(-gamma * .9) / gamma, math.expm1(-gamma * -.4) / gamma
        positive = torch.where(mu + sigma * eps[..., 0] >= 0, good, bad)
        negative = torch.where(mu - sigma * eps[..., 0] >= 0, good, bad)
        actual = float(antithetic_gradient(positive, negative, eps, sigma)[0, 0])
        expected = (good - bad) * math.exp(-.5 * (mu / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        self.assertAlmostEqual(actual, expected, delta=.004)
        def integrated(value):
            probability = .5 * (1 + math.erf(value / sigma / math.sqrt(2)))
            return probability * good + (1 - probability) * bad
        finite_difference = (integrated(mu + 1e-5) - integrated(mu - 1e-5)) / 2e-5
        self.assertAlmostEqual(expected, finite_difference, places=8)

    def test_private_targets_cannot_enter_generation(self):
        target = Target(torch.zeros(1, 1, 28, 56), torch.zeros(1, 8, dtype=torch.long),
                        torch.zeros(1, 2, dtype=torch.long))
        with self.assertRaises(TypeError):
            terminal_state(None, target, None)

    def test_paired_outcomes_are_required(self):
        with self.assertRaises(ValueError):
            antithetic_gradient(torch.zeros(2, 1), torch.zeros(3, 1), torch.zeros(2, 1, 1), .1)


if __name__ == "__main__":
    unittest.main()
