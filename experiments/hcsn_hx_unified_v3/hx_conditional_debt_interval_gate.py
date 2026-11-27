"""Conditional perturbation certificate for a *fixed discrete* HX financial obstacle.

Given a nominal binary64 PDE bond/equity grid and externally supplied absolute
bounds for its interior debt cash flows and its upper equity boundary, this
routine bounds all solutions of the perturbed *finite-dimensional* Bellman
system. It cannot establish that the supplied bounds cover the true HX bond
process, mesh/time discretization, or continuum value. No production admission.

Let T(V)_i=max(0,(qL V_(i-1)+qR V_(i+1)+f_i)/d) with
 d = rate+qL+qR and gamma = (qL+qR)/d < 1.
The nominal residual R = max |V-T(V)|, including exact rationals for supplied
binary64 coefficients and values. If interior cashflow perturbations are <= e
and the upper Dirichlet perturbation is <= u, a conservative value bound is
 E = max(u,(R+(e+qR*u)/d)/(1-gamma)).
Then every true continuation value has difference at most
 D = ((qL+qR)*E+e)/d from the nominal continuation value.
Every return is CONDITIONAL on the *external* input error budgets actually
bounding the perturbed finite problem; the routine cannot certify that premise.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math


class UnresolvedDebtInterval(ValueError):
    """Invalid, unsupported, or numerically noncontractive problem."""


@dataclass(frozen=True)
class ConditionalDecisionCertificate:
    nodes: int
    guaranteed_continue: tuple[int, ...]
    guaranteed_stop: tuple[int, ...]
    ambiguous: tuple[int, ...]
    exact_nominal_residual: Fraction
    sup_value_perturbation: Fraction
    continuation_error_budget: Fraction
    cashflow_abs_budget: Fraction
    upper_equity_abs_budget: Fraction
    contraction: Fraction
    statement: str = 'CONDITIONAL ON SUPPLIED ERRORS; quantized finite grid only'
    continuum_certified: bool = False
    input_error_bounds_verified: bool = False
    scientific_gate_closed: bool = False
    production_activation: bool = False


def _nonnegative_decimal(value: str, name: str) -> Fraction:
    """Never infer a bound from a rounded input float, NaN, or boolean."""
    if type(value) is not str or len(value) > 96:
        raise UnresolvedDebtInterval(f'{name} requires a bounded decimal string')
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise UnresolvedDebtInterval(f'{name} invalid decimal') from exc
    if not d.is_finite() or d < 0 or len(d.as_tuple().digits) > 40:
        raise UnresolvedDebtInterval(f'{name} not a bounded nonnegative decimal')
    if d != 0 and abs(d.adjusted()) > 50:
        raise UnresolvedDebtInterval(f'{name} exponent outside supported domain')
    return Fraction(d)


def _float_exact(value, name: str) -> Fraction:
    if type(value) not in (float, int):
        raise UnresolvedDebtInterval(f'{name} not finite binary64')
    try:
        q = float(value)
    except (ValueError, OverflowError) as exc:
        raise UnresolvedDebtInterval(f'{name} not representable binary64') from exc
    if not math.isfinite(q):
        raise UnresolvedDebtInterval(f'{name} not finite binary64')
    return Fraction.from_float(q)


def conditional_debt_error_gate(p, grid, *, debt_error: str,
                                upper_equity_error: str) -> ConditionalDecisionCertificate:
    """Classify only those grid nodes whose STOP/CONTINUE sign is robust.

    Unknown or merely *measured* PDE-vs-density debt differences are not a
    proved bound on the true financial model. The caller must supply separate
    evidence before interpreting these conditional decisions physically.
    """
    e = _nonnegative_decimal(debt_error, 'debt_error')
    u = _nonnegative_decimal(upper_equity_error, 'upper_equity_error')
    try:
        n = grid.nodes
        b = grid.candidate_barrier
        L = grid.log_upper
        V = grid.equity_values
        debt = grid.debt_values
        params = (p.rate, p.payout, p.volatility, p.principal,
                  p.coupon, p.tax_shield, p.maturity)
    except (TypeError, AttributeError) as exc:
        raise UnresolvedDebtInterval('missing HX finite grid contract') from exc
    if (type(n) is not int or not 33 <= n <= 1025 or not isinstance(V,(list,tuple))
            or not isinstance(debt,(list,tuple)) or len(V) != n or len(debt) != n):
        raise UnresolvedDebtInterval('invalid grid dimensions or resource budget')
    _float_exact(b,'boundary'); _float_exact(L,'log_upper')
    if not (0 < b and 0 < L <= 12):
        raise UnresolvedDebtInterval('invalid fixed financial candidate/domain')
    for name, x in zip(('rate','payout','volatility','principal','coupon',
                        'tax_shield','maturity'),params):
        _float_exact(x,name)
    if not (p.rate > 0 and p.payout >= 0 and p.volatility > 0
            and p.principal > 0 and p.coupon >= 0
            and 0 <= p.tax_shield <= 1 and p.maturity > 0):
        raise UnresolvedDebtInterval('invalid financial domain')
    for i, (v,dv) in enumerate(zip(V,debt)):
        _float_exact(v,f'V[{i}]'); _float_exact(dv,f'debt[{i}]')
    h = L/(n-1)
    drift = p.rate-p.payout-.5*p.volatility**2
    diffusion = .5*(p.volatility/h)**2
    ql = diffusion - drift/(2*h)
    qr = diffusion + drift/(2*h)
    if min(ql,qr) < 0:
        ql = diffusion+max(0.,-drift)/h
        qr = diffusion+max(0.,drift)/h
    d = p.rate + ql + qr
    if not all(math.isfinite(z) and z > 0 for z in (h, ql, qr, d)):
        raise UnresolvedDebtInterval('invalid M-matrix rates')
    F = _float_exact
    left = F(ql,'left jump'); right = F(qr,'right jump')
    den = F(d,'discounted generator')
    gamma = (left+right)/den
    if not (0 <= gamma < 1):
        raise UnresolvedDebtInterval('quantized Bellman not a contraction')
    v = tuple(F(x,f'V[{i}]') for i,x in enumerate(V))
    if v[0] != 0:
        raise UnresolvedDebtInterval('default equity must be zero at lower boundary')
    const = (1-p.tax_shield)*p.coupon+p.principal/p.maturity
    if not math.isfinite(const):
        raise UnresolvedDebtInterval('invalid financial cashflow offset')
    continuations = []
    residual = Fraction(0)
    for i in range(1,n-1):
        asset = b*math.exp(i*h)
        cash = p.payout*asset + debt[i] - const
        cash_f = F(cash,f'cash[{i}]')
        hold = (left*v[i-1]+right*v[i+1]+cash_f)/den
        continuations.append(hold)
        residual = max(residual, abs(v[i]-max(Fraction(0),hold)))
    # In an unknown perturbed grid, cash shifts by at most e and upper
    # Dirichlet by at most u; qR*u is relevant at the final interior row.
    forcing = (e+right*u)/den
    value_bound = max(u, (residual+forcing)/(1-gamma))
    hold_bound = ((left+right)*value_bound+e)/den
    yes = tuple(i+1 for i,c in enumerate(continuations) if c>hold_bound)
    no = tuple(i+1 for i,c in enumerate(continuations) if c<-hold_bound)
    ambiguous = tuple(i+1 for i,c in enumerate(continuations)
                      if -hold_bound<=c<=hold_bound)
    if len(yes)+len(no)+len(ambiguous) != n-2:
        raise UnresolvedDebtInterval('non-partitioned financial grid')
    return ConditionalDecisionCertificate(n,yes,no,ambiguous,residual,
                                          value_bound,hold_bound,e,u,gamma)
