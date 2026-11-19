"""HX first-passage F/G ordering is a fail-closed numerical contract.

These are research f64 source-integration regressions, not interval proofs or
production native-precision benchmarks.
"""
import math
import unittest
from unittest.mock import patch

from scipy.special import ndtr

from . import hx
from .hx import HX, bond_value, default_probability, discounted_default_factor


class JointFirstPassageContractTests(unittest.TestCase):
    def test_ordinary_values_preserve_the_previous_two_formulas(self):
        for p in (HX(), HX(sale_fraction=0.), HX(payout=0.)):
            for tau in (1e-8, p.maturity / 2., p.maturity):
                for ratio in (1.00001, 1.1, 1.6, 2., 4.):
                    with self.subTest(p=p, tau=tau, ratio=ratio):
                        v=math.log(ratio)
                        u=p.volatility*math.sqrt(tau)
                        old_f=(float(ndtr((-v-p.a*u*u)/u))
                               +hx._exp_cdf(-2*p.a*v,(-v+p.a*u*u)/u))
                        old_g=(hx._exp_cdf((-p.a+p.zhat)*v,(-v-p.zhat*u*u)/u)
                               +hx._exp_cdf((-p.a-p.zhat)*v,(-v+p.zhat*u*u)/u))
                        actual_f=default_probability(p,ratio,tau,1.)
                        actual_g=discounted_default_factor(p,ratio,tau,1.)
                        self.assertEqual((actual_f,actual_g),(old_f,old_g))
                        self.assertTrue(0<=actual_g<=actual_f<=1)

    def test_forced_invalid_pairs_are_refused_without_clamping(self):
        p=HX()
        v=math.log(1.6)
        for forced in ((0., .9, .9), (math.nan, 0., 0.),
                       (0., -.5, 0.), (1.5, 0., 0.)):
            with self.subTest(forced=forced):
                with patch.object(hx, '_exp_cdf', side_effect=forced):
                    with self.assertRaises(ArithmeticError):
                        hx._first_passage_factors(p,v,p.maturity)

    def test_near_boundary_real_roundoff_cannot_escape_as_bad_result(self):
        # This witness gives G-F=+1 f64 ULP with Python 3.13/SciPy 1.17.
        # Different libm/SciPy versions may round to an admissible pair;
        # both explicit refusal and physically ordered admission are valid.
        p=HX(rate=1.3090468849180657e-7,
             payout=.11176379671252477,
             volatility=.9066753141892397,
             maturity=.0002461050758857373,
             shock_intensity=.0009457207995848884,
             sale_fraction=1.)
        asset=1.0000000000032205
        try:
            f=default_probability(p,asset,p.maturity,1.)
            g=discounted_default_factor(p,asset,p.maturity,1.)
            bond=bond_value(p,asset,p.maturity,1.)
        except ArithmeticError:
            return
        self.assertTrue(0<=g<=f<=1)
        self.assertTrue(math.isfinite(bond))

    def test_endpoint_and_extreme_ratio_paths(self):
        p=HX()
        self.assertEqual(default_probability(p,1.,p.maturity,1.),1.)
        self.assertEqual(discounted_default_factor(p,1.,p.maturity,1.),1.)
        self.assertEqual(default_probability(p,1.6,0.,1.),0.)
        self.assertEqual(discounted_default_factor(p,1.6,0.,1.),0.)
        self.assertEqual(bond_value(p,1.6,0.,1.),p.per_bond_principal)
        for tau in (1e-6,p.maturity):
            with self.subTest(tau=tau):
                self.assertEqual(default_probability(p,1e308,tau,1e-308),0.)
                self.assertEqual(discounted_default_factor(p,1e308,tau,1e-308),0.)
                self.assertTrue(math.isfinite(bond_value(p,1e308,tau,1e-308)))


if __name__=='__main__':
    unittest.main()
