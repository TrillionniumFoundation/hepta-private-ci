"""Independent numerical and boundary checks of fixed-policy renewal values."""

from decimal import Decimal, localcontext
import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.regenerative import (
    basis_perpetual_value, first_hit_laplace, perpetual_value, refractory_value,
)


def parameters(mu=-0.12, sigma=0.4, rho=0.3, reset=1.5, boundary=0.0, grad=False):
    return PhysicalParameters(*(torch.tensor(value, dtype=torch.float64, requires_grad=grad)
                                for value in (boundary, mu, sigma, reset, rho)))


def simpson(function, a, b, intervals=12000):
    step = (b - a) / intervals
    total = function(a) + function(b)
    total += math.fsum((4 if i % 2 else 2) * function(a + i * step)
                       for i in range(1, intervals))
    return total * step / 3


class RegenerativeTests(unittest.TestCase):
    def test_laplace_matches_independent_first_passage_density_integral(self):
        for mu, sigma, rho, x in ((-0.12, 0.4, 0.3, 0.25), (0.3, 0.7, 0.1, 0.7),
                                  (0.0, 0.5, 1.2, 0.1)):
            # Integrate inverse-Gaussian density in log time; no operator F/G.
            def density_log_time(u):
                t = math.exp(u)
                return x / (sigma * math.sqrt(2 * math.pi * t)) * math.exp(
                    -(x + mu * t) ** 2 / (2 * sigma * sigma * t) - rho * t)
            reference = simpson(density_log_time, -20, 12)
            observed = float(first_hit_laplace(x, parameters(mu, sigma, rho)))
            self.assertAlmostEqual(observed, reference, delta=2e-12)

    def test_occupation_matches_independent_survival_integral(self):
        mu, sigma, rho, x = -0.12, 0.4, 0.3, 0.25
        def survival_log_time(u):
            t = math.exp(u)
            first = 0.5 * math.erfc((x + mu * t) / (sigma * math.sqrt(2 * t)))
            second = math.exp(-2 * mu * x / sigma ** 2) * 0.5 * math.erfc(
                (x - mu * t) / (sigma * math.sqrt(2 * t)))
            return math.exp(-rho * t) * (1 - first - second) * t
        reference = simpson(survival_log_time, -25, 12)
        value = perpetual_value(x, parameters(), refractory=0.1)
        self.assertAlmostEqual(float(value.discounted_active_time), reference, delta=2e-11)

    def test_renewal_boundary_and_generator_equation(self):
        p = parameters()
        x = torch.tensor(0.25, dtype=torch.float64, requires_grad=True)
        value = perpetual_value(x, p, refractory=0.1)
        derivative, = torch.autograd.grad(value.regenerative_value, x, create_graph=True)
        second, = torch.autograd.grad(derivative, x)
        residual = 0.5 * p.sigma.square() * second + p.mu * derivative - p.discount * value.regenerative_value + 0.4
        self.assertAlmostEqual(float(residual), 0.0, delta=2e-13)
        at_hit = perpetual_value(0.0, p, refractory=0.1).regenerative_value
        self.assertAlmostEqual(float(at_hit), float(1 + math.exp(-0.03) * value.reset_value), delta=1e-13)
        self.assertAlmostEqual(float(refractory_value(0.1, p, refractory=0.1)), float(at_hit - 1), delta=1e-13)
        self.assertAlmostEqual(float(perpetual_value(1e5, p, refractory=0.1).regenerative_value), 0.4 / 0.3)

    def test_explicit_cycle_sum_and_killed_control(self):
        p = parameters(rho=1.2)
        value = perpetual_value(0.2, p, refractory=0.1)
        reset = perpetual_value(torch.log(p.absolute_reset), p, refractory=0.1, reset_enabled=False)
        ratio = float(value.renewal_ratio)
        continuation = math.fsum(ratio ** n * float(reset.single_cycle_value) for n in range(1000))
        expected = float(value.single_cycle_value) + float(value.discounted_first_hit) * math.exp(-0.12) * continuation
        self.assertAlmostEqual(float(value.regenerative_value), expected, delta=1e-12)
        killed = perpetual_value(0.2, p, refractory=0.1, reset_enabled=False)
        self.assertTrue(torch.equal(killed.regenerative_value, killed.single_cycle_value))
        self.assertEqual(float(refractory_value(0.05, p, refractory=0.1, reset_enabled=False)), 0.0)

    def test_parameter_gradients_against_central_difference(self):
        p = parameters(grad=True)
        initial = p.mu.new_tensor(1.3)
        value = perpetual_value(torch.log(initial) - p.log_boundary, p, refractory=0.1)
        derivatives = torch.autograd.grad(value.regenerative_value, p.tensors())
        for index, derivative in enumerate(derivatives):
            estimates = []
            for sign in (-1, 1):
                numbers = [v.detach().clone() for v in p.tensors()]
                numbers[index] += sign * 1e-5
                perturbed = PhysicalParameters(*numbers)
                estimates.append(perpetual_value(torch.log(initial) - perturbed.log_boundary,
                                                 perturbed, refractory=0.1).regenerative_value)
            fd = (estimates[1] - estimates[0]) / 2e-5
            self.assertAlmostEqual(float(derivative), float(fd), delta=2e-7 * max(1, abs(float(fd))))

    def test_small_root_and_denominator_against_decimal(self):
        p = parameters(mu=-2.0, sigma=0.05, rho=0.001, reset=math.exp(0.0002))
        observed = perpetual_value(0.0001, p, refractory=0.0)
        with localcontext() as ctx:
            ctx.prec = 70
            mu, sigma, rho = (Decimal.from_float(float(v)) for v in (p.mu, p.sigma, p.discount))
            xr = Decimal.from_float(float(torch.log(p.absolute_reset)))
            x = Decimal.from_float(0.0001)
            root = (mu + (mu * mu + 2 * rho * sigma * sigma).sqrt()) / (sigma * sigma)
            g, gr = (-root * x).exp(), (-root * xr).exp()
            a = Decimal.from_float(0.4)
            c, cr = a * (1 - g) / rho + g, a * (1 - gr) / rho + gr
            reference = c + g * cr / (1 - gr)
        self.assertAlmostEqual(float(observed.regenerative_value) / float(reference), 1.0, delta=3e-15)
        self.assertGreater(float(observed.renewal_denominator), 0.0)

    def test_exact_basis_averages_and_coordinate_invariance(self):
        p = parameters()
        grid = GridSpec(active_cells=4, phase_cells=2)
        values = basis_perpetual_value(grid, p)
        for index, (lo, hi) in enumerate(zip(grid.active_edges[:-1], grid.active_edges[1:])):
            reference = simpson(lambda x: float(perpetual_value(x, p, refractory=grid.refractory).regenerative_value), lo, hi, 200)
            self.assertAlmostEqual(float(values[index]), reference / (hi - lo), delta=2e-10)
        tail_reference = simpson(lambda y: float(perpetual_value(grid.endpoint + y, p,
                                  refractory=grid.refractory).regenerative_value)
                                  * grid.tail_rate * math.exp(-grid.tail_rate * y), 0, 35, 6000)
        self.assertAlmostEqual(float(values[grid.active_cells]), tail_reference, delta=2e-10)
        phase_reference = simpson(lambda r: float(refractory_value(r, p, refractory=grid.refractory)), 0, 0.05, 100)
        self.assertAlmostEqual(float(values[-2]), phase_reference / 0.05, delta=1e-12)
        shifted = parameters(reset=1.5 * math.exp(0.4), boundary=0.4)
        self.assertTrue(torch.allclose(values, basis_perpetual_value(grid, shifted), atol=1e-13, rtol=0))
        killed = basis_perpetual_value(grid, p, reset_enabled=False)
        self.assertTrue(torch.equal(killed[-2:], torch.zeros(2, dtype=torch.float64)))

    def test_declared_extreme_values_remain_resolved(self):
        for mu, sigma, rho, reset, delay in ((-2, 0.05, 0.001, math.exp(0.0002), 0),
                                             (2, 0.05, 4, math.exp(7.5), 2),
                                             (0, 2, 0.001, 1.3, 0.1),
                                             (0, 0.05, 4, 1.3, 0.1)):
            p = parameters(mu, sigma, rho, reset)
            value = perpetual_value(0.1, p, refractory=delay)
            self.assertTrue(torch.isfinite(value.regenerative_value))
            self.assertGreater(float(value.renewal_denominator), 0)
            self.assertGreaterEqual(float(value.regenerative_value), float(value.single_cycle_value))
            self.assertTrue(0 <= float(value.discounted_first_hit) <= 1)

    def test_invalid_domains_fail_without_silent_repairs(self):
        with self.assertRaises(ValueError):
            perpetual_value(-0.1, parameters(), refractory=0.1)
        with self.assertRaises(ValueError):
            perpetual_value(0.1, parameters(rho=0), refractory=0.1)
        with self.assertRaises(ValueError):
            perpetual_value(0.1, parameters(), refractory=-1)
        with self.assertRaises(ValueError):
            perpetual_value(0.1, parameters(), refractory=0.1, active_reward=float("nan"))
        with self.assertRaises(ValueError):
            refractory_value(0.2, parameters(), refractory=0.1)



