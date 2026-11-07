"""Short-time positive quadrature: independent values and scale-aware gradients."""

import math
import unittest

from scipy.integrate import quad
import torch

from qualification.hcsn_regenerative.audit import (
    five_point_derivative, hit_integral, survivor_integral,
)
from qualification.hcsn_regenerative import process as scalar
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset, finite_horizon_value


DEVICES = ("cpu", "cuda") if torch.cuda.is_available() else ("cpu",)
DTYPES = (torch.float32, torch.float64)


def positive_occupation(x, horizon, mu, sigma, discount, *, discount_derivative=False):
    """Integrate an independent positive killed density, in dimensionless time.

    The outer integral is O(1), so its tolerance remains meaningful when the
    final physical occupation is O(1e-8). No difference of discounted hits is
    used as an oracle; the inner survivor integral is itself nonnegative.
    """
    def integrand(u):
        if u == 0:
            return 0.
        time = horizon*u*u
        weight = 2*u*math.exp(-discount*time)
        if discount_derivative:
            weight *= -u*u
        return weight*survivor_integral(x, time, mu, sigma)
    result, error = quad(integrand, 0., 1., epsabs=1e-12, epsrel=1e-12, limit=200)
    if error > 1e-10*abs(result)+2e-12:
        raise ArithmeticError("positive occupation oracle unresolved")
    return result*horizon**(2 if discount_derivative else 1)


def inputs(values, dtype, device, gradients=False):
    return [torch.tensor(v, dtype=dtype, device=device, requires_grad=gradients) for v in values]


