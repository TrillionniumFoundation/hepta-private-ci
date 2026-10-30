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


    def test_large_finite_sigma_does_not_drop_discounted_tail(self):
        # The old delta numerator overflows although the final small
        # exponent is finite. This tests reflection only, not quadrature.
        sigma=1e154
        self.assertTrue(math.isfinite(sigma*sigma))
        self.assertTrue(math.isinf(2.*(sigma*sigma)))
        for drift in (-1e154,1e154):
            with self.subTest(drift=drift):
                result=reflected_passage(1.,drift=drift,sigma=sigma,
                                          discount=1.,horizon=1.)
                # Distance / sigma is 1e-154; both exact probabilities
                # differ from one below f64 resolution for these inputs.
                self.assertAlmostEqual(result.probability,1.,delta=3e-15)
                self.assertAlmostEqual(result.discounted,1.,delta=3e-15)

    def test_direct_exponent_retains_both_drift_fixture_controls(self):
        # Reuse frozen ordinary-range values, without importing high
        # precision arithmetic or claiming a general-domain error bound.
        cases=(
            (.15927864477835885,-1.057495025698587,.0010799136435169741,
             2.0743660892253688e-5,5.221671082293789,.9999968756193146843707),
            (.04,.35,.03,1e-8,3.,3.080463860371850719369e-14),
        )
        for x,drift,sigma,discount,horizon,expected in cases:
            with self.subTest(drift=drift):
                result=reflected_passage(x,drift=drift,sigma=sigma,
                                          discount=discount,horizon=horizon)
                self.assertLess(abs(result.discounted-expected),3e-15)

    def test_subnormal_squared_scale_retains_nonzero_exponent(self):
        # Rejected proposal v1 formed denominator*x before dividing by s2,
        # producing zero although the dimensionless exponent is exactly .25.
        sigma=math.ldexp(1.,-537)
        x=math.ldexp(1.,-539)
        self.assertGreater(sigma*sigma,0.)
        self.assertEqual(sigma*x,0.)
        result=reflected_passage(x,drift=0.,sigma=sigma,discount=.5,horizon=1.)
        # Independent dimensionless substitution: F=2*Phi(-.25),
        # G=exp(.25)*Phi(-1.25)+exp(-.25)*Phi(.75).
        self.assertAlmostEqual(result.probability,.8025873486341526,delta=3e-15)
        self.assertAlmostEqual(result.discounted,.7379602182304501,delta=3e-15)

    def test_unresolved_reflection_intermediates_fail_closed(self):
        base=dict(x=1.,drift=-1.,sigma=1.,discount=1.,horizon=1.)
        changes=(
            dict(sigma=1e200),  # sigma squared overflows
            dict(sigma=1e-200),  # sigma squared underflows to zero
            dict(discount=1e308),  # twice discount overflows
            dict(drift=1e308),  # z + abs(drift) overflows
            dict(x=5e-324),  # distance / denominator underflows to zero
            dict(discount=5e-324,x=1e-100),  # small exponent product underflows
            dict(drift=1e154,sigma=1e-154),  # denominator / sigma overflows
            dict(drift=5e-324,sigma=1e154),  # nonzero drift / sigma becomes zero
            dict(drift=1e-200,x=1e-200),  # dimensionless drift product becomes zero
            dict(x=1e308),  # noncancelling exponent product overflows
            dict(drift=-2.,horizon=1e308),  # tail argument overflows
            dict(sigma=math.ldexp(1.,-537),horizon=math.ldexp(1.,-1074),
                 drift=.25,x=math.ldexp(1.,-1074)),  # positive time products lost
        )
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ArithmeticError):
                reflected_passage(**(base | change))

    def test_subnormal_drift_products_retain_both_sign_probabilities(self):
        sigma=math.ldexp(1.,-537)
        x=math.ldexp(1.,-539)
        # Independent dimensionless inputs are x=.25, drift=+/-1,
        # sigma=1, q=.5, T=1. Frozen values use the two normal-CDF terms.
        cases=((-1.,.9475596767123303,.8793139640911344),
               (1.,.5747239958334194,.5333308787347266))
        for sign,expected_f,expected_g in cases:
            drift=sign*sigma
            with self.subTest(sign=sign):
                self.assertEqual((-2*drift)*x,0.)
                result=reflected_passage(x,drift=drift,sigma=sigma,
                                          discount=.5,horizon=1.)
                self.assertAlmostEqual(result.probability,expected_f,delta=3e-15)
                self.assertAlmostEqual(result.discounted,expected_g,delta=3e-15)


if __name__ == '__main__':
    unittest.main()
