"""Independent identities for the fixed-generator regenerative reference."""

import math
import unittest
import warnings

import numpy as np
from scipy.integrate import quad

from qualification.hcsn import reference
from qualification.hcsn_regenerative.process import (
    KilledDiffusion, ResetRule, finite_horizon_value, regenerative_transition, stationary_hx_value,
)


def density(time, x, mu, sigma):
    if time == 0 or x == 0:
        return 0.0
    return x * math.exp(-(x + mu * time)**2 / (2 * sigma**2 * time)) / (
        sigma * math.sqrt(2 * math.pi * time**3))


def integrated_hit(x, horizon, process, discounted=False):
    rate = process.discount if discounted else 0.0
    return quad(lambda t: math.exp(-rate * t) * density(t, x, process.mu, process.sigma),
                0, horizon, epsabs=2e-12, epsrel=2e-11)[0]


class KilledGeneratorTests(unittest.TestCase):
    def test_survivor_hit_and_upper_tail_share_mass(self):
        for mu in (-0.3, 0.0, 0.4):
            with self.subTest(mu=mu):
                process = KilledDiffusion(mu, 0.4, 0.07)
                transition = process.transition(0.3, 0.8, [0, .1, .2, .5])
                self.assertGreater(transition.upper_tail, 0)
                self.assertAlmostEqual(sum(transition.survivor_bins) + transition.upper_tail,
                                       process.survival(.3, .8), delta=2e-13)
                self.assertAlmostEqual(transition.hit, integrated_hit(.3, .8, process), delta=2e-12)
                self.assertAlmostEqual(sum(transition.survivor_bins) + transition.hit
                                       + transition.upper_tail, 1, delta=2e-13)
                expected = integrated_hit(.3, .8, process, discounted=True)
                self.assertAlmostEqual(process.discounted_hit(.3, .8), expected, delta=2e-12)

    def test_boundary_and_zero_horizon_atoms(self):
        process = KilledDiffusion(-.2, .3, .05)
        killed = process.transition(0, 0, [0, .2, .4])
        self.assertEqual((killed.hit, killed.survivor_bins, killed.upper_tail), (1, (0, 0), 0))
        at_edge = process.transition(.2, 0, [0, .2, .4])
        self.assertEqual(at_edge.survivor_bins, (0, 1))
        tail = process.transition(.4, 0, [0, .2, .4])
        self.assertEqual(tail.upper_tail, 1)
        self.assertEqual(process.density(.2, 0), 0)
        self.assertEqual(process.discounted_hit(0, 0), 1)
        self.assertEqual(process.survival(0, 0), 0)

    def test_infinite_bin_edge_has_no_warning_or_renormalization(self):
        process = KilledDiffusion(.1, .3)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            transition = process.transition(.2, .4, [0, .1, .5, np.inf])
        self.assertEqual(transition.upper_tail, 0)
        self.assertAlmostEqual(sum(transition.survivor_bins), process.survival(.2, .4), delta=2e-14)

    def test_laplace_solves_same_interior_generator(self):
        for mu in (-1., .0, .3):
            process = KilledDiffusion(mu, .2, .08)
            root = process.laplace_root(process.discount)
            self.assertAlmostEqual(.5 * process.sigma**2 * root**2 - mu * root,
                                   process.discount, delta=2e-15)
        self.assertEqual(KilledDiffusion(-1, .2).laplace(.5), 1)
        self.assertAlmostEqual(KilledDiffusion(.3, .2).laplace(.5), math.exp(-7.5))


