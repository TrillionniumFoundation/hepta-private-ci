"""Behavioral/numerical contract tests, independent of the frozen case report."""

import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

from experiments.first_passage_operator.free_boundary import NaturalSpikeSpec
from experiments.first_passage_deadline.policy import evaluate_policy, killed_matrix
from experiments.first_passage_deadline.qvi import solve_deadline, state_grid


def reference_killed(spec, x, y, boundary, duration):
    scale = spec.sigma * math.sqrt(duration)
    first = math.exp(-.5 * ((y - x - spec.mu * duration) / scale) ** 2)
    second = math.exp(2 * spec.mu * (boundary - x) / spec.sigma ** 2
                      - .5 * ((y - 2 * boundary + x - spec.mu * duration) / scale) ** 2)
    return (first - second) / (math.sqrt(2 * math.pi) * scale)


def reference_hit_weight(spec, distance, duration):
    zeta = math.sqrt(spec.mu ** 2 + 2 * spec.discount * spec.sigma ** 2)
    scale = spec.sigma * math.sqrt(duration)
    return (math.exp((spec.mu - zeta) * distance / spec.sigma ** 2)
            * ndtr((zeta * duration - distance) / scale)
            + math.exp((spec.mu + zeta) * distance / spec.sigma ** 2)
            * ndtr((-zeta * duration - distance) / scale))


def single_segment_reference(spec, x, boundary, duration):
    if x >= boundary:
        return x - spec.spike_cost
    terminal = quad(
        lambda y: reference_killed(spec, x, y, boundary, duration)
        * max(y - spec.spike_cost, 0), spec.spike_cost, boundary,
        epsabs=2e-13, epsrel=2e-12,
    )[0]
    return (math.exp(-spec.discount * duration) * terminal
            + (boundary - spec.spike_cost) * reference_hit_weight(spec, boundary - x, duration))


class DeadlineContractTests(unittest.TestCase):
    def setUp(self):
        self.spec = NaturalSpikeSpec(.12, .45, 0., .2, .2, .6)

    def test_single_segment_matches_independent_image_integral(self):
        policy = evaluate_policy(self.spec, .1, [.6, 1.0], dt=.1, dx=.02)
        for x in [.2, .603, .803, .999]:
            expected = single_segment_reference(self.spec, x, 1.0, .1)
            self.assertAlmostEqual(policy.value(.1, x), expected, delta=3e-11)
        self.assertLess(policy.diagnostics["mass_defect_max"], 2e-10)

    def test_boundary_lowering_uses_current_state_for_immediate_atom(self):
        spec = NaturalSpikeSpec(.12, .45, 0., .4, .2, .6)
        policy = evaluate_policy(spec, .2, [.6, .75, 1.15], dt=.1, dx=.01)
        self.assertAlmostEqual(policy.value(.1, .9), .3, delta=1e-14)
        x = .9
        terminal = quad(
            lambda y: reference_killed(spec, x, y, 1.15, .1)
            * single_segment_reference(spec, y, .75, .1),
            .1, 1.15, points=[.6, .75], epsabs=1e-11,
        )[0]
        expected = (math.exp(-spec.discount * .1) * terminal
                    + (1.15 - spec.spike_cost) * reference_hit_weight(spec, 1.15 - x, .1))
        self.assertAlmostEqual(policy.value(.2, x), expected, delta=5e-5)
        missed_atom_premium = quad(
            lambda y: reference_killed(spec, x, y, 1.15, .1) * (y - .75),
            .75, 1.15, epsabs=1e-13,
        )[0]
        self.assertGreater(missed_atom_premium, .05)

    def test_off_grid_refractory_release_and_terminal_hold(self):
        spec = NaturalSpikeSpec(.12, .45, .6, .2, .2, .6)
        policy = evaluate_policy(spec, .2, [.6, 1.0, 1.15], dt=.1, dx=.02)
        expected = math.exp(-spec.discount * .073) * single_segment_reference(spec, .6, 1.0, .067)
        self.assertAlmostEqual(policy.value(.14, .6, .073), expected, delta=3e-11)
        self.assertEqual(policy.value(.05, .6, .1), 0.0)
        self.assertEqual(policy.value(.1, .6, .1), 0.0)
        with self.assertRaises(ValueError):
            policy.value(.14, .7, .073)

    def test_short_partial_step_keeps_mass_without_normalization(self):
        x, _, _ = state_grid(self.spec, .02, 1e-8)
        matrix, checks = killed_matrix(self.spec, [.7, .9, .999], x, 1.0, 1e-6)
        self.assertGreaterEqual(matrix.data.min(), 0.0)
        self.assertLess(checks["mass_defect"], 2e-10)
        self.assertEqual(checks["negative_weight_mass"], 0.0)

    def test_lcp_upper_ray_residual_and_positive_drift_terminal_jump(self):
        solution = solve_deadline(self.spec, .2, dt=.01, dx=.02)
        self.assertLess(solution.diagnostics["complementarity_residual_max"], 5e-10)
        self.assertLessEqual(solution.boundaries.max(), .6 + 1 / self.spec.exponent + .02)
        self.assertEqual(solution.boundaries[0], .6)
        self.assertGreaterEqual(solution.boundaries[1], .6 + .12 / .2 - .02)
        self.assertLessEqual(solution.diagnostics["lower_truncation_value_bound"], 1e-8)
        self.assertEqual(solution.value(0., 1.), .4)
        self.assertEqual(solution.value(.05, 0., .1), 0.0)

    def test_non_aligned_or_refractory_sized_steps_are_rejected(self):
        with self.assertRaises(ValueError):
            solve_deadline(self.spec, .2, dt=.2)
        with self.assertRaises(ValueError):
            solve_deadline(self.spec, .3, dt=.03)


if __name__ == "__main__":
    unittest.main()
