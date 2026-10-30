"""Extreme-domain roundoff regression for the *analytic reference* F/G.

These independent expected G values were computed from the two normal-CDF
terms using mpmath 1.3.0 at 100 decimal digits, with the input decimal
literals interpreted as exact decimals. They are frozen test fixtures, not
validated real-number enclosures or evidence of native fp32 performance.
"""
import math
import unittest

from .bond_fpt_independent import integrate_passage, reflected_passage


class ReflectionCancellationTests(unittest.TestCase):
    def test_large_negative_drift_small_discount_reference_matches_high_precision(self):
        x = 0.15927864477835885
        drift = -1.057495025698587
        sigma = 0.0010799136435169741
        discount = 2.0743660892253688e-05
        horizon = 5.221671082293789
        expected_g = 0.9999968756193146843707
        kwargs = dict(drift=drift, sigma=sigma, discount=discount, horizon=horizon)
        analytic = reflected_passage(x, **kwargs)
        density = integrate_passage(x, **kwargs)
        self.assertLess(abs(analytic.discounted - expected_g), 3e-15)
        self.assertLess(abs(density.discounted - expected_g), 3e-14)
        # Preserve the actual negative witness: the *uncorrected analytic*
        # exponent loses information even though density integration is fine.
        z = math.hypot(drift, math.sqrt(2*discount)*sigma)
        naive_exponent = (-drift-z)*x/(sigma*sigma)
        rationalized_exponent = -2*discount*x/(z+abs(drift))
        self.assertGreater(abs(naive_exponent-rationalized_exponent), 1e-11)

    def test_low_discount_high_drift_positive_and_negative_fixtures(self):
        # Frozen 100-dps independent results. The positive-drift cases have
        # tiny hitting probabilities, so use absolute, not percent, checks.
        cases = (
            (.18,-.65,.005,1e-9,.6,0.9999999997230769231153),
            (.04,.35,.03,1e-8,3.,3.080463860371850719369e-14),
            (.1,-.8,.012,1e-10,1.1,0.9999999999875000000001),
            (.025,-.24,.025,1e-7,2.,0.9999999895833333932382),
            (.15,.15,.04,1e-8,2.,6.086458636504095555281e-13),
        )
        for x,drift,sigma,discount,horizon,expected in cases:
            with self.subTest(x=x,drift=drift,discount=discount):
                analytic=reflected_passage(x,drift=drift,sigma=sigma,
                                            discount=discount,horizon=horizon)
                density=integrate_passage(x,drift=drift,sigma=sigma,
                                          discount=discount,horizon=horizon)
                tolerance=max(3e-15,1e-8*expected)
                self.assertLess(abs(analytic.discounted-expected),tolerance)
                self.assertLess(abs(density.discounted-expected),2e-12)
                self.assertLess(abs(analytic.discounted-density.discounted),2e-12)

    def test_discounted_never_exceeds_probability_in_frozen_fixtures(self):
        for drift in (-1.057495025698587,-.8,-.24,.15,.35):
            result=reflected_passage(.04,drift=drift,sigma=.03,
                                      discount=1e-8,horizon=3.)
            self.assertGreaterEqual(result.discounted,0.)
            self.assertLessEqual(result.discounted,result.probability+5e-15)
            self.assertLessEqual(result.probability,1.+5e-15)


if __name__ == '__main__':
    unittest.main()
