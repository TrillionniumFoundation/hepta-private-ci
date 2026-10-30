"""Independent, contract-level checks for the regenerative task Bellman oracle."""

import unittest
import numpy as np

from .task_value import (binary_observation_model, solve,
                         literal_binary_reference, binary_rollouts)


class TaskValueTests(unittest.TestCase):
    def test_literal_history_reference(self):
        model = binary_observation_model(6, .72)
        for horizon, tasks, price, refractory, discount in (
                (0, 1, .01, 2, 1.), (1, 3, .01, 2, 1.),
                (4, 2, .03, 0, .97), (6, 3, .03, 1, 1.),
                (7, 2, .005, 2, .96), (6, 2, 1.2, 1, 1.)):
            actual = solve(model, horizon=horizon, tasks=tasks, price=price,
                           refractory=refractory, discount=discount)
            expected = literal_binary_reference(horizon=horizon, tasks=tasks, price=price,
                       refractory=refractory, discount=discount, max_reads=6, reliability=.72)
            self.assertAlmostEqual(actual.fresh[tasks, horizon], expected, places=13)

    def test_future_rewards_are_from_later_tasks(self):
        model = binary_observation_model(6)
        one = solve(model, horizon=12, tasks=1, price=.02)
        three = solve(model, horizon=12, tasks=3, price=.02)
        self.assertGreater(three.fresh[3, 12], 2 * one.fresh[1, 12])
        self.assertGreater(three.future_after_reset[3, 8], 0)
        self.assertEqual(three.future_after_reset[3, 2], 0)
        self.assertEqual(three.future_after_reset[1, 12], 0)
        raw = binary_rollouts(three, samples=4000, seed=32001)
        self.assertTrue(np.all(raw['firings'] >= 2))
        self.assertGreater(raw['later_task_correct'].mean(), .8)

    def test_reward_decomposition_and_price_gradient(self):
        model = binary_observation_model(8, .73)
        solution = solve(model, horizon=14, tasks=3, price=.027, discount=.98)
        np.testing.assert_allclose(solution.fresh,
            solution.fresh_correct - .027 * solution.fresh_reads, atol=1e-13, rtol=0)
        eps = 1e-7
        plus = solve(model, horizon=14, tasks=3, price=.027 + eps, discount=.98)
        minus = solve(model, horizon=14, tasks=3, price=.027 - eps, discount=.98)
        numerical = (plus.fresh[3, 14] - minus.fresh[3, 14]) / (2 * eps)
        self.assertAlmostEqual(numerical, -solution.fresh_reads[3, 14], places=7)

    def test_actual_label_monte_carlo(self):
        model = binary_observation_model(10, .72)
        solution = solve(model, horizon=18, tasks=3, price=.018,
                         refractory=2, discount=.985)
        raw = binary_rollouts(solution, samples=20000, seed=32002)
        error = raw['utility'].mean() - solution.fresh[3, 18]
        se = raw['utility'].std(ddof=1) / np.sqrt(len(raw['utility']))
        self.assertLess(abs(error) / se, 4.5)
        self.assertTrue(np.all(raw['actual_reads'] <= 18))
        self.assertTrue(np.all(raw['firings'] <= 3))

    def test_deadline_refractory_and_high_price(self):
        model = binary_observation_model(8)
        short = solve(model, horizon=1, tasks=3, price=.03, refractory=2)
        self.assertAlmostEqual(short.fresh[3, 1], .72 - .03)
        expensive = solve(model, horizon=20, tasks=3, price=1.01)
        self.assertEqual(expensive.fresh[3, 20], 0)
        self.assertEqual(expensive.decision(3, 20, 0, 0), 'decline')
        fast = solve(model, horizon=12, tasks=3, price=.01, refractory=0)
        slow = solve(model, horizon=12, tasks=3, price=.01, refractory=8)
        self.assertGreater(fast.fresh[3, 12], slow.fresh[3, 12])

    def test_reject_invalid_observation_law(self):
        model = binary_observation_model(4)
        model.transition[1, 3, 4] += .1
        with self.assertRaises(ValueError):
            solve(model, horizon=8, tasks=2, price=.01)


if __name__ == '__main__':
    unittest.main()
