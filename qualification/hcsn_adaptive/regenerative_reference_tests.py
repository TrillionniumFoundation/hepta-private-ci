"""Synthetic quadrature/renewal checks; no historical data or network acceptance.

Run: python -m unittest qualification.hcsn_adaptive.regenerative_reference_tests -v
"""

import math
import unittest
from unittest.mock import patch

from scipy.integrate import quad

from qualification.hcsn_adaptive.regenerative_reference import RegenerativeReference


def density(x, t, mu, sigma):
    """Independent first-passage density for quadrature, not the production kernel."""
    if t <= 0:
        return 0.0
    return (
        x
        / (sigma * math.sqrt(2 * math.pi * t**3))
        * math.exp(-((x + mu * t) ** 2) / (2 * sigma**2 * t))
    )


def integrate(function, upper):
    return quad(function, 0, upper, epsabs=2e-12, epsrel=2e-11, limit=240)[0]


class RegenerativeReferenceTests(unittest.TestCase):
    def test_signed_drift_cdf_discount_and_defective_mass_against_integrals(self):
        for mu in (-0.7, 0.0, 0.7):
            with self.subTest(drift=mu):
                model = RegenerativeReference(mu, 0.6, 1.1, 0.2)
                for discount in (0.0, 0.35):
                    integrand = lambda t: (
                        math.exp(-discount * t) * density(0.8, t, mu, 0.6)
                    )
                    for horizon in (3.0, None):
                        expected = integrate(
                            integrand, math.inf if horizon is None else horizon
                        )
                        actual = model.discounted_hit(0.8, discount, horizon=horizon)
                        self.assertAlmostEqual(actual, expected, delta=2e-10)
                self.assertAlmostEqual(
                    model.first_hit_cdf(0.8, 3.0),
                    integrate(lambda t: density(0.8, t, mu, 0.6), 3.0),
                    delta=2e-11,
                )
                eventual = model.discounted_hit(0.8, 0.0)
                if mu > 0:
                    self.assertLess(eventual, 0.05)
                else:
                    self.assertEqual(eventual, 1.0)

    def test_second_event_convolution_for_negative_zero_and_positive_drift(self):
        x, reset, sigma, delay, horizon = 0.8, 1.1, 0.6, 0.2, 3.0
        for mu in (-0.7, 0.0, 0.7):
            with self.subTest(drift=mu):
                model = RegenerativeReference(mu, sigma, reset, delay)
                active_time = horizon - delay
                cdf = integrate(
                    lambda s: (
                        density(x, s, mu, sigma)
                        * integrate(
                            lambda u: density(reset, u, mu, sigma), active_time - s
                        )
                    ),
                    active_time,
                )
                flux = integrate(
                    lambda s: (
                        density(x, s, mu, sigma)
                        * density(reset, active_time - s, mu, sigma)
                    ),
                    active_time,
                )
                self.assertAlmostEqual(
                    model.nth_hit_cdf(x, horizon, 2), cdf, delta=2e-11
                )
                self.assertAlmostEqual(
                    model.nth_hit_density(x, horizon, 2), flux, delta=2e-11
                )

    def test_count_moments_from_independent_two_event_probabilities(self):
        mu, sigma, x, reset, delay, horizon = -0.3, 0.8, 0.1, 0.2, 0.4, 0.6
        model = RegenerativeReference(mu, sigma, reset, delay)
        first = integrate(lambda t: density(x, t, mu, sigma), horizon)
        second = integrate(
            lambda s: (
                density(x, s, mu, sigma)
                * integrate(lambda u: density(reset, u, mu, sigma), horizon - delay - s)
            ),
            horizon - delay,
        )
        probabilities = (1 - first, first - second, second)
        result = model.summary(x, horizon)
        self.assertAlmostEqual(
            result["expected_events"],
            math.fsum(n * p for n, p in enumerate(probabilities)),
            delta=2e-11,
        )
        self.assertAlmostEqual(
            result["second_event_moment"],
            math.fsum(n * n * p for n, p in enumerate(probabilities)),
            delta=2e-11,
        )

    def test_boundary_atom_zero_horizon_and_flux_integral(self):
        model = RegenerativeReference(-0.4, 0.7, 0.5, 0.25)
        zero = model.summary(0.0, 0.0)
        self.assertEqual(
            zero,
            {
                "first_event_probability": 1.0,
                "expected_events": 1.0,
                "second_event_moment": 1.0,
                "continuous_event_rate": 0.0,
                "time_zero_event_mass": 1.0,
                "terms_evaluated": 1,
            },
        )
        self.assertEqual(
            model.summary(0.1, 0.0),
            {
                **zero,
                "first_event_probability": 0.0,
                "expected_events": 0.0,
                "second_event_moment": 0.0,
                "time_zero_event_mass": 0.0,
            },
        )
        self.assertEqual(model.nth_hit_cdf(0.0, 0.25, 2), 0.0)
        self.assertEqual(model.discounted_hit(0.0, 0.7, horizon=0.0), 1.0)
        for x in (0.0, 0.6):
            result = model.summary(x, 1.0)
            mass = integrate(
                lambda t: model.summary(x, t)["continuous_event_rate"], 1.0
            )
            self.assertAlmostEqual(
                result["expected_events"],
                mass + result["time_zero_event_mass"],
                delta=2e-10,
            )
            paid = integrate(
                lambda t: (
                    math.exp(-0.7 * t) * model.summary(x, t)["continuous_event_rate"]
                ),
                1.0,
            )
            self.assertAlmostEqual(
                model.discounted_events(x, 0.7, horizon=1.0),
                paid + result["time_zero_event_mass"],
                delta=2e-10,
            )

    def test_regenerative_value_against_integrated_cycle_value_iteration(self):
        mu, sigma, reset, delay, discount, reward, payoff = (
            -0.4,
            0.7,
            0.5,
            0.25,
            0.8,
            0.6,
            -0.2,
        )
        model = RegenerativeReference(mu, sigma, reset, delay)

        def cycle(x):
            hit = integrate(
                lambda t: math.exp(-discount * t) * density(x, t, mu, sigma), math.inf
            )
            # Independent survival integral; omitted reward tail <= reward*exp(-64)/discount.
            active = reward * integrate(
                lambda t: (
                    math.exp(-discount * t)
                    * (1 - integrate(lambda u: density(x, u, mu, sigma), t))
                ),
                64 / discount,
            )
            return active, hit

        operating, hit = cycle(reset)
        value = 0.0
        for _ in range(256):
            following = operating + hit * (payoff + math.exp(-discount * delay) * value)
            if abs(following - value) < 1e-12:
                value = following
                break
            value = following
        else:
            self.fail("independent renewal value iteration failed to converge")
        operating, hit = cycle(0.8)
        expected = operating + hit * (payoff + math.exp(-discount * delay) * value)
        self.assertAlmostEqual(
            model.value(0.8, discount, reward, payoff), expected, delta=3e-10
        )
        self.assertAlmostEqual(
            model.value(0.0, discount, reward, payoff),
            payoff + math.exp(-discount * delay) * value,
            delta=3e-10,
        )

    def test_cancelling_cdf_and_undiscounted_defective_event_series(self):
        model = RegenerativeReference(-1.0, 1e-4, 0.5, 0.25)
        risk = model.first_hit_cdf(1.0, 1.0)  # exp(2e8)*Phi(-2e4) must not overflow.
        self.assertTrue(0.5 < risk < 0.5001)
        self.assertTrue(0.0 < model.discounted_hit(1.0, 0.5, horizon=1.0) < risk)
        positive = RegenerativeReference(0.7, 0.6, 1.1, 0.2)
        first = integrate(lambda t: density(0.8, t, 0.7, 0.6), math.inf)
        reset = integrate(lambda t: density(1.1, t, 0.7, 0.6), math.inf)
        independent = math.fsum(first * reset**k for k in range(32))
        self.assertAlmostEqual(
            positive.discounted_events(0.8, 0.0), independent, delta=2e-11
        )
        for mu in (-0.7, 0.0):
            with self.assertRaises(ValueError):
                RegenerativeReference(mu, 0.6, 1.1, 0.2).discounted_events(0.8, 0.0)
        for mu, sigma in ((1e-310, 1.0), (5e-324, 1e6)):
            with self.assertRaises(ArithmeticError):
                RegenerativeReference(mu, sigma, 1.0, 1.0).discounted_events(1.0, 0.0)

    def test_rounded_clock_product_does_not_erase_a_just_released_cohort(self):
        model = RegenerativeReference(0.0, 1e6, 1e-12, 0.1)
        horizon = 3 * model.refractory
        # Although FP64 subtraction gives zero, the represented horizon is
        # strictly later than three copies of the represented delay. Tiny reset
        # distance makes the otherwise lost fourth-event mass observable.
        self.assertEqual(horizon - 3 * model.refractory, 0.0)
        self.assertGreater(model.nth_hit_cdf(0.0, horizon, 4), 0.99)
        self.assertGreater(model.summary(0.0, horizon)["expected_events"], 3.99)

    def test_domains_and_preflight_horizon_term_budgets(self):
        for field, value in (
            ("sigma", 0.0),
            ("reset", 0.0),
            ("refractory", 0.0),
            ("drift", math.nan),
            ("drift", True),
            ("sigma", 1e-13),
            ("max_terms", 0),
            ("max_terms", 4097),
            ("max_horizon", math.inf),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                RegenerativeReference(
                    **{
                        **dict(drift=0.0, sigma=0.6, reset=0.5, refractory=0.25),
                        field: value,
                    }
                )
        model = RegenerativeReference(0.0, 0.6, 0.5, 0.25, max_terms=4, max_horizon=1.0)
        for distance, time in (
            (-1.0, 0.0),
            (math.inf, 0.0),
            (0.5, -1.0),
            (0.5, 1.01),
            (0.5, None),
        ):
            with self.assertRaises(ValueError):
                model.summary(distance, time)
        with patch(
            "qualification.hcsn_adaptive.regenerative_reference._log_cdf",
            side_effect=AssertionError("kernel ran before budget check"),
        ):
            with self.assertRaises(ValueError):
                model.summary(0.5, 1.0)
            with self.assertRaises(ValueError):
                model.discounted_events(0.5, 0.2, horizon=1.0)
        self.assertEqual(model.summary(0.5, 0.75)["terms_evaluated"], 4)
        for number in (0, 5, True):
            with self.assertRaises(ValueError):
                model.nth_hit_cdf(0.5, 0.5, number)
        for discount in (-1.0, 1e-15, math.inf):
            with self.assertRaises(ValueError):
                model.discounted_hit(0.5, discount)
        with self.assertRaises(ValueError):
            model.value(0.5, 0.0, 0.6, -0.2)


if __name__ == "__main__":
    unittest.main()