class FirstHitRegimeTests(unittest.TestCase):
    """Independent undiscounted controls for the signed drift regimes."""

    def test_three_drift_regimes_and_long_run_rate(self):
        from qualification.hcsn_differentiable.regenerative import first_hit_regime
        x, delay = 0.3, 0.1
        negative = first_hit_regime(x, parameters(mu=-0.2), refractory=delay)
        self.assertEqual(negative.drift_regime, "negative")
        self.assertEqual(negative.eventual_hit_probability, 1.0)
        self.assertAlmostEqual(negative.mean_first_hit_time, 1.5)
        self.assertAlmostEqual(
            negative.long_run_event_rate,
            1.0 / (delay + math.log(1.5) / 0.2),
            delta=1e-14,
        )
        zero = first_hit_regime(x, parameters(mu=0.0), refractory=delay)
        self.assertEqual(zero.drift_regime, "zero")
        self.assertEqual(zero.eventual_hit_probability, 1.0)
        self.assertTrue(math.isinf(zero.mean_first_hit_time))
        self.assertEqual(zero.long_run_event_rate, 0.0)
        positive = first_hit_regime(x, parameters(mu=0.2), refractory=delay)
        self.assertEqual(positive.drift_regime, "positive")
        self.assertAlmostEqual(
            positive.eventual_hit_probability,
            math.exp(-2 * 0.2 * x / 0.4 ** 2),
            delta=1e-15,
        )
        self.assertTrue(math.isinf(positive.mean_first_hit_time))
        self.assertEqual(positive.long_run_event_rate, 0.0)
        self.assertLess(float(first_hit_laplace(x, parameters(mu=0.2))), positive.eventual_hit_probability)

    def test_log_rare_hit_survives_probability_underflow(self):
        from qualification.hcsn_differentiable.regenerative import first_hit_regime
        reported = first_hit_regime(8.0, parameters(mu=2.0, sigma=0.05), refractory=0.1)
        self.assertEqual(reported.eventual_hit_probability, 0.0)
        self.assertAlmostEqual(reported.log_eventual_hit_probability, -12800.0, places=5)
        self.assertTrue(math.isfinite(reported.log_eventual_hit_probability))
        self.assertGreater(reported.reset_eventual_hit_probability, 0.0)

    def test_boundary_immediate_hit_and_invalid_inputs(self):
        from qualification.hcsn_differentiable.regenerative import first_hit_regime
        now = first_hit_regime(0.0, parameters(mu=0.2), refractory=0.1)
        self.assertEqual(now.eventual_hit_probability, 1.0)
        self.assertEqual(now.mean_first_hit_time, 0.0)
        with self.assertRaises(ValueError):
            first_hit_regime(-0.1, parameters(), refractory=0.1)
        with self.assertRaises(ValueError):
            first_hit_regime(torch.tensor([0.1, 0.2], dtype=torch.float64),
                             parameters(), refractory=0.1)
        with self.assertRaises(ValueError):
            first_hit_regime(0.2, parameters(), refractory=-0.1)


if __name__ == "__main__":
    unittest.main()
