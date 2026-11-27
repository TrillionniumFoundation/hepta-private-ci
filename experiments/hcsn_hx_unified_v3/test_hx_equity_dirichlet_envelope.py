"""Fixed-barrier HX upper-equity error enclosure regression tests."""
import unittest
from types import SimpleNamespace
from decimal import Decimal
from fractions import Fraction
from .hx_equity_dirichlet_envelope import (
    fixed_barrier_equity_dirichlet, UnresolvedEquityEnvelope, _decimal, _exp_bounds)

def p(**changes):
    fields=dict(rate=.05,payout=.03,volatility=.25,maturity=2.,
                principal=60.,coupon=4.,tax_shield=.25,recovery=.6,
                shock_intensity=1.,sale_fraction=.015)
    fields.update(changes)
    return SimpleNamespace(**fields)

class EquityEnvelopeTests(unittest.TestCase):
    def test_opposite_rounding_directions(self):
        self.assertEqual(_decimal(Fraction(1,3),False),'0.333333333333')
        self.assertEqual(_decimal(Fraction(1,3),True),'0.333333333334')

    def test_taylor_bounds(self):
        for x in (Fraction(1,10),Fraction(18,5),Fraction(12)):
            lo,hi=_exp_bounds(x,160)
            self.assertLess(lo,hi)
            self.assertGreater(lo,0)
            self.assertLess(hi-lo,Fraction(1,10**30))

    def test_financial_panels_do_not_upgrade_certification(self):
        for change in ({},{'sale_fraction':.2},{'volatility':.4,'payout':.01}):
            e=fixed_barrier_equity_dirichlet(p(**change),
                    candidate_boundary=80.,log_upper=3.6,
                    nominal_upper_equity=2700.)
            self.assertLessEqual(Decimal(e.asset_lower),Decimal(e.asset_upper))
            self.assertLessEqual(Decimal(e.equity_lower),Decimal(e.equity_upper))
            self.assertGreaterEqual(Decimal(e.equity_upper),Decimal(e.asset_upper))
            self.assertFalse(e.global_certification)
            self.assertFalse(e.complete_debt_error_budget)
            self.assertFalse(e.production_activation)
            self.assertFalse(e.all_scientific_blockers_closed)
            with self.assertRaises(UnresolvedEquityEnvelope):e.certify_global_hx()

    def test_no_payout_or_invalid_domain_refused(self):
        for ch in ({'payout':0},{'rate':0},{'recovery':2},
                   {'sale_fraction':2},{'maturity':0}):
            with self.subTest(ch=ch),self.assertRaises(UnresolvedEquityEnvelope):
                fixed_barrier_equity_dirichlet(p(**ch),
                  candidate_boundary=80.,log_upper=3.6,nominal_upper_equity=2700.)

    def test_invalid_boundaries_refused(self):
        for b,L in ((0,3.6),(80,0),(80,13)):
            with self.subTest(b=b,L=L),self.assertRaises(UnresolvedEquityEnvelope):
                fixed_barrier_equity_dirichlet(p(),
                    candidate_boundary=b,log_upper=L,nominal_upper_equity=300.)

if __name__=="__main__":
    unittest.main()
