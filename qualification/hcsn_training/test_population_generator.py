"""Independent checks of the opt-in finite-volume transport, not science gates.

SciPy supplies an independent exponential, and the mean exit-time identity
checks the declared absorbing-boundary discretization against a continuum
solution. Neither establishes convergence of the complete nonlinear reset model.
"""

import math
import unittest

import numpy as np
from scipy.linalg import expm
import torch

from .population_generator import finite_volume_generator, finite_volume_transition


def reference_generator(edges, drift, sigma):
    """Assemble flux transfers face-by-face, including two absorbing accounts."""
    bins, width = len(edges)-1, edges[1]-edges[0]
    result = np.zeros((bins+2, bins+2))
    diffusion = sigma*sigma/(2*width*width)
    for face in range(1, bins):
        for source, destination, flow in ((face-1, face, drift[face]),
                                          (face, face-1, -drift[face])):
            rate = diffusion+max(flow, 0)/width
            result[source, source] -= rate
            result[source, destination] += rate
    for source, destination, flow in ((0, bins, -drift[0]),
                                      (bins-1, bins+1, drift[-1])):
        rate = 2*diffusion+max(flow, 0)/width
        result[source, source] -= rate
        result[source, destination] += rate
    return result


def full_transition(edges, drift, sigma, dt):
    active, hit, escaped = finite_volume_transition(edges, drift, sigma, dt)
    bins = len(edges)-1
    result = torch.eye(bins+2, dtype=edges.dtype)
    result[:bins] = torch.cat((active, hit[:, None], escaped[:, None]), dim=1)
    return result


class PopulationGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_batched_transition_matches_independent_face_flux_and_exponential(self):
        edges = torch.linspace(0, 2.5, 17, dtype=torch.float64)
        face_drift = torch.stack((.31-.47*edges, -1.7+.21*edges))
        active, hit, escaped = finite_volume_transition(edges, face_drift, .15, .137001)
        actual = torch.cat((active, hit[..., None], escaped[..., None]), -1)
        reference = np.stack([expm(.137001*reference_generator(edges.numpy(), drift.numpy(), .15))[:-2]
                              for drift in face_drift])
        np.testing.assert_allclose(actual.numpy(), reference, rtol=2e-12, atol=2e-14)
        torch.testing.assert_close(actual.sum(-1), torch.ones_like(hit), rtol=0, atol=2e-14)
        self.assertGreaterEqual(float(actual.min()), 0)
        generator = finite_volume_generator(edges, face_drift, .15)
        torch.testing.assert_close(generator.sum(-1), torch.zeros_like(generator[..., 0]), rtol=0, atol=1e-14)
        self.assertEqual(torch.count_nonzero(generator[..., -2:, :]).item(), 0)

    def test_fixed_generator_semigroup_includes_both_absorbing_accounts(self):
        edges = torch.linspace(0, 2.5, 33, dtype=torch.float64)
        drift = .31-.47*edges
        for first, second in ((.000001, .137001), (.001, .031007), (.137001, .301007)):
            with self.subTest(first=first, second=second):
                whole = full_transition(edges, drift, .15, first+second)
                split = full_transition(edges, drift, .15, first) @ full_transition(edges, drift, .15, second)
                # Torch matrix_exp uses different approximation branches around small
                # norms; the observed absolute FP64 residual is below 2e-12.
                torch.testing.assert_close(whole, split, rtol=0, atol=3e-12)

    def test_small_time_steps_preserve_nonzero_transport_on_fixed_spatial_grid(self):
        edges = torch.linspace(0, 2.5, 33, dtype=torch.float64)
        drift = torch.full_like(edges, -2)
        coarse = full_transition(edges, drift, .15, .8)
        fine = torch.linalg.matrix_power(full_transition(edges, drift, .15, .001), 800)
        torch.testing.assert_close(coarse, fine, rtol=2e-11, atol=2e-13)
        # The source is the centre nearest x=0.8; finer time slices must not
        # suppress its exit mass through repeated projection onto that centre.
        self.assertGreater(float(fine[10, 32]), .9)

    def test_drift_parameter_derivative_matches_finite_difference_away_from_upwind_kinks(self):
        edges = torch.linspace(0, 2.5, 17, dtype=torch.float64)
        parameter = torch.tensor(.31, dtype=torch.float64, requires_grad=True)
        weights = torch.linspace(.3, 1.7, 16, dtype=torch.float64)

        def objective(value):
            active, hit, escaped = finite_volume_transition(edges, value-.47*edges, .15, .137001)
            return ((active*weights).sum(-1)+2*hit+3*escaped).mean()

        gradient, = torch.autograd.grad(objective(parameter), parameter)
        epsilon = 1e-6
        with torch.no_grad():
            numerical = (objective(parameter+epsilon)-objective(parameter-epsilon))/(2*epsilon)
        self.assertTrue(math.isfinite(float(gradient)))
        self.assertGreater(abs(float(gradient)), 1e-6)
        self.assertAlmostEqual(float(gradient), float(numerical), delta=2e-9)

    def test_zero_drift_mean_exit_time_has_second_order_spatial_error(self):
        # D*u''=-1, u(0)=u(L)=0 gives u(x)=x*(L-x)/(2D).
        # The declared half-cell boundary flux has error h²/(8D).
        length, diffusion, errors = 2.5, .15**2/2, []
        for bins in (8, 16, 32):
            edges = torch.linspace(0, length, bins+1, dtype=torch.float64)
            generator = finite_volume_generator(edges, torch.zeros_like(edges), .15)
            mean = torch.linalg.solve(-generator[:bins, :bins], torch.ones(bins, dtype=torch.float64))
            centres = (edges[:-1]+edges[1:])/2
            exact = centres*(length-centres)/(2*diffusion)
            error = (mean-exact).numpy()
            expected = (length/bins)**2/(8*diffusion)
            np.testing.assert_allclose(error, expected, rtol=1e-10, atol=2e-12)
            errors.append(float(np.max(np.abs(error))))
        np.testing.assert_allclose(np.array(errors[:-1])/errors[1:], 4, rtol=1e-10, atol=0)


if __name__ == "__main__":
    unittest.main()
