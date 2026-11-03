"""Research-only *exact rational* enclosures for a finite-time Brownian FPT.

Under decimal-string parameter semantics, bounded domain, and Python arbitrary
precision integers, all interval endpoints come from rational arithmetic,
integer square roots, and analytically bounded alternating/Taylor series.
This DOES certify the scalar fixed-drift / fixed-barrier F and G formulas under
these assumptions. It does NOT certify He-Xiong coupled equity/bond valuation,
GPU/FP32 evaluation or floating-point roundoff of a production implementation.

Cdf: Phi(z)=1/2 + (1/sqrt(2*pi)) sum (-1)^n z^(2n+1) /
    (2^n n! (2n+1)).  Once terms decrease, the alternating-series tail is
    bounded by the first omitted term. Pi=16 atan(1/5)-4 atan(1/239), with
    alternating rational series bounds. Exponential: Taylor around zero after
    argument halving, remainder <= 2 |x|^(N+1)/(N+1)! for |x|<=1/2.

Everything outside the certified compact domain fails closed. No floats are
used in the interval computation or the Taylor-stopping decision.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from math import isqrt
import re

_DECIMAL = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?$')


def decimal(s: str) -> Fraction:
    if not isinstance(s, str) or len(s)>128 or not _DECIMAL.fullmatch(s):
        raise ValueError('Inputs must be finite decimal strings, never binary floats')
    if 'e' in s.lower():
        exponent=s.lower().rsplit('e',1)[1]
        if len(exponent)>5 or abs(int(exponent))>100:
            raise ValueError('decimal exponent outside safe research domain')
    p = Fraction(s)
    if max(p.numerator.bit_length(), p.denominator.bit_length()) > 1024:
        raise ValueError('decimal input too extreme for this research certificate')
    return p


def _floor(f: Fraction) -> int:
    return f.numerator // f.denominator


def _ceil(f: Fraction) -> int:
    return -_floor(-f)


@dataclass(frozen=True)
class I:
    lo: Fraction
    hi: Fraction

    def __post_init__(self):
        if self.lo > self.hi:
            raise ValueError('inverted rational interval')

    @staticmethod
    def point(x):
        f = x if isinstance(x, Fraction) else Fraction(x)
        return I(f, f)

    def quant(self, places: int) -> I:
        scale=10 ** places
        return I(Fraction(_floor(self.lo*scale),scale),
                 Fraction(_ceil(self.hi*scale),scale))

    def __add__(self, other):
        other=_interval(other)
        return I(self.lo+other.lo, self.hi+other.hi)

    __radd__ = __add__

    def __neg__(self):
        return I(-self.hi,-self.lo)

    def __sub__(self,other):
        return self + (-_interval(other))

    def __rsub__(self,other):
        return _interval(other)-self

    def __mul__(self,other):
        other=_interval(other)
        v=(self.lo*other.lo,self.lo*other.hi,self.hi*other.lo,self.hi*other.hi)
        return I(min(v),max(v))

    __rmul__=__mul__

    def inv(self):
        if self.lo<=0<=self.hi:
            raise ArithmeticError('interval divisor contains zero')
        return I(1/self.hi,1/self.lo)

    def __truediv__(self,other):
        return self*_interval(other).inv()

    def __rtruediv__(self,other):
        return _interval(other)/self


def _interval(x) -> I:
    return x if isinstance(x,I) else I.point(x)


def _atan_bound_inverse(m: int, places: int) -> I:
    """Alternating arctan(1/m), with exact rational next-term tail."""
    if m<2:raise ValueError('m >= 2 required')
    z=Fraction(1,m)
    term=z
    partial=Fraction(0)
    eps=Fraction(1,10**(places+8))
    for n in range(1000):
        partial+=term if n%2==0 else -term
        next_term = term * z*z * Fraction(2*n+1,2*n+3)
        if next_term<eps:
            if n%2==0:return I(partial-next_term,partial)
            return I(partial,partial+next_term)
        term=next_term
    raise ArithmeticError('pi-series convergence budget exceeded')


@lru_cache(maxsize=16)
def pi(places:int) -> I:
    return (16*_atan_bound_inverse(5,places)-4*_atan_bound_inverse(239,places)).quant(places+7)


def sqrt_point(a:Fraction, places:int) -> I:
    if a<0:raise ValueError('negative square root')
    scale=10**(places+7)
    y=isqrt((a.numerator*scale*scale)//a.denominator)
    lo=Fraction(y,scale)
    hi=lo if (y*y*a.denominator == a.numerator*scale*scale) else Fraction(y+1,scale)
    return I(lo,hi)


def sqrt_interval(a:I,places:int) -> I:
    if a.lo<0:raise ArithmeticError('interval contains negative square root argument')
    return I(sqrt_point(a.lo,places).lo,sqrt_point(a.hi,places).hi).quant(places+5)


def _exp_nonnegative(y:Fraction,places:int)->I:
    if y<0:raise ValueError('positive-argument helper')
    halvings=0
    while y>Fraction(1,2):
        y/=2
        halvings+=1
    total=Fraction(1)
    term=Fraction(1)
    eps=Fraction(1,10**(places+halvings+12))
    for n in range(1,1000):
        term=term*y/n
        total+=term
        next_term=term*y/(n+1)
        err=2*next_term
        if err<eps:
            out=I(total-err,total+err).quant(places+halvings+9)
            for _ in range(halvings):
                out=(out*out).quant(places+6)
            return out.quant(places+4)
    raise ArithmeticError('exp series convergence budget exceeded')


def exp_point(y:Fraction,places:int)->I:
    if abs(y)>40:
        raise ArithmeticError('out-of-domain exponential: requires |arg|<=40')
    if y<0:
        return _exp_nonnegative(-y,places).inv().quant(places+4)
    return _exp_nonnegative(y,places)


def exp_interval(y:I,places:int)->I:
    return I(exp_point(y.lo,places).lo,exp_point(y.hi,places).hi).quant(places+3)


def _cdf_pos(z:Fraction,places:int)->I:
    if z<0 or z>8:
        raise ArithmeticError('CDF certificate supports |z| <=8')
    total=Fraction(0)
    term=z
    eps=Fraction(1,10**(places+12))
    for n in range(1500):
        total += term if n%2==0 else -term
        next_term=term*z*z*Fraction(2*n+1,2*(n+1)*(2*n+3))
        if n > 1 and Fraction(n,1) > z*z/2 and next_term<eps:
            s=I(total-next_term,total) if n%2==0 else I(total,total+next_term)
            norm=sqrt_interval(2*pi(places),places).inv()
            return (I.point(Fraction(1,2))+s*norm).quant(places+2)
        term=next_term
    raise ArithmeticError('CDF alternating-series convergence budget exceeded')


def cdf_point(z:Fraction,places:int)->I:
    if z>=0:return _cdf_pos(z,places)
    return (I.point(1)-_cdf_pos(-z,places)).quant(places+2)


def cdf_interval(z:I,places:int)->I:
    return I(cdf_point(z.lo,places).lo,cdf_point(z.hi,places).hi).quant(places+2)


def dump(i:I, digits:int=35):
    """Render rounded decimal endpoints outward with exact rational rounding."""
    scale=10**digits
    lo=_floor(i.lo*scale)
    hi=_ceil(i.hi*scale)
    def d(v):
        prefix='-' if v<0 else ''
        val=str(abs(v)).zfill(digits+1)
        return prefix+val[:-digits]+'.'+val[-digits:]
    return {'lower':d(lo),'upper':d(hi),'width_upper':d(_ceil((i.hi-i.lo)*scale))}


def certified_fpt(x:str,drift:str,sigma:str,horizon:str,discount:str,places:int=45):
    """Positive mathematical gap enclosure for a COMPACT scalar FPT subdomain.

    Inputs represent exact decimal rationals; outputs are guaranteed enclosures
    for mathematical formulas, not hardware libm or actual float32 code.
    """
    if not isinstance(places,int) or not 25<=places<=75:
        raise ValueError('places outside supported range 25..75')
    x,mu,sig,t,q=map(decimal,(x,drift,sigma,horizon,discount))
    if not (x>0 and sig>0 and t>0 and q>0):
        raise ValueError('requires x,sigma,T,discount strictly positive')
    if x>8 or abs(mu)>4 or sig<Fraction(1,100) or sig>4 or t>10 or q>4:
        raise ArithmeticError('outside researched compact input domain')
    s2=sig*sig
    a=I.point(mu/s2)
    ell=sqrt_interval(a*a+I.point(2*q/s2),places)
    u=I.point(sig)*sqrt_interval(I.point(t),places)
    h1=(I.point(-x-mu*t)/u)
    h2=(I.point(-x+mu*t)/u)
    F=(cdf_interval(h1,places)+exp_interval(I.point(-2*mu*x/s2),places)*cdf_interval(h2,places)).quant(places+2)
    hg1=(I.point(-x)-ell*I.point(s2*t))/u
    hg2=(I.point(-x)+ell*I.point(s2*t))/u
    G=(exp_interval((-a+ell)*I.point(x),places)*cdf_interval(hg1,places)
       +exp_interval((-a-ell)*I.point(x),places)*cdf_interval(hg2,places)).quant(places+2)
    gap=(F-G).quant(places+2)
    status=('CERTIFIED_POSITIVE_F_MINUS_G' if gap.lo>0 and F.lo>=0 and
            F.hi<=1 and G.lo>=0 and G.hi<=F.hi else 'DENY_UNRESOLVED')
    return {'input_exact_decimals':dict(x=str(x),drift=str(mu),sigma=str(sig),
                                      horizon=str(t),discount=str(q)),
            'arithmetic':'exact rational intervals; proved pi/erf/exp/sqrt bounds',
            'model':'Brownian fixed drift/fixed absorbing barrier ONLY',
            'F':dump(F,digits=places),'G':dump(G,digits=places),
            'F_minus_G':dump(gap,digits=places),'reported_decimal_places':places,
            'decision':status,'original_HX_validated':False,
            'production_FP32_or_GPU_validated':False}


if __name__=='__main__':
    import json
    print(json.dumps(certified_fpt('0.8','-0.3','0.7','0.9','0.05'),indent=2))


def _square(i:I)->I:
    """Exact enclosure of z^2; avoid negative interval pollution at zero."""
    if i.lo>=0:return I(i.lo*i.lo,i.hi*i.hi)
    if i.hi<=0:return I(i.hi*i.hi,i.lo*i.lo)
    return I(Fraction(0),max(i.lo*i.lo,i.hi*i.hi))


def _pdf_interval(z:I, places:int)->I:
    return (exp_interval(-_square(z)/2,places) /
            sqrt_interval(2*pi(places),places)).quant(places+1)


def certified_risk_distance_gradient(x:str,drift:str,sigma:str,horizon:str,
                                     places:int=45):
    """Proved rational interval for d/dx P(tau <=T) at x>=0.

    At x=0 this is the derivative from the *positive* side only. The
    boundary extension P=1 for x<=0 has derivative 0 from the negative side;
    its nonzero positive-side gradient disproves global smooth pasting of
    the risk feature. The value channel of HX equity is not studied here.
    """
    if not isinstance(places,int) or not 25<=places<=75:
        raise ValueError('places outside supported range')
    x,mu,sig,t=map(decimal,(x,drift,sigma,horizon))
    if x<0 or x>8 or t<=0 or t>10 or sig<Fraction(1,100) or sig>4 or abs(mu)>4:
        raise ValueError('outside certified scalar derivative domain')
    u=I.point(sig)*sqrt_interval(I.point(t),places)
    a=I.point(-x-mu*t)/u
    b=I.point(-x+mu*t)/u
    factor=exp_interval(I.point(-2*mu*x/(sig*sig)),places)
    result=((-_pdf_interval(a,places)/u)
            +factor*((I.point(-2*mu/(sig*sig))*cdf_interval(b,places))
                    -_pdf_interval(b,places)/u)).quant(places+2)
    return {'scope':'fixed barrier Brownian FPT; derivative from x>0 side',
            'x':str(x),'gradient':dump(result,digits=places),
            'reported_decimal_places':places,
            'strictly_negative_certified':result.hi<0,
            'boundary_smooth_pasting_certified':False,
            'coupled_HX_equity_gradient_certified':False}
