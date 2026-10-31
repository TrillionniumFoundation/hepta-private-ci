"""Independent high-precision references and fail-closed checks for tight envelope."""
from dataclasses import replace
from fractions import Fraction
import math
import unittest

import mpmath as mp

from .hx import HX, boundary, equity_closed
from .hx_equity_upper_envelope import (fixed_barrier_equity_upper_envelope,
                                        UnresolvedEquityEnvelope)
from .hx_occupation_bound import (_exp_neg_interval, _sqrt_interval,
    _occupation_upper, _tail_cdf_bound, sharp_fixed_barrier_equity_envelope)


def _as_mp(q):
    if isinstance(q,Fraction):
        return mp.mpf(q.numerator)/q.denominator
    return mp.mpf(float(q))


class TightFixedBarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mp.mp.dps=400

    def test_exact_rational_exp_and_sqrt_bounds(self):
        for x in (Fraction(0),Fraction(1,10),Fraction(7,2),Fraction(9),
                  Fraction(31,2),Fraction(41),Fraction(63)):
            with self.subTest(x=str(x)):
                lo,hi=_exp_neg_interval(x)
                truth=mp.exp(-_as_mp(x))
                self.assertLessEqual(_as_mp(lo),truth)
                self.assertGreaterEqual(_as_mp(hi),truth)
                self.assertLess(hi-lo,Fraction(1,10**30))
        for x in (Fraction(2),Fraction(1,1000),Fraction(123456,7)):
            lo,hi=_sqrt_interval(x)
            self.assertLessEqual(lo*lo,x)
            self.assertGreater(hi*hi,x)
            self.assertLess(hi-lo,Fraction(1,10**16))

    def test_brownian_occupation_and_gaussian_tail_upper(self):
        for p in (HX(),HX(sale_fraction=.2),HX(rate=.08,payout=.04,volatility=.2)):
            mu=Fraction.from_float(p.rate)-Fraction.from_float(p.payout)-Fraction.from_float(p.volatility)**2/2
            s2=Fraction.from_float(p.volatility)**2
            rate=Fraction.from_float(p.rate)
            T=Fraction.from_float(p.maturity)
            a=mu/s2
            z=mp.sqrt(_as_mp(a)**2+2*_as_mp(rate)/_as_mp(s2))
            gamma=_as_mp(a)+z
            eta=z-_as_mp(a)
            zl,zu=_sqrt_interval(a*a+2*rate/s2)
            gl=a+zl
            L=Fraction(18,5)
            for u in (Fraction(1,5),Fraction(1,2),Fraction(1)):
                with self.subTest(p=p,u=str(u)):
                    upper=_occupation_upper(L,u,s2,zl,gl)
                    ex=mp.exp(-gamma*_as_mp(L))/(_as_mp(s2)*z)*(
                        mp.expm1(gamma*_as_mp(u))/gamma-
                        (-mp.expm1(-eta*_as_mp(u)))/eta)
                    self.assertGreaterEqual(_as_mp(upper),ex)
                    tighter=_occupation_upper(L,u,s2,zl,gl,zu,a)
                    self.assertGreaterEqual(_as_mp(tighter),ex)
                    self.assertLessEqual(tighter,upper)
                    self.assertGreater(ex,0)
                    y=_as_mp(u)
                    actual_first_hit=.5*mp.erfc((y+_as_mp(mu)*_as_mp(T))/
                                                mp.sqrt(2*_as_mp(s2)*_as_mp(T)))
                    actual_first_hit+=.5*mp.exp(-2*_as_mp(mu)*y/_as_mp(s2))*mp.erfc(
                        (y-_as_mp(mu)*_as_mp(T))/mp.sqrt(2*_as_mp(s2)*_as_mp(T)))
                    self.assertLessEqual(actual_first_hit,_as_mp(_tail_cdf_bound(u,mu,T,s2)))

    def test_sharper_than_existing_and_hold_value_inside(self):
        for p in (HX(),HX(sale_fraction=.2)):
            b=boundary(p);L=3.6
            true=equity_closed(p,b*math.exp(L),b) # feasible hold-to-default policy
            old=fixed_barrier_equity_upper_envelope(p,candidate_barrier=b,
                log_upper=L,nominal_upper_equity=true)
            new=sharp_fixed_barrier_equity_envelope(p,candidate_barrier=b,
                log_upper=L,nominal_upper_equity=true)
            with self.subTest(sale_fraction=p.sale_fraction):
                self.assertGreaterEqual(float(new.equity_upper),true)
                self.assertLessEqual(float(new.equity_lower),true)
                self.assertLess(float(new.nominal_absolute_error_upper),
                                float(old.upper_equity_abs_budget)/20)
                self.assertLess(float(new.nominal_absolute_error_upper),9.)
                self.assertFalse(new.scientific_gate_closed)
                self.assertFalse(new.complete_debt_error_budget)
                with self.assertRaises(UnresolvedEquityEnvelope):
                    new.to_production()

    def test_staircase_refinement_and_bounded_real_inputs(self):
        p=HX();b=boundary(p);L=3.6;A=b*math.exp(L)
        vals=[sharp_fixed_barrier_equity_envelope(p,candidate_barrier=b,
                log_upper=L,nominal_upper_equity=A,
                gaussian_steps=n) for n in (8,16,32)]
        H=[float(v.occupation_error_upper) for v in vals]
        self.assertGreater(H[0],H[1])
        self.assertGreater(H[1],H[2])
        self.assertTrue(all(math.isfinite(v) for v in H))

    def test_reject_unsound_put_and_invalid_resources(self):
        p=HX();b=boundary(p)
        cases=[(p,dict(gaussian_steps=2)),(p,dict(gaussian_steps=130)),
               (p,dict(gaussian_cutoff=10.)),(p,dict(log_upper=.4)),
               (replace(p,payout=0),{}),
               (replace(p,payout=.09,volatility=.4),{})]
        for spec,extras in cases:
            with self.subTest(p=spec,extra=extras),self.assertRaises(UnresolvedEquityEnvelope):
                kw=extras.copy()
                L=kw.pop('log_upper',3.6)
                sharp_fixed_barrier_equity_envelope(spec,candidate_barrier=b,
                    log_upper=L,nominal_upper_equity=0.,**kw)
        with self.assertRaises(UnresolvedEquityEnvelope):
            _exp_neg_interval(Fraction(129))
        with self.assertRaises(UnresolvedEquityEnvelope):
            _sqrt_interval(Fraction(-1))

if __name__=='__main__':
    unittest.main()
