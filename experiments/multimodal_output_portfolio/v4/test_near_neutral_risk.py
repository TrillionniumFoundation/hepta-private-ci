"""Near-neutral risk arithmetic tests independent of frozen v4 outcomes.

Small risk coefficients are admitted by Config. These are finite synthetic
value-function tests, not actual decoder quality or a new scientific result.
"""
import math
import unittest
from decimal import Decimal, localcontext

from portfolio import Config, conditional_ce


def decimal_reference(values, probabilities, gamma):
    """Independent high-precision direct exponential-utility oracle."""
    with localcontext() as ctx:
        ctx.prec = 90
        risk = Decimal(str(gamma))
        total = sum(
            (Decimal(str(p)) * (-risk * Decimal(str(v))).exp()
             for p, v in zip(probabilities, values)), Decimal(0)
        )
        return float(-total.ln() / risk)


class NearNeutralRiskTests(unittest.TestCase):
    def test_positive_tiny_risk_agrees_with_decimal_oracle(self):
        values, probabilities = (-10.0, -3.0), (0.4, 0.6)
        self.assertAlmostEqual(
            conditional_ce(values, probabilities, 1e-16), -5.8, places=9
        )
        for gamma in (1e-16, 1e-14, 1e-12, 1e-8, 1e-6):
            with self.subTest(gamma=gamma):
                self.assertAlmostEqual(
                    conditional_ce(values, probabilities, gamma),
                    decimal_reference(values, probabilities, gamma),
                    places=8,
                )

    def test_near_neutral_ignores_impossible_extreme_outcome(self):
        # A zero-mass extreme outcome must never change the supported anchor.
        self.assertAlmostEqual(
            conditional_ce((-1e200, -10.0, -3.0),
                           (0.0, 0.4, 0.6), 1e-16),
            -5.8, places=9,
        )

    def test_roundoff_mass_and_subnormal_risk_stay_continuous(self):
        self.assertAlmostEqual(
            conditional_ce((-10.0, -3.0), (0.4, 0.6000000000001), 1e-16),
            -5.8, places=8,
        )
        self.assertAlmostEqual(
            conditional_ce((-10.0, -3.0), (0.4, 0.6), 1e-320),
            -5.8, places=9,
        )
        self.assertEqual(Config(risk_aversion=1e-320).risk_aversion, 1e-320)

    def test_tiny_risk_can_still_be_material_on_wide_finite_support(self):
        # Counterexample to a gamma-only risk-neutral shortcut: gamma -> 0
        # does not imply a small gamma * payoff span.
        probabilities = (0.5, 0.5)
        for gamma, payoff in ((1e-260, 1e260), (1e-308, 1e308)):
            with self.subTest(gamma=gamma):
                values = (0.0, payoff)
                actual = conditional_ce(values, probabilities, gamma)
                reference = decimal_reference(values, probabilities, gamma)
                self.assertTrue(
                    math.isclose(actual, reference, rel_tol=2e-14),
                    (gamma, actual, reference),
                )
                # An incorrectly neutralized policy would value this at
                # payoff / 2 instead of the risk-sensitive certainty equivalent.
                self.assertLess(actual, 0.9 * (payoff / 2))

    def test_registered_ordinary_risk_uses_unchanged_evaluation(self):
        values, probabilities, gamma = (-10.0, -3.0), (0.4, 0.6), 0.5
        anchor = min(values)
        original = anchor - math.log(math.fsum(
            p * math.exp(-gamma * (v - anchor))
            for p, v in zip(probabilities, values)
        )) / gamma
        self.assertEqual(conditional_ce(values, probabilities, gamma), original)


if __name__ == "__main__":
    unittest.main()
