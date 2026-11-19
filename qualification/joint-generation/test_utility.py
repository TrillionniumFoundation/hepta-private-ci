import itertools
import unittest

import numpy as np

from utility import certainty_equivalent, joint_value_and_grad


def softmax(x):
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class UtilityTests(unittest.TestCase):
    def test_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(42)
        a, b = rng.normal(size=(2, 3)), rng.normal(size=(2, 3))
        rewards = rng.uniform(-2, 3, size=(2, 3, 3))
        for rho in (0, 1e-7, 0.7, 15):
            _, ga, gb = joint_value_and_grad(softmax(a), softmax(b), rewards, rho)
            for logits, analytic in ((a, ga), (b, gb)):
                numeric = np.empty_like(logits)
                for index in np.ndindex(logits.shape):
                    original = logits[index]
                    logits[index] = original + 1e-5
                    high = -joint_value_and_grad(softmax(a), softmax(b), rewards, rho)[0].mean()
                    logits[index] = original - 1e-5
                    low = -joint_value_and_grad(softmax(a), softmax(b), rewards, rho)[0].mean()
                    logits[index] = original
                    numeric[index] = (high - low) / 2e-5
                np.testing.assert_allclose(analytic, numeric, atol=2e-8, rtol=2e-5)

    def test_tower_recursion_matches_flattened_law(self):
        p, q = np.array([[0.3, 0.7]]), np.array([[0.8, 0.2]])
        r = np.array([[[-2.0, 4.0], [1.0, 3.0]]])
        for rho in (0, 1e-8, 0.9, 100):
            inner = certainty_equivalent(r, np.broadcast_to(q[:, None, :], r.shape), rho)
            nested = certainty_equivalent(inner, p, rho)
            flat, _, _ = joint_value_and_grad(p, q, r, rho)
            np.testing.assert_allclose(nested, flat, atol=1e-9)

    def test_risk_and_numerical_extremes(self):
        p = np.array([0.5, 0.5])
        self.assertLess(certainty_equivalent([-2, 4], p, 1), 0.5)
        self.assertEqual(certainty_equivalent([0.5, 0.5], p, 1), 0.5)
        self.assertEqual(certainty_equivalent([1000, 1000], p, 1000), 1000)
        self.assertEqual(certainty_equivalent([-1e6, 7], [0, 1], 1000), 7)
        np.testing.assert_allclose(certainty_equivalent([-2, 4], p, 1e-10), 1, atol=1e-8)

    def test_invalid_inputs_reject(self):
        for p, q, r, rho in (
            ([[0.4, 0.4]], [[0.5, 0.5]], np.ones((1, 2, 2)), 1),
            ([[0.5, 0.5]], [[0.5, 0.5]], np.full((1, 2, 2), np.nan), 1),
            ([[0.5, 0.5]], [[0.5, 0.5]], np.ones((1, 2, 2)), -1),
            ([[0.5, 0.5]], [[1]], np.ones((1, 2, 2)), 1),
        ):
            with self.assertRaises(ValueError):
                joint_value_and_grad(p, q, r, rho)

    def test_budget_dynamic_program_matches_exhaustive_tree(self):
        # State: (quality, remaining budget). Stop after success; buy again only
        # after failure. This exercises history-dependent budget allocation.
        # Enumerate adaptive second-stage decisions, not only fixed sequences.
        outcomes = ((0.5, 0), (0.5, 2))
        rho = 0.6
        terminal = lambda quality, budget: min(quality, 2) + 0.15 * budget
        def dp(quality, budget):
            if not budget:
                return terminal(quality, budget)
            return max(terminal(quality, budget), certainty_equivalent(
                [dp(quality + reward, budget - 1) for _, reward in outcomes],
                [prob for prob, _ in outcomes], rho))
        budget = 2
        bellman = dp(0, budget)
        exhaustive = [terminal(0, budget)]
        for continuation in itertools.product((False, True), repeat=2):
            rewards, probabilities = [], []
            for (prob, reward), buy in zip(outcomes, continuation):
                if buy:
                    for prob2, reward2 in outcomes:
                        rewards.append(terminal(reward + reward2, 0))
                        probabilities.append(prob * prob2)
                else:
                    rewards.append(terminal(reward, 1))
                    probabilities.append(prob)
            exhaustive.append(certainty_equivalent(rewards, probabilities, rho))
        self.assertAlmostEqual(bellman, max(exhaustive), places=12)
        self.assertEqual(int(np.argmax(exhaustive)), 3)  # retry failure, stop success


if __name__ == "__main__":
    unittest.main()