class RenewalTests(unittest.TestCase):
    def test_two_hit_window_against_independent_time_convolution(self):
        process = KilledDiffusion(-.1, .3, .08)
        reset = ResetRule(.15, .35, 1.7)
        x, horizon = .1, .6  # Third hit cannot precede 2*refractory.
        out = finite_horizon_value(process, reset, x, horizon, terminal_reward=.9)
        first = integrated_hit(x, horizon, process, discounted=True)
        second = quad(lambda s: math.exp(-process.discount * (s + reset.refractory))
                      * density(s, x, process.mu, process.sigma)
                      * integrated_hit(reset.margin, horizon - reset.refractory - s,
                                       process, discounted=True),
                      0, horizon - reset.refractory, epsabs=2e-11)[0]
        survivor = 1 - integrated_hit(x, horizon, process)
        restarted = quad(lambda s: density(s, x, process.mu, process.sigma)
                         * (1 - integrated_hit(reset.margin, horizon-reset.refractory-s, process)),
                         0, horizon - reset.refractory, epsabs=2e-11)[0]
        expected = reset.hit_reward * (first + second) + .9 * math.exp(
            -process.discount * horizon) * (survivor + restarted)
        self.assertAlmostEqual(out.regenerative, expected, delta=2e-10)
        self.assertAlmostEqual(out.expected_discounted_hits, first + second, delta=2e-10)
        self.assertAlmostEqual(out.active_probability, survivor + restarted, delta=2e-10)
        self.assertGreater(out.regenerative, out.single_cycle)

    def test_remaining_time_boundary_identity_and_release_atom(self):
        process = KilledDiffusion(-.25, .3, .1)
        reset = ResetRule(.3, .137, 2)
        for horizon in (0, .1, .137, .8):
            with self.subTest(horizon=horizon):
                out = finite_horizon_value(process, reset, 0, horizon,
                                           active_reward=.5, terminal_reward=.7)
                expected = reset.hit_reward
                if horizon >= reset.refractory:
                    restarted = finite_horizon_value(process, reset, reset.margin,
                                                      horizon-reset.refractory,
                                                      active_reward=.5, terminal_reward=.7)
                    expected += math.exp(-process.discount * reset.refractory) * restarted.regenerative
                self.assertAlmostEqual(out.regenerative, expected, delta=2e-10)
                self.assertEqual(out.single_cycle, reset.hit_reward)
        before = finite_horizon_value(process, reset, 0, np.nextafter(reset.refractory, 0))
        at = finite_horizon_value(process, reset, 0, reset.refractory)
        self.assertEqual(before.active_probability, 0)
        self.assertEqual(at.active_probability, 1)

    def test_zero_refractory_and_multiple_hits(self):
        process = KilledDiffusion(-.8, .12, .04)
        reset = ResetRule(.1, 0, .8)
        out = finite_horizon_value(process, reset, .1, 1, active_reward=.3, terminal_reward=.2)
        self.assertEqual(out.active_probability, 1)
        self.assertAlmostEqual(out.active_time, -math.expm1(-.04) / .04, delta=2e-14)
        self.assertGreater(out.expected_discounted_hits, 6)
        self.assertGreater(out.regenerative, 5 * out.single_cycle)
        corner = finite_horizon_value(process, reset, 0, 0, terminal_reward=.2)
        self.assertEqual(corner.single_cycle, .8)
        self.assertEqual(corner.regenerative, 1)
        regular = finite_horizon_value(process, reset, .1, 0, terminal_reward=.2)
        self.assertEqual(regular.single_cycle, regular.regenerative)
        self.assertEqual(regular.regenerative, .2)

    def test_tail_receipt_bounds_tolerance_change(self):
        process = KilledDiffusion(.1, .35, .03)
        reset = ResetRule(.2, 0, -1.3)
        loose = finite_horizon_value(process, reset, .12, .9,
                                     active_reward=.2, terminal_reward=-.4, tolerance=1e-4)
        tight = finite_horizon_value(process, reset, .12, .9,
                                     active_reward=.2, terminal_reward=-.4, tolerance=1e-12)
        self.assertLess(loose.terms, tight.terms)
        self.assertGreater(loose.renewal_tail_bound, 0)
        self.assertLessEqual(abs(loose.regenerative-tight.regenerative),
                             loose.value_tail_bound+tight.value_tail_bound+2e-13)

    def test_low_noise_active_occupation(self):
        process = KilledDiffusion(-1, 1e-4)
        out = finite_horizon_value(process, ResetRule(.3, .07), .4, 1.2,
                                   active_reward=1)
        # Deterministic-limit hit times .4, .77, 1.14; last release is 1.21.
        self.assertAlmostEqual(out.expected_discounted_hits, 3, delta=1e-10)
        self.assertAlmostEqual(out.active_time, 1, delta=1e-8)
        self.assertAlmostEqual(out.single_cycle, 1.4, delta=1e-8)
        self.assertAlmostEqual(out.regenerative, 4, delta=1e-8)

    def test_domains_and_unresolved_tail_fail_explicitly(self):
        for constructor, args in ((KilledDiffusion, (0, 0)), (KilledDiffusion, (0, 1, -1)),
                                  (ResetRule, (0,)), (ResetRule, (.1, -1))):
            with self.assertRaises(ValueError):
                constructor(*args)
        process = KilledDiffusion(-.2, .3)
        with self.assertRaises(ValueError):
            finite_horizon_value(process, ResetRule(1e-5), .1, 1, max_terms=1)
        with self.assertRaises(ValueError):
            process.transition(.2, .1, [0, .3, .2])


