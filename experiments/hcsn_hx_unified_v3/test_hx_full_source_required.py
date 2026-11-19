"""Mandatory source-level HX integration gate; missing hx.py is a TEST ERROR.

Unlike the optional development-only integration in test_bond_fpt_independent,
importing the real upstream HX module is unconditional. No test skips.
Research-only finite sample, not production admission or rigorous interval proof.
"""
import math
import unittest

from .hx import HX, boundary, bond_value, default_probability, discounted_default_factor
from .bond_fpt_independent import independent_bond


class FullHXIntegrationTests(unittest.TestCase):
    def test_f_g_and_bond_exact_upstream_90_comparisons(self):
        checks=0
        for p in (HX(), HX(sale_fraction=.2), HX(payout=0),
                  HX(sale_fraction=0), HX(maturity=.5, volatility=.36)):
            b=boundary(p)
            self.assertTrue(math.isfinite(b) and b>0)
            for ratio in (1.02, 1.2, 2.5):
                asset=b*ratio
                for tau in (.15*p.maturity,p.maturity):
                    d,fp=independent_bond(x=math.log(ratio),
                        drift=p.rate-p.payout-.5*p.volatility**2,
                        sigma=p.volatility, discount=p.q, horizon=tau,
                        coupon_per_bond=p.per_bond_coupon,
                        principal_per_bond=p.per_bond_principal,
                        recovery_per_bond=p.recovery*b/p.maturity)
                    self.assertAlmostEqual(fp.probability,
                        default_probability(p,asset,tau,b),delta=3e-9)
                    self.assertAlmostEqual(fp.discounted,
                        discounted_default_factor(p,asset,tau,b),delta=3e-9)
                    self.assertAlmostEqual(d,bond_value(p,asset,tau,b),delta=3e-8)
                    checks+=3
        self.assertEqual(checks,90)

    def test_near_barrier_and_short_maturity_108_independent_values(self):
        checks=0
        for p in (HX(),HX(sale_fraction=.2),HX(payout=0),HX(sale_fraction=0)):
            b=boundary(p)
            for ratio in (1.+1e-8,1.+1e-5,1.+1e-2):
                for tau in (p.maturity*1e-4,p.maturity*.05,p.maturity):
                    d,fp=independent_bond(x=math.log(ratio),
                        drift=p.rate-p.payout-.5*p.volatility**2,
                        sigma=p.volatility,discount=p.q,horizon=tau,
                        coupon_per_bond=p.per_bond_coupon,
                        principal_per_bond=p.per_bond_principal,
                        recovery_per_bond=p.recovery*b/p.maturity)
                    self.assertAlmostEqual(fp.probability,
                        default_probability(p,b*ratio,tau,b),delta=1e-7)
                    self.assertAlmostEqual(fp.discounted,
                        discounted_default_factor(p,b*ratio,tau,b),delta=1e-7)
                    self.assertAlmostEqual(d,bond_value(p,b*ratio,tau,b),delta=3e-6)
                    checks+=3
        self.assertEqual(checks,108)


if __name__=='__main__':
    unittest.main()
