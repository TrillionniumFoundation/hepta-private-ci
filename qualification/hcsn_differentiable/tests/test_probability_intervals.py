"""Regression for cancellation between survivor probabilities near one."""

import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import TrainablePhysics
from qualification.hcsn_differentiable.operator import (
    DifferentiableDistributionOperator, _killed_interval_probability, _normal_interval_logprob,
)


def tensor(value, grad=False):
    return torch.tensor(value, dtype=torch.float64, requires_grad=grad)


def integral(x, mu, sigma, duration, left, right, steps=4000):
    # Positive killed density: phi((y-x-mu*t)/s)/s * (1-exp(-2*x*y/s**2)).
    variance = sigma * sigma * duration
    def density(y):
        return (math.exp(-(y - x - mu * duration) ** 2 / (2 * variance))
                / math.sqrt(2 * math.pi * variance) * -math.expm1(-2 * x * y / variance))
    h = (right - left) / steps
    return h / 3 * (density(left) + density(right)
                    + math.fsum((4 if i % 2 else 2) * density(left + i * h) for i in range(1, steps)))


class ProbabilityIntervalTests(unittest.TestCase):
    def test_rare_left_bin_matches_eighty_digit_reference(self):
        p = TrainablePhysics().double().requires_grad_(False)()
        x, dt, right = float.fromhex("0x1.a502e0d34aa95p-1"), 0.0810876, 0.009375
        result = _killed_interval_probability(tensor(x), tensor(dt), p.mu, p.sigma, tensor(0), tensor(right))
        reference = 1.118858573369923048040421964063422109637e-16
        self.assertGreater(float(result), 0)
        self.assertAlmostEqual(float(result) / reference, 1, delta=2e-12)
        self.assertAlmostEqual(float(result) / integral(x, float(p.mu), float(p.sigma), dt, 0, right), 1, delta=2e-12)
        self.numerical_evidence = {"probability": float(result), "reference_80_digits": reference,
                                   "relative_error": abs(float(result) / reference - 1)}

    def test_normal_intervals_cover_cdf_sf_and_extreme_tails(self):
        for lower, upper in ((-12, -11.9), (-1.0, 0.2), (0.2, 1.0), (11.9, 12)):
            lo, hi = tensor(lower, True), tensor(upper, True)
            result = torch.exp(_normal_interval_logprob(lo, hi))
            expected = (0.5 * (math.erfc(-upper / math.sqrt(2)) - math.erfc(-lower / math.sqrt(2)))
                        if lower < 0 else 0.5 * (math.erfc(lower / math.sqrt(2)) - math.erfc(upper / math.sqrt(2))))
            self.assertAlmostEqual(float(result) / expected, 1, delta=3e-13)
            derivatives = torch.autograd.grad(result, (lo, hi))
            self.assertAlmostEqual(float(derivatives[0]) / (-math.exp(-lower ** 2 / 2) / math.sqrt(2 * math.pi)), 1, delta=3e-12)
            self.assertAlmostEqual(float(derivatives[1]) / (math.exp(-upper ** 2 / 2) / math.sqrt(2 * math.pi)), 1, delta=3e-12)

    def test_killed_intervals_and_first_order_gradients(self):
        for x, mu, sigma, dt, left, right in ((0.15, -0.12, 0.35, 0.05, 0, 0.2),
                                             (0.8, 0.2, 0.4, 0.3, 0.1, 0.6),
                                             (0.001, 0., 0.5, 1., 0, 0.1)):
            values = [tensor(v, True) for v in (x, mu, sigma)]
            result = _killed_interval_probability(values[0], tensor(dt), values[1], values[2], tensor(left), tensor(right))
            reference = integral(x, mu, sigma, dt, left, right)
            self.assertAlmostEqual(float(result) / reference, 1, delta=3e-10)
            derivatives = torch.autograd.grad(result, values)
            for index, derivative in enumerate(derivatives):
                estimates = []
                for sign in (-1, 1):
                    arguments = [v.detach().clone() for v in values]
                    arguments[index] += sign * 1e-5
                    estimates.append(_killed_interval_probability(arguments[0], tensor(dt), arguments[1], arguments[2], tensor(left), tensor(right)))
                fd = float((estimates[1] - estimates[0]) / 2e-5)
                self.assertAlmostEqual(float(derivative), fd, delta=3e-7 * max(1e-4, abs(fd)))

    def test_full_triggering_space_refinement_preserves_probability(self):
        p = TrainablePhysics().double().requires_grad_(False)()
        operator = DifferentiableDistributionOperator(GridSpec(active_cells=256, endpoint=2.4,
                    phase_cells=16, refractory=0.2, quadrature_order=32))
        table = operator(*p.tensors()[:4], 0.0810876, p.discount)
        self.assertGreaterEqual(float(table.matrix.min()), 0)
        self.assertLess(float((table.matrix.sum(-1) - 1).abs().max()), 5e-11)
        self.numerical_evidence = {"mass_residual": float((table.matrix.sum(-1) - 1).abs().max()),
                                   "minimum_probability": float(table.matrix.min()),
                                   "active_bin_profile": operator.configuration()["active_bin_probability"]}


if __name__ == "__main__":
    unittest.main()