class SuccessorTests(unittest.TestCase):
    def test_reset_successor_and_remaining_time_atoms(self):
        process = KilledDiffusion(-.1, .3, .08)
        reset = ResetRule(.15, .35)
        edges, remaining = [0, .1, .2, .6], [0, .1, .2, .35]
        before = regenerative_transition(process, reset, 0, .2, edges,
                                         refractory_edges=remaining)
        self.assertEqual(before.active_bins, (0, 0, 0))
        self.assertEqual(before.refractory_bins, (0, 1, 0))
        released = regenerative_transition(process, reset, 0, .35, edges,
                                           refractory_edges=remaining)
        self.assertEqual(released.active_bins, (0, 1, 0))
        self.assertEqual(released.refractory_bins, (0, 0, 0))
        later = regenerative_transition(process, reset, 0, 1.1, edges,
                                        refractory_edges=remaining)
        restarted = regenerative_transition(process, reset, .15, 1.1-.35, edges,
                                             refractory_edges=remaining)
        np.testing.assert_allclose(later.active_bins, restarted.active_bins, atol=2e-10)
        np.testing.assert_allclose(later.refractory_bins, restarted.refractory_bins, atol=2e-10)
        self.assertAlmostEqual(later.expected_hits, 1+restarted.expected_hits, delta=2e-13)

    def test_successor_matches_independent_time_and_space_kernel(self):
        process = KilledDiffusion(-.1, .3, .08)
        reset = ResetRule(.15, .35)
        x, horizon = .1, .6
        edges, remaining = [0, .1, .2, .6], [0, .1, .2, .35]
        out = regenerative_transition(process, reset, x, horizon, edges,
                                      refractory_edges=remaining)

        def normal_cdf(z):
            return .5*math.erfc(-z/math.sqrt(2))

        def killed_bin(start, time, lo, hi):
            scale = process.sigma*math.sqrt(time)
            mean, image = start+process.mu*time, -start+process.mu*time
            first = normal_cdf((hi-mean)/scale)-normal_cdf((lo-mean)/scale)
            second = normal_cdf((hi-image)/scale)-normal_cdf((lo-image)/scale)
            return first-math.exp(-2*process.mu*start/process.sigma**2)*second

        initial_bin = killed_bin(x, horizon, .1, .2)
        restarted_bin = quad(lambda t: density(t, x, process.mu, process.sigma)
                             * killed_bin(reset.margin, horizon-reset.refractory-t, .1, .2),
                             0, horizon-reset.refractory, epsabs=2e-11)[0]
        self.assertAlmostEqual(out.active_bins[1], initial_bin+restarted_bin, delta=2e-10)
        for i, (lo, hi) in enumerate(zip(remaining[:-1], remaining[1:])):
            expected = 0.0
            for n in (1, 2):
                left = max(0, horizon-n*reset.refractory+lo)
                right = max(0, horizon-n*reset.refractory+hi)
                expected += quad(lambda t: density(t, x+(n-1)*reset.margin,
                                                   process.mu, process.sigma),
                                 left, right, epsabs=2e-12)[0]
            self.assertAlmostEqual(out.refractory_bins[i], expected, delta=2e-11)
        self.assertGreater(out.upper_tail, 0)
        self.assertAlmostEqual(sum(out.active_bins)+out.upper_tail+sum(out.refractory_bins),
                               1, delta=2e-10)
        value = finite_horizon_value(process, reset, x, horizon)
        self.assertAlmostEqual(out.active_probability, value.active_probability, delta=2e-10)

    def test_instant_reset_successor_and_undiscounted_counts(self):
        reset = ResetRule(.1)
        edges = [0, .05, .2, math.inf]
        corner = regenerative_transition(KilledDiffusion(-.2, .2), reset, 0, 0, edges)
        self.assertEqual(corner.active_bins, (0, 1, 0))
        self.assertEqual(corner.expected_hits, 1)
        out = regenerative_transition(KilledDiffusion(-.2, .2, .9), reset, .1, .8, edges)
        count = finite_horizon_value(KilledDiffusion(-.2, .2), reset, .1, .8)
        self.assertGreater(out.expected_hits, 1)
        self.assertEqual(out.refractory_bins, ())
        self.assertEqual(out.upper_tail, 0)
        self.assertAlmostEqual(sum(out.active_bins), 1, delta=2e-9)
        self.assertAlmostEqual(out.expected_hits, count.expected_discounted_hits, delta=2e-9)

    def test_low_noise_successor_resolves_active_and_refractory_phases(self):
        process = KilledDiffusion(-1, 1e-4)
        reset = ResetRule(.3, .07)
        active = regenerative_transition(process, reset, .4, 1.1, [0, .1, .3, .5],
                                          refractory_edges=[0, .005, .015, .07])
        refractory = regenerative_transition(process, reset, .4, 1.2, [0, .1, .3, .5],
                                              refractory_edges=[0, .005, .015, .07])
        self.assertAlmostEqual(active.active_bins[0], 1, delta=1e-8)
        self.assertEqual(active.expected_hits, 2)
        self.assertAlmostEqual(refractory.refractory_bins[1], 1, delta=1e-8)
        self.assertEqual(refractory.expected_hits, 3)
        self.assertAlmostEqual(refractory.active_probability, 0, delta=1e-8)

    def test_invalid_remaining_time_partition(self):
        process = KilledDiffusion(-.1, .3)
        for remaining in ([0, .1], [0, .4, .3], [.1, .3]):
            with self.assertRaises(ValueError):
                regenerative_transition(process, ResetRule(.1, .3), .1, .2, [0, 1],
                                        refractory_edges=remaining)


