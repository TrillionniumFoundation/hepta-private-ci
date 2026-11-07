"""Numerical regressions for saturated policies, without model training."""

import unittest

import numpy as np

from .core import Config, Environment, evaluate_policy
from .gradients import SoftmaxPolicy, policy_value_gradient


class SaturatedGradientTests(unittest.TestCase):
    def policy(self, risk, preferred=1):
        policy = SoftmaxPolicy(Environment(Config(risk=risk, budget=4, horizon=5)))
        policy.theta[:] = -1000.0
        policy.theta[:, preferred] = 1000.0
        return policy

    def assert_matches_forward(self, policy):
        with np.errstate(invalid="raise", divide="raise", over="raise"):
            value, gradient = policy_value_gradient(policy)
        self.assertTrue(np.isfinite(gradient).all())
        self.assertAlmostEqual(value, evaluate_policy(policy.env, policy), places=12)
        np.testing.assert_allclose(gradient.sum(axis=1), 0.0, atol=2e-13, rtol=0)
        for state in policy.states:
            probabilities = policy(state)
            for index, action in enumerate(policy.actions):
                if probabilities.get(action, 0.0) == 0.0:
                    self.assertEqual(gradient[policy.rows[state], index], 0.0)
        return value, gradient

    def test_saturated_small_risk_matches_risk_neutral_limit(self):
        neutral_value, neutral_gradient = self.assert_matches_forward(self.policy(0.0))
        small_value, small_gradient = self.assert_matches_forward(self.policy(1e-12))
        self.assertAlmostEqual(small_value, neutral_value, places=11)
        np.testing.assert_allclose(small_gradient, neutral_gradient, atol=2e-12, rtol=0)

    def test_zero_mass_low_return_cannot_poison_high_risk_tilt(self):
        # A zero-mass return used as the old exponential shift made every
        # supported weight underflow, although the independent value was finite.
        self.assert_matches_forward(self.policy(1e6, preferred=1))

    def test_saturated_preferences_keep_zero_and_masked_gradients_zero(self):
        for preferred in range(4):
            with self.subTest(preferred=preferred):
                self.assert_matches_forward(self.policy(0.25, preferred))

    def test_deterministic_support_does_not_gain_an_artificial_probability_floor(self):
        for risk in (0.0, 1e-12, 0.25, 1e6):
            with self.subTest(risk=risk):
                policy = self.policy(risk)
                policy.theta[:] = -1000.0
                for state in policy.states:
                    legal = policy.env.actions(state)
                    policy.theta[policy.rows[state], policy.actions.index(legal[0])] = (
                        1000.0
                    )
                    self.assertEqual(
                        sorted(policy(state).values()), [0.0] * (len(legal) - 1) + [1.0]
                    )
                _, gradient = self.assert_matches_forward(policy)
                np.testing.assert_array_equal(gradient, np.zeros_like(gradient))

    def test_resolvable_extreme_logits_match_independent_forward_differences(self):
        for risk in (0.0, 1e-12, 0.25, 50.0):
            with self.subTest(risk=risk):
                policy = self.policy(risk)
                for row in range(len(policy.states)):
                    policy.theta[row] = np.roll(np.linspace(-9.0, 9.0, 4), row % 4)
                _, gradient = self.assert_matches_forward(policy)
                positive = [
                    p for state in policy.states for p in policy(state).values()
                ]
                self.assertGreater(min(positive), 0.0)
                self.assertLess(min(positive), 1e-6)
                coordinates = sorted(
                    [
                        (policy.rows[state], policy.actions.index(action))
                        for state in policy.states
                        for action in policy.env.actions(state)
                    ],
                    key=lambda ij: abs(gradient[ij]),
                    reverse=True,
                )[:20]
                self.assertGreater(max(abs(gradient[ij]) for ij in coordinates), 1e-7)
                epsilon = 1e-3
                for coordinate in coordinates:
                    original = policy.theta[coordinate]
                    try:
                        policy.theta[coordinate] = original + epsilon
                        plus = evaluate_policy(policy.env, policy)
                        policy.theta[coordinate] = original - epsilon
                        minus = evaluate_policy(policy.env, policy)
                    finally:
                        policy.theta[coordinate] = original
                    numerical = (plus - minus) / (2 * epsilon)
                    self.assertAlmostEqual(numerical, gradient[coordinate], delta=2e-9)


if __name__ == "__main__":
    unittest.main()
