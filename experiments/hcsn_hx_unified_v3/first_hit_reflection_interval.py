"""Auxiliary exact-rational Brownian first-hit reflection oracle.

Uses normal CDF via independently enclosed alternating rational Gaussian
power series, with a Mills tail bound. Faster near distance zero than
physical-time Darboux. This is a *second analytic* oracle, not a fully
independent PDE or global HX financial free-boundary certificate.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
import math

from .first_hit_time_interval import (
    _pi_bounds, _sqrt_bounds, _exp_neg, _rational, _floor_grid, _ceil_grid, UnresolvedFirstHit,
)


@dataclass(frozen=True)
class ReflectionHitInterval:
    first_lower: F
    first_upper: F
    discounted_lower: F
    discounted_upper: F
    method: str = 'rational Gaussian series and Brownian reflection; analytic auxiliary'
    global_financial_equilibrium_certified: bool = False
    production_activation: bool = False

    @property
    def max_width(self):
        return max(self.first_upper-self.first_lower,
                   self.discounted_upper-self.discounted_lower)


def _norm_factor():
    pi_lo,pi_hi=_pi_bounds()
    lo,hi=_sqrt_bounds(2*pi_lo,2*pi_hi)
    return F(1)/hi,F(1)/lo


def _tail_positive(z: F):
    """Rigorous Phi(-z) bounds for exact rational z>=0."""
    if z<0:
        raise UnresolvedFirstHit('normal tail requires nonnegative argument')
    if z==0:return F(1,2),F(1,2)
    c_lo,c_hi=_norm_factor()
    # Mills inequality: 0 < Phi(-z) < phi(z)/z; for z>=5.5 this is
    # deliberately wider but still enclosed; certify only the final error test.
    if z>=F(11,2):
        exp_lo,exp_hi=_exp_neg(z*z/2)
        return F(0),min(F(1,2),c_hi*exp_hi/z)
    # The integral from 0 to z of exp(-u^2/2) du is an alternating
    # power series. Bound with adjacent partial sums ONLY after the term
    # magnitudes are provably decreasing and the omitted term is tiny.
    term=z;total=F(0);n=0
    while True:
        total+=term
        next_term=-term*z*z*F(2*n+1,2*(n+1)*(2*n+3))
        if (abs(next_term)<=F(1,10**22)
                and abs(next_term)<=abs(term)
                and n>=z*z/2):
            integral_lo=min(total,total+next_term)
            integral_hi=max(total,total+next_term)
            if not (0<=integral_lo<=integral_hi):
                raise UnresolvedFirstHit('Gaussian Taylor cancellation invalid')
            a=F(1,2)-c_hi*integral_hi
            b=F(1,2)-c_lo*integral_lo
            if b<0 or a>F(1,2):
                raise UnresolvedFirstHit('normal tail outside unit bounds')
            return max(F(0),a),min(F(1,2),b)
        term=next_term;n+=1
        if n>350:
            raise UnresolvedFirstHit('Gaussian power-series resource limit')


@lru_cache(maxsize=4000)
def _tail(x: F):
    """Phi(-x) for signed rational x, outward bounded."""
    if x>=0:return _tail_positive(x)
    lo,hi=_tail_positive(-x)
    return F(1)-hi,F(1)-lo


def _tail_interval(low:F,high:F):
    if high<low: raise UnresolvedFirstHit('reversed normal argument')
    # Phi(-x) decreases with x.
    return _tail(high)[0],_tail(low)[1]


def _arg(numer:F,den_lo:F,den_hi:F):
    if not 0<den_lo<=den_hi:
        raise UnresolvedFirstHit('nonpositive Gaussian denominator')
    a=numer/den_lo; b=numer/den_hi
    return min(a,b),max(a,b)


def _exp_neg_signed(x:F):
    if x>=0:return _exp_neg(x)
    lo,hi=_exp_neg(-x)
    if lo<=0:
        raise UnresolvedFirstHit('exp positive scale underflow interval')
    return F(1)/hi,F(1)/lo


def _probability(y:F,mu:F,sigma:F,T:F):
    """Finite-time lower-hit CDF using independently bounded Gaussian tails."""
    sqrt_lo,sqrt_hi=_sqrt_bounds(T,T)
    den_lo=sigma*sqrt_lo;den_hi=sigma*sqrt_hi
    t1=_tail_interval(*_arg(y+mu*T,den_lo,den_hi))
    t2=_tail_interval(*_arg(y-mu*T,den_lo,den_hi))
    exp_lo,exp_hi=_exp_neg_signed(2*mu*y/(sigma*sigma))
    lo=t1[0]+exp_lo*t2[0]
    hi=t1[1]+exp_hi*t2[1]
    if lo>1 or hi<0:
        raise UnresolvedFirstHit('invalid reflection probability')
    return max(F(0),lo),min(F(1),hi)


def bound_first_hit_reflection(*,distance,drift,diffusion,maturity,discount):
    """Independent rational reflection identities for F(T) and G(T).

    Samples physical f64 inputs as exact rationals; Gaussian series and
    multiplier intervals are outward-bounded. Not a numerical integration
    reference independent of the reflection formula itself.
    """
    y,mu,sigma,T,q=map(_rational,(distance,drift,diffusion,maturity,discount))
    if not (y>0 and sigma>0 and T>0 and q>=0):
        raise UnresolvedFirstHit('invalid reflection first-hit contract')
    f_lo,f_hi=_probability(y,mu,sigma,T)
    s0,s1=_sqrt_bounds(mu*mu+2*q*sigma*sigma,
                        mu*mu+2*q*sigma*sigma)
    if not 0<=s0<=s1:
        raise UnresolvedFirstHit('invalid discounted drift sqrt')
    # f_mu(t)e^{-qt} = exp((theta-mu)*y/sigma^2) f_theta(t),
    # theta=sqrt(mu^2+2q sigma^2). Use endpoint evaluation to enclose
    # the Gaussian reflection expression for all theta in [s0,s1].
    fa0=_probability(y,s0,sigma,T)
    fa1=_probability(y,s1,sigma,T)
    ff_lo=min(fa0[0],fa1[0]);ff_hi=max(fa0[1],fa1[1])
    # Finite-time first-hit probability is decreasing in upward drift;
    # this monotonicity makes the endpoint enclosure rigorous.
    pref_lo=_exp_neg_signed(-(s0-mu)*y/(sigma*sigma))[0]
    pref_hi=_exp_neg_signed(-(s1-mu)*y/(sigma*sigma))[1]
    g_lo=pref_lo*ff_lo;g_hi=pref_hi*ff_hi
    if g_lo>f_hi or g_hi<0:
        raise UnresolvedFirstHit('discounted first-hit inconsistent with F')
    f_lo=max(f_lo,g_lo)
    g_hi=min(g_hi,f_hi)
    if not (0<=g_lo<=g_hi<=f_hi<=1 and f_lo<=f_hi):
        raise UnresolvedFirstHit('invalid rational F/G ordering')
    # Outward truncate gigantic exact fractions to the shared 1e-35 grid.
    # The guaranteed enclosure remains valid and evidence stays serializable.
    return ReflectionHitInterval(_floor_grid(f_lo),_ceil_grid(f_hi),
                                 _floor_grid(g_lo),_ceil_grid(g_hi))
