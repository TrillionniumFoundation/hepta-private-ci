"""Finite-operand extreme asset/boundary ratio: no silent HX NaN.

This is a targeted analytic reference regression, not all-domain certified
He--Xiong QVI, low-precision verification, or a neural causal-gain result.
"""
import math
import unittest

from .hx import (HX, _log_asset_ratio, bond_value, default_probability,
                 discounted_default_factor)


class HXLogRatioOverflowTests(unittest.TestCase):
    def test_finite_extreme_ratios_reach_zero_first_passage_tail(self):
        p = HX()
        for asset, b in ((1e308, 1e-308), (1e308, 1e-100),
                         (1e200, 1e-200)):
            self.assertTrue(math.isinf(asset / b))
            for tau in (1e-6, p.maturity):
                with self.subTest(asset=asset, boundary=b, tau=tau):
                    f = default_probability(p, asset, tau, b)
                    g = discounted_default_factor(p, asset, tau, b)
                    self.assertTrue(math.isfinite(f))
                    self.assertTrue(math.isfinite(g))
                    self.assertEqual(f, 0.)
                    self.assertEqual(g, 0.)

    def test_extreme_ratio_bond_has_finite_risk_free_asymptote(self):
        p = HX()
        base = p.per_bond_coupon / p.q
        for asset, b in ((1e308, 1e-308), (1e308, 1e-100),
                         (1e200, 1e-200)):
            for tau in (1e-6, p.maturity):
                with self.subTest(asset=asset, boundary=b, tau=tau):
                    observed = bond_value(p, asset, tau, b)
                    reference = (base + math.exp(-p.q * tau) *
                                 (p.per_bond_principal - base))
                    self.assertTrue(math.isfinite(observed))
                    self.assertAlmostEqual(observed, reference, delta=2e-12)

    def test_normal_ratios_preserve_existing_quotient_log(self):
        for asset, b in ((1.00000001, 1.), (2., 1.), (100., 1.),
                         (1e8, 1e5), (1e-7, 1e-8)):
            with self.subTest(asset=asset, boundary=b):
                self.assertEqual(_log_asset_ratio(asset, b),
                                 math.log(asset / b))

    def test_default_and_zero_maturity_unchanged(self):
        p = HX()
        b = 1e-308
        self.assertEqual(default_probability(p, b, p.maturity, b), 1.)
        self.assertEqual(discounted_default_factor(p, b, p.maturity, b), 1.)
        self.assertEqual(bond_value(p, 1e308, 0., b), p.per_bond_principal)
        self.assertEqual(default_probability(p, 1e308, 0., b), 0.)
        self.assertEqual(discounted_default_factor(p, 1e308, 0., b), 0.)


if __name__ == '__main__':
    unittest.main()
