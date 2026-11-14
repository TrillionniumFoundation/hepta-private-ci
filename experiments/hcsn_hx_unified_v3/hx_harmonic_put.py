"""Exact-rational, fail-closed r-harmonic perpetual-put upper certificate.

For GBM dA=(r-delta)A dt+sigma A dW and a fixed absorbing b>0,

  gamma = (r-delta-sigma^2/2)/sigma^2 +
          sqrt(((r-delta-sigma^2/2)/sigma^2)^2 + 2*r/sigma^2) > 0

makes (b/A)^gamma r-harmonic for A>b. Hence optional sampling gives

  sup_{tau<=tau_b} E[e^{-r tau}(K-A_tau)^+]
  <= exp(-gamma*log(A/b)) * sup_{z>=b} (K-z)^+ (z/b)^gamma.

For any rational k >= gamma, z>=b implies (z/b)^gamma <= (z/b)^k.
The maximizer for k is z*=max(b,k*K/(k+1)); thus the rightmost
coefficient can be conservatively evaluated with exact rational logarithm,
positive Taylor exponential and rational integer sqrt enclosures.

This removes the delta+sigma^2<=2*r requirement for this *one optional
stopping component*, NOT for the parent's full equity enclosure. Every
result is strictly fixed-barrier and RESEARCH_ONLY/DENY_ALL/NO_GO.
"""

from dataclasses import dataclass
from fractions import Fraction
from .hx_equity_upper_envelope import (_f64, _ceil_decimal, _floor_decimal,
                                        _exp_interval_positive, UnresolvedEquityEnvelope)
from .hx_occupation_bound import (_exp_neg_interval, _sqrt_interval,
                                  sharp_fixed_barrier_equity_envelope)


