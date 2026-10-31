"""Independent Brownian law, complete successor and gradient checks."""

import unittest

import numpy as np
import torch

from .kernel_audit import analytic_checks, gradient_checks, refinement_checks
from .kernels import BrownianEventDynamics, gaussian_events, gaussian_propagate


class KernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_independent_integrals_and_gaussian_equivalence(self):
        result = analytic_checks()
        self.assertLess(result["maximum_bin_error"], 2e-11)
        self.assertLess(result["maximum_flux_error"], 2e-11)
        self.assertLess(result["maximum_mass_error"], 2e-11)
        self.assertLess(result["low_noise"]["absolute_error"], 1e-12)
        self.assertLess(result["tails"]["maximum_relative_error"], 2e-12)
        self.assertEqual(result["gaussian_probit_maximum_difference"], 0.)

    def test_complete_successor_nonlinear_loss_and_gradient(self):
        for record in gradient_checks():
            self.assertLess(record["enumeration_error"], 2e-12)
            self.assertLess(record["maximum_gradient_error"], 2e-7)
            self.assertGreater(abs(record["jensen_difference"]), 1e-6)

    def test_refinement_and_physical_recovery(self):
        result = refinement_checks()
        errors = [r["maximum_event_error"] for r in result["projected_successor_refinement"][:4]]
        self.assertTrue(all(a > b for a, b in zip(errors, errors[1:])))
        self.assertLess(max(r["cohort_error"] for r in result["physical_recovery"]), 2e-13)
        self.assertLess(max(r["max_difference_from_order_16"][2] for r in result["image_order"]), 2e-12)

    def test_unbounded_gaussian_semigroup_and_atom(self):
        for leak in (0., .35):
            m, v = gaussian_propagate(.2, .1, 1.2, .45, .4, leak=leak)
            actual = gaussian_propagate(m, v, 1.2, .45, .6, leak=leak)
            expected = gaussian_propagate(.2, .1, 1.2, .45, 1., leak=leak)
            np.testing.assert_allclose([float(x) for x in actual], [float(x) for x in expected], atol=1e-14, rtol=1e-14)
        np.testing.assert_array_equal(gaussian_events(torch.tensor([-1., 0., 1.]), 0., 0., 0.).numpy(),
                                      [[1., 0., 0.], [1., 0., 0.], [0., 0., 1.]])
        leak = torch.tensor(0., dtype=torch.float64, requires_grad=True)
        mean, variance = gaussian_propagate(.2, .1, 1.2, .45, 1., leak=leak)
        derivative = torch.autograd.grad(mean + variance, leak)[0]
        self.assertAlmostEqual(float(derivative), -.2 - 1.2 / 2 - .2 - .45**2, places=13)

    def test_reset_is_complete_successor_and_new_event_cannot_release(self):
        cell = BrownianEventDynamics("first_passage", 7)
        transition, rewards = cell.transition_matrix(torch.tensor([1.], dtype=torch.float64), .7)
        np.testing.assert_allclose(transition.detach().sum(-1).numpy(), 1., atol=2e-12)
        np.testing.assert_allclose(transition[0, :7, -2:].detach().numpy(), rewards[0, :7].detach().numpy(), atol=1e-14)
        q = -torch.expm1(-cell.physical_parameters()["recovery_rate"] * .7)
        np.testing.assert_allclose(transition[0, -2:, :7].detach().numpy(),
                                   (q * torch.stack(cell.reset_distributions())).detach().numpy(), atol=1e-14)
        np.testing.assert_array_equal(rewards[0, -2:].detach().numpy(), np.zeros((2, 2)))


if __name__ == "__main__":
    unittest.main()
