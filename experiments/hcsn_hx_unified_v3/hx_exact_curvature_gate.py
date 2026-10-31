"""Exact local necessary-sign audit for the He--Xiong smooth-fit boundary.

For the equity PDE, E(b)=E'(b)=0 gives
    E''(b+) = -2 f(b;b)/(sigma**2*b**2)
    m*f(b;b) = m*delta*b - m*(1-pi)*coupon + alpha*b - principal.
Positive f forces negative local continuation immediately above the boundary
under the stated C2 assumption. Nonpositive f does NOT certify a global
obstacle, equilibrium, neuron, or production eligibility.

All signs use exact rational arithmetic from finite decimal literals; the
finite-decimal I/O budget prevents unbounded rational construction. No input
floats are allowed, because conversion would erase the desired exact sign.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction


@dataclass(frozen=True)
class LocalHXVerdict:
    decision: str
    boundary_cashflow_numerator: int
    boundary_cashflow_denominator: int
    curvature_sign: int
    global_obstacle_certified: bool = False


def _rational(value: str | int, label: str) -> Fraction:
    if type(value) not in (str, int):
        raise ValueError(f'{label} requires a decimal string or integer (not float/bool)')
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f'{label} is not a decimal literal') from exc
    if not d.is_finite() or len(d.as_tuple().digits) > 30:
        raise ValueError(f'{label} outside bounded finite-decimal domain')
    # Decimal(0) has adjusted exponent -999999; zero is allowed where
    # the parameter domain permits it, regardless of its representation.
    if d and abs(d.adjusted()) > 100:
        raise ValueError(f'{label} outside bounded exponent range')
    return Fraction(d)


def check_hx_local_curvature(*, boundary: str | int,
                             dividend_yield: str | int,
                             rollover_fraction: str | int,
                             coupon: str | int,
                             recovery_fraction: str | int,
                             maturity: str | int,
                             principal: str | int,
                             sigma: str | int) -> LocalHXVerdict:
    """REJECT, UNRESOLVED or LOCAL_NECESSARY_ONLY; never a global PASS."""
    b = _rational(boundary, 'boundary')
    delta = _rational(dividend_yield, 'dividend_yield')
    pi = _rational(rollover_fraction, 'rollover_fraction')
    c = _rational(coupon, 'coupon')
    alpha = _rational(recovery_fraction, 'recovery_fraction')
    m = _rational(maturity, 'maturity')
    p = _rational(principal, 'principal')
    s = _rational(sigma, 'sigma')
    if not (b > 0 and delta >= 0 and 0 <= pi <= 1 and c >= 0 and
            0 <= alpha <= 1 and m > 0 and p >= 0 and s > 0):
        raise ValueError('invalid HX boundary cashflow parameters')
    # No fixed-precision arithmetic before the sign check.
    numerator = m*delta*b - m*(1-pi)*c + alpha*b - p
    f = numerator / m
    if numerator > 0:
        decision = 'REJECT_NEGATIVE_LOCAL_CONTINUATION'
        curvature_sign = -1
    elif numerator == 0:
        decision = 'UNRESOLVED_ZERO_CURVATURE'
        curvature_sign = 0
    else:
        decision = 'LOCAL_NECESSARY_ONLY_GLOBAL_UNCERTIFIED'
        curvature_sign = 1
    return LocalHXVerdict(decision, f.numerator, f.denominator, curvature_sign)
