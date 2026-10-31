"""Independent exact-rational fixed-b GBM stopping-policy lower witness.

RESEARCH_ONLY / DENY_ALL / NO_GO.  This bounds ONLY the constant-bond
American put approximation to the He--Xiong financial equity problem.
It does not bound the endogenous barrier, debt PDE, complete equity,
or any neural operator.

For risk-neutral dA=(r-delta)A dt+sigma*A dW, starting at A0=b exp(L),
choose a deterministic level z strictly in (b,A0]. The policy exercises at
its first hit of z, before absorbing at b, with payoff (K-z)^+ where
K=max(0,(C-B_inf)/r), C=(1-tax)coupon+principal/T and
B_inf=c/q+exp(-qT)(principal/T-c/q), c=coupon/T,
q=r+shock_intensity*sale_fraction.
Its expected discounted payoff is exactly
    (K-z)^+ exp[-gamma (L-log(z/b))],
where gamma is the positive root for the r-discounted downward hitting time.
This is a feasible-policy LOWER bound on the perpetual put premium; it is
NOT a lower bound on the original HX equity without bond-error analysis.

All user floats are interpreted as exact binary64 rationals. Transcendentals
are enclosed with finite rational Taylor/geometric remainders, not silently
rounded to machine floating point. Unsupported domains fail closed.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, isqrt


class UnresolvedPutLowerWitness(ValueError):
    """Out-of-domain or unrepresentable research certificate."""


def _f64(x, name):
    if type(x) not in (float, int):
        raise UnresolvedPutLowerWitness(f'{name}: binary64 input required')
    try:
        y = float(x)
    except (OverflowError, ValueError) as exc:
        raise UnresolvedPutLowerWitness(f'{name}: invalid binary64') from exc
    if not isfinite(y) or abs(y) > 1e12 or (type(x) is int and int(y) != x):
        raise UnresolvedPutLowerWitness(f'{name}: nonfinite or out-of-range')
    return Fraction.from_float(y)


def _down(x, *, places=18):
    scale=10**places
    return Fraction(x.numerator*scale//x.denominator,scale)


def _up(x, *, places=18):
    scale=10**places
    return Fraction((x.numerator*scale+x.denominator-1)//x.denominator,scale)


def _sqrt_bracket(x, *, digits=22):
    if not isinstance(x, Fraction) or not 0 < x <= 10**12:
        raise UnresolvedPutLowerWitness('sqrt domain')
    scale = 10**digits
    v = isqrt(x.numerator * scale * scale // x.denominator)
    lo, hi = Fraction(v,scale), Fraction(v+1,scale)
    if not (0 < lo and lo*lo <= x < hi*hi):
        raise UnresolvedPutLowerWitness('invalid outward sqrt')
    return lo,hi


def _positive_exp_bracket(x, *, terms=96):
    if not isinstance(x, Fraction) or not 0 < x <= 8:
        raise UnresolvedPutLowerWitness('positive exponential domain')
    if type(terms) is not int or not 80 <= terms <= 160:
        raise UnresolvedPutLowerWitness('exponential work budget')
    term = total = Fraction(1)
    for j in range(1,terms+1):
        term *= x/j
        total += term
    next_term = term*x/(terms+1)
    ratio = x/Fraction(terms+2)
    if not ratio<1:
        raise UnresolvedPutLowerWitness('exponential tail invalid')
    return total,total+next_term/(1-ratio)


def _positive_exp_large_bracket(x, *, terms=96):
    if not isinstance(x,Fraction) or not 0<=x<=128:
        raise UnresolvedPutLowerWitness('large exponential domain')
    if x==0:
        return Fraction(1),Fraction(1)
    segments=max(1,(x.numerator+8*x.denominator-1)//(8*x.denominator))
    if segments>32:
        raise UnresolvedPutLowerWitness('excessive positive exp segments')
    lo,hi=_positive_exp_bracket(x/segments,terms=terms)
    return lo**segments,hi**segments


def _negative_exp_bracket(x, *, terms=96):
    if not isinstance(x, Fraction) or not 0<=x<=128:
        raise UnresolvedPutLowerWitness('negative exponential domain')
    if x==0:
        return Fraction(1),Fraction(1)
    segments = max(1,(x.numerator+8*x.denominator-1)//(8*x.denominator))
    if segments>32:
        raise UnresolvedPutLowerWitness('too many exponential segments')
    lo,hi=_positive_exp_bracket(x/segments,terms=terms)
    return (1/hi)**segments,(1/lo)**segments


def _log_upper_ge_one(x, *, terms=24):
    """Exact rational upper bound on log(x) from an atanh tail bound."""
    if not isinstance(x, Fraction) or not 1<=x<=8:
        raise UnresolvedPutLowerWitness('log ratio outside [1,8]')
    if type(terms) is not int or not 8<=terms<=64:
        raise UnresolvedPutLowerWitness('log work budget')
    if x==1:
        return Fraction(0)
    y=(x-1)/(x+1)
    power=y
    total=Fraction(0)
    for j in range(terms):
        total+=power/(2*j+1)
        power*=y*y
    return 2*(total+power/((2*terms+1)*(1-y*y)))


def _log_lower_ge_one(x, *, terms=24):
    """Strictly outward lower from positive atanh power series."""
    if not isinstance(x, Fraction) or not 1<=x<=8:
        raise UnresolvedPutLowerWitness('log ratio outside [1,8]')
    if type(terms) is not int or not 8<=terms<=64:
        raise UnresolvedPutLowerWitness('log work budget')
    if x==1:
        return Fraction(0)
    y=(x-1)/(x+1)
    power=y
    total=Fraction(0)
    for j in range(terms):
        total+=power/(2*j+1)
        power*=y*y
    return 2*total


def _ceil_decimal(x, *, places=12):
    if not isinstance(x,Fraction) or not 0<=x<=10**20:
        raise UnresolvedPutLowerWitness('invalid decimal output')
    scale=10**places
    quotient=(x.numerator*scale+x.denominator-1)//x.denominator
    return f'{quotient//scale}.{quotient%scale:0{places}d}'


def _floor_decimal(x, *, places=12):
    if not isinstance(x,Fraction) or not 0<=x<=10**20:
        raise UnresolvedPutLowerWitness('invalid decimal output')
    scale=10**places
    quotient=x.numerator*scale//x.denominator
    return f'{quotient//scale}.{quotient%scale:0{places}d}'


@dataclass(frozen=True)
class FixedBarrierPutLowerWitness:
    put_lower: str
    exact_rational_hit_level: str
    strike_lower: str
    gamma_lower: str
    gamma_upper: str
    discounted_hit_factor_lower: str
    exercise_is_strictly_above_barrier: bool
    scope: str = 'constant-bond GBM fixed-barrier perpetual-put feasible-hit policy only'
    scientific_gate_closed: bool = False
    production_activation: bool = False

    def certify_p0(self):
        raise UnresolvedPutLowerWitness('isolated feasible-hit lower witness does not close P0')


def certify_fixed_barrier_put_hit_lower(p, *, candidate_barrier: float,
                                        log_upper: float,
                                        taylor_terms: int=96,
                                        log_terms: int=24):
    names=('rate','payout','volatility','maturity','principal','coupon',
           'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        a={name:_f64(getattr(p,name),name) for name in names}
    except AttributeError as exc:
        raise UnresolvedPutLowerWitness('missing HX field') from exc
    r,delta,sigma,T=(a[n] for n in ('rate','payout','volatility','maturity'))
    if not (r>0 and delta>0 and sigma>0 and T>0 and
            a['principal']>0 and a['coupon']>=0 and
            0<=a['tax_shield']<=1 and 0<=a['recovery']<=1 and
            a['shock_intensity']>=0 and 0<=a['sale_fraction']<=1):
        raise UnresolvedPutLowerWitness('invalid physical domain')
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    if not b>0 or not 0<L<=8:
        raise UnresolvedPutLowerWitness('invalid barrier or log horizon')
    q=r+a['shock_intensity']*a['sale_fraction']
    c=a['coupon']/T
    par=a['principal']/T
    C=(1-a['tax_shield'])*a['coupon']+par
    exp_lo,exp_hi=_negative_exp_bracket(q*T,terms=taylor_terms)
    # Reduce rational size only with proven outward rounding.
    exp_lo,exp_hi=_down(exp_lo),_up(exp_hi)
    factor=par-c/q
    bond_hi=max(c/q+factor*exp_lo,c/q+factor*exp_hi)
    strike_lo=_down(max(Fraction(0),(C-bond_hi)/r))
    drift=(r-delta-sigma*sigma/2)/(sigma*sigma)
    zl,zu=_sqrt_bracket(drift*drift+2*r/(sigma*sigma))
    gamma_lo,gamma_hi=_down(drift+zl),_up(drift+zu)
    if gamma_lo<=0:
        raise UnresolvedPutLowerWitness('uncertified downward hit exponent')
    asset_lo=b*_down(_positive_exp_bracket(L,terms=taylor_terms)[0])
    if strike_lo<=b or asset_lo<=b:
        return FixedBarrierPutLowerWitness('0.000000000000','NONE',
            _floor_decimal(strike_lo),_floor_decimal(gamma_lo),
            _ceil_decimal(gamma_hi),'0.000000000000',False)
    # Choose a strict feasible lower stopping level, unlike default at b.
    optimum=gamma_lo*strike_lo/(gamma_lo+1)
    z=_down(min(asset_lo,max(b+(strike_lo-b)/1024,optimum)))
    if not b<z<=asset_lo or not z<strike_lo:
        raise UnresolvedPutLowerWitness('invalid feasible hitting level')
    ratio=_down(z/b)
    log_ratio_lo=_down(_log_lower_ge_one(ratio,terms=log_terms))
    dist_hi=L-log_ratio_lo
    if dist_hi<0:
        raise UnresolvedPutLowerWitness('unresolved log distance')
    discounted_hit_lo=_down(_negative_exp_bracket(gamma_hi*dist_hi,terms=taylor_terms)[0])
    payoff_lo=(strike_lo-z)*discounted_hit_lo
    if not payoff_lo>=0:
        raise UnresolvedPutLowerWitness('negative feasible-payoff lower')
    return FixedBarrierPutLowerWitness(
        _floor_decimal(payoff_lo),str(z),_floor_decimal(strike_lo),
        _floor_decimal(gamma_lo),_ceil_decimal(gamma_hi),
        _floor_decimal(discounted_hit_lo),True)


@dataclass(frozen=True)
class FixedBarrierPutDualCertificate:
    put_lower: str
    put_upper: str
    witness_level: str
    strike_lower: str
    strike_upper: str
    gamma_lower: str
    gamma_upper: str
    comparison_scope: str = 'same fixed-b constant-bond perpetual-put, not original debt/equity'
    scientific_gate_closed: bool = False
    production_activation: bool = False

    def certify_p0(self):
        raise UnresolvedPutLowerWitness('isolated perpetual-put dual interval is not P0')


def certify_fixed_barrier_put_dual(p, *, candidate_barrier: float,
                                   log_upper: float, taylor_terms: int=96,
                                   log_terms: int=24):
    """Dual enclosure: feasible first-hit lower plus r-harmonic upper.

    Unlike the coarse rational-power grid of #4518, take k=gamma_upper
    itself (a rational 18-decimal upper endpoint), avoiding avoidable
    rational exponent discretization loss. Algebraic supremum is over z>=b.
    """
    lower=certify_fixed_barrier_put_hit_lower(p,candidate_barrier=candidate_barrier,
                                              log_upper=log_upper,
                                              taylor_terms=taylor_terms,
                                              log_terms=log_terms)
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    a={name:_f64(getattr(p,name),name) for name in fields}
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    r=a['rate'];T=a['maturity'];q=r+a['shock_intensity']*a['sale_fraction']
    c=a['coupon']/T;par=a['principal']/T
    C=(1-a['tax_shield'])*a['coupon']+par
    exp_lo,exp_hi=_negative_exp_bracket(q*T,terms=taylor_terms)
    exp_lo,exp_hi=_down(exp_lo),_up(exp_hi)
    off=par-c/q
    bond_lo=min(c/q+off*exp_lo,c/q+off*exp_hi)
    strike_hi=_up(max(Fraction(0),(C-bond_lo)/r))
    gamma_lo=Fraction(lower.gamma_lower)
    gamma_hi=Fraction(lower.gamma_upper)
    if not 0<gamma_lo<=gamma_hi:
        raise UnresolvedPutLowerWitness('invalid dual gamma endpoints')
    coeff_hi=Fraction(0)
    if strike_hi>b:
        optimum=gamma_hi*strike_hi/(gamma_hi+1)
        if optimum<=b:
            coeff_hi=strike_hi-b
        else:
            ratio_hi=_up(optimum/b)
            log_hi=_up(_log_upper_ge_one(ratio_hi,terms=log_terms))
            power_exponent=gamma_hi*log_hi
            if not 0<power_exponent<=128:
                raise UnresolvedPutLowerWitness('exponential power outside certified domain')
            pow_hi=_up(_positive_exp_large_bracket(power_exponent,terms=taylor_terms)[1])
            coeff_hi=_up((strike_hi-optimum)*pow_hi)
    discount_hi=_up(_negative_exp_bracket(gamma_lo*L,terms=taylor_terms)[1])
    put_hi=_up(coeff_hi*discount_hi)
    put_hi_decimal=_ceil_decimal(put_hi)
    if Fraction(put_hi_decimal)<Fraction(lower.put_lower):
        raise UnresolvedPutLowerWitness('empty independent dual interval')
    return FixedBarrierPutDualCertificate(
        lower.put_lower,put_hi_decimal,lower.exact_rational_hit_level,
        lower.strike_lower,_ceil_decimal(strike_hi),
        lower.gamma_lower,lower.gamma_upper)
