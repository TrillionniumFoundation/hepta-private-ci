"""Extreme finite-input safety witnesses for the independent FPT oracle.

The old implementation returned F=G=0 for a near-deterministic negative-drift
hit when its distant peak was narrower than the floating-point u grid.  These
cases must fail closed; rejection is not a certified probability evaluation.
"""
import unittest

from .bond_fpt_independent import integrate_passage, reflected_passage


class ExtremePeakGuardTests(unittest.TestCase):
    def test_distant_peak_must_not_silently_vanish(self):
        # Both inputs are finite with finite a; the old quadrature returns
        # zero for both F and G, contradicting the independent reflection.
        params = dict(x=1e-10, drift=-1., sigma=1e-30,
                      discount=.1, horizon=1.)
        analytic = reflected_passage(**params, require_consistent_ordering=True)
        self.assertEqual(analytic.probability, 1.)
        self.assertGreater(analytic.discounted, .999999)
        with self.assertRaisesRegex(ArithmeticError, 'density peak unresolved'):
            integrate_passage(**params)

    def test_finite_input_transformed_drift_overflow_rejected(self):
        # sigma**2 is subnormal but nonzero; a=drift*x/sigma**2
        # overflows to -inf.  The old quadrature silently returned zero.
        params = dict(x=1e-10, drift=-1., sigma=1e-160,
                      discount=.1, horizon=1.)
        with self.assertRaisesRegex(ArithmeticError, 'transformed drift unresolved'):
            integrate_passage(**params)

    def test_squaring_tiny_but_finite_sigma_must_not_divide_by_zero(self):
        params = dict(x=1e-10, drift=-1., sigma=1e-170,
                      discount=.1, horizon=1.)
        with self.assertRaisesRegex(ArithmeticError, 'squared volatility unresolved'):
            integrate_passage(**params)

    def test_ordinary_resolved_fpt_unchanged(self):
        params = dict(x=.16, drift=-.02, sigma=.25, discount=.08, horizon=2.)
        independent = integrate_passage(**params)
        analytic = reflected_passage(**params, require_consistent_ordering=True)
        self.assertLess(abs(independent.probability-analytic.probability), 3e-11)
        self.assertLess(abs(independent.discounted-analytic.discounted), 3e-11)


if __name__ == '__main__':
    unittest.main()
