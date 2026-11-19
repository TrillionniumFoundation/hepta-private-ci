"""Conservative fixed-barrier HX equity Dirichlet bounds; research-only.

For positive payout delta, killed GBM stockholder equity has:
 max(0,A-b-max(C-m,0)/r) <= V(A) <= A+max(M-C,0)/r,
where C=(1-tax)*coupon+principal/T, and HX debt cash flow lies
between m=min(coupon/(T*q), principal/T, recovery*b/T) and corresponding M.
This does not certify endogenous free boundary, mesh, or full P0.
All lower decimal bounds are rounded DOWN, upper bounds UP.
"""
from dataclasses import dataclass
from fractions import Fraction
import math

class UnresolvedEquityEnvelope(ValueError):
    pass

def _r(x):
    if type(x) not in (float,int) or not math.isfinite(float(x)) or abs(float(x))>1e12:
        raise UnresolvedEquityEnvelope("unsupported finite physical scalar")
    if type(x) is int and int(float(x))!=x:
        raise UnresolvedEquityEnvelope("integer exceeds exact binary64 range")
    return Fraction.from_float(float(x))

def _exp_bounds(x, terms=96):
    if not 0<x<=12 or type(terms) is not int or not 64<=terms<=160:
        raise UnresolvedEquityEnvelope("unsupported Taylor domain")
    s=Fraction(1);t=Fraction(1)
    for k in range(1,terms+1):
        t*=x/k;s+=t
    tail=t*x/(terms+1)/(1-x/(terms+2))
    return s,s+tail

def _decimal(x, upward, digits=12):
    if not isinstance(x,Fraction) or x<0 or x>10**20:
        raise UnresolvedEquityEnvelope("invalid nonnegative enclosure")
    scale=10**digits; num=x.numerator*scale
    value=(num+x.denominator-1)//x.denominator if upward else num//x.denominator
    whole,fraction=divmod(value,scale)
    return f"{whole}.{fraction:0{digits}d}"

@dataclass(frozen=True)
class EquityBoundaryEnvelope:
    asset_lower: str
    asset_upper: str
    equity_lower: str
    equity_upper: str
    upper_dirichlet_abs_error_budget: str
    debt_lower: str
    debt_upper: str
    global_certification: bool = False
    complete_debt_error_budget: bool = False
    production_activation: bool = False
    all_scientific_blockers_closed: bool = False

    def certify_global_hx(self):
        raise UnresolvedEquityEnvelope("fixed-barrier Dirichlet bound is not coupled HX")

def fixed_barrier_equity_dirichlet(p, *, candidate_boundary, log_upper,
                                  nominal_upper_equity, terms=96):
    names=("rate","payout","volatility","maturity","principal","coupon",
           "tax_shield","recovery","shock_intensity","sale_fraction")
    try:
        a={n:_r(getattr(p,n)) for n in names}
    except AttributeError as e:
        raise UnresolvedEquityEnvelope("missing HX input") from e
    r=a["rate"];delta=a["payout"];T=a["maturity"]
    if not (r>0 and delta>0 and T>0 and a["volatility"]>0 and
            a["principal"]>0 and a["coupon"]>=0 and
            0<=a["tax_shield"]<=1 and 0<=a["recovery"]<=1 and
            a["shock_intensity"]>=0 and 0<=a["sale_fraction"]<=1):
        raise UnresolvedEquityEnvelope("unsupported HX physical domain")
    b=_r(candidate_boundary);L=_r(log_upper);guess=_r(nominal_upper_equity)
    if b<=0:
        raise UnresolvedEquityEnvelope("nonpositive fixed barrier")
    exp_low,exp_high=_exp_bounds(L,terms)
    A_lo=b*exp_low;A_hi=b*exp_high
    q=r+a["shock_intensity"]*a["sale_fraction"]
    coupon_rate=a["coupon"]/T
    par=a["principal"]/T
    recovery=a["recovery"]*b/T
    m=min(coupon_rate/q,par,recovery)
    M=max(coupon_rate/q,par,recovery)
    C=(1-a["tax_shield"])*a["coupon"]+par
    low=max(Fraction(0),A_lo-b-max(C-m,Fraction(0))/r)
    high=A_hi+max(M-C,Fraction(0))/r
    if low>high:
        raise UnresolvedEquityEnvelope("inconsistent equity bounds")
    err=max(abs(guess-low),abs(high-guess))
    return EquityBoundaryEnvelope(
        _decimal(A_lo,False),_decimal(A_hi,True),
        _decimal(low,False),_decimal(high,True),_decimal(err,True),
        _decimal(m,False),_decimal(M,True))
