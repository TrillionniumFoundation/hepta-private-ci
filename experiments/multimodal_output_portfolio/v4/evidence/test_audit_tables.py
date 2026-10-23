"""Analytically specified, model-free checks of the independent audit solver."""

import unittest

import numpy as np

from audit_tables import NODES, PLANS, ce, first_best, leaf_policy_value, solve_tables


def settings():
    return {'objective': {'gamma': 0., 'mac_price_lambda': .01},
            'resource_contract': {'emit_all_macs': 2, 'refine_macs': {'text': 1}},
            'disturbance_design': {'branch_probabilities': [.25, .5, .25]},
            'policies': {'tie_tolerance': 1e-12}}


def contingent_fixture(repeated=False):
    losses = [np.full(NODES[0], .4), np.ones(NODES[1]), np.full(NODES[2], .5)]
    for root in range(32):
        for first_branch in range(3):
            node = root * 12 + first_branch
            losses[1][node] = .6
            second_modality = 0 if repeated else first_branch + 1
            losses[2][node * 12 + second_modality * 3:node * 12 + second_modality * 3 + 3] = 0
    return losses


class AuditSolverTests(unittest.TestCase):
    def test_contingent_second_action_beats_all_initially_committed_plans(self):
        protocol, losses = settings(), contingent_fixture()
        result = solve_tables(losses, protocol)
        np.testing.assert_array_equal(result['dynamic_actions_0'], np.ones(32, np.int64))
        np.testing.assert_array_equal(result['myopic_actions_0'], np.zeros(32, np.int64))
        np.testing.assert_array_equal(result['plan_choice'], np.full(32, PLANS.index((0, 2))))
        np.testing.assert_allclose(result['dynamic_values_0'], -.04, atol=1e-14)
        np.testing.assert_allclose(result['plan_selected_value'], -.29, atol=1e-14)
        np.testing.assert_allclose(result['myopic_values_0'], -.42, atol=1e-14)
        for branch in range(3):
            self.assertEqual(result['dynamic_actions_1'][branch], branch + 2)
        actions = [result[f'dynamic_actions_{depth}'] for depth in range(3)]
        self.assertAlmostEqual(leaf_policy_value(0, losses, actions, protocol), -.04, places=14)

    def test_same_modality_twice_is_an_admissible_plan(self):
        result = solve_tables(contingent_fixture(repeated=True), settings())
        np.testing.assert_array_equal(result['plan_choice'], np.full(32, PLANS.index((0, 0))))
        np.testing.assert_allclose(result['plan_selected_value'], -.04, atol=1e-14)

    def test_positive_cost_and_terminal_zero_placeholders_cannot_displace_emit(self):
        result = solve_tables([np.full(count, .3) for count in NODES], settings())
        for mode in ('dynamic', 'myopic'):
            for depth in range(3):
                np.testing.assert_array_equal(result[f'{mode}_actions_{depth}'], np.zeros(NODES[depth]))
            self.assertLess(result[f'{mode}_scores_2'][0, 0], 0)
            np.testing.assert_array_equal(result[f'{mode}_scores_2'][:, 1:], 0)
        np.testing.assert_array_equal(result['plan_choice'], np.zeros(32))

    def test_stable_ties_probability_checks_and_constant_ce(self):
        self.assertEqual(first_best([0., 5e-13, 2e-12, 2e-12]), 2)
        self.assertAlmostEqual(ce([-3., -3., -3.], [.25, .5, .25], 2.), -3.)
        with self.assertRaises(AssertionError):
            ce([0., 1.], [-.2, 1.2], 2.)
        with self.assertRaises(AssertionError):
            ce([0., float('nan')], [.5, .5], 2.)
        losses = [np.ones(count) for count in NODES]
        losses[2][0] = np.nan
        with self.assertRaises(AssertionError):
            solve_tables(losses, settings())


if __name__ == '__main__':
    unittest.main()
