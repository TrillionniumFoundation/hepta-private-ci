"""Independent conservative HX *equity* far-field enclosure, research-only.

For a FIXED positive absorbing financial default barrier b, the Brownian GBM
asset follows dA=(r-delta)A dt+sigma A dW until default; stockholders may
exercise at any stopping time no later than first hitting b, with zero
exercise/default payoff. Their running cashflow is

    delta*A + B(A,T) - C,   C=(1-tax)*coupon + principal/T.

HX finite-maturity debt has nonnegative cashflow coupon/T under discount
q=r+shock_intensity*sale_fraction, positive terminal principal/T and
positive recovery*b/T at default. The comparison principle gives

    m <= B(A,T) <= M,
    m=min(coupon/(Tq),principal/T,recovery*b/T),
    M=max(coupon/(Tq),principal/T,recovery*b/T).

When delta>0, discounted ex-dividend asset plus dividend integral is a
martingale and the remaining e^{-rt} A_t expectation vanishes at infinity.
The feasible hold-to-default strategy and the bound on every stopping rule
therefore imply, for all A>=b,

  max(0, A-b-max(C-m,0)/r) <= V_opt(A)
  V_opt(A) <= A+max(M-C,0)/r.

The upper bound is deliberately loose. A precise log-boundary interval is
formed using rational finite-Taylor bounds for exp(L), not rounded math.exp.
The resulting rational error budget encloses the difference between the
user-supplied nominal upper equity Dirichlet and the *continuum optimal-
stopping* equity for that fixed barrier. No claim of optimal barrier,
financial equilibrium, full obstacle, debt PDE mesh/time error, or complete
P0-P5 admission. delta=0 is refused (transversality requires separate proof).
"""
from dataclasses import dataclass
from fractions import Fraction
import math


class UnresolvedEquityEnvelope(ValueError):
    """Unsupported, unchecked, nonphysical or resource-exhaustive domain."""


def _f64(x, name: str) -> Fraction:
    if type(x) not in (float, int):
        raise UnresolvedEquityEnvelope(f'{name}: exact binary64 scalar required')
    try:
        y = float(x)
    except (ValueError, OverflowError) as e:
        raise UnresolvedEquityEnvelope(f'{name}: not finite binary64') from e
    if not math.isfinite(y) or abs(y) > 1e12 or (type(x) is int and int(y) != x):
        raise UnresolvedEquityEnvelope(f'{name}: unsupported physical/resource range')
    return Fraction.from_float(y)


def _exp_interval_positive(x: Fraction, *, terms: int) -> tuple[Fraction, Fraction]:
    """EXACT rational positive series with geometric upper remainder."""
    if not isinstance(x, Fraction) or not 0 < x <= 12:
        raise UnresolvedEquityEnvelope('log upper must be in (0,12]')
    if type(terms) is not int or not (64 <= terms <= 160):
        raise UnresolvedEquityEnvelope('Taylor work budget outside 64..160')
    s = Fraction(1)
    t = Fraction(1)
    for k in range(1,terms+1):
        t = t*x/k
        s += t
    next_term = t*x/(terms+1)
    ratio = x/Fraction(terms+2)
    if ratio >= 1:
        raise UnresolvedEquityEnvelope('Taylor remainder ratio >=1')
    return s, s+next_term/(1-ratio)


def _ceil_decimal(x: Fraction, *, places: int = 12) -> str:
    """Exact upward round; intended for #4508 external decimal-string input."""
    if not isinstance(x, Fraction) or x < 0 or type(places) is not int or not 1 <= places <= 16:
        raise UnresolvedEquityEnvelope('unsupported decimal bound')
    if x > 10**20:
        raise UnresolvedEquityEnvelope('unusable equity boundary budget magnitude')
    scale = 10**places
    ceil_int = (x.numerator*scale+x.denominator-1)//x.denominator
    whole, fract = divmod(ceil_int,scale)
    return f'{whole}.{fract:0{places}d}'


