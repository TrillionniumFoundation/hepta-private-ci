"""Research-only HX F/G physical envelope regression (never silently clip)."""
import math
import unittest

from .hx import HX, bond_value, default_probability, discounted_default_factor


class HXFirstPassageEnvelope(unittest.TestCase):
    def test_frozen_near_boundary_roundoff_reversal_is_denied(self):
        # Both rates are strictly positive, tau>0 and asset>barrier.
        # Original f64 F=0.9999999999942438, G=0.9999999999942439;
        # independent 110-dps mpmath gives F-G~9.71516418409e-22 > 0.
        p=HX(rate=.007595780582070804,
             payout=3.5072936797757205e-07,
             volatility=1.8581469732429565,
             maturity=2.2216211523554883e-08,
             shock_intensity=1.158839083935111e-13,
             sale_fraction=1.0)
        b=1.0
        asset=1.000000000000002
        for evaluate in (default_probability, discounted_default_factor, bond_value):
            with self.subTest(entry=evaluate.__name__):
                with self.assertRaisesRegex(ArithmeticError, 'F/G ordering unresolved'):
                    evaluate(p, asset, p.maturity, b)

    def test_regular_fpt_pair_and_bond_remain_finite(self):
        p=HX()
        for ratio in (1.00001, 1.1, 2., 4.):
            for tau in (1e-8, .5, p.maturity):
                with self.subTest(ratio=ratio, tau=tau):
                    f=default_probability(p,ratio,tau,1.)
                    g=discounted_default_factor(p,ratio,tau,1.)
                    d=bond_value(p,ratio,tau,1.)
                    self.assertTrue(0 <= g <= f <= 1)
                    self.assertTrue(math.isfinite(d))

    def test_immediate_event_and_zero_horizon_endpoints(self):
        p=HX()
        self.assertEqual(default_probability(p,1.,p.maturity,1.),1.)
        self.assertEqual(discounted_default_factor(p,1.,p.maturity,1.),1.)
        self.assertEqual(default_probability(p,2.,0.,1.),0.)
        self.assertEqual(discounted_default_factor(p,2.,0.,1.),0.)
        self.assertEqual(bond_value(p,2.,0.,1.),p.per_bond_principal)
        self.assertEqual(bond_value(p,1.,p.maturity,1.),p.recovery/p.maturity)


if __name__ == '__main__':
    unittest.main()
