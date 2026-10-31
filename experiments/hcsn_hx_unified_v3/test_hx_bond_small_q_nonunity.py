"""HX stopped-coupon small-q sub-unity regression, research only.

Tests deliberately preserve the frozen ordinary-discount branch and explicitly
refuse hit mass when finite-f64 F-G cannot safely resolve the coupon duration.
A high-precision independent Decimal no-hit cashflow is the reference, not
an assertion of full-domain certified rounding or obstacle admissibility.
"""

from decimal import Decimal, localcontext
import math
import random
import unittest
from unittest.mock import patch

from . import hx
from .hx import HX, bond_value


def independent_no_hit(p: HX, tau: float) -> float:
    with localcontext() as ctx:
        ctx.prec = 110
        q = Decimal.from_float(p.q)
        t = Decimal.from_float(tau)
        surviving = (-q * t).exp()
        principal = Decimal.from_float(p.per_bond_principal)
        coupon = Decimal.from_float(p.per_bond_coupon)
        return float(principal * surviving + coupon * (1 - surviving) / q)


class HxBondSmallQNonunityTests(unittest.TestCase):
    def test_existing_unit_rounding_fix_misses_nonunity_subtraction(self):
        p = HX(rate=1e-16, shock_intensity=0., sale_fraction=0.)
        self.assertNotEqual(math.exp(-p.q), 1.)
        expected = independent_no_hit(p, 1.)
        self.assertAlmostEqual(expected, 32., delta=1e-12)
        self.assertAlmostEqual(bond_value(p, 1e100, 1., 1.), expected, delta=1e-12)

    def test_nonunity_maturity_coupon_reference(self):
        p = HX(rate=1e-16, shock_intensity=0., sale_fraction=0.,
               principal=60., coupon=16.)
        tau = .7
        self.assertNotEqual(math.exp(-p.q*tau), 1.)
        self.assertAlmostEqual(bond_value(p, 1e100, tau, 1.),
                               independent_no_hit(p, tau), delta=2e-12)

    def test_underflow_and_tiny_no_hit_limit(self):
        for q in (math.nextafter(0., 1.), 1e-300, 1e-20, 1e-17, 1e-16):
            for tau in (.25, 1., 2.):
                with self.subTest(q=q, tau=tau):
                    p = HX(rate=q, shock_intensity=0., sale_fraction=0.)
                    expected = p.per_bond_principal + p.per_bond_coupon*tau
                    self.assertAlmostEqual(bond_value(p, 1e100, tau, 1.),
                                           expected, delta=2e-12)

    def test_first_hit_mass_in_small_q_band_must_refuse(self):
        for q in (1e-20, 1e-16, 1e-12, 1e-10):
            p = HX(rate=q, shock_intensity=0., sale_fraction=0.)
            with self.subTest(q=q), patch.object(hx, '_first_passage_factors',
                                                 return_value=(.5, .49)):
                with self.assertRaisesRegex(ArithmeticError, 'stopped coupon'):
                    bond_value(p, 1.1, 1., 1.)

    def test_regular_discount_formula_preserved_exactly(self):
        for p in (HX(), HX(sale_fraction=0.)):
            for tau in (.1, 1., p.maturity):
                for asset in (1.1, 2., 1e100):
                    with self.subTest(p=p, tau=tau, asset=asset):
                        F,G = hx._first_passage_factors(p,
                                 hx._log_asset_ratio(asset, 1.), tau)
                        base=p.per_bond_coupon/p.q
                        original=(base+math.exp(-p.q*tau)
                                  *(p.per_bond_principal-base)*(1-F)
                                  +(p.recovery/p.maturity-base)*G)
                        self.assertEqual(bond_value(p,asset,tau,1.), original)

    def test_zero_coupon_not_refused_by_coupon_guard(self):
        p = HX(rate=1e-16, shock_intensity=0., sale_fraction=0., coupon=0.)
        with patch.object(hx, '_first_passage_factors', return_value=(.5,.49)):
            actual=bond_value(p, 1.1, 1., 1.)
        expected=math.exp(-p.q)*p.per_bond_principal*.5+p.recovery/p.maturity*.49
        self.assertEqual(actual,expected)

    def test_seeded_no_hit_decimal_crosscheck(self):
        rng=random.Random(202610301047)
        for _ in range(240):
            q=10.**rng.uniform(-20.,-9.)
            tau=10.**rng.uniform(-1.,math.log10(2.))
            coupon=10.**rng.uniform(-2.,1.)
            p=HX(rate=q, shock_intensity=0., sale_fraction=0., coupon=2*coupon)
            with self.subTest(q=q, tau=tau, coupon=coupon):
                self.assertLess(q*tau,2.**-26)
                self.assertAlmostEqual(bond_value(p,1e100,tau,1.),
                                       independent_no_hit(p,tau),delta=5e-12)


if __name__ == '__main__':
    unittest.main()
