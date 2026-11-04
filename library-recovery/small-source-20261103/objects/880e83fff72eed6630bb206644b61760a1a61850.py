"""Focused reproduction of exact #4462 bond_value rounding paths.

This is not a full hcsn checkout. Only bond arithmetic (and no-hit/first-hit
inputs) are modeled, while the standalone oracle supplies F=G=0 explicitly.
"""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class Inputs:
    per_bond_principal: float
    per_bond_coupon: float
    q: float
    recovery: float = 0.0


def parent_coupon(p: Inputs, tau: float, F: float, G: float) -> float:
    qt=p.q*tau
    # Copied from PR #4462 bond_value after first-passage computation.
    if p.per_bond_coupon>0 and math.exp(-qt)==1.0:
        if F!=0.0 or G!=0.0:
            raise ArithmeticError('HX stopped coupon unresolved at unit discount rounding')
        lost=-math.expm1(-qt)
        annuity=tau if qt==0.0 else tau*(lost/qt)
        try:
            value=math.fsum((p.per_bond_principal,
                             -p.per_bond_principal*lost,
                             p.per_bond_coupon*annuity))
        except (OverflowError,ValueError) as exc:
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64') from exc
        if not math.isfinite(value):
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64')
        return value
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(p.recovery-base)*G


def fixed_coupon(p: Inputs, tau: float, F: float, G: float) -> float:
    qt=p.q*tau
    # Strict lower-band refusal threshold: one half of sqrt(binary64 eps),
    # a conservative diagnostic, NOT an interval/rounding guarantee.
    if p.per_bond_coupon>0 and qt<2.0**-26:
        if F!=0.0 or G!=0.0:
            raise ArithmeticError('HX stopped coupon unresolved at small discount product')
        lost=-math.expm1(-qt)
        annuity=tau if qt==0.0 else tau*(lost/qt)
        try:
            value=math.fsum((p.per_bond_principal,
                             -p.per_bond_principal*lost,
                             p.per_bond_coupon*annuity))
        except (OverflowError,ValueError) as exc:
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64') from exc
        if not math.isfinite(value):
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64')
        return value
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(p.recovery-base)*G
