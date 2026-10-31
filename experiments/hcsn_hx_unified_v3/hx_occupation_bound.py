"""Conservative rational HX *fixed-barrier* far-field equity enclosure.

For log-asset Y=log(A/b) killed at Y=0, running equity cashflow is
  f(A)=delta*A+B(A;b,T)-C,
where the maturity-T *bond* B is represented as a coupon/default/terminal
expectation (not by calling any HX closed-form pricing routine).

Write B_inf=c/q+exp(-q*T)*(par-c/q). For any y>0, the bond deviation obeys
  |B(b*exp(y))-B_inf| <= D F_T(y),
  D=exp(-q*T)*|par-c/q| + |rec-c/q|,
where F_T is log-Brownian lower first-hit probability by maturity T.

Conservatively bound F_T(y) by the Gaussian exponential-martingale estimate
  exp(-max(y-|mu|T,0)^2/(2*sigma^2*T)), mu=r-delta-sigma^2/2.
Its decreasing staircase majorant f_j on [j*h,(j+1)*h) permits the exact
killed resolvent occupancy bound for each lower interval [0,u]:
  E_L integral_0^tau0 exp(-rt) 1{Y_t<=u} dt =
  [exp(-gamma*(L-u))*(1-exp(-gamma*u))/gamma
  - exp(-gamma*L)*(1-exp(-eta*u))/eta]/(sigma^2*z),
where a=mu/sigma^2, z=sqrt(a^2+2r/sigma^2), gamma=a+z,
eta=z-a. The second (positive) term is rigorously lower-enclosed before
subtraction. Each numerator, positive denominator, sqrt and exponential
is enclosed in exact rational arithmetic.

The resulting bound H controls absolute *discounted cumulative bond cashflow*
errors for ANY stopping time <= tau0, not merely one stationary policy.
For constant debt B_inf, the discounted ex-dividend asset martingale gives
  base = A+(B_inf-C)/r,
  hold_to_default = base - (b+(B_inf-C)/r)*exp(-gamma*L).
The upper optional-stopping premium of (K-A_tau)^+ with K=-d, d=(B_inf-C)/r
is bounded by C_put*b/A. This requires L(A^-1)<=r A^-1, i.e.
  delta+sigma^2 <= 2*r,
and C_put=sup_{A>=b} ((K-A)^+*A/b), computed as a rational quadratic.

ALL transcendental evaluations are enclosed by finite exact-rational
Taylor/geometric tails. The sqrt z is rationally bracketed by integer isqrt.
This is deliberately a RESEARCH-ONLY, FIXED-b *continuum* far-field bound.
It is NOT an independently proven endogenous He--Xiong boundary, complete
financial obstacle, debt PDE interior/rounding certificate or GPU kernel.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isqrt

from .hx_equity_upper_envelope import (_f64, _exp_interval_positive,
                                        _ceil_decimal, _floor_decimal,
                                        UnresolvedEquityEnvelope)


def _exp_neg_interval(x: Fraction, *, terms: int = 96) -> tuple[Fraction, Fraction]:
    """Enclose exp(-x) for nonnegative rational x, using exact exp(+x)."""
    if not isinstance(x, Fraction) or not 0 <= x <= 128:
        raise UnresolvedEquityEnvelope('exponential argument outside certified resource domain')
    if x == 0:
        return Fraction(1), Fraction(1)
    # Reduce to chunks of <=8 before powering positive Taylor intervals.
    segments = max(1, (x.numerator + 8*x.denominator-1)//(8*x.denominator))
    if segments > 32:
        raise UnresolvedEquityEnvelope('excessive exponential segmentation')
    lo,hi = _exp_interval_positive(x/segments, terms=terms)
    return (1/hi)**segments, (1/lo)**segments


def _sqrt_interval(x: Fraction, *, digits: int = 18) -> tuple[Fraction, Fraction]:
    """Enclose sqrt of an exact positive rational by scaled integer isqrt."""
    if not isinstance(x,Fraction) or x<=0 or x>10**12 or not 10<=digits<=24:
        raise UnresolvedEquityEnvelope('unsupported positive rational sqrt')
    scale=10**digits
    n=isqrt((x.numerator*scale*scale)//x.denominator)
    lower=Fraction(n,scale)
    upper=Fraction(n+1,scale)
    if not (lower>0 and lower*lower<=x<upper*upper):
        raise UnresolvedEquityEnvelope('sqrt bracket invariant failed')
    return lower,upper


def _max_product(x: tuple[Fraction,Fraction], y: tuple[Fraction,Fraction]) -> Fraction:
    return max(a*b for a in x for b in y)


def _occupation_upper(L: Fraction, u: Fraction, sigma2: Fraction,
                      zl: Fraction, gamma_l: Fraction,
                      zu: Fraction | None = None,
                      drift_ratio: Fraction | None = None) -> Fraction:
    """Exact-rational upper on discounted occupation of Y<=u, 0<=u<=L."""
    if u==0:
        return Fraction(0)
    if not 0<u<=L or gamma_l<=0 or zl<=0 or sigma2<=0:
        raise UnresolvedEquityEnvelope('invalid killed Brownian occupation bound')
    tail_hi=_exp_neg_interval(gamma_l*(L-u))[1]
    one_minus_hi=1-_exp_neg_interval(gamma_l*u)[0]
    first_hi=tail_hi*one_minus_hi/gamma_l
    # The optional extra inputs allow a stronger, still outward, enclosure
    # from the *full* killed Green integral. The simple upper bound remains
    # available as an independent reference for direct testing.
    if zu is None and drift_ratio is None:
        return first_hi/(sigma2*zl)
    if zu is None or drift_ratio is None or zu<zl:
        raise UnresolvedEquityEnvelope('incomplete Green bracket')
    gamma_u=drift_ratio+zu
    eta_u=zu-drift_ratio
    if gamma_u<=0 or eta_u<=0:
        raise UnresolvedEquityEnvelope('nonpositive Green exponents')
    tail_lo=_exp_neg_interval(gamma_u*L)[0]
    one_minus_lo=1-_exp_neg_interval(eta_u*u)[1]
    second_lo=tail_lo*one_minus_lo/eta_u
    numerator_hi=first_hi-second_lo
    if numerator_hi<=0:
        raise UnresolvedEquityEnvelope('unresolved positive Green occupancy')
    return numerator_hi/(sigma2*zl)


def _tail_cdf_bound(y: Fraction, mu: Fraction, T: Fraction,
                    sigma2: Fraction) -> Fraction:
    displacement=max(Fraction(0), y-abs(mu)*T)
    return _exp_neg_interval(displacement*displacement/(2*sigma2*T))[1]


@dataclass(frozen=True)
class SharpEquityBoundary:
    # Endpoint values are outward-rounded decimal strings, never point guesses.
    equity_lower: str
    equity_upper: str
    nominal_absolute_error_upper: str
    occupation_error_upper: str
    put_optional_premium_upper: str
    asset_lower: str
    asset_upper: str
    gaussian_steps: int
    gaussian_cutoff: str
    candidate_boundary: float
    log_upper: float
    lower_exponential_drift: str
    guarantee: str = ('fixed positive default barrier, original coupon/default/terminal '
                      'bond and killed-GBM optimal stopping; exact rational enclosures')
    # A finite bound is not a coupled barrier or complete P0 certificate.
    scientific_gate_closed: bool = False
    complete_debt_error_budget: bool = False
    global_equilibrium_certified: bool = False
    production_activation: bool = False

    def to_production(self):
        raise UnresolvedEquityEnvelope('fixed-barrier envelope is not production admission')


def sharp_fixed_barrier_equity_envelope(p, *, candidate_barrier: float,
                                        log_upper: float,
                                        nominal_upper_equity: float,
                                        gaussian_steps: int = 32,
                                        gaussian_cutoff: float = 1.5,
                                        taylor_terms: int = 96) -> SharpEquityBoundary:
    """Outward rational enclosure for fixed-barrier optimal equity at b*e^L.

    All input floats are interpreted exactly as binary64. A conservative
    1/A perpetual-put super-solution is used only when its exact generator
    inequality holds. Otherwise this bounded implementation REFUSES.
    """
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        a={n:_f64(getattr(p,n),n) for n in fields}
    except AttributeError as e:
        raise UnresolvedEquityEnvelope('missing financial parameter') from e
    r=a['rate'];delta=a['payout'];s2=a['volatility']**2;T=a['maturity']
    if not (r>0 and delta>0 and s2>0 and T>0 and a['principal']>0
            and a['coupon']>=0 and a['shock_intensity']>=0
            and 0<=a['sale_fraction']<=1 and 0<=a['recovery']<=1
            and 0<=a['tax_shield']<=1):
        raise UnresolvedEquityEnvelope('unsupported financial parameters')
    if not delta+s2<=2*r:
        raise UnresolvedEquityEnvelope('perpetual 1/A put super-solution not available')
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    gmax=_f64(gaussian_cutoff,'gaussian_cutoff')
    nominal=_f64(nominal_upper_equity,'nominal_upper_equity')
    if not b>0 or not Fraction(1,2)<=gmax<L<=8:
        raise UnresolvedEquityEnvelope('invalid finite upper/cutoff domain')
    if type(gaussian_steps) is not int or not 8<=gaussian_steps<=128:
        raise UnresolvedEquityEnvelope('unsupported gaussian staircase resolution')
    if type(taylor_terms) is not int or not 80<=taylor_terms<=160:
        raise UnresolvedEquityEnvelope('unsupported Taylor work budget')
    exp_lo,exp_hi=_exp_interval_positive(L,terms=taylor_terms)
    asset_lo,asset_hi=b*exp_lo,b*exp_hi
    if asset_hi>10**20:
        raise UnresolvedEquityEnvelope('asset outside exact decimal budget')

    q=r+a['shock_intensity']*a['sale_fraction']
    c=a['coupon']/T;par=a['principal']/T;recovery=a['recovery']*b/T
    C=(1-a['tax_shield'])*a['coupon']+par
    e_lo,e_hi=_exp_neg_interval(q*T,terms=taylor_terms)
    bond_coeff=par-c/q
    bond_inf_lo=min(c/q+bond_coeff*e_lo,c/q+bond_coeff*e_hi)
    bond_inf_hi=max(c/q+bond_coeff*e_lo,c/q+bond_coeff*e_hi)
    d_lo=(bond_inf_lo-C)/r
    d_hi=(bond_inf_hi-C)/r
    deviation_max=abs(bond_coeff)*e_hi+abs(recovery-c/q)

    mu=r-delta-s2/2
    drift_ratio=mu/s2
    zl,zu=_sqrt_interval(drift_ratio**2+2*r/s2)
    gamma_l=drift_ratio+zl
    gamma_u=drift_ratio+zu
    if gamma_l<=0:
        raise UnresolvedEquityEnvelope('nonpositive discounted downward-hit exponent')
    u=[gmax*i/gaussian_steps for i in range(gaussian_steps+1)]
    F=[Fraction(1)]
    for y in u[1:]:
        F.append(min(F[-1],_tail_cdf_bound(y,mu,T,s2)))
    occupation=F[-1]/r
    for j in range(gaussian_steps):
        occupation+=(F[j]-F[j+1])*_occupation_upper(
            L,u[j+1],s2,zl,gamma_l,zu,drift_ratio)
    H=deviation_max*occupation
    if not 0<=H<=10**20:
        raise UnresolvedEquityEnvelope('unusable financial occupation uncertainty')

    # Starting asset on the far-field upper boundary is A=b*exp(L).
    # Cput/A * b is superharmonic for drift condition delta+sigma^2<=2r.
    K=max(Fraction(0),-d_lo)
    if K<=b:
        put_coefficient=Fraction(0)
    elif K>=2*b:
        put_coefficient=K*K/(4*b)
    else:
        put_coefficient=K-b
    put_upper=put_coefficient*_exp_neg_interval(L,terms=taylor_terms)[1]

    # Any stopping rule's value <= base + put premium + bond-occupation.
    equity_hi=asset_hi+d_hi+put_upper+H
    # Hold-to-default policy is feasible; derive a lower envelope from the
    # discounted first hit of the fixed barrier, with optional never-stop tail.
    hit_lo=_exp_neg_interval(gamma_u*L,terms=taylor_terms)[0]
    hit_hi=_exp_neg_interval(gamma_l*L,terms=taylor_terms)[1]
    stopped_term_hi=_max_product((b+d_lo,b+d_hi),(hit_lo,hit_hi))
    equity_lo=max(Fraction(0),asset_lo+d_lo-stopped_term_hi-H)
    if equity_hi<equity_lo:
        raise UnresolvedEquityEnvelope('empty fixed-barrier continuum enclosure')
    budget=max(abs(nominal-equity_lo),abs(equity_hi-nominal))
    return SharpEquityBoundary(
        _floor_decimal(equity_lo),_ceil_decimal(equity_hi),
        _ceil_decimal(budget),_ceil_decimal(H),_ceil_decimal(put_upper),
        _floor_decimal(asset_lo),_ceil_decimal(asset_hi),
        gaussian_steps,str(gmax),float(candidate_barrier),float(log_upper),
        _floor_decimal(gamma_l))