def _floor_decimal(x: Fraction, *, places: int = 12) -> str:
    """Exact downward rounding of a nonnegative lower enclosure endpoint."""
    if not isinstance(x, Fraction) or x < 0 or type(places) is not int or not 1 <= places <= 16:
        raise UnresolvedEquityEnvelope('unsupported decimal lower bound')
    if x > 10**20:
        raise UnresolvedEquityEnvelope('unusable equity lower endpoint magnitude')
    scale = 10**places
    floor_int = (x.numerator*scale)//x.denominator
    whole, fract = divmod(floor_int,scale)
    return f'{whole}.{fract:0{places}d}'


@dataclass(frozen=True)
class FixedBarrierEquityEnvelope:
    log_upper: float
    barrier: float
    nominal_upper_equity: float
    asset_lower: str
    asset_upper: str
    equity_lower: str
    equity_upper: str
    upper_equity_abs_budget: str
    bond_lower: str
    bond_upper: str
    taylor_terms: int
    # This specifically encloses the specified optimal-stopping financial
    # equity boundary. It is NOT a full validated input pair for #4508.
    boundary_model: str = 'killed GBM fixed-barrier equity optimal stopping, positive payout'
    arithmetic: str = 'exact rational for supplied binary64 parameters; Taylor remainder enclosed'
    uncovered: tuple[str,...] = (
        'financial free-barrier self-consistency',
        'continuum all-state obstacle and nonlocal regeneration',
        'bond PDE spatial/time discretization and roundoff',
        'stochastic parameter calibration error',
        'FP32/BF16 finance gradients and Rust/GPU performance')
    complete_debt_error_budget: bool = False
    global_equilibrium_certified: bool = False
    scientific_gate_closed: bool = False
    production_activation: bool = False

    def to_complete_p0_certificate(self):
        raise UnresolvedEquityEnvelope('equity Dirichlet alone is not coupled HX proof')


def fixed_barrier_equity_upper_envelope(p, *, candidate_barrier: float,
                                        log_upper: float,
                                        nominal_upper_equity: float,
                                        taylor_terms: int=96) -> FixedBarrierEquityEnvelope:
    """Proof-carrying *loose* upper equity boundary budget for fixed b.

    Floats are interpreted as their exact binary64 values. This certificate
    does not make any assertion about how candidate_barrier was obtained.
    It cannot be used as total P0 or total debt-error certification.
    """
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        a={n:_f64(getattr(p,n),n) for n in fields}
    except AttributeError as e:
        raise UnresolvedEquityEnvelope('missing HX field') from e
    r=a['rate']; delta=a['payout']; sigma=a['volatility']; T=a['maturity']
    if not (r>0 and delta>0 and sigma>0 and T>0 and a['principal']>0
            and a['coupon']>=0 and a['shock_intensity']>=0
            and 0<=a['sale_fraction']<=1 and 0<=a['tax_shield']<=1
            and 0<=a['recovery']<=1):
        raise UnresolvedEquityEnvelope('unsupported HX domain: delta must be >0')
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    guess=_f64(nominal_upper_equity,'nominal_upper_equity')
    if not b>0:
        raise UnresolvedEquityEnvelope('barrier must be positive')
    e_lo,e_hi=_exp_interval_positive(L,terms=taylor_terms)
    A_lo,A_hi=b*e_lo,b*e_hi
    if A_hi>10**20:
        raise UnresolvedEquityEnvelope('unrepresentable financial upper asset budget')
    q=r+a['shock_intensity']*a['sale_fraction']
    c=a['coupon']/T
    par=a['principal']/T
    recovery=a['recovery']*b/T
    m=min(c/q,par,recovery)
    M=max(c/q,par,recovery)
    C=(1-a['tax_shield'])*a['coupon']+par
    low=max(Fraction(0),A_lo-b-max(C-m,Fraction(0))/r)
    high=A_hi+max(M-C,Fraction(0))/r
    if high<low:
        raise UnresolvedEquityEnvelope('invalid stockholder value envelope')
    u=max(abs(guess-low),abs(high-guess))
    return FixedBarrierEquityEnvelope(
        float(log_upper),float(candidate_barrier),float(nominal_upper_equity),
        _floor_decimal(A_lo),_ceil_decimal(A_hi),
        _floor_decimal(low),_ceil_decimal(high),_ceil_decimal(u),
        _floor_decimal(m),_ceil_decimal(M),taylor_terms)
