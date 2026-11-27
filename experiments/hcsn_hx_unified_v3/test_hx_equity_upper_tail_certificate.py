"""Independent numerical Green-resolvent audit of a rational equity-tail bound.

This is a bounded fixed-barrier test, not finite-grid/financial equilibrium CI.
"""
from dataclasses import replace, dataclass
from decimal import Decimal
from fractions import Fraction
from math import exp, log, sqrt
import unittest

from scipy.integrate import quad
from scipy.special import ndtr

from .hx_equity_upper_tail_certificate import (
    UnresolvedEquityTail, _sqrt_enclosure, _exp_enclosure, _ceil_decimal,
    certified_equity_farfield_boundary)

@dataclass(frozen=True)
class P:
    rate: float=.05
    payout: float=.03
    volatility: float=.25
    maturity: float=2.
    principal: float=60.
    coupon: float=4.
    tax_shield: float=.25
    recovery: float=.6
    shock_intensity: float=1.
    sale_fraction: float=.015


def independent_equity_tail_discrepancy(p,b,x):
    """Separate reflected-Green integral with normal-CDF debt, NOT Laplace bound.

    Numerics used here are ordinary scipy binary64 and cannot independently
    certify rounding; they test gross algebra, constants and model semantics.
    """
    r=p.rate;delta=p.payout;sigma=p.volatility;T=p.maturity
    mu=r-delta-.5*sigma*sigma
    q=r+p.shock_intensity*p.sale_fraction
    a=mu/(sigma*sigma)
    z=sqrt(a*a+2*r/(sigma*sigma))
    kr=a+z
    principal=p.principal/T
    base=p.coupon/T/q
    discount=exp(-q*T)
    no_default=base+discount*(principal-base)
    const=(1-p.tax_shield)*p.coupon+principal
    recovery=p.recovery*b/T
    hb=b+(no_default-const)/r
    u=sigma*sqrt(T)
    zh=sqrt(a*a+2*q/(sigma*sigma))
    def debt_delta(y):
        if y<=0:
            return recovery-no_default
        F=ndtr((-y-a*u*u)/u)+exp(-2*a*y)*ndtr((-y+a*u*u)/u)
        G=exp((-a+zh)*y)*ndtr((-y-zh*u*u)/u) + exp((-a-zh)*y)*ndtr((-y+zh*u*u)/u)
        return -discount*(principal-base)*F+(recovery-base)*G
    def weighted(y):
        # Killed Green density of discounted drift Brownian on y>0
        if y<x:
            g=exp((-a-z)*x+(a+z)*y)*(-__import__('math').expm1(-2*z*y))
        else:
            g=exp((a-z)*y+(-a+z)*x)*(-__import__('math').expm1(-2*z*x))
        return g*debt_delta(y)/(sigma*sigma*z)
    integral=quad(weighted,0,x,epsabs=3e-9,limit=200)[0]
    integral+=quad(weighted,x,max(x+15,35),epsabs=3e-9,limit=200)[0]
    return -hb*exp(-kr*x)+integral


class HXEquityUpperTailTests(unittest.TestCase):
    def test_exact_rational_numerical_primitives(self):
        for n in (Fraction(2,1),Fraction(1,3),Fraction(387,100)):
            lo,hi=_sqrt_enclosure(n,40)
            self.assertLessEqual(lo*lo,n)
            self.assertGreaterEqual(hi*hi,n)
        for n in (Fraction(0),Fraction(1,10),Fraction(4)):
            lo,hi=_exp_enclosure(n,64)
            import mpmath
            mpmath.mp.dps=100
            actual=mpmath.exp(mpmath.mpf(n.numerator)/n.denominator)
            self.assertLessEqual(mpmath.mpf(lo.numerator)/lo.denominator,actual)
            self.assertGreaterEqual(mpmath.mpf(hi.numerator)/hi.denominator,actual)
        self.assertGreaterEqual(Fraction(Decimal(_ceil_decimal(Fraction(1,3)))),Fraction(1,3))
        self.assertGreaterEqual(Fraction(Decimal(_ceil_decimal(Fraction(1,10**90)))),Fraction(1,10**90))

    def test_independent_financial_resolvent_within_outward_bound(self):
        cases=((P(),64.6251766753),
               (P(sale_fraction=.2),101.324028609),
               (P(rate=.09,payout=.02,volatility=.2,maturity=1.5,
                  coupon=8.,principal=30.),54.3))
        for p,b in cases:
            for L in (1.25,3.6,6.0,10.):
                with self.subTest(sale=p.sale_fraction,b=b,L=L):
                    c=certified_equity_farfield_boundary(p,candidate_barrier=b,log_upper=L)
                    bound=Fraction(Decimal(c.upper_equity_abs_budget))
                    numerical=abs(independent_equity_tail_discrepancy(p,b,L))
                    self.assertLessEqual(numerical,float(bound)+1e-8)
                    self.assertFalse(c.entire_P0_certified)
                    self.assertFalse(c.input_debt_error_verified)
                    self.assertFalse(c.production_activation)
                    self.assertGreater(c.compared_lambdas,0)

    def test_tail_shrinks_on_fixed_regime(self):
        p=P();b=64.6251766753
        values=[Fraction(Decimal(certified_equity_farfield_boundary(
                p,candidate_barrier=b,log_upper=L).upper_equity_abs_budget))
                for L in (2.0,4.0,8.0,12.0)]
        self.assertEqual(values,sorted(values,reverse=True))

    def test_refuse_unsupported_precision_or_physical_domain(self):
        for p in (P(payout=0.),P(rate=0),P(volatility=0.),
                  P(maturity=0),P(recovery=1.2),P(sale_fraction=-1)):
            with self.subTest(p=p),self.assertRaises(UnresolvedEquityTail):
                certified_equity_farfield_boundary(p,candidate_barrier=60.,log_upper=3.6)
        for opts in ({'candidate_barrier':0.,'log_upper':3.6},
                     {'candidate_barrier':60.,'log_upper':0.},
                     {'candidate_barrier':60.,'log_upper':13.},
                     {'candidate_barrier':60.,'log_upper':3.6,'taylor_terms':8},
                     {'candidate_barrier':60.,'log_upper':3.6,'sqrt_decimal_digits':8}):
            with self.subTest(opts=opts),self.assertRaises(UnresolvedEquityTail):
                certified_equity_farfield_boundary(P(),**opts)

    def test_cannot_promote_component_to_full_p0(self):
        c=certified_equity_farfield_boundary(P(),candidate_barrier=64.6,log_upper=3.6)
        with self.assertRaises(UnresolvedEquityTail):
            c.certify_complete_p0()
        self.assertIn('actual PDE debt approximation',c.uncovered)

if __name__=='__main__': unittest.main()
