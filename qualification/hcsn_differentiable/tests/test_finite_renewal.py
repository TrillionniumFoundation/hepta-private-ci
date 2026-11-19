"""Independent convolution/occupation checks of the finite renewal law."""

import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import PhysicalParameters
from qualification.hcsn_differentiable.finite_renewal import finite_renewal_value
from qualification.hcsn_differentiable.regenerative import perpetual_value


def parameters(mu=-0.2, rho=0.3, grad=False):
    return PhysicalParameters(*(torch.tensor(value, dtype=torch.float64, requires_grad=grad)
                                for value in (0.0, mu, 0.4, math.exp(0.237), rho)))


def density(t, x, mu, sigma):
    if t <= 0:
        return 0.0
    return x / (sigma * math.sqrt(2 * math.pi * t ** 3)) * math.exp(
        -(x + mu * t) ** 2 / (2 * sigma * sigma * t))


def cdf(t, x, mu, sigma):
    if t <= 0:
        return 0.0
    return (0.5 * math.erfc((x + mu * t) / (sigma * math.sqrt(2 * t)))
            + math.exp(-2 * mu * x / sigma ** 2)
            * 0.5 * math.erfc((x - mu * t) / (sigma * math.sqrt(2 * t))))


def simpson(function, end, intervals=12000):
    step = end / intervals
    return step / 3 * (function(0) + function(end)
                       + math.fsum((4 if index % 2 else 2) * function(index * step)
                                   for index in range(1, intervals)))


