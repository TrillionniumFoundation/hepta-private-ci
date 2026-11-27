"""Binary-input high-precision regressions; no scientific acceptance claim."""
import math
import sys
import unittest
from decimal import ROUND_UP, Decimal, Inexact, localcontext

from portfolio import conditional_ce


def oracle(values, probabilities, gamma, normalize=True):
    # Direct, unanchored exponential utility, independent of production's
    # shifted evaluation and adaptive precision. Test exponents are bounded.
    with localcontext() as ctx:
        ctx.prec = 1500
        risk = Decimal.from_float(gamma)
        terms = [(Decimal.from_float(p), Decimal.from_float(v))
                 for p, v in zip(probabilities, values) if p]
        mass = sum(p for p, _ in terms) if normalize else Decimal(1)
        moment = sum(p * (-risk * v).exp() for p, v in terms) / mass
        return float(-moment.ln() / risk)


class ExtremeRiskTests(unittest.TestCase):
    def assert_reference(self, values, probabilities, gamma, normalize=True):
        actual = conditional_ce(values, probabilities, gamma)
        expected = oracle(values, probabilities, gamma, normalize)
        self.assertTrue(math.isfinite(actual), (values, gamma, actual))
        self.assertTrue(math.isclose(actual, expected, rel_tol=3e-12,
                                     abs_tol=math.ulp(expected) * 4),
                        (values, gamma, actual, expected))
        return actual

    def test_two_sided_extremes_and_subnormal_risk(self):
        for scale, gamma in ((1e308, 1e-308), (1e308, 1e-320),
                             (1e300, 1e-320), (2.0, 5e-324),
                             (sys.float_info.max, 1e-308)):
            with self.subTest(scale=scale, gamma=gamma):
                result = self.assert_reference((-scale, scale), (.5, .5), gamma)
                self.assertLess(result, 0.0)

    def test_caller_decimal_context_does_not_change_float_function(self):
        expected = conditional_ce((-1e308, 1e308), (.5, .5), 1e-320)
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.rounding = ROUND_UP
            ctx.traps[Inexact] = True
            ctx.Emin = -9
            ctx.Emax = 9
            self.assertEqual(conditional_ce((-1e308, 1e308), (.5, .5), 1e-320),
                             expected)
            self.assertEqual((ctx.prec, ctx.Emin, ctx.Emax, ctx.rounding),
                             (6, -9, 9, ROUND_UP))
            self.assertTrue(ctx.traps[Inexact])

    def test_subnormal_positive_mass_is_preserved(self):
        for values, probabilities in (((-1e308, 0.), (5e-324, 1.)),
                                       ((0., 1e308), (1., 5e-324))):
            actual = self.assert_reference(values, probabilities, 1e-320)
            self.assertGreaterEqual(actual, min(values))
            self.assertLessEqual(actual, max(values))
            self.assertNotEqual(actual, 0.)

    def test_rare_outcome_at_ordinary_scaled_risk(self):
        for probability in (5e-324, 1e-300, 1e-80):
            self.assert_reference((-1e308, 0.), (probability, 1.),
                                  1e-308, normalize=False)

    def test_wide_support_is_not_neutralized(self):
        for gamma, high in ((1e-260, 1e260), (1e-308, 1e308),
                            (1e-251, 1e252)):
            with self.subTest(gamma=gamma):
                result = self.assert_reference((0., high), (.5, .5), gamma)
                self.assertLess(result, .9 * high / 2)

    def test_zero_mass_extremes_and_permutation(self):
        for gamma in (1e-320, 1e-8, .5):
            expected = conditional_ce((-10., -3.), (.4, .6), gamma)
            self.assertEqual(conditional_ce((-sys.float_info.max, -3., -10.,
                                             sys.float_info.max),
                                            (0., .6, .4, 0.), gamma), expected)

    def test_scaled_span_threshold_both_sides(self):
        for gamma in (math.nextafter(1e-4, 0.), 1e-4,
                      math.nextafter(1e-4, math.inf)):
            self.assert_reference((0., 1.), (.5, .5), gamma)

    def test_translation_and_support_bounds(self):
        for values, shift, gamma in (((-2., 2.), 16., 1e-8),
                                      ((-1e308, 1e308), 1e307, 1e-308),
                                      ((-10., -3.), 2., .5)):
            translated = tuple(v + shift for v in values)
            original = self.assert_reference(values, (.5, .5), gamma)
            actual = self.assert_reference(translated, (.5, .5), gamma)
            self.assertTrue(math.isclose(actual, original + shift,
                                         rel_tol=2e-13, abs_tol=1e-14))
            self.assertLessEqual(min(translated), actual)
            self.assertLessEqual(actual, math.fsum(v / 2 for v in translated))

    def test_existing_probability_mass_conventions_are_explicit(self):
        probabilities = (.4, .6000000000001)
        # Retain the baseline's near-neutral normalization and ordinary raw
        # mass semantics, including zero risk. Unifying them is separate work.
        for values, gamma, normalized in (((-10., -3.), 1e-16, True),
                                          ((-10., -3.), .5, False),
                                          ((-1e308, 1e308), 1e-308, False),
                                          ((-1e308, 1e308), 1e-320, True)):
            self.assert_reference(values, probabilities, gamma, normalized)
        self.assertEqual(conditional_ce((-10., -3.), probabilities, 0.),
                         math.fsum(p * v for p, v in zip(probabilities, (-10., -3.))))

    def test_large_risk_and_degenerate_extreme_support(self):
        for gamma in (1., sys.float_info.max):
            self.assertEqual(conditional_ce((-1e308, 1e308), (.5, .5), gamma),
                             -1e308)
        self.assertEqual(conditional_ce((1e308, 1e308), (.5, .5), 5e-324),
                         1e308)


if __name__ == "__main__":
    unittest.main()
