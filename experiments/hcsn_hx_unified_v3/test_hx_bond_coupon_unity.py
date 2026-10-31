"""HX bond tiny-discount coupon regression: research-only, not interval proof.

The source-exact integration suite must run in an actual repository checkout;
focused reproductions are reported separately from full-repository CI.
"""
import math
import unittest

from . import hx
from .hx import HX, bond_value, default_probability, discounted_default_factor


class HxBondCouponUnityTests(unittest.TestCase):
    def test_extreme_small_q_no_hit_cashflow(self):
        p=HX(rate=1e-20,shock_intensity=0.,sale_fraction=0.)
        for tau in (.25,1.,p.maturity):
            with self.subTest(tau=tau):
                self.assertEqual(default_probability(p,1e100,tau,1.),0.)
                self.assertEqual(discounted_default_factor(p,1e100,tau,1.),0.)
                expected=p.per_bond_principal+p.per_bond_coupon*tau
                self.assertAlmostEqual(bond_value(p,1e100,tau,1.),expected,delta=2e-12)

    def test_q_times_tau_underflow_retains_coupon_limit(self):
        p=HX(rate=math.nextafter(0.,1.),shock_intensity=0.,sale_fraction=0.)
        self.assertEqual(p.q*.25,0.)
        self.assertEqual(default_probability(p,1e100,.25,1.),0.)
        self.assertEqual(discounted_default_factor(p,1e100,.25,1.),0.)
        self.assertEqual(bond_value(p,1e100,.25,1.),30.5)

    def test_near_boundary_material_first_hit_refused_when_discount_is_one(self):
        p=HX(rate=1e-20,shock_intensity=0.,sale_fraction=0.)
        self.assertEqual(math.exp(-p.q),1.)
        # Previously: an impossible bond price ~32768 despite a 32.3
        # undiscounted bound on principal + stopped coupon + recovery.
        with self.assertRaisesRegex(ArithmeticError,'stopped coupon'):
            bond_value(p,1.1,1.,1.)

    def test_zero_coupon_does_not_inherit_coupon_only_refusal(self):
        p=HX(rate=1e-20,shock_intensity=0.,sale_fraction=0.,coupon=0.)
        f=default_probability(p,1.1,1.,1.)
        g=discounted_default_factor(p,1.1,1.,1.)
        expected=p.per_bond_principal*(1-f)+p.recovery/p.maturity*g
        self.assertEqual(bond_value(p,1.1,1.,1.),expected)

    def test_regular_discount_path_is_legacy_bit_exact(self):
        for p in (HX(),HX(sale_fraction=0.)):
            for tau in (1e-6,p.maturity/2.,p.maturity):
                for ratio in (1.1,1.6,4.,1e100):
                    with self.subTest(p=p,tau=tau,ratio=ratio):
                        f,g=hx._first_passage_factors(p,math.log(ratio),tau)
                        base=p.per_bond_coupon/p.q
                        recovery=p.recovery/p.maturity
                        old=(base+math.exp(-p.q*tau)
                             *(p.per_bond_principal-base)*(1-f)
                             +(recovery-base)*g)
                        self.assertEqual(bond_value(p,ratio,tau,1.),old)

    def test_public_boundary_and_zero_duration_endpoints_unchanged(self):
        p=HX()
        self.assertEqual(bond_value(p,1.,p.maturity,1.),p.recovery/p.maturity)
        self.assertEqual(bond_value(p,1.1,0.,1.),p.per_bond_principal)


if __name__=='__main__':
    unittest.main()
