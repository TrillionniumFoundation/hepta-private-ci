"""Bounded far-field debt tests against independent existing HX bond formula.

These comparisons are empirical; they do not prove outward-rounded floating
point enclosure and do not provide the equity upper-bound hypothesis.
"""
from dataclasses import replace
import math
import unittest
from .hx import HX, bond_value, boundary
from .hx_far_field_bond_budget import far_field_bond_budget, UnresolvedFarTail

class FarFieldBudgetTests(unittest.TestCase):
    def test_bounded_sampled_bonds(self):
        cases=(HX(),HX(sale_fraction=.2),HX(shock_intensity=0),
               HX(volatility=.5,payout=.005),HX(payout=0))
        for p in cases:
            b=boundary(p)
            for ratio in (1.01,1.1,1.5,2,5,10,50,100):
                with self.subTest(p=p,ratio=ratio):
                    result=far_field_bond_budget(p,asset=b*ratio,boundary=b,
                                                 maturity=p.maturity)
                    actual=bond_value(p,b*ratio,p.maturity,b)
                    self.assertLessEqual(abs(actual-result.no_default_bond),
                                         result.bond_error_budget+1e-10)
                    self.assertIsNone(result.equity_upper_error_budget)
                    self.assertFalse(result.production_activation)
                    self.assertFalse(result.scientific_admission)

    def test_tail_shrinks_and_no_false_equity_certificate(self):
        p=HX()
        b=boundary(p)
        near=far_field_bond_budget(p,asset=b*2,boundary=b,maturity=p.maturity)
        far=far_field_bond_budget(p,asset=b*100,boundary=b,maturity=p.maturity)
        self.assertLess(far.bond_error_budget,near.bond_error_budget)
        self.assertIsNone(far.equity_upper_error_budget)

    def test_refuse_invalid_domain(self):
        p=HX(); b=boundary(p)
        for kwargs in ({'asset':b},{'asset':math.nan},
                       {'boundary':0},{'maturity':-1}):
            kw={'asset':b*2,'boundary':b,'maturity':p.maturity}
            kw.update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(UnresolvedFarTail):
                far_field_bond_budget(p,**kw)
        with self.assertRaises(UnresolvedFarTail):
            far_field_bond_budget(replace(p,volatility=0),asset=b*2,
                                  boundary=b,maturity=p.maturity)

if __name__=='__main__':
    unittest.main()
