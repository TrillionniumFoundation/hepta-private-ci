import itertools
import unittest

import numpy as np

from qualification.hcsn_qvi.oracle import FiniteControl, Problem, cost_sensitivity


class OracleTests(unittest.TestCase):
    def test_policy_iteration_matches_exhaustive_seven_state_policies(self):
        control = FiniteControl(Problem(nodes=7))
        solved = control.policy_iteration()
        exhaustive = np.full(7, -np.inf)
        for bits in itertools.product((0, 1), repeat=7):
            value, _ = control.evaluate(bits)
            exhaustive = np.maximum(exhaustive, value)
        np.testing.assert_allclose(solved["value"], exhaustive, rtol=0, atol=2e-11)

    def test_independent_dp_residual_and_ordinary_threshold_domination(self):
        control = FiniteControl(Problem(nodes=21))
        solved, dp = control.policy_iteration(), control.value_iteration()
        np.testing.assert_allclose(solved["value"], dp["value"], rtol=0, atol=2e-9)
        fixed, _ = control.evaluate(control.x <= 0.4)
        learned = control.fit_soft_threshold(updates=16)
        self.assertTrue(np.all(solved["value"] >= fixed - 1e-10))
        self.assertTrue(np.all(solved["value"] >= learned["value"] - 1e-10))
        self.assertGreaterEqual(
            learned["history"][-1]["objective"], learned["history"][0]["objective"]
        )
        self.assertLess(solved["bellman_residual"], 1e-10)
        self.assertIsNotNone(control.boundary_bracket(solved["policy"]))

    def test_implicit_cost_derivative_checks_active_set_before_claiming_gradient(self):
        smooth = cost_sensitivity(Problem(nodes=21), step=1e-4)
        self.assertTrue(smooth["active_set_unchanged"])
        self.assertLess(smooth["maximum_absolute_difference"], 1e-7)
        crossing = cost_sensitivity(Problem(nodes=21), step=0.5)
        self.assertFalse(crossing["active_set_unchanged"])
        self.assertFalse(crossing["gradient_comparison_qualified"])
