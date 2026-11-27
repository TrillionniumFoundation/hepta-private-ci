"""Fixed-seed no-drop broad numeric audit; exploratory, NOT proof by sampling.

Higher-precision reference and the mathematical proof live in sibling tests.
This stress panel uses the same sound Taylor enclosure at 64 terms for cost.
"""
from decimal import Decimal
import random
import unittest

from .test_hx_equity_upper_tail_certificate import P, independent_equity_tail_discrepancy
from .hx_equity_upper_tail_certificate import certified_equity_farfield_boundary


class HXEquityUpperTailNoDropStress(unittest.TestCase):
    def test_16_by_2_no_drop_bounded_numerical_panel(self):
        rng=random.Random(20261031)
        records=[]
        for index in range(16):
            p=P(rate=rng.uniform(.035,.11),payout=rng.uniform(.008,.065),
                volatility=rng.uniform(.16,.43),maturity=rng.uniform(.7,3.5),
                principal=rng.uniform(30.,90.),coupon=rng.uniform(2.,9.),
                tax_shield=rng.uniform(0.,.5),recovery=rng.uniform(.2,.9),
                sale_fraction=rng.uniform(0.,.23),shock_intensity=rng.uniform(.3,2.))
            b=rng.uniform(35.,140.)
            for L in (3.6,6.):
                with self.subTest(index=index,L=L):
                    c=certified_equity_farfield_boundary(p,candidate_barrier=b,
                                                        log_upper=L,taylor_terms=64)
                    bound=float(Decimal(c.upper_equity_abs_budget))
                    observed=abs(independent_equity_tail_discrepancy(p,b,L))
                    self.assertGreater(bound,0)
                    self.assertLessEqual(observed,bound+1e-8)
                    self.assertFalse(c.entire_P0_certified)
                    records.append((index,L,observed,bound))
        self.assertEqual(len(records),32)

if __name__=='__main__': unittest.main()
