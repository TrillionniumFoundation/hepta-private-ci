"""Identify stationary coupon, principal, recovery and tax using four boundaries."""
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]/"contract_inverse"))
from contract_inverse import Probe


def from_boundaries(surface, maturities, scales, walls):
    """walls[i,j] is the boundary for maturity i and principal multiplier j.

    Only the rate, payout, volatility and premium of surface enter. Absolute
    currency and time units must agree across the four quotations.
    """
    m = np.asarray(maturities,dtype=float)
    s = np.asarray(scales,dtype=float)
    b = np.asarray(walls,dtype=float)
    if m.shape!=(2,) or s.shape!=(2,) or b.shape!=(2,2):
        raise ValueError("two maturities, two principal scales and four boundaries required")
    if not all(np.all(np.isfinite(z)) and np.min(z)>0 for z in (m,s,b)):
        raise ValueError("positive finite maturities, scales and boundaries required")
    if m[1]==m[0] or s[1]==s[0]:
        raise ValueError("each pair of experimental settings must be distinguishable")
    slopes = (b[:,1]-b[:,0])/(s[1]-s[0])
    if min(slopes)<=0:
        raise ValueError("boundaries must increase with principal in both regimes")
    offsets = b[:,0]-slopes*s[0]
    p = [Probe.at(replace(surface,maturity=t),0.) for t in m]
    a = np.array([v.a for v in p])
    g = np.array([v.g for v in p])
    hit_weight = g/m
    liquid_cost = (a-g)/m
    if hit_weight[0]==hit_weight[1] or liquid_cost[0]==liquid_cost[1]:
        raise ArithmeticError("maturity exposures indistinguishable at working precision")

    u = a/(m*slopes)
    recovery_over_principal = (u[1]-u[0])/(hit_weight[1]-hit_weight[0])
    intercept = u[0]-recovery_over_principal*hit_weight[0]
    if intercept<=0:
        raise ValueError("no positive principal can match these boundaries")
    principal = p[0].d0/intercept
    recovery = principal*recovery_over_principal
    v = offsets*(p[0].d0+recovery*hit_weight)
    coupon_over_q = (v[1]-v[0])/(liquid_cost[0]-liquid_cost[1])
    coupon = p[0].q*coupon_over_q
    if coupon==0:
        raise ValueError("tax is unidentified at zero recovered coupon")
    after_tax = p[0].eta*(v[0]+liquid_cost[0]*coupon_over_q)
    return np.array([coupon,principal,recovery,1.-after_tax/coupon])
