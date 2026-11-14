"""Two-sided exact-rational enclosures of finite-time Brownian FIRST-HIT factors.

A separate time-density/Darboux oracle for P0 debt PDE error accounting.
It does NOT invoke HX Eq.(8), its normal CDF, the financial smooth-fit root,
Green resolvent, the downstream PDE, or any neural operator.

State y>0: dY=mu dt + sigma dW. Downward hitting density
  f(t)=y/(sigma*sqrt(2*pi*t^3))*exp(-(y+mu*t)^2/(2*sigma^2*t)).
F(T)=integral f dt; G(T)=integral exp(-q*t) f dt, q >= 0.
Each probability is enclosed by rational lower/upper Darboux sums using the
UNIQUE density mode (proved by signed quadratic log derivative). Time-zero
missing mass is upper bounded with a reflection/Chernoff inequality. exp and
sqrt endpoints use rational, outward-quantized Taylor/isqrt enclosures. Pi is
bounded independently by alternating rational Machin arctan series.

IMPORTANT: a rational enclosure for B(y,T) is NOT a full debt PDE discretization
error estimate or continuum financial default-equilibrium certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
import heapq
import math


class UnresolvedFirstHit(ValueError):
    """Missing admissible error bound, resource limit, or invalid domain."""


Q = 10 ** 35
E = F(1, Q)
# e^100 > (8/3)^100 > 10^40, so exp(-x) <= 10^-40 for x>=100.
assert F(8, 3) ** 100 > 10 ** 40


def _rational(x):
    if type(x) is bool:
        raise UnresolvedFirstHit('booleans are not physical numbers')
    if type(x) is int:
        return F(x)
    if type(x) is float and math.isfinite(x):
        return F(*x.as_integer_ratio())
    if type(x) is str:
        try:
            return F(x)
        except (ValueError, ZeroDivisionError) as e:
            raise UnresolvedFirstHit('invalid exact decimal literal') from e
    if isinstance(x, F):
        return x
    raise UnresolvedFirstHit('require finite binary64, rational or decimal input')


def _floor_grid(x: F):
    return F(x.numerator * Q // x.denominator, Q)


def _ceil_grid(x: F):
    return -_floor_grid(-x)


def _arctan_bracket(reciprocal: int, pairs: int = 78):
    z = F(1, reciprocal)
    power = z
    series = F(0)
    for k in range(2 * pairs):
        series += (power / (2*k + 1)) * (1 if k % 2 == 0 else -1)
        power *= z*z
    # Partial alternating sum at odd index (last negative): lower.
    lower = series
    upper = series + power / (4*pairs + 1)
    return lower, upper


@lru_cache(maxsize=1)
def _pi_bounds():
    a0,a1 = _arctan_bracket(5)
    b0,b1 = _arctan_bracket(239)
    return _floor_grid(16*a0-4*b1),_ceil_grid(16*a1-4*b0)


def _sqrt_bounds(lo: F, hi: F):
    if lo<=0 or hi<lo:
        raise UnresolvedFirstHit('nonpositive sqrt interval')
    # k=floor(Q*sqrt(lo)); integer arithmetic has no floating uncertainty.
    z=(lo.numerator*Q*Q)//lo.denominator
    k=math.isqrt(z)
    z2=(hi.numerator*Q*Q + hi.denominator-1)//hi.denominator
    l=math.isqrt(z2)
    return F(k,Q), F(l+1,Q)


@lru_cache(maxsize=32768)
def _exp_neg_quantized(x: F):
    """Taylor on a fixed rational grid; x is one exact grid endpoint."""
    if x < 0:
        raise UnresolvedFirstHit('negative exponent magnitude')
    if x == 0:
        return F(1),F(1)
    if x >= 100:
        return F(0),F(1,10**40)
    halves=0
    a=x
    while a>F(1,2):
        a/=2
        halves+=1
    summation=F(1)
    term=F(1)
    lower=upper=None
    for n in range(1,42):
        term *= -a/n
        summation += term
        if n==40: upper=summation
        elif n==41: lower=summation
    assert 0<lower<=upper<1
    lower=_floor_grid(lower)
    upper=_ceil_grid(upper)
    for _ in range(halves):
        lower=_floor_grid(lower*lower)
        upper=_ceil_grid(upper*upper)
    return max(F(0),lower),min(F(1),upper)


def _exp_neg(x: F):
    """Enclose the full exact rational exponent by outward grid arguments."""
    lo=_floor_grid(x)
    hi=_ceil_grid(x)
    # exp(-x) is monotone decreasing, including across Taylor range reductions.
    lower=_exp_neg_quantized(hi)[0]
    upper=_exp_neg_quantized(lo)[1]
    return lower,upper


def _density_enclosure(y: F, mu: F, sigma: F, q: F, t: F):
    phi=((y+mu*t)**2)/(2*sigma*sigma*t)+q*t
    lowe,highe=_exp_neg(phi)
    lo_pi,hi_pi=_pi_bounds()
    low_denom,hi_denom=_sqrt_bounds(2*lo_pi*t**3,2*hi_pi*t**3)
    c=y/sigma
    return _floor_grid(c*lowe/hi_denom),_ceil_grid(c*highe/low_denom)


def _sign_poly(y: F, mu: F, sigma: F, q: F, t: F):
    # log-density derivative has sign of y^2 -3*sigma^2*t -(mu^2+2*q*sigma^2)*t^2.
    return y*y-3*sigma*sigma*t-(mu*mu+2*q*sigma*sigma)*t*t


def _mode_upper(y: F,mu: F,sigma: F,q: F,a: F,b: F):
    left,right=a,b
    for _ in range(65):
        mid=(left+right)/2
        if _sign_poly(y,mu,sigma,q,mid)>0:
            left=mid
        else:
            right=mid
    # t* is within [left,right]. phi(t) >= y^2/(2*sigma^2*right)
    # + y*mu/sigma^2 + (mu^2+2q*sigma^2)*left/(2*sigma^2).
    phi_lower=(y*y/right+2*y*mu+(mu*mu+2*q*sigma*sigma)*left)/(2*sigma*sigma)
    if phi_lower<0:
        phi_lower=F(0)
    _,exp_hi=_exp_neg(phi_lower)
    lo_pi,_=_pi_bounds()
    low_denom,_=_sqrt_bounds(2*lo_pi*left**3,2*lo_pi*left**3)
    return _ceil_grid((y/sigma)*exp_hi/low_denom)


@dataclass(frozen=True)
class _Piece:
    a: F
    b: F
    flo: F
    fhi: F
    glo: F
    ghi: F

    @property
    def width(self):
        return (self.fhi-self.flo)+(self.ghi-self.glo)


def _create_piece(y,mu,sigma,q,a,b,eval_at):
    fa,ga=eval_at(a)
    fb,gb=eval_at(b)
    def bounds(weight,la,lb):
        pa=_sign_poly(y,mu,sigma,weight,a)
        pb=_sign_poly(y,mu,sigma,weight,b)
        if pb>=0:
            return la[0],lb[1]
        if pa<=0:
            return lb[0],la[1]
        return min(la[0],lb[0]), _mode_upper(y,mu,sigma,weight,a,b)
    fl,fu=bounds(F(0),fa,fb)
    gl,gu=bounds(q,ga,gb)
    if fu<fl or gu<gl:
        raise UnresolvedFirstHit('invalid density enclosure')
    scale=b-a
    def certified_trapezoid(weight, left, right, maximum):
        # L'=S(t)/(2*sigma^2*t^2); S decreases for t>0.
        # L''=(3t-2*y^2/sigma^2)/(2*t^3). Therefore
        # |f''| <= sup(f)*(sup|L''|+(sup|L'|)^2).
        sa=_sign_poly(y,mu,sigma,weight,a)
        sb=_sign_poly(y,mu,sigma,weight,b)
        kp=max(abs(sa),abs(sb))/(2*sigma*sigma*a*a)
        kk=max(abs(3*a-2*y*y/(sigma*sigma)),
               abs(3*b-2*y*y/(sigma*sigma)))/(2*a**3)
        err=scale**3*maximum*(kk+kp*kp)/12
        center_lower=scale*(left[0]+right[0])/2
        center_upper=scale*(left[1]+right[1])/2
        return max(F(0),_floor_grid(center_lower-err)),_ceil_grid(center_upper+err)
    flo,fhi=certified_trapezoid(F(0),fa,fb,fu)
    glo,ghi=certified_trapezoid(q,ga,gb,gu)
    # Two entirely separate mathematical enclosures: take intersection.
    lo_f=max(_floor_grid(scale*fl),flo)
    hi_f=min(_ceil_grid(scale*fu),fhi)
    lo_g=max(_floor_grid(scale*gl),glo)
    hi_g=min(_ceil_grid(scale*gu),ghi)
    if lo_f>hi_f or lo_g>hi_g:
        raise UnresolvedFirstHit('independent quadrature enclosures disagree')
    return _Piece(a,b,lo_f,hi_f,lo_g,hi_g)


@dataclass(frozen=True)
class FirstHitBounds:
    first_lower: F
    first_upper: F
    discounted_lower: F
    discounted_upper: F
    time_zero_upper: F
    cells: int
    target_width: F
    research_only: bool = True
    continuum_debt_pde_certified: bool = False

    @property
    def max_width(self):
        return max(self.first_upper-self.first_lower,
                   self.discounted_upper-self.discounted_lower)

    def decimal_summary(self, digits: int=16):
        return dict(F=[format(float(self.first_lower),f'.{digits}g'),
                       format(float(self.first_upper),f'.{digits}g')],
                    G=[format(float(self.discounted_lower),f'.{digits}g'),
                       format(float(self.discounted_upper),f'.{digits}g')],
                    missing_prefix_upper=format(float(self.time_zero_upper),'.6g'),
                    cells=self.cells, max_width=float(self.max_width),
                    continuum_debt_pde_certified=False)


def bound_first_hit(*,distance,drift,diffusion,maturity,discount,
                    tolerance='0.0005',max_cells=5000):
    """Independent *rigorous rational* two-sided time first-hit enclosure.

    All physical floats are treated as exact binary64 inputs. Input tolerance
    and cell budgets are part of the acceptance contract. Max cap -> REFUSE.
    Financial default/maturity corner is handled upstream: for T=0 and
    distance=0 reject rather than silently deciding which contractual cashflow
    wins. Only positive T and positive distance enter this integral.
    """
    y,mu,sigma,T,q,tol=map(_rational,(distance,drift,diffusion,
                                    maturity,discount,tolerance))
    if not(y>0 and sigma>0 and T>0 and q>=0 and 0<tol<F(1,10)):
        raise UnresolvedFirstHit('invalid positive-distance finite-time contract')
    if type(max_cells) is not int or not 16<=max_cells<=50000:
        raise UnresolvedFirstHit('invalid resource cap')
    # Start sufficiently near time-zero that Chernoff's rational upper bound
    # is below 1/16 of the requested error; no unbounded integration to zero.
    epsilon=min(T/1024, y*y/(512*sigma*sigma),y/(4*(abs(mu)+1)))
    if epsilon<=0:
        raise UnresolvedFirstHit('invalid time-zero truncation')
    for _ in range(180):
        gap=y-abs(mu)*epsilon
        if gap>0:
            exponent=(gap*gap)/(2*sigma*sigma*epsilon)
            _,prefix=_exp_neg(exponent)
            if prefix<tol/16: break
        epsilon/=2
    else:
        raise UnresolvedFirstHit('could not certify early first-hit mass')
    values={}
    def eval_at(t):
        if t not in values:
            values[t]=(_density_enclosure(y,mu,sigma,F(0),t),
                       _density_enclosure(y,mu,sigma,q,t))
        return values[t]
    # Dyadic mass bins avoid near-time-zero ill-conditioning.
    pieces=[]
    a=epsilon
    while a<T:
        b=min(2*a,T)
        pieces.append(_create_piece(y,mu,sigma,q,a,b,eval_at))
        a=b
        if len(pieces)>max_cells:
            raise UnresolvedFirstHit('dyadic work cap exhausted')
    total_flo=sum((p.flo for p in pieces),F(0))
    total_fhi=sum((p.fhi for p in pieces),prefix)
    total_glo=sum((p.glo for p in pieces),F(0))
    total_ghi=sum((p.ghi for p in pieces),prefix)
    # Use interval largest-gap refinement; never mark success when capped.
    h=[(-p.width,i,p) for i,p in enumerate(pieces)]
    heapq.heapify(h)
    serial=len(h)
    while max(total_fhi-total_flo,total_ghi-total_glo)>tol:
        if len(h)>=max_cells:
            raise UnresolvedFirstHit('requested certified width exceeds work budget')
        _,_,piece=heapq.heappop(h)
        mid=(piece.a+piece.b)/2
        left=_create_piece(y,mu,sigma,q,piece.a,mid,eval_at)
        right=_create_piece(y,mu,sigma,q,mid,piece.b,eval_at)
        total_flo+=left.flo+right.flo-piece.flo
        total_fhi+=left.fhi+right.fhi-piece.fhi
        total_glo+=left.glo+right.glo-piece.glo
        total_ghi+=left.ghi+right.ghi-piece.ghi
        heapq.heappush(h,(-left.width,serial,left));serial+=1
        heapq.heappush(h,(-right.width,serial,right));serial+=1
    if not(0<=total_glo<=total_fhi and 0<=total_flo<=total_fhi
           and total_glo<=total_ghi and total_fhi<=1+tol
           and total_ghi<=1+tol):
        raise UnresolvedFirstHit('invalid probability interval')
    f_lo,f_hi=max(F(0),total_flo),min(F(1),total_fhi)
    g_lo,g_hi=max(F(0),total_glo),min(F(1),total_ghi)
    # The discounted event is a nonnegative pointwise factor of first hit.
    # Intersect with 0 <= G <= F <= 1, refusing impossible intervals.
    f_lo=max(f_lo,g_lo)
    g_hi=min(g_hi,f_hi)
    if f_lo>f_hi or g_lo>g_hi:
        raise UnresolvedFirstHit('probability ordering impossible after enclosure')
    return FirstHitBounds(f_lo,f_hi,g_lo,g_hi,
                          prefix,len(h),tol)


def financial_bond_from_hit_interval(*, first: FirstHitBounds,
                                     rate, maturity, principal, coupon,
                                     shock_intensity, sale_fraction,
                                     recovery, boundary):
    """Rigorous financial fixed-barrier bond interval, given F/G enclosures.

    B = c/q + exp(-qT)*(P-c/q)*(1-F) + (R-c/q)*G.
    exp is outward-enclosed, all other arithmetic exact over supplied input
    binary64/rational values. Does not bound PDE spatial/time truncation.
    """
    r,T,par,coupon,z,sale,recovery,b=map(_rational,
       (rate,maturity,principal,coupon,shock_intensity,sale_fraction,recovery,boundary))
    if not (r>0 and T>0 and par>0 and coupon>=0 and z>=0 and
            0<=sale<=1 and 0<=recovery<=1 and b>0):
        raise UnresolvedFirstHit('invalid finance bond parameters')
    q=r+z*sale
    P=par/T
    c=coupon/T
    base=c/q
    R=recovery*b/T
    D_lo,D_hi=_exp_neg(q*T)
    def mult_bounds(coeff,lo,hi):
        return (coeff*lo,coeff*hi) if coeff>=0 else (coeff*hi,coeff*lo)
    v1_lo,v1_hi=mult_bounds(P-base,F(1)-first.first_upper,
                                     F(1)-first.first_lower)
    v2_lo,v2_hi=mult_bounds(R-base,first.discounted_lower,
                                     first.discounted_upper)
    d1=[v1_lo*D_lo,v1_lo*D_hi,v1_hi*D_lo,v1_hi*D_hi]
    result_lo=base+min(d1)+v2_lo
    result_hi=base+max(d1)+v2_hi
    return result_lo,result_hi
