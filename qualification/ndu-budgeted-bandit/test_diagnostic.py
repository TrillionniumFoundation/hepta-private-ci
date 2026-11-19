import unittest
from diagnostic import *


class RoutingTests(unittest.TestCase):
    def test_missing_rewards_cannot_change_observed_log(self):
        self.assertEqual(generate_train(17, deficient=True, means=HIGH),
                         generate_train(17, deficient=True, means=LOW))

    def test_missing_cells_fall_back(self):
        fitted = fit(generate_train(17, deficient=True, means=HIGH))
        self.assertEqual(fitted['maps']['support_lcb'][2:], [0, 0])
        self.assertEqual([row[1] for row in fitted['counts'][2:]], [0, 0])

    def test_low_support_falls_back(self):
        rows = [LoggedEvent(x, a, a, .5, COSTS[a])
                for x in range(4) for a in range(2) for _ in range(31)]
        self.assertEqual(fit(rows)['maps']['support_lcb'], [0] * 4)

    def test_sufficient_positive_data_uses_alternative(self):
        rows = [LoggedEvent(x, a, a, .5, COSTS[a])
                for x in range(4) for a in range(2) for _ in range(100)]
        self.assertEqual(fit(rows)['maps']['support_lcb'], [1] * 4)

    def test_ties_are_baseline(self):
        rows = [LoggedEvent(x, a, 1, .5, COSTS[a])
                for x in range(4) for a in range(2) for _ in range(100)]
        self.assertEqual(fit(rows)['maps']['empirical_extrapolation'], [0] * 4)
        self.assertEqual(fit(rows)['maps']['support_lcb'], [0] * 4)

    def test_integer_cap_reserves_all_baselines(self):
        # Exhaustively test small horizons/caps; no reward fixture involved.
        for horizon in range(1, 20):
            for cap in range(horizon, horizon * 3 + 1):
                spent = 0
                for i in range(horizon):
                    action = admitted_action(1, spent, i, horizon, cap)
                    spent += COSTS[action]
                    self.assertLessEqual(spent + horizon - i - 1, cap)
                self.assertEqual(spent, horizon + 2 * min(horizon, (cap - horizon) // 2))

    def test_infeasible_cap_rejected(self):
        with self.assertRaises(ValueError):
            admitted_action(0, 0, 0, 10, 9)
        with self.assertRaises(ValueError):
            admitted_action(0, 20, 5, 10, 10)

    def test_zero_propensity_logged_action_rejected(self):
        with self.assertRaises(ValueError):
            fit([LoggedEvent(0, 1, 1, 0., 3)])

    def test_bad_logged_cost_rejected(self):
        with self.assertRaises(ValueError):
            fit([LoggedEvent(0, 1, 1, .5, 1)])

    def test_training_and_eval_are_reproducible_separate_streams(self):
        self.assertEqual(evaluation_stream(2), evaluation_stream(2))
        self.assertNotEqual(evaluation_stream(2), evaluation_stream(3))
        self.assertEqual(generate_train(2), generate_train(2))


if __name__ == '__main__':
    unittest.main()
