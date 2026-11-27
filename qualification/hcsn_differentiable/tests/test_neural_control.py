"""Regenerative optimal control: interface, task gradients and policy oracle."""

import unittest

import torch

from qualification.hcsn_differentiable.finite_renewal import finite_renewal_value
from qualification.hcsn_differentiable.neural_control import (
    optimal_boundary, optimal_value, physical_parameters, policy_value, refractory_value)
from qualification.hcsn_differentiable.neural_control_study import TASKS, run_study


class NeuralControlTests(unittest.TestCase):
    def test_independent_optimum_and_learning(self):
        result = run_study()
        self.assertEqual(result["failures"], [])

    def test_optimal_value_parameter_gradient(self):
        theta = torch.tensor(TASKS[0], dtype=torch.float64, requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(
            lambda x: optimal_value(torch.tensor([.7, 1., 1.5], dtype=torch.float64), x),
            (theta,), eps=1e-6, atol=2e-6, rtol=2e-5))

    def test_shared_first_passage_reset_and_refractory_contract(self):
        theta = torch.tensor(TASKS[0], dtype=torch.float64)
        boundary = optimal_boundary(theta)
        params = physical_parameters(boundary, theta)
        renewal = finite_renewal_value(theta[3]-boundary, params, horizon=4.,
                                      refractory=float(theta[4]))
        self.assertGreater(float(renewal.expected_events), float(renewal.first_hit_probability))
        reset = policy_value(theta[3], boundary, theta)
        torch.testing.assert_close(refractory_value(0., boundary, theta), reset)
        torch.testing.assert_close(policy_value(boundary, boundary, theta),
                                   -theta[7]+refractory_value(theta[4], boundary, theta))

    def test_reject_unsupported_optimum_and_reward_domain(self):
        for index, value in ((1, 0.), (2, 0.), (4, 0.), (5, 0.), (6, -1.), (7, 100.)):
            theta = torch.tensor(TASKS[0], dtype=torch.float64)
            theta[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                optimal_boundary(theta)


if __name__ == "__main__":
    unittest.main()
