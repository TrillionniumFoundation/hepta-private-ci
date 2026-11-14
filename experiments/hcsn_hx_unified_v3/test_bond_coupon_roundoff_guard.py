"""Frozen discount-cancellation witnesses in independent HX stopped cash flow.

Research-only diagnostic: an ArithmeticError is a denial, not a proof that
its positive-return numerical values have rigorously certified intervals.
"""
import math
import unittest

from .bond_fpt_independent import independent_bond


class BondCouponRoundoffGuardTests(unittest.TestCase):
    def test_unresolved_default_coupon_duration_is_refused(self):
        # For q approaching zero, coupon present value must not collapse to
        # zero: a positive stopping time earns strictly positive coupons.
        # The historical subtraction (1-G-exp(-qh)*(1-F))/q returned 0.0.
        for x, drift, sigma, horizon in (
                (.7, .01, .22, 3.),
                (.005, -.03, .2, 2.),
                (.1, -.5, .3, 3.)):
            with self.subTest(x=x):
                with self.assertRaisesRegex(ArithmeticError, 'coupon duration unresolved'):
                    independent_bond(x=x, drift=drift, sigma=sigma,
                        discount=1e-20, horizon=horizon,
                        coupon_per_bond=1., principal_per_bond=0.,
                        recovery_per_bond=0.)

    def test_no_default_tail_preserves_near_zero_discount_coupon(self):
        # F=G=0 to f64 precision here; no spurious cancellation of the
        # survival coupon annuity is permitted.
        b,fp=independent_bond(x=50., drift=.2, sigma=.2,
            discount=1e-20, horizon=3., coupon_per_bond=1.,
            principal_per_bond=0., recovery_per_bond=0.)
        self.assertEqual(fp.probability,0.)
        self.assertAlmostEqual(b,3.,delta=1e-13)

    def test_zero_or_subnormal_discount_horizon_is_refused(self):
        # Exact q=2**-1074: q*T rounds to 0, q, or 2*q, respectively.
        # The unguarded expm1 annuity is 0, 1, or 2 instead of T.
        q=math.ldexp(1.,-1074)
        for horizon,rounded_product in ((.25,0.),(.75,q),(1.5,2*q)):
            with self.subTest(horizon=horizon):
                self.assertEqual(q*horizon,rounded_product)
                with self.assertRaisesRegex(ArithmeticError,
                                            'discount-horizon product unresolved'):
                    independent_bond(x=50.,drift=.2,sigma=.2,
                        discount=q,horizon=horizon,coupon_per_bond=1.,
                        principal_per_bond=0.,recovery_per_bond=0.)

    def test_zero_coupon_does_not_require_resolved_annuity(self):
        # No coupon division is needed. Keep the zero-coupon API valid
        # for these same discount products when other guards permit it.
        q=math.ldexp(1.,-1074)
        for horizon in (.25,.75,1.5):
            with self.subTest(horizon=horizon):
                bond,fp=independent_bond(x=50.,drift=.2,sigma=.2,
                    discount=q,horizon=horizon,coupon_per_bond=0.,
                    principal_per_bond=1.,recovery_per_bond=0.)
                self.assertEqual(fp.probability,0.)
                self.assertEqual(bond,1.)

    def test_well_resolved_bond_matches_legacy_decomposition(self):
        kwargs=dict(x=.7, drift=.01, sigma=.22, discount=.09,
            horizon=3., coupon_per_bond=2., principal_per_bond=30.,
            recovery_per_bond=11.)
        b,fp=independent_bond(**kwargs)
        survival=1-fp.probability
        terminal=math.exp(-kwargs['discount']*kwargs['horizon'])*survival
        legacy=(kwargs['coupon_per_bond']*(1-fp.discounted-terminal)/kwargs['discount']
                +kwargs['principal_per_bond']*terminal
                +kwargs['recovery_per_bond']*fp.discounted)
        self.assertAlmostEqual(b,legacy,delta=2e-12)


if __name__ == '__main__':
    unittest.main()
