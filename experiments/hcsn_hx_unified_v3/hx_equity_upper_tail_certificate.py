"""Outward exact-rational bound on *one component* of HX equity tail error.

For a fixed positive financial default barrier b and positive asset payout
(delta>0), let X_t=log(A_t/b), drift mu=r-delta-sigma^2/2, and tau_0 be
its first zero. The fixed-barrier financial equity is

  V(b exp x) = E_x[int_0^tau0 exp(-r*t)*(delta*b exp(X_t)
                      + B(b exp(X_t);b,T) - C) dt],

  C=(1-tax)*coupon + principal/T.

Let B_inf=coupon/(T*q)+exp(-q*T)*(principal/T-coupon/(T*q)),
H(A)=A+(B_inf-C)/r. For delta>0, exact killed Feynman-Kac yields
  V(b exp x)-H(b exp x) = -H(b)*exp(-k_r*x)
          + E_x[int_0^tau0 exp(-r*t)*(B(A_t)-B_inf)dt].

For lambda>0 (lambda!=r), first-passage Laplace gives
 |B(b exp y)-B_inf| <= D*exp(lambda*T-k_lambda*y),
 D=exp(-qT)*abs(principal/T-coupon/(T*q))
      +abs(recovery*b/T-coupon/(T*q)),
 k_lambda=(mu+sqrt(mu^2+2*lambda*sigma^2))/sigma^2.
The killed exponential resolvent is
 E_x[int_0^tau0 exp(-r*t-k_lambda*X_t)dt]
     = (exp(-k_lambda*x)-exp(-k_r*x))/(r-lambda),
including the lambda>r sign reversal. Thus the certificate bounds the
*continuum fixed-barrier financial-equity upper Dirichlet* discrepancy
from the correct no-default H. All arithmetic for bounds uses Fractions,
integer square-root enclosures and positive Taylor series inequalities.

Only exact binary64 inputs are interpreted; no floating transcendental
computation enters the certificate. This does NOT bound debt PDE errors,
finite-grid/time truncation, coupling, true economic admissibility, model
uncertainty, or precision of a floating-point financial solver.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, isqrt


class UnresolvedEquityTail(ValueError):
    """Unsupported regime or insufficient exact-arithmetic resource budget."""


def _f64(x, name):
    if type(x) not in (float, int):
        raise UnresolvedEquityTail(f'{name}: expected finite binary64 input')
    try:
        f = float(x)
    except (OverflowError, ValueError) as e:
        raise UnresolvedEquityTail(f'{name}: unrepresentable input') from e
    if not isfinite(f) or (type(x) is int and int(f) != x):
        raise UnresolvedEquityTail(f'{name}: unrepresentable input')
    return Fraction.from_float(f)


def _sqrt_enclosure(x, digits):
    if not isinstance(x, Fraction) or x <= 0 or not (24 <= digits <= 60):
        raise UnresolvedEquityTail('invalid positive square-root input')
    q = 10**digits
    z = isqrt((x.numerator * q * q)//x.denominator)
    low = Fraction(z,q)
    high = Fraction(z+1,q)
    if not (low*low <= x <= high*high):
        raise UnresolvedEquityTail('square-root enclosure failed')
    return low, high


def _exp_enclosure(x, terms):
    """For x>=0, rational lower<=exp(x)<=upper from positive Taylor terms."""
    if not isinstance(x,Fraction) or x<0 or x>=terms+2 or not (32<=terms<=256):
        raise UnresolvedEquityTail('exponential argument exceeds Taylor budget')
    total = Fraction(1)
    term = Fraction(1)
    for k in range(1, terms+1):
        term=term*x/k
        total+=term
    following=term*x/(terms+1)
    upper=total+following/(1-x/Fraction(terms+2))
    return total,upper


def _exp_neg_bounds(x, terms):
    lo,hi=_exp_enclosure(x,terms)
    return Fraction(1,1)/hi,Fraction(1,1)/lo


def _kappa_bounds(mu,sigma,rho,digits):
    root_low,root_high=_sqrt_enclosure(mu*mu+2*rho*sigma*sigma,digits)
    kl=(mu+root_low)/(sigma*sigma)
    kh=(mu+root_high)/(sigma*sigma)
    if kl<=0 or kh<=kl:
        raise UnresolvedEquityTail('unresolved strictly positive first-hit exponent')
    return kl,kh


def _power10(k):
    return Fraction(10**k) if k>=0 else Fraction(1,10**(-k))


def _ceil_decimal(value, sig=14):
    """Outward scientific-decimal rounding using exact Fraction operations."""
    if not isinstance(value,Fraction) or value<0 or not 5<=sig<=25:
        raise UnresolvedEquityTail('invalid nonnegative decimal bound')
    if value == 0:
        return '0'
    k = int((value.numerator.bit_length()-value.denominator.bit_length())*.3010299956639812)
    while value < _power10(k): k-=1
    while value >= _power10(k+1): k+=1
    if not -300<=k<=100:
        raise UnresolvedEquityTail('decimal exponent outside finite resource budget')
    scaled=value*_power10(sig-1-k)
    n=(scaled.numerator+scaled.denominator-1)//scaled.denominator
    if n >= 10**sig:
        return f'1e{k+1}'
    return f'{n}e{k-sig+1}'


@dataclass(frozen=True)
class EquityUpperTailCertificate:
    upper_equity_abs_budget: str
    default_component_budget: str
    bond_cashflow_component_budget: str
    selected_lambda: str
    compared_lambdas: int
    taylor_terms: int
    sqrt_decimal_digits: int
    assumption: str = 'fixed financial default barrier; positive payout; exact binary64 parameters'
    coverage: tuple[str,...] = ('continuum equity far-field Dirichlet discrepancy only',)
    uncovered: tuple[str,...] = ('actual PDE debt approximation',
        'spatial and temporal discretization', 'finite-grid rounding',
        'endogenous coupled equilibrium', 'global obstacle admissibility',
        'floating point implementation error')
    input_debt_error_verified: bool = False
    entire_P0_certified: bool = False
    all_scientific_blockers_closed: bool = False
    production_activation: bool = False

    def certify_complete_p0(self):
        raise UnresolvedEquityTail('single boundary error cannot certify full P0')


def certified_equity_farfield_boundary(p, *, candidate_barrier, log_upper,
                                       taylor_terms=64, sqrt_decimal_digits=40):
    """Mathematically bounded one-component budget, conservative and finite.

    The returned upper bound is OUTWARD decimal rounded, unlike simply
    comparing two numerical HX/PDE solvers. Choosing lambda minimizes a set
    of independently valid Chernoff/Laplace bounds; no numerical optimization
    or observed-data filtering enters validity.
    """
    names=('rate','payout','volatility','maturity','principal','coupon',
           'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        a={name:_f64(getattr(p,name),name) for name in names}
    except (AttributeError,TypeError) as exc:
        raise UnresolvedEquityTail('missing or invalid HX fields') from exc
    r=a['rate'];delta=a['payout'];sigma=a['volatility'];T=a['maturity']
    if not (r>0 and delta>0 and sigma>0 and T>0 and a['principal']>0
            and a['coupon']>=0 and 0<=a['tax_shield']<=1
            and 0<=a['recovery']<=1 and a['shock_intensity']>=0
            and 0<=a['sale_fraction']<=1):
        raise UnresolvedEquityTail('invalid domain: payout must be positive')
    b=_f64(candidate_barrier,'candidate_barrier')
    L=_f64(log_upper,'log_upper')
    if not (b>0 and 0<L<=12 and type(taylor_terms) is int
            and 32<=taylor_terms<=256 and type(sqrt_decimal_digits) is int
            and 24<=sqrt_decimal_digits<=60):
        raise UnresolvedEquityTail('unsupported barrier/length/resource budget')
    q=r+a['shock_intensity']*a['sale_fraction']
    base=a['coupon']/T/q
    principal=a['principal']/T
    recovery=a['recovery']*b/T
    const=(1-a['tax_shield'])*a['coupon']+principal
    mu=r-delta-sigma*sigma/2
    disc_max=_exp_neg_bounds(q*T,taylor_terms)[1]
    Hbound=abs(b+(base-const)/r)+disc_max*abs(principal-base)/r
    Dbound=disc_max*abs(principal-base)+abs(recovery-base)
    kr_low,kr_high=_kappa_bounds(mu,sigma,r,sqrt_decimal_digits)
    e_r_low=_exp_neg_bounds(kr_high*L,taylor_terms)[0]
    e_r_high=_exp_neg_bounds(kr_low*L,taylor_terms)[1]
    default=Hbound*e_r_high
    lambdas=(r/4,r/2,2*r,4*r,8*r,16*r,1/T,2/T,4/T)
    best=None
    seen=set()
    for lam in lambdas:
        if lam<=0 or lam==r or lam in seen:
            continue
        seen.add(lam)
        try:
            kl_low,kl_high=_kappa_bounds(mu,sigma,lam,sqrt_decimal_digits)
            e_lam_low=_exp_neg_bounds(kl_high*L,taylor_terms)[0]
            e_lam_high=_exp_neg_bounds(kl_low*L,taylor_terms)[1]
            if lam<r:
                diff_upper=max(Fraction(0),e_lam_high-e_r_low)
            else:
                diff_upper=max(Fraction(0),e_r_high-e_lam_low)
            e_lam_t_max=_exp_enclosure(lam*T,taylor_terms)[1]
            candidate=Dbound*e_lam_t_max*diff_upper/abs(r-lam)
            if best is None or candidate<best[0]:
                best=(candidate,lam)
        except UnresolvedEquityTail:
            continue
    if best is None:
        raise UnresolvedEquityTail('no bounded admissible Laplace exponent')
    cashflow,lambda_used=best
    total=default+cashflow
    if not (total>0 and len(seen)>0):
        raise UnresolvedEquityTail('unresolved upper equity uncertainty')
    return EquityUpperTailCertificate(_ceil_decimal(total),_ceil_decimal(default),
        _ceil_decimal(cashflow),_ceil_decimal(lambda_used),len(seen),
        taylor_terms,sqrt_decimal_digits)
