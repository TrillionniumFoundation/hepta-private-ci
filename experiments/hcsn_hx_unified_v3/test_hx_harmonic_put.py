"""Independent high-precision formula and composition tests for r-harmonic put."""
from dataclasses import replace
from fractions import Fraction
import math
import unittest
import mpmath as mp
from .hx import HX,boundary,equity_closed
from .hx_equity_upper_envelope import UnresolvedEquityEnvelope
from .hx_occupation_bound import sharp_fixed_barrier_equity_envelope
from .hx_harmonic_put import (harmonic_put_component,
    tightened_fixed_equity_envelope,_log_upper_ge_one)

class HarmonicPutProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mp.mp.dps=140

    @staticmethod
    def mp_fraction(x):
        return mp.mpf(x.numerator)/x.denominator

    def test_rational_log_upper_exact_direction(self):
        for numer in (100,101,110,123,150,200,350,799):
            ratio=Fraction(numer,100)
            with self.subTest(ratio=str(ratio)):
                upper=_log_upper_ge_one(ratio)
                self.assertGreaterEqual(self.mp_fraction(upper),mp.log(self.mp_fraction(ratio)))
        with self.assertRaises(UnresolvedEquityEnvelope):
            _log_upper_ge_one(Fraction(9))

    def test_harmonic_put_superharmonic_reference(self):
        cases=[HX(), HX(sale_fraction=.2),
            HX(rate=.04,payout=.07,volatility=.32),
            HX(rate=.07,payout=.025,volatility=.2),
            HX(rate=.03,payout=.045,volatility=.21)]
        for p in cases:
            b=boundary(p)
            cert=harmonic_put_component(p,candidate_barrier=b,log_upper=3.6)
            r=mp.mpf(p.rate); delta=mp.mpf(p.payout)
            sigma=mp.mpf(p.volatility);sig2=sigma*sigma
            mu=r-delta-sig2/2
            gamma=(mu+mp.sqrt(mu*mu+2*r*sig2))/sig2
            self.assertLessEqual(mp.mpf(cert.gamma_lower),gamma)
            self.assertGreaterEqual(mp.mpf(cert.gamma_upper),gamma)
            self.assertTrue(float(cert.put_premium_upper)>=0)
            self.assertFalse(cert.production_activation)
            # Compare analytic supremum of the put payoff against certified C.
            T=mp.mpf(p.maturity);q=r+mp.mpf(p.shock_intensity)*mp.mpf(p.sale_fraction)
            c=mp.mpf(p.coupon)/T;par=mp.mpf(p.principal)/T
            C=(1-mp.mpf(p.tax_shield))*mp.mpf(p.coupon)+par
            bond_inf=c/q+mp.exp(-q*T)*(par-c/q)
            K=max(mp.mpf(0),(C-bond_inf)/r)
            bb=mp.mpf(b)
            if K<=bb: coeff=mp.mpf(0)
            else:
                zstar=max(bb,gamma*K/(gamma+1))
                coeff=(K-zstar)*(zstar/bb)**gamma
            exact=coeff*mp.exp(-gamma*mp.mpf(3.6))
            self.assertGreaterEqual(mp.mpf(cert.put_premium_upper),exact)

    def test_tightened_farfield_contains_feasible_hold_policy(self):
        for frac in (.015,.2):
            p=HX(sale_fraction=frac);b=boundary(p);L=3.6
            held=equity_closed(p,b*math.exp(L),b)
            bound=tightened_fixed_equity_envelope(p,candidate_barrier=b,
                log_upper=L,nominal_upper_equity=held)
            with self.subTest(sale_fraction=frac):
                self.assertLessEqual(float(bound.equity_lower),held)
                self.assertGreaterEqual(float(bound.equity_upper),held)
                self.assertLessEqual(float(bound.equity_upper),float(bound.original_equity_upper))
                self.assertFalse(bound.all_scientific_blockers_closed)
                self.assertFalse(bound.production_activation)

    def test_component_extends_old_put_domain_without_promoting_equity(self):
        p=HX(rate=.04,payout=.07,volatility=.32)
        b=boundary(p)
        self.assertGreater(p.payout+p.volatility**2,2*p.rate)
        cert=harmonic_put_component(p,candidate_barrier=b,log_upper=3.6)
        self.assertGreaterEqual(float(cert.put_premium_upper),0)
        with self.assertRaises(UnresolvedEquityEnvelope):
            sharp_fixed_barrier_equity_envelope(p,candidate_barrier=b,
                log_upper=3.6,nominal_upper_equity=0)
        with self.assertRaises(UnresolvedEquityEnvelope):
            cert.certify_p0()

    def test_refuse_bad_domains_and_resource_limits(self):
        p=HX();b=boundary(p)
        for kw in [dict(candidate_barrier=-1,log_upper=3.6),
                   dict(candidate_barrier=b,log_upper=9),
                   dict(candidate_barrier=b,log_upper=3.6,k_denominator=0),
                   dict(candidate_barrier=b,log_upper=3.6,exp_terms=10)]:
            with self.subTest(kw=kw),self.assertRaises(UnresolvedEquityEnvelope):
                harmonic_put_component(p,**kw)
        with self.assertRaises(UnresolvedEquityEnvelope):
            harmonic_put_component(replace(p,payout=0),candidate_barrier=b,log_upper=3.6)

if __name__=='__main__':
    unittest.main()
