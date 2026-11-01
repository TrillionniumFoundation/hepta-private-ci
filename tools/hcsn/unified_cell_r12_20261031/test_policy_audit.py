"""Executable checks that future core updates, not Bayes-oracle tails, run."""
import copy
import unittest

import numpy as np

from .cell import Cell
from .data import encode_observation
from .estimators import HXFilter
from .policy_audit import audit_deployed_policy, run_policy_fixture
from .recurrent import RecurrentEstimator
from .task_value import ExactBeliefDP


class PolicyAuditTests(unittest.TestCase):
    def test_same_model_hx_filter_equals_fitted_world_optimal(self):
        estimator = HXFilter(seed=7)
        cell = estimator.build_cell()
        result = run_policy_fixture(cell, estimator)
        np.testing.assert_allclose(list(result["actual_recurrent_q_pi"].values()),
                                   list(result["fitted_world_q_star"].values()), rtol=0, atol=2e-12)
        self.assertLess(result["max_leaf_mass_error"], 2e-12)
        self.assertTrue(result["original_state_unchanged"])

    def test_recurrent_terminal_predictions_use_real_step_and_world_weights(self):
        cell = Cell()
        estimator = RecurrentEstimator("gru", seed=19)
        estimator.start(cell.prior)
        estimator.step(encode_observation(0, .15))
        true_belief = cell.prior @ cell.transition(.15)
        true_belief *= cell.E[:, 0]
        true_belief /= true_belief.sum()
        hidden_before = estimator.hidden.copy()
        current_before = estimator.current.copy()
        planner = ExactBeliefDP(cell)
        dt = .45
        result = audit_deployed_policy(cell, estimator, true_belief, (dt,), 1, planner)
        successor = true_belief @ cell.transition(dt)
        expected = -.01*dt-successor @ cell.read_cost
        for token in range(7):
            branch_mass = successor*cell.E[:, token]
            if branch_mass.sum() > 0:
                branch = copy.deepcopy(estimator)
                branch.step(encode_observation(token, dt))
                action = planner.choose(branch.current, (), 0)
                expected += branch_mass @ cell.reward[:, int(action[-1])]
        self.assertAlmostEqual(result["actual_recurrent_q_pi"]["READ"], expected, places=13)
        np.testing.assert_array_equal(hidden_before, estimator.hidden)
        np.testing.assert_array_equal(current_before, estimator.current)
        self.assertGreater(np.max(np.abs(true_belief-estimator.current)), .01)
        self.assertLess(result["max_leaf_mass_error"], 2e-12)

    def test_hidden_state_preserved_for_both_ordinary_cores(self):
        for kind in ("gru", "continuous_diagonal_ssm"):
            model = RecurrentEstimator(kind, seed=23)
            result = run_policy_fixture(Cell(), model)
            self.assertTrue(result["original_state_unchanged"])
            self.assertGreater(result["read_branches"], 0)
            self.assertLess(result["max_leaf_mass_error"], 2e-12)
            self.assertGreaterEqual(min(result["continuation_policy_component"].values()), -2e-12)


if __name__ == "__main__":
    unittest.main()
