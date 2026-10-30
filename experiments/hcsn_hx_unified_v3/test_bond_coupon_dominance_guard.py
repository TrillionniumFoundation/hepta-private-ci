"""Research-only fail-closed upper envelope for stopped coupon cashflows.

For every stopping time tau >= 0 and horizon h > 0, the discounted coupon
annuity up to min(tau,h) is in [0,(1-exp(-q*h))/q]. These are necessary
bounds, NOT a certified quadrature error interval. Frozen 100-dps direct
first-passage-density counterexample from an independently seeded scan.
"""
import math
import unittest

from .bond_fpt_independent import independent_bond


class BondCouponDominanceGuardTests(unittest.TestCase):
    def test_tiny_default_mass_must_not_overpay_undiscounted_coupon(self):
        # 2026103008 seeded scan, index 19121. The previous carveout
        # F<1e-9 bypassed F-G cancellation and returned a coupon PV
        # 3.3944358168769027 > full-horizon annuity 3.3944358165869706.
        # Independent 100-dps integration of the *time-domain* hitting
        # density gives 3.3944358165861241828787692424615... instead.
        kwargs = dict(x=7.574364447822511,
                      drift=-0.10335391582430709,
                      sigma=0.5722860259650109,
                      discount=2.2140977267535007e-16,
                      horizon=3.394435816586972,
                      coupon_per_bond=1., principal_per_bond=0.,
                      recovery_per_bond=0.)
        with self.assertRaisesRegex(ArithmeticError, 'coupon domination unresolved'):
            independent_bond(**kwargs)

    def test_no_default_control_retains_stable_coupon(self):
        kwargs = dict(x=50.,drift=.2,sigma=.2,discount=1e-20,horizon=3.,
                      coupon_per_bond=1.,principal_per_bond=0.,
                      recovery_per_bond=0.)
        actual, fp = independent_bond(**kwargs)
        ceiling=-math.expm1(-kwargs['discount']*kwargs['horizon'])/kwargs['discount']
        self.assertEqual(fp.probability,0.)
        self.assertAlmostEqual(actual,ceiling,delta=1e-13)


if __name__ == '__main__':
    unittest.main()