class FiniteRenewalTests(unittest.TestCase):
    def test_second_event_matches_independent_convolution(self):
        p = parameters(mu=0.2)
        x, delay, horizon, xr = 0.15, 0.4, 0.7, 0.237
        result = finite_renewal_value(x, p, horizon=horizon, refractory=delay)
        active_horizon = horizon - delay
        reference = simpson(lambda s: density(s, x, 0.2, 0.4)
                            * cdf(active_horizon - s, xr, 0.2, 0.4), active_horizon)
        self.assertAlmostEqual(float(result.expected_events - result.first_hit_probability), reference, delta=3e-12)

    def test_counts_and_occupations_match_independent_integrals(self):
        p = parameters()
        x, delay, horizon, xr, rho = 0.15, 0.1, 1.3, 0.237, 0.3
        def rate(t):
            return math.fsum(density(t - k * delay, x + k * xr, -0.2, 0.4)
                             for k in range(int(t / delay) + 1))
        def active(t):
            window_count = math.fsum(cdf(t - k * delay, x + k * xr, -0.2, 0.4)
                                    - cdf(t - (k + 1) * delay, x + k * xr, -0.2, 0.4)
                                    for k in range(int(t / delay) + 1))
            return 1 - window_count
        result = finite_renewal_value(x, p, horizon=horizon, refractory=delay)
        m = simpson(rate, horizon)
        h = simpson(lambda t: math.exp(-rho * t) * rate(t), horizon)
        a = simpson(lambda t: math.exp(-rho * t) * active(t), horizon)
        r = simpson(lambda t: math.exp(-rho * t) * (1 - active(t)), horizon)
        for observed, expected in ((result.expected_events, m), (result.discounted_events, h),
                                    (result.discounted_active_time, a), (result.discounted_refractory_time, r)):
            self.assertAlmostEqual(float(observed), expected, delta=2e-10)

    def test_instantaneous_rate_is_derivative_of_cumulative_count(self):
        p = parameters()
        horizon, step = 1.13, 1e-5
        result = finite_renewal_value(0.15, p, horizon=horizon, refractory=0.1)
        low = finite_renewal_value(0.15, p, horizon=horizon - step, refractory=0.1)
        high = finite_renewal_value(0.15, p, horizon=horizon + step, refractory=0.1)
        derivative = (high.expected_events - low.expected_events) / (2 * step)
        self.assertAlmostEqual(float(result.event_rate), float(derivative), delta=2e-8)
        self.assertGreater(abs(float(result.event_rate - result.expected_events / horizon)), 0.01)

    def test_repeated_counts_are_distinct_from_first_hit_probability(self):
        result = finite_renewal_value(0.15, parameters(), horizon=10, refractory=0.1)
        self.assertGreater(float(result.expected_events), 1)
        self.assertGreater(float(result.discounted_events), float(result.discounted_first_hit))
        self.assertTrue(0 <= float(result.first_hit_probability) <= 1)
        self.assertTrue(0 <= float(result.active_probability) <= 1)
        self.assertLessEqual(float(result.discounted_events), float(result.expected_events))

    def test_long_horizon_agrees_with_independent_perpetual_solution(self):
        p = parameters(rho=1.2)
        finite = finite_renewal_value(0.15, p, horizon=30, refractory=0.1)
        perpetual = perpetual_value(0.15, p, refractory=0.1)
        self.assertAlmostEqual(float(finite.value), float(perpetual.regenerative_value), delta=2e-12)
        expected_discounted_count = perpetual.discounted_first_hit / perpetual.renewal_denominator
        self.assertAlmostEqual(float(finite.discounted_events), float(expected_discounted_count), delta=2e-12)

    def test_terminal_payment_once_and_zero_horizon(self):
        p = parameters()
        result = finite_renewal_value(0.15, p, horizon=1.3, refractory=0.1,
                                      active_reward=0, hit_reward=0, terminal_reward=2.5)
        self.assertAlmostEqual(float(result.value), 2.5 * math.exp(-0.3 * 1.3) * float(result.active_probability), delta=1e-14)
        zero = finite_renewal_value(0.15, p, horizon=0, refractory=0.1, terminal_reward=2.5)
        self.assertEqual(float(zero.value), 2.5)
        self.assertEqual(float(zero.expected_events), 0)
        self.assertEqual(float(zero.event_rate), 0)
        self.assertEqual(float(zero.active_probability), 1)
        # Queries do not create new terminal settlements at intermediate times.
        early = finite_renewal_value(0.15, p, horizon=0.65, refractory=0.1,
                                     active_reward=0, hit_reward=0, terminal_reward=2.5)
        self.assertGreater(float(early.value + result.value), float(result.value))

    def test_all_physical_gradients_against_finite_difference(self):
        p = parameters(grad=True)
        x = p.mu.new_tensor(0.15) - p.log_boundary
        result = finite_renewal_value(x, p, horizon=1.13, refractory=0.1)
        ad = torch.autograd.grad(result.value, p.tensors())
        for index, derivative in enumerate(ad):
            endpoints = []
            for sign in (-1, 1):
                values = [value.detach().clone() for value in p.tensors()]
                values[index] += sign * 1e-5
                candidate = PhysicalParameters(*values)
                endpoints.append(finite_renewal_value(0.15 - candidate.log_boundary, candidate,
                                                      horizon=1.13, refractory=0.1).value)
            fd = (endpoints[1] - endpoints[0]) / 2e-5
            self.assertAlmostEqual(float(derivative), float(fd), delta=2e-6 * max(1, abs(float(fd))))

    def test_delay_boundary_is_continuous(self):
        p = parameters()
        middle = finite_renewal_value(0.15, p, horizon=0.1, refractory=0.1)
        # At T=d the second-event term has zero active time and therefore zero mass.
        self.assertAlmostEqual(float(middle.expected_events), float(middle.first_hit_probability), delta=1e-14)
        low = finite_renewal_value(0.15, p, horizon=0.1 - 1e-7, refractory=0.1)
        high = finite_renewal_value(0.15, p, horizon=0.1 + 1e-7, refractory=0.1)
        self.assertLess(abs(float(high.value - low.value)), 2e-6)

    def test_invalid_and_unresolved_inputs_are_rejected(self):
        p = parameters()
        for horizon, delay in ((-1, 0.1), (1, 0), (1, -1), (1, 3), (409.6, 0.1)):
            with self.assertRaises(ValueError):
                finite_renewal_value(0.15, p, horizon=horizon, refractory=delay)
        with self.assertRaises(ValueError):
            finite_renewal_value(0, p, horizon=1, refractory=0.1)
        with self.assertRaises(ValueError):
            finite_renewal_value(0.15, p, horizon=torch.tensor(1.0, requires_grad=True), refractory=0.1)
        with self.assertRaises(FloatingPointError):
            finite_renewal_value(0.15, parameters(rho=0.001), horizon=1e-5, refractory=0.1)


if __name__ == "__main__":
    unittest.main()