def _ceil_rational(x: Fraction, *, places: int = 20) -> Fraction:
    if not isinstance(x,Fraction):
        raise UnresolvedEquityEnvelope('not exact rational')
    scale=10**places
    return Fraction((x.numerator*scale+x.denominator-1)//x.denominator,scale)


def _floor_rational(x: Fraction, *, places: int = 20) -> Fraction:
    if not isinstance(x,Fraction):
        raise UnresolvedEquityEnvelope('not exact rational')
    scale=10**places
    return Fraction(x.numerator*scale//x.denominator,scale)


def _log_upper_ge_one(x: Fraction, *, terms: int = 16) -> Fraction:
    """Exact rational log(x) upper using 2*atanh((x-1)/(x+1))."""
    if not isinstance(x, Fraction) or not 1 <= x <= 8:
        raise UnresolvedEquityEnvelope('rational log argument outside [1,8]')
    if type(terms) is not int or not 8<=terms<=64:
        raise UnresolvedEquityEnvelope('unsupported log series work budget')
    if x == 1:
        return Fraction(0)
    z=(x-1)/(x+1)
    zz=z*z
    term=z
    summation=Fraction(0)
    for j in range(terms):
        summation+=term/(2*j+1)
        term*=zz
    # Exact geometric upper on the positive atanh tail.
    return 2*(summation+term/((2*terms+1)*(1-zz)))


@dataclass(frozen=True)
class HarmonicPutComponent:
    put_premium_upper: str
    strike_upper: str
    gamma_lower: str
    gamma_upper: str
    rational_power: str
    max_multiplier_upper: str
    scope: str = 'fixed-barrier perpetual put optional-stopping component only'
    production_activation: bool = False
    all_scientific_blockers_closed: bool = False

    def certify_p0(self):
        raise UnresolvedEquityEnvelope('isolated r-harmonic put component is not P0 proof')


def harmonic_put_component(p, *, candidate_barrier: float, log_upper: float,
                           exp_terms: int = 96,
                           k_denominator: int = 1000,
                           log_terms: int = 16) -> HarmonicPutComponent:
    """Conservatively bound the exact fixed-barrier optimal-stop put premium.

    All physical floats are EXACT binary64 rational inputs. Parameter regimes
    outside resource limits fail closed (no synthetic lower thresholds).
    """
    names=('rate','payout','volatility','maturity','principal','coupon',
           'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        a={n:_f64(getattr(p,n),n) for n in names}
    except AttributeError as exc:
        raise UnresolvedEquityEnvelope('missing HX finance parameter') from exc
    r=a['rate'];delta=a['payout'];s2=a['volatility']**2;T=a['maturity']
    if not (r>0 and delta>0 and s2>0 and T>0 and a['principal']>0 and
            a['coupon']>=0 and a['shock_intensity']>=0 and
            0<=a['tax_shield']<=1 and 0<=a['recovery']<=1 and
            0<=a['sale_fraction']<=1):
        raise UnresolvedEquityEnvelope('invalid finance parameter domain')
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    if not (b>0 and 0<L<=8 and type(exp_terms) is int and
            80<=exp_terms<=160 and type(k_denominator) is int and
            16<=k_denominator<=10000):
        raise UnresolvedEquityEnvelope('invalid barrier, log distance, or work budget')
    q=r+a['shock_intensity']*a['sale_fraction']
    c=a['coupon']/T;par=a['principal']/T
    C=(1-a['tax_shield'])*a['coupon']+par
    e0raw,e1raw=_exp_neg_interval(q*T,terms=exp_terms)
    e0,e1=_floor_rational(e0raw),_ceil_rational(e1raw)
    off=par-c/q
    bond_inf_lower=min(c/q+off*e0,c/q+off*e1)
    K=_ceil_rational(max(Fraction(0),(C-bond_inf_lower)/r))
    drift=(r-delta-s2/2)/s2
    zl,zu=_sqrt_interval(drift*drift+2*r/s2)
    gamma_lo=_floor_rational(drift+zl)
    gamma_hi=_ceil_rational(drift+zu)
    if gamma_lo<=0:
        raise UnresolvedEquityEnvelope('unresolved positive r-harmonic exponent')
    k=Fraction((gamma_hi*k_denominator).numerator //
               (gamma_hi*k_denominator).denominator+1,k_denominator)
    if not (k>=gamma_hi):
        raise UnresolvedEquityEnvelope('inward rational exponent')
    coeff=Fraction(0)
    if K>b:
        optimum=k*K/(k+1)
        if optimum<=b:
            coeff=K-b
        else:
            ratio=_ceil_rational(optimum/b)
            loghi=_ceil_rational(_log_upper_ge_one(ratio,terms=log_terms))
            if not 0<k*loghi<=12:
                raise UnresolvedEquityEnvelope('unrepresentable optimal put ratio')
            pow_upper=_ceil_rational(_exp_interval_positive(k*loghi,terms=exp_terms)[1])
            coeff=_ceil_rational((K-optimum)*pow_upper)
    tail_up=_ceil_rational(_exp_neg_interval(gamma_lo*L,terms=exp_terms)[1])
    puthi=_ceil_rational(coeff*tail_up)
    if not 0<=puthi<=10**20:
        raise UnresolvedEquityEnvelope('put budget outside output domain')
    return HarmonicPutComponent(_ceil_decimal(puthi),
        _ceil_decimal(K),_floor_decimal(gamma_lo),_ceil_decimal(gamma_hi),
        str(k),_ceil_decimal(coeff))


@dataclass(frozen=True)
class TightenedFixedEquity:
    equity_lower: str
    equity_upper: str
    nominal_absolute_error_upper: str
    original_equity_upper: str
    old_put_premium_upper: str
    harmonic_put_premium_upper: str
    arithmetic: str = 'exact rational composition of outward 12-digit certificates'
    scope: str = 'fixed-barrier continuum upper Dirichlet only'
    production_activation: bool = False
    all_scientific_blockers_closed: bool = False
    complete_debt_error_budget: bool = False
    global_equilibrium_certified: bool = False


def tightened_fixed_equity_envelope(p, *, candidate_barrier: float,
                                    log_upper: float,
                                    nominal_upper_equity: float,
                                    gaussian_steps: int = 32,
                                    gaussian_cutoff: float = 1.5) -> TightenedFixedEquity:
    """Compose with #4516 without treating rounded-up put as exact subtraction.

    If the old put certificate P is rounded upward with decimal quantum eps,
    its exact algebraic term lies in (P-eps,P]. Subtract only the rigorous
    lower P-eps from the existing upward-rounded equity endpoint, then add
    the rigorous harmonic put *upper*; min with original safe endpoint.
    """
    parent=sharp_fixed_barrier_equity_envelope(p,
        candidate_barrier=candidate_barrier,log_upper=log_upper,
        nominal_upper_equity=nominal_upper_equity,
        gaussian_steps=gaussian_steps,gaussian_cutoff=gaussian_cutoff)
    new=harmonic_put_component(p,candidate_barrier=candidate_barrier,
                               log_upper=log_upper)
    eps=Fraction(1,10**12)
    prev_hi=Fraction(parent.equity_upper)
    prev_put_ceil=Fraction(parent.put_optional_premium_upper)
    prev_put_floor=max(Fraction(0),prev_put_ceil-eps)
    sharp_put_ceil=Fraction(new.put_premium_upper)
    new_hi=min(prev_hi,prev_hi-prev_put_floor+sharp_put_ceil)
    lower=Fraction(parent.equity_lower)
    if new_hi<lower:
        raise UnresolvedEquityEnvelope('empty improved equity enclosure')
    nominal=_f64(nominal_upper_equity,'nominal_upper_equity')
    budget=max(abs(nominal-lower),abs(new_hi-nominal))
    return TightenedFixedEquity(parent.equity_lower,
        _ceil_decimal(new_hi),_ceil_decimal(budget),parent.equity_upper,
        parent.put_optional_premium_upper,new.put_premium_upper)
