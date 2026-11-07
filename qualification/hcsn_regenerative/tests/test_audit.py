"""Independent numerical challenges, separate from production algebra tests."""

import math
import unittest

from qualification.hcsn.reference import HXParams, hx_boundary
from qualification.hcsn_regenerative.audit import (
    five_point_derivative, hit_integral, pde_value, stationary_hx_pde, survivor_integral,
)
from qualification.hcsn_regenerative.process import (
    KilledDiffusion, ResetRule, finite_horizon_value, stationary_hx_value,
)


class RegenerativeAuditTests(unittest.TestCase):
    def test_positive_integral_in_tail_and_at_low_noise(self):
        for args in [(4, .5, .2, .2, .1), (.12, .8, -.2, .015, .1),
                     (1e-5, 1e-5, -.2, .2, .1)]:
            with self.subTest(args=args):
                x, time, mu, sigma, q = args
                oracle = hit_integral(*args)
                candidate = KilledDiffusion(mu, sigma, q).discounted_hit(x, time)
                self.assertGreater(oracle.value, 0)
                self.assertLess(abs(math.log(candidate) - oracle.log_absolute_value), 1e-9)
        self.assertEqual(hit_integral(0, 0, -.1, .2).value, 1)
        self.assertEqual(hit_integral(.1, 0, -.1, .2).value, 0)
        with self.assertRaises(ValueError):
            hit_integral(0, 1, -.1, .2, derivative="x")

    def test_integrated_density_scores_against_function_derivatives(self):
        point = [.4, 1, -.2, .3, .1]
        for field, index in [("x", 0), ("mu", 2), ("sigma", 3), ("discount", 4)]:
            with self.subTest(field=field):
                def candidate(value):
                    p = point.copy()
                    p[index] = value
                    return KilledDiffusion(p[2], p[3], p[4]).discounted_hit(p[0], p[1])
                oracle = hit_integral(*point, derivative=field).value
                difference = five_point_derivative(candidate, point[index], 1e-5)
                self.assertLess(abs(oracle - difference), 2e-8)

    def test_killed_bins_and_explicit_upper_tail(self):
        process = KilledDiffusion(.4, .25, .1)
        edges = [0, .2, .6, 1.0]
        transition = process.transition(.8, .9, edges)
        oracle_bins = [survivor_integral(.8, .9, .4, .25, a, b)
                       for a, b in zip(edges[:-1], edges[1:])]
        for candidate, oracle in zip(transition.survivor_bins, oracle_bins):
            self.assertLess(abs(candidate - oracle), 2e-12)
        oracle_tail = survivor_integral(.8, .9, .4, .25, 1, math.inf)
        self.assertGreater(oracle_tail, .5)
        self.assertLess(abs(transition.upper_tail - oracle_tail), 2e-12)
        hit = hit_integral(.8, .9, .4, .25).value
        self.assertLess(abs(sum(oracle_bins) + oracle_tail + hit - 1), 3e-12)

    def test_refinement_of_killed_and_regenerative_values(self):
        args = dict(x=.35, horizon=1.4, mu=-.1, sigma=.3, discount=.15,
                    margin=.25, refractory=.11, active_reward=.4, terminal_reward=.2)
        expected = finite_horizon_value(KilledDiffusion(-.1, .3, .15), ResetRule(.25, .11),
                                        .35, 1.4, active_reward=.4, terminal_reward=.2)
        coarse = pde_value(**args, space_step=.01, time_step=.01)
        fine = pde_value(**args, space_step=.0025, time_step=.00125)
        for key in ("single_cycle", "regenerative"):
            fine_error = abs(getattr(fine, key) - getattr(expected, key))
            coarse_error = abs(getattr(coarse, key) - getattr(expected, key))
            self.assertLess(fine_error, 3e-4)
            self.assertLess(fine_error, coarse_error)

    def test_short_horizon_and_low_noise_require_resolved_grids(self):
        args = dict(x=.12, horizon=.8, mu=-.2, sigma=.015, discount=.1,
                    margin=.08, refractory=.07)
        candidate = finite_horizon_value(KilledDiffusion(-.2, .015, .1), ResetRule(.08, .07), .12, .8)
        coarse = pde_value(**args, domain=.8, space_step=.01, time_step=.004)
        fine = pde_value(**args, domain=.8, space_step=.00025, time_step=.0005)
        self.assertGreater(abs(coarse.single_cycle - candidate.single_cycle), .1)
        self.assertEqual(coarse.drift_scheme, "monotone_upwind")
        self.assertEqual(fine.drift_scheme, "central")
        self.assertLess(abs(fine.single_cycle - candidate.single_cycle), 5e-4)
        self.assertLess(abs(fine.regenerative - candidate.regenerative), 5e-4)
        short = pde_value(.1, .15, -.3, .2, .1, .12, .03, active_reward=.2,
                          terminal_reward=.1, domain=1.5, space_step=.00125, time_step=.00025)
        expected = finite_horizon_value(KilledDiffusion(-.3, .2, .1), ResetRule(.12, .03),
                                        .1, .15, active_reward=.2, terminal_reward=.1)
        self.assertLess(abs(short.single_cycle - expected.single_cycle), 3e-4)
        self.assertLess(abs(short.regenerative - expected.regenerative), 3e-4)

    def test_remaining_horizon_and_exact_refractory_release_atom(self):
        process, reset = KilledDiffusion(-.1, .3, .15), ResetRule(.25, .2)
        before = pde_value(0, .199, -.1, .3, .15, .25, .2, terminal_reward=.7)
        at = pde_value(0, .2, -.1, .3, .15, .25, .2, terminal_reward=.7)
        self.assertEqual(before.regenerative, 1)
        self.assertAlmostEqual(at.regenerative, 1 + math.exp(-.15*.2)*.7, places=12)
        initial = pde_value(0, 0, -.1, .3, .15, .25, 0, terminal_reward=.7)
        self.assertEqual(initial.single_cycle, 1)
        self.assertEqual(initial.regenerative, 1.7)
        correct = finite_horizon_value(process, reset, 0, .45, terminal_reward=.7).regenerative
        remaining = finite_horizon_value(process, reset, .25, .25, terminal_reward=.7).regenerative
        full = finite_horizon_value(process, reset, .25, .45, terminal_reward=.7).regenerative
        self.assertAlmostEqual(correct, 1 + math.exp(-.15*.2) * remaining, places=12)
        self.assertGreater(abs(correct - (1 + math.exp(-.15*.2) * full)), .05)

    def test_parameter_sensitivity_uses_independent_pde(self):
        args = dict(x=.35, horizon=1.4, mu=-.1, sigma=.3, discount=.15,
                    margin=.25, refractory=.11, active_reward=.4, terminal_reward=.2)
        def candidate(margin):
            return finite_horizon_value(KilledDiffusion(-.1, .3, .15), ResetRule(margin, .11),
                                        .35, 1.4, active_reward=.4, terminal_reward=.2).regenerative
        expected = five_point_derivative(candidate, .25, .001)
        values = [pde_value(**dict(args, margin=m), space_step=.0025,
                            time_step=.0005).regenerative for m in [.245, .255]]
        oracle = (values[1] - values[0]) / .01
        self.assertLess(abs(expected - oracle), .001)

    def test_stationary_hx_resolvent_and_regenerative_slope(self):
        par, reset = HXParams(), ResetRule(.25, .11, .3)
        oracle = stationary_hx_pde(par, hx_boundary(par), .25, .11, .3, .5, space_step=.005)
        expected = stationary_hx_value(par, reset, .5)
        self.assertLess(abs(oracle.single_cycle - expected.single_cycle), .0015)
        self.assertLess(abs(oracle.regenerative - expected.regenerative), .003)
        slope = five_point_derivative(lambda x: stationary_hx_value(par, reset, x).regenerative, .5, 1e-4)
        self.assertLess(abs(oracle.regenerative_slope - slope), .007)
        self.assertGreater(abs(oracle.regenerative_slope - oracle.single_slope), 50)


if __name__ == "__main__":
    unittest.main()
