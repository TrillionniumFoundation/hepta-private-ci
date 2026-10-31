"""Independent analytic-CDF and high-precision checks of rational time bounds.

These tests compare to separate formulas without importing them in the oracle.
The bound and its width are math certificates for the sampled 1D first-hit
integrals only, NOT for actual financial PDE discretization or HX equilibrium.
"""
import math
import unittest

import mpmath as mp
from scipy.special import ndtr

from .first_hit_time_interval import (
    F, _exp_neg, _pi_bounds, _sqrt_bounds, _rational,
    bound_first_hit, financial_bond_from_hit_interval, UnresolvedFirstHit,
)


def analytic_first_hit(y,mu,sigma,q,T):
    def expcdf(a,z):
        return math.exp(a)*float(ndtr(z))
    root=math.sqrt(mu*mu+2*q*sigma*sigma)
    Fhit=expcdf(0.,(-y-mu*T)/(sigma*math.sqrt(T))) + \
         expcdf(-2*mu*y/sigma**2,(-y+mu*T)/(sigma*math.sqrt(T)))
    G=expcdf((-mu+root)*y/sigma**2,(-y-root*T)/(sigma*math.sqrt(T))) + \
      expcdf((-mu-root)*y/sigma**2,(-y+root*T)/(sigma*math.sqrt(T)))
    return Fhit,G


class RationalFirstHitTest(unittest.TestCase):
    def test_exact_elementary_interval_bounds(self):
        low,high=_pi_bounds()
        with mp.workdps(120):
            pi=mp.pi
            self.assertTrue(mp.mpf(low.numerator)/low.denominator<pi)
            self.assertTrue(pi<mp.mpf(high.numerator)/high.denominator)
        for v in (F(0),F(1,10_000),F(1,3),F(5),F(101)):
            lo,hi=_exp_neg(v)
            with mp.workdps(120):
                exact=mp.exp(-mp.mpf(v.numerator)/v.denominator)
                self.assertLessEqual(mp.mpf(lo.numerator)/lo.denominator,exact)
                self.assertGreaterEqual(mp.mpf(hi.numerator)/hi.denominator,exact)
        for v in (F(1,100),F(2),F(10**6)):
            l,h=_sqrt_bounds(v,v)
            with mp.workdps(120):
                s=mp.sqrt(mp.mpf(v.numerator)/v.denominator)
                self.assertLessEqual(mp.mpf(l.numerator)/l.denominator,s)
                self.assertGreaterEqual(mp.mpf(h.numerator)/h.denominator,s)

    def test_five_physical_first_hit_enclosures(self):
        cases=((.03,-.01125,.25,.065,2.),
               (.25,-.01125,.25,.25,2.),
               (1.,.3,.6,.1,1.),
               (.15,-.4,.45,.03,3.),
               (.01,0.,.6,0.,.4))
        for y,mu,sigma,q,T in cases:
            with self.subTest(y=y,mu=mu,q=q):
                b=bound_first_hit(distance=y,drift=mu,diffusion=sigma,
                                  discount=q,maturity=T,tolerance='0.00005',max_cells=5000)
                f,g=analytic_first_hit(y,mu,sigma,q,T)
                self.assertLessEqual(float(b.first_lower),f)
                self.assertGreaterEqual(float(b.first_upper),f)
                self.assertLessEqual(float(b.discounted_lower),g)
                self.assertGreaterEqual(float(b.discounted_upper),g)
                self.assertLessEqual(float(b.max_width),.00005)
                self.assertFalse(b.continuum_debt_pde_certified)

    def test_adaptive_precision_refuses_insufficient_work(self):
        with self.assertRaises(UnresolvedFirstHit):
            bound_first_hit(distance=.03,drift=-.01125,diffusion=.25,
                            discount=.065,maturity=2.,tolerance='0.00000001',
                            max_cells=20)

    def test_financial_bond_interval_encloses_independent_hx_bond(self):
        from .hx import HX,boundary,bond_value
        for sf,y in ((.015,.03),(.2,.03),(.015,.25),(.2,.25)):
            p=HX(sale_fraction=sf)
            b=boundary(p)
            mu=p.rate-p.payout-.5*p.volatility**2
            q=p.rate+p.shock_intensity*p.sale_fraction
            hits=bound_first_hit(distance=y,drift=mu,diffusion=p.volatility,
                                 maturity=p.maturity,discount=q,
                                 tolerance='0.00005',max_cells=5000)
            lo,hi=financial_bond_from_hit_interval(first=hits,rate=p.rate,
                maturity=p.maturity,principal=p.principal,coupon=p.coupon,
                shock_intensity=p.shock_intensity,sale_fraction=p.sale_fraction,
                recovery=p.recovery,boundary=b)
            bond=bond_value(p,b*math.exp(y),p.maturity,b)
            self.assertLess(float(lo)-1e-11,bond)
            self.assertGreater(float(hi)+1e-11,bond)
            self.assertGreater(hi,lo)

    def test_invalid_or_ambiguous_corner_fails_closed(self):
        kwargs=dict(distance=.03,drift=0.,diffusion=.25,maturity=2.,discount=.1)
        for change in ({'distance':0},{'distance':-1},{'diffusion':0},
                       {'maturity':0},{'discount':-1},{'distance':float('nan')},
                       {'tolerance':'0.5'},{'max_cells':1}):
            with self.subTest(change=change),self.assertRaises(UnresolvedFirstHit):
                bound_first_hit(**(kwargs|change))
        with self.assertRaises(UnresolvedFirstHit):
            financial_bond_from_hit_interval(first=bound_first_hit(**kwargs),
                rate=.05,maturity=2.,principal=0.,coupon=4.,shock_intensity=1.,
                sale_fraction=.1,recovery=.6,boundary=50.)


if __name__=='__main__':
    unittest.main()