class NonfiniteResultTests(unittest.TestCase):
    def test_finite_extreme_inputs_cannot_return_nan_transition(self):
        process = KilledDiffusion(-1e155, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with self.assertRaisesRegex(FloatingPointError, "FP64"):
                process.transition(1e155, 1, [0, 1, 2])
            with self.assertRaisesRegex(FloatingPointError, "FP64"):
                regenerative_transition(process, ResetRule(.1, .1), 1e155, 1, [0, 1, 2])

    def test_finite_rewards_cannot_return_infinite_finite_horizon_value(self):
        with self.assertRaisesRegex(FloatingPointError, "Finite-horizon value"):
            finite_horizon_value(KilledDiffusion(-1, .2), ResetRule(.1, hit_reward=1e308),
                                 .1, 1)

    def test_finite_rewards_cannot_return_infinite_stationary_value(self):
        with self.assertRaisesRegex(FloatingPointError, "Stationary HX value"):
            stationary_hx_value(reference.HXParams(), ResetRule(.2, .137, 1e308), .4)


class StationaryHXTests(unittest.TestCase):
    def test_renewal_fixed_point_and_boundary(self):
        par = reference.HXParams()
        reset = ResetRule(.2, .137, .4)
        out = stationary_hx_value(par, reset, reset.margin)
        process = KilledDiffusion(par.mu, par.sigma, par.r)
        expected = out.single_cycle + process.laplace(reset.margin) * (
            reset.hit_reward + math.exp(-par.r*reset.refractory)*out.regenerative)
        self.assertAlmostEqual(out.regenerative, expected, delta=2e-12)
        boundary = stationary_hx_value(par, reset, 0)
        self.assertEqual(boundary.single_cycle, 0)
        self.assertAlmostEqual(boundary.regenerative,
                               reset.hit_reward + math.exp(-par.r*reset.refractory)*out.regenerative,
                               delta=2e-12)
        self.assertGreater(out.renewal_multiplier, 1)

    def test_same_interior_cashflow_for_E_and_U(self):
        par = reference.HXParams()
        reset = ResetRule(.2, .137, .4)
        boundary = reference.hx_boundary(par)
        for x in (.4, .8):
            with self.subTest(x=x):
                h = 2e-4
                values = [stationary_hx_value(par, reset, x+i*h) for i in (-2,-1,0,1,2)]
                cashflow = (par.delta*boundary*math.exp(x)-(1-par.tax)*par.coupon
                            + reference.hx_debt(x, par.maturity, par, boundary)-par.p)
                for name in ("single_cycle", "regenerative"):
                    mm, m, mid, p, pp = [getattr(v, name) for v in values]
                    first = (mm-8*m+8*p-pp)/(12*h)
                    second = (-mm+16*m-30*mid+16*p-pp)/(12*h*h)
                    residual = par.r*mid-par.mu*first-.5*par.sigma**2*second-cashflow
                    self.assertAlmostEqual(residual, 0, delta=2e-6)


if __name__ == "__main__":
    unittest.main()