class ShortTensorTests(unittest.TestCase):
    def assert_relative(self, actual, expected, tolerance, label):
        actual = float(actual.detach().cpu()) if isinstance(actual, torch.Tensor) else float(actual)
        self.assertTrue(math.isfinite(actual), msg=label)
        self.assertLessEqual(abs(actual-expected), tolerance*abs(expected)+1e-20, msg=label)

    def test_tiny_and_preexisting_short_horizon_positive_values(self):
        for x, horizon in ((1e-5, 1e-6), (1e-4, 1e-4)):
            expected = positive_occupation(x, horizon, -.1, .3, .15)
            for device in DEVICES:
                for dtype in DTYPES:
                    xx, tt, mu, sigma, q = inputs((x, horizon, -.1, .3, .15), dtype, device)
                    p = TensorDiffusion(mu, sigma, q)
                    result = finite_horizon_value(p, TensorReset(.25, .11, 0.), xx, tt, active_reward=1.)
                    tolerance = 2e-5 if dtype == torch.float32 else 1e-8
                    self.assert_relative(result.active_time, expected, tolerance, f"{device}/{dtype}/I")
                    self.assert_relative(result.regenerative, expected, tolerance, f"{device}/{dtype}/U")
                    self.assertEqual(result.regenerative.dtype, dtype)
                    self.assertGreater(float(result.active_time.cpu()), 0.)
                    self.assertTrue(bool(torch.isfinite(result.quadrature_error)))
                    self.assertLessEqual(float(p.discounted_hit(xx, tt).cpu()), float(p.hit_probability(xx, tt).cpu()))

    def test_tiny_occupation_gradients_against_positive_oracles(self):
        values = [1e-5, 1e-6, -.1, .3, .15]
        expected = []
        for index, step in ((0, 1e-7), (2, 1e-3), (3, 1e-4)):
            def evaluate(v):
                arguments = values.copy()
                arguments[index] = v
                return positive_occupation(*arguments)
            full = five_point_derivative(evaluate, values[index], step)
            half = five_point_derivative(evaluate, values[index], step/2)
            self.assert_relative(full, half, 1e-6, f"oracle refinement {index}")
            expected.append((index, half))
        expected += [(1, math.exp(-values[4]*values[1])*survivor_integral(*values[:4])),
                     (4, positive_occupation(*values, discount_derivative=True))]
        for device in DEVICES:
            for dtype in DTYPES:
                z = inputs(values, dtype, device, True)
                result = finite_horizon_value(TensorDiffusion(*z[2:]), TensorReset(.25, .11, 0.),
                                               *z[:2], active_reward=1.)
                derivatives = torch.autograd.grad(result.active_time, z)
                tolerance = 1e-3 if dtype == torch.float32 else 1e-7
                for index, oracle in expected:
                    self.assert_relative(derivatives[index], oracle, tolerance,
                                         f"{device}/{dtype}/occupation gradient {index}")

    def test_tiny_discounted_hit_gradients_against_density_scores(self):
        x, horizon, mu, sigma, q = values = [1e-5, 1e-6, -.1, .3, .15]
        expected = {index: hit_integral(x, horizon, mu, sigma, q, derivative=name).value
                    for index, name in ((0, "x"), (2, "mu"), (3, "sigma"))}
        # Scale the q score by T before integrating. The existing general
        # density-score oracle has an absolute tolerance too loose to certify
        # a 1e-8-sized derivative to a 1e-7 relative tolerance.
        radius, drift = x/(sigma*math.sqrt(horizon)), mu*math.sqrt(horizon)/sigma
        def q_score(u):
            if u == 0:
                return 0.
            return (-2*radius/math.sqrt(2*math.pi)
                    *math.exp(-.5*(radius/u+drift*u)**2-q*horizon*u*u))
        scaled, error = quad(q_score, 0., 1., epsabs=1e-12, epsrel=1e-12, limit=200)
        self.assertLess(error, 1e-9*abs(scaled))
        expected[4] = horizon*scaled
        expected[1] = (math.exp(-q*horizon)*x/(sigma*math.sqrt(2*math.pi)*horizon**1.5)
                       *math.exp(-(x+mu*horizon)**2/(2*sigma*sigma*horizon)))
        for device in DEVICES:
            for dtype in DTYPES:
                z = inputs(values, dtype, device, True)
                hit = TensorDiffusion(*z[2:]).discounted_hit(*z[:2])
                derivatives = torch.autograd.grad(hit, z)
                tolerance = 2e-3 if dtype == torch.float32 else 1e-7
                for index, oracle in expected.items():
                    self.assert_relative(derivatives[index], oracle, tolerance,
                                         f"{device}/{dtype}/discounted-hit gradient {index}")

    def test_exact_release_and_binary_representable_remaining_horizon(self):
        refractory, remaining = .125, 2.**-20
        expected = math.exp(-.15*refractory)*positive_occupation(.25, remaining, -.1, .3, .15)
        for device in DEVICES:
            for dtype in DTYPES:
                p = TensorDiffusion(*inputs((-.1, .3, .15), dtype, device))
                reset = TensorReset(.25, refractory, 0.)
                at = finite_horizon_value(p, reset, 0., refractory, active_reward=1.)
                after = finite_horizon_value(p, reset, 0., refractory+remaining, active_reward=1.)
                self.assertEqual(float(at.active_time.cpu()), 0.)
                self.assert_relative(after.active_time, expected, 2e-6 if dtype == torch.float32 else 1e-10,
                                     f"{device}/{dtype}/release occupation")

    def test_short_subset_preserves_batched_graph_and_other_cells(self):
        expected_short = positive_occupation(1e-5, 1e-6, -.1, .3, .15)
        expected_long = scalar.finite_horizon_value(scalar.KilledDiffusion(-.1, .3, .15),
                                                    scalar.ResetRule(.25, .11, 0.), .35, 1.4,
                                                    active_reward=1.).active_time
        for device in DEVICES:
            for dtype in DTYPES:
                x = torch.tensor([1e-5, .35], dtype=dtype, device=device, requires_grad=True)
                horizon = torch.tensor([1e-6, 1.4], dtype=dtype, device=device, requires_grad=True)
                p = TensorDiffusion(*inputs((-.1, .3, .15), dtype, device))
                result = finite_horizon_value(p, TensorReset(.25, .11, 0.), x, horizon, active_reward=1.)
                self.assertEqual(tuple(result.quadrature_error.shape), (2,))
                self.assert_relative(result.active_time[0], expected_short, 2e-5, "short batch cell")
                self.assert_relative(result.active_time[1], expected_long, 3e-5, "long batch cell")
                derivatives = torch.autograd.grad(result.active_time.sum(), (x, horizon))
                self.assertTrue(all(bool(torch.isfinite(v).all()) for v in derivatives))

    def test_unresolved_short_survivor_scale_rejects(self):
        for device in DEVICES:
            p = TensorDiffusion(*inputs((-.1, .3, .15), torch.float32, device))
            with self.assertRaisesRegex(FloatingPointError, "short survivor scale unresolved"):
                finite_horizon_value(p, TensorReset(.25, .11), 1e-8, 1e-3)


if __name__ == "__main__":
    unittest.main()
