"""P0 research-only exact-rational upper-equity budget tests.

Sampled comparisons are independent numerical smoke, not continuum proof.
"""
from types import SimpleNamespace
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import unittest
from .hx import HX, boundary, bond_value, equity_closed
from .hx_equity_upper_envelope import (
    fixed_barrier_equity_upper_envelope, UnresolvedEquityEnvelope,
    _exp_interval_positive, _ceil_decimal, _floor_decimal)


def fdec(s):
    return Fraction(Decimal(s))


class EquityFarFieldEnvelopeTests(unittest.TestCase):
    def test_rational_exp_series_encloses_high_precision_reference(self):
        with localcontext() as c:
            c.prec=900
            for v in (.001,.1,1.,3.6,7.,12.):
                for terms in (64,96,128):
                    with self.subTest(L=v,N=terms):
                        exact=Fraction.from_float(float(v))
                        lo,hi=_exp_interval_positive(exact,terms=terms)
                        ref=Fraction(Decimal.from_float(float(v)).exp())
                        self.assertLess(lo,ref)
                        self.assertGreater(hi,ref)
                        self.assertLess(hi-lo,hi)

    def test_fixed_barrier_bond_and_equity_sampled_comparison(self):
        cases=(HX(),HX(sale_fraction=.2),HX(shock_intensity=0.),
               HX(volatility=.5,payout=.005),HX(coupon=2.,tax_shield=.4))
        for p in cases:
            b=boundary(p)
            q=p.rate+p.shock_intensity*p.sale_fraction
            m=min(p.coupon/(p.maturity*q),p.principal/p.maturity,
                  p.recovery*b/p.maturity)
            M=max(p.coupon/(p.maturity*q),p.principal/p.maturity,
                  p.recovery*b/p.maturity)
            C=(1-p.tax_shield)*p.coupon+p.principal/p.maturity
            for ratio in (1.02,1.2,2.,5.,10.,50.):
                for duration in (0.,.1*p.maturity,p.maturity):
                    with self.subTest(p=p,ratio=ratio,tau=duration):
                        observed=bond_value(p,b*ratio,duration,b)
                        self.assertGreaterEqual(observed,m-1e-9)
                        self.assertLessEqual(observed,M+1e-9)
            for log_upper in (2.,3.6,5.):
                A=b*math.exp(log_upper)
                Bnd=(p.coupon/p.maturity)/q+math.exp(-q*p.maturity)*(
                    p.principal/p.maturity-(p.coupon/p.maturity)/q)
                guess=A+(Bnd-C)/p.rate
                out=fixed_barrier_equity_upper_envelope(
                    p,candidate_barrier=b,log_upper=log_upper,
                    nominal_upper_equity=guess)
                observed=equity_closed(p,A,b)
                low=fdec(out.equity_lower);high=fdec(out.equity_upper)
                err=fdec(out.upper_equity_abs_budget)
                with self.subTest(p=p,log_upper=log_upper):
                    # The reference is a fixed-barrier resolvent, not the
                    # optimal-stopping value; at these far states it still
                    # lies within the conservative optimal-equity envelope.
                    self.assertLessEqual(float(low)-1e-6,observed)
                    self.assertLessEqual(observed,float(high)+1e-6)
                    self.assertLessEqual(abs(Fraction.from_float(guess)-Fraction.from_float(observed)),err+Fraction(1,10**6))
                    self.assertGreater(err,0)
                    self.assertEqual(out.taylor_terms,96)
                    self.assertFalse(out.scientific_gate_closed)
                    self.assertFalse(out.global_equilibrium_certified)
                    self.assertFalse(out.complete_debt_error_budget)
                    self.assertFalse(out.production_activation)
                    with self.assertRaises(UnresolvedEquityEnvelope):
                        out.to_complete_p0_certificate()

    def test_decimal_budget_is_outward_from_exact_rational(self):
        for x in (Fraction(0),Fraction(1,7),Fraction(10**6,3),
                  Fraction(104**5,11),Fraction(1,10**15)):
            for d in (4,12,16):
                with self.subTest(x=x,places=d):
                    got=fdec(_ceil_decimal(x,places=d))
                    self.assertGreaterEqual(got,x)
                    self.assertLess(got-x,Fraction(1,10**d))
                    lower=fdec(_floor_decimal(x,places=d))
                    self.assertLessEqual(lower,x)
                    self.assertLess(x-lower,Fraction(1,10**d))

    def test_nominal_equity_error_not_hidden_when_upper_guess_corrupt(self):
        p=HX();b=boundary(p)
        a=fixed_barrier_equity_upper_envelope(p,candidate_barrier=b,
             log_upper=3.6,nominal_upper_equity=1e5)
        z=fdec(a.upper_equity_abs_budget)
        self.assertGreater(z,90000)
        self.assertTrue(a.equity_upper)

    def test_fail_closed_domains(self):
        p=HX(); b=boundary(p)
        # Use standalone field contracts: upstream HX constructor itself
        # rejects invalid finance, and must not prevent testing THIS gate.
        bad=lambda **kw: SimpleNamespace(**(vars(p)|kw))
        invalid=[(bad(payout=0.),{}), (bad(payout=-.01),{}),
                 (bad(rate=0.),{}), (bad(volatility=0.),{}),
                 (bad(recovery=2.),{}), (bad(maturity=0.),{}),
                 (bad(principal=0.),{}), (bad(coupon=-1.),{}),
                 (p,{'candidate_barrier':0.}),
                 (p,{'candidate_barrier':float('nan')}),
                 (p,{'nominal_upper_equity':float('inf')}),
                 (p,{'log_upper':-1.}), (p,{'log_upper':12.1}),
                 (p,{'log_upper':'3.6'}), (p,{'taylor_terms':1}),
                 (p,{'taylor_terms':161})]
        for bad,changed in invalid:
            params={'candidate_barrier':b,'log_upper':3.6,
                    'nominal_upper_equity':2000.}
            params.update(changed)
            with self.subTest(changed=changed,bad=bad),self.assertRaises(UnresolvedEquityEnvelope):
                fixed_barrier_equity_upper_envelope(bad,**params)

if __name__=='__main__':unittest.main()
