"""Independent renewal, conservation, semigroup, and derivative checks."""

import unittest

import torch

from .distributional_flow import (Grid, exact_renewal_moments, generator,
                                   gradient_audit, initial_state, moments, project_values,
                                   propagate, renewal_count)
from .oracle import OracleParams


class DistributionalFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_conservative_nonnegative_generator_and_repeated_events(self):
        for drift, tau in ((0.3, 0.2), (-0.3, 0.2), (0.3, 0.0)):
            flow = generator(drift, 0.8, 1.1, -0.2, tau, Grid(48, -4, 8))
            Q = flow["Q"]
            torch.testing.assert_close(Q.sum(0), torch.zeros(Q.shape[0], dtype=Q.dtype),
                                       rtol=0, atol=1e-12)
            off_diagonal = Q - torch.diag(torch.diag(Q))
            self.assertGreaterEqual(off_diagonal.min().item(), 0)
            state = propagate(flow, initial_state(flow, 0.1), 4)
            result = moments(flow, state)
            self.assertAlmostEqual(float(result["mass"]), 1, places=11)
            self.assertGreaterEqual(float(result["minimum_probability"]), -1e-13)
            self.assertGreater(float(result["variance"]), 0.1)
            if drift > 0:
                self.assertGreater(float(result["events"]), 1)

    def test_same_grid_semigroup_preserves_counts_and_variance(self):
        flow = generator(0, 1, 1, 0, 0.2, Grid(64, -4, 16))
        start = initial_state(flow, 0)
        once = propagate(flow, start, 1)
        for count in (4, 16, 64, 256):
            split = propagate(flow, start, 1, count)
            torch.testing.assert_close(split, once, rtol=1e-10, atol=1e-11)
            result = moments(flow, split)
            self.assertGreater(float(result["events"]), 0.25)
            self.assertGreater(float(result["variance"]), 0.3)

    def test_independent_renewal_moments_include_instant_reset_and_negative_drift(self):
        for mu, tau in ((0.0, 0.2), (-0.3, 0.2), (0.2, 0.0)):
            params = OracleParams(mu=mu, sigma=0.8, rho=0.4, K=0.4, r=-0.2, tau=tau)
            expected = exact_renewal_moments(0.1, 1, params, 2)
            flow = generator(mu, 0.8, 1, -0.2, tau, Grid(192, -4, 64))
            actual = moments(flow, propagate(flow, initial_state(flow, 0.1), 2))
            for key in ("events", "mean", "variance"):
                self.assertLess(abs(float(actual[key]) - expected[key]), 0.04,
                                (mu, tau, key, float(actual[key]), expected[key]))

    def test_five_parameter_gradients_against_centered_finite_differences(self):
        for name, result in gradient_audit().items():
            self.assertLess(result["relative_error"], 2e-4, (name, result))
            self.assertGreater(abs(result["autograd"]), 1e-7, (name, result))

    def test_initial_hit_atom_and_zero_delay_have_conservative_mass(self):
        for tau in (0.0, 0.3):
            flow = generator(-0.2, 0.7, 1, -0.2, tau, Grid(40, -3, 8))
            state = initial_state(flow, 1.1)
            result = moments(flow, state)
            self.assertEqual(float(result["events"]), 1)
            self.assertAlmostEqual(float(result["mean"]), -0.2, places=12)
            self.assertAlmostEqual(float(result["mass"]), 1, places=12)
            self.assertEqual(float(result["refractory_mass"]), 1 if tau else 0)
            params = OracleParams(mu=-0.2, sigma=0.7, rho=0.4, K=0.4, r=-0.2, tau=tau)
            self.assertEqual(renewal_count(1.1, 1, params, 0), 1)

    def test_phase_aware_value_projection_preserves_mean_and_gradients(self):
        flow = generator(0.3, 0.8, 1.1, -0.2, 0.3, Grid(40, -3, 8))
        state = propagate(flow, initial_state(flow, 0.1), 2)
        with self.assertRaises(ValueError):
            project_values(flow, state, flow["points"])
        phase = flow["points"].new_full((8,), -0.2)
        expected_mean = project_values(flow, state, flow["points"], phase)
        torch.testing.assert_close(expected_mean, moments(flow, state)["mean"])
        features = torch.stack((flow["points"], flow["points"].square()), -1).requires_grad_()
        phase_features = torch.stack((phase, phase.square()), -1).requires_grad_()
        projected = project_values(flow, state, features, phase_features)
        projected.sum().backward()
        self.assertGreater(features.grad.abs().sum().item(), 0)
        self.assertGreater(phase_features.grad.abs().sum().item(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
