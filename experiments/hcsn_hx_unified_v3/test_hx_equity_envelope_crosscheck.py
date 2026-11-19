"""Independent two-implementation differential audit of HCSN P0 PR #4513.

Both targets compute a mathematical component only.  Equality cannot prove
that the fixed default barrier is self-consistent or a global HX solution.
"""
from decimal import Decimal
import math
import random
import unittest
from .hx import HX, boundary
from .hx_equity_dirichlet_envelope import fixed_barrier_equity_dirichlet
from .hx_equity_upper_envelope import fixed_barrier_equity_upper_envelope


class EquityEnvelopeDifferentialTests(unittest.TestCase):
    def test_two_independent_implementations_60_deterministic_inputs(self):
        rng=random.Random(20261031)
        cases=[]
        for i in range(60):
            p=HX(rate=rng.uniform(.01,.15),payout=rng.uniform(.0001,.1),
                 volatility=rng.uniform(.05,.7),maturity=rng.uniform(.5,8.),
                 principal=rng.uniform(10.,200.),coupon=rng.uniform(0.,12.),
                 tax_shield=rng.uniform(0.,.8),recovery=rng.uniform(0.,1.),
                 shock_intensity=rng.uniform(0.,2.),sale_fraction=rng.uniform(0.,.75))
            b=rng.uniform(10.,200.)
            L=rng.uniform(.05,8.)
            guess=b*math.exp(L)-rng.uniform(-2000.,2000.)
            cases.append((p,b,L,guess))
        for i,(p,b,L,guess) in enumerate(cases):
            with self.subTest(case=i):
                left=fixed_barrier_equity_upper_envelope(p,candidate_barrier=b,
                    log_upper=L,nominal_upper_equity=guess)
                right=fixed_barrier_equity_dirichlet(p,candidate_boundary=b,
                    log_upper=L,nominal_upper_equity=guess)
                pairs=((left.asset_lower,right.asset_lower),
                       (left.asset_upper,right.asset_upper),
                       (left.equity_lower,right.equity_lower),
                       (left.equity_upper,right.equity_upper),
                       (left.upper_equity_abs_budget,right.upper_dirichlet_abs_error_budget),
                       (left.bond_lower,right.debt_lower),
                       (left.bond_upper,right.debt_upper))
                for a,z in pairs: self.assertEqual(a,z)
                self.assertFalse(left.production_activation)
                self.assertFalse(right.production_activation)
                self.assertFalse(left.global_equilibrium_certified)
                self.assertFalse(right.global_certification)

    def test_historical_high_liquidity_and_censored_boundaries(self):
        cases=(HX(),HX(sale_fraction=.2),HX(shock_intensity=0.))
        for p in cases:
            b=boundary(p)
            for upper in (2.,3.6,5.):
                for guess in (-500.,0.,50_000.):
                    a=fixed_barrier_equity_upper_envelope(p,candidate_barrier=b,
                        log_upper=upper,nominal_upper_equity=guess)
                    z=fixed_barrier_equity_dirichlet(p,candidate_boundary=b,
                        log_upper=upper,nominal_upper_equity=guess)
                    with self.subTest(p=p,upper=upper,guess=guess):
                        self.assertEqual(a.upper_equity_abs_budget,z.upper_dirichlet_abs_error_budget)
                        self.assertGreaterEqual(Decimal(a.upper_equity_abs_budget),0)
                        self.assertTrue(a.uncovered)

    def test_strict_interval_direction_and_denied_admission(self):
        p=HX();b=boundary(p)
        z=fixed_barrier_equity_dirichlet(p,candidate_boundary=b,
                    log_upper=3.6,nominal_upper_equity=2000.)
        self.assertLessEqual(Decimal(z.equity_lower),Decimal(z.equity_upper))
        self.assertFalse(z.complete_debt_error_budget)
        self.assertFalse(z.all_scientific_blockers_closed)
        with self.assertRaises(ValueError): z.certify_global_hx()

if __name__=='__main__':unittest.main()
