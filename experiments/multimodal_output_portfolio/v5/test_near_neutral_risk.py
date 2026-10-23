"""Independent near-risk-neutral utility precision regressions.

All values are bounded toy utilities. Decimal is an offline numerical oracle,
not a neural loss observation or external resource meter.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import unittest

from joint_portfolio import (
    JointController, Profile, PublicState, conditional_ce,
)


def decimal_oracle(values, probabilities, gamma):
    with localcontext() as ctx:
        ctx.prec = 90
        risk = Decimal(str(gamma))
        v = [Decimal(str(x)) for x in values]
        p = [Decimal(str(x)) for x in probabilities]
        normalizer = sum(p)
        normal = [weight / normalizer for weight in p]
        return float(-(
            sum(weight * (-risk * value).exp()
                for weight, value in zip(normal, v))
        ).ln() / risk)


class NearNeutralRiskTests(unittest.TestCase):
    def test_continuity_against_high_precision_independent_oracle(self):
        values, weights = (-10.0, -3.0), (0.4, 0.6)
        neutral = conditional_ce(values, weights, 0)
        self.assertAlmostEqual(neutral, -5.8, places=13)
        for gamma in (1e-8, 1e-12, 1e-14, 1e-16):
            with self.subTest(gamma=gamma):
                actual = conditional_ce(values, weights, gamma)
                oracle = decimal_oracle(values, weights, gamma)
                self.assertLess(abs(actual - oracle), 2e-12)
                self.assertLessEqual(actual, neutral + 1e-12)

    def test_symmetric_tiny_risk_never_creates_fake_large_loss(self):
        for gamma in (1e-12, 1e-14, 1e-16):
            actual = conditional_ce((-2.0, 2.0), (0.5, 0.5), gamma)
            self.assertLessEqual(actual, 1e-12)
            self.assertGreater(actual, -1e-8)

    def test_zero_probability_outlier_does_not_change_risk(self):
        for gamma in (1e-12, 1e-16):
            base = conditional_ce((-10.0, -3.0), (0.4, 0.6), gamma)
            with_impossible = conditional_ce(
                (-1_000_000.0, -10.0, -3.0), (0.0, 0.4, 0.6), gamma,
            )
            self.assertAlmostEqual(base, with_impossible, places=12)

    def test_admitted_roundoff_mass_cannot_explode_at_small_risk(self):
        almost_normalized = (0.4, 0.6000000000001)
        for gamma in (1e-12, 1e-16):
            result = conditional_ce((-10.0, -3.0),
                                    almost_normalized, gamma)
            expected = decimal_oracle((-10.0, -3.0),
                                      almost_normalized, gamma)
            self.assertLess(abs(result - expected), 2e-12)

    def test_subnormal_risk_is_effectively_risk_neutral(self):
        vals, weights = (-10.0, -3.0), (0.4, 0.6)
        neutral = conditional_ce(vals, weights, 0)
        for gamma in (1e-260, 1e-300, 5e-324):
            self.assertEqual(conditional_ce(vals, weights, gamma), neutral)

    def test_bellman_terminal_value_near_gamma_zero(self):
        state = PublicState((2, 2, 2, 2), Fraction(1, 2), 4)
        neutral = JointController(Profile(gamma=0)).terminal(state)
        for gamma in (1e-12, 1e-16):
            with self.subTest(gamma=gamma):
                actual = JointController(Profile(gamma=gamma)).terminal(state)
                self.assertTrue(math.isfinite(actual))
                self.assertLess(abs(actual - neutral), 1e-9)


if __name__ == "__main__":
    unittest.main()
