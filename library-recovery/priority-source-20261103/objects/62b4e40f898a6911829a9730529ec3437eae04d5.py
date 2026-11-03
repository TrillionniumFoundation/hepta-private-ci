"""Independent finite-horizon Brownian first-hit discount-loss reference.

RESEARCH ONLY: decimal/mpmath quadrature is not directed-rounding certified.
Freeze constant drift/diffusion/barrier for [0,T]. Do not reuse on general
moving boundaries, recurrent whole-network states, or HX self-consistent QVI.

The critical primitive is L=E[(1-exp(-q*tau))1{tau<=T}].  Compute L from
its positive hitting-time density integrand, not from two rounded scalars F-G.
This yields an independently auditable triple (F, G, L).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import mpmath as mp
import numpy as np

Real = Union[str, int, float, mp.mpf]


@dataclass(frozen=True)
class FirstHitTriple:
    first_probability: mp.mpf
    discounted_probability: mp.mpf
    discount_loss: mp.mpf
    precision_dps: int
    method: str = "mpmath-density-plus-independent-reflection; NOT certified intervals"


@dataclass(frozen=True)
class Float32Review:
    allowed: bool
    reason: str
    probability: float | None
    discounted: float | None
    loss: float | None


def _finite(value: Real, name: str) -> mp.mpf:
    if isinstance(value, (bool, complex)):
        raise ValueError(f"{name} must be finite real")
    try:
        value = mp.mpf(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite real") from exc
    if not mp.isfinite(value):
        raise ValueError(f"{name} must be finite real")
    return value


def _normal(z: mp.mpf) -> mp.mpf:
    return mp.erfc(-z / mp.sqrt(2)) / 2


def _cdf(x: mp.mpf, drift: mp.mpf, sigma: mp.mpf, T: mp.mpf) -> mp.mpf:
    denom = sigma * mp.sqrt(T)
    return (_normal((-x-drift*T)/denom)
            + mp.exp(-2*drift*x/sigma**2)*_normal((-x+drift*T)/denom))


def _panels(x: mp.mpf, drift: mp.mpf, sigma: mp.mpf, T: mp.mpf) -> list[mp.mpf]:
    # Stable peak of the inverse-Gaussian hitting-time density.
    mode = 2*x*x / (3*sigma*sigma + mp.sqrt(9*sigma**4 + 4*drift**2*x*x))
    candidates = (mp.mpf(0), T/64, T/16, T/4, mode/4, mode, 4*mode, T)
    return sorted(set(v for v in candidates if 0 <= v <= T))


def first_hit_loss(x: Real, drift: Real, sigma: Real, T: Real, q: Real,
                   *, dps: int = 90) -> FirstHitTriple:
    """Calculate F, G and F-G with independently integrated, positive L.

    A conservative agreement threshold catches many quadrature failures, but
    is a NUMERICAL diagnostic, not a rigorous tail/error enclosure.
    """
    if type(dps) is not int or not 60 <= dps <= 220:
        raise ValueError("dps must be in [60,220]")
    with mp.workdps(dps):
        x, drift, sigma, T, q = (
            _finite(v, name) for v, name in
            zip((x, drift, sigma, T, q), ("x", "drift", "sigma", "T", "q")))
        if sigma <= 0 or x < 0 or T < 0 or q < 0:
            raise ValueError("require x>=0, sigma>0, T>=0, q>=0")
        if x == 0:
            return FirstHitTriple(mp.mpf(1), mp.mpf(1), mp.mpf(0), dps)
        if T == 0:
            return FirstHitTriple(mp.mpf(0), mp.mpf(0), mp.mpf(0), dps)
        if q > 0 and q*T < mp.power(10, -(dps//2)):
            raise ArithmeticError("discount loss below declared precision budget")

        F = _cdf(x, drift, sigma, T)
        if not 0 < F < 1:
            raise ArithmeticError("first-hit mass unresolved at finite precision")
        if q == 0:
            return FirstHitTriple(+F, +F, mp.mpf(0), dps)

        scale = x / (sigma*mp.sqrt(2*mp.pi))
        def density(t: mp.mpf) -> mp.mpf:
            if t <= 0:
                return mp.mpf(0)
            return scale / (t*mp.sqrt(t)) * mp.exp(-(x+drift*t)**2/(2*sigma**2*t))

        panels = _panels(x, drift, sigma, T)
        F_quad = mp.quad(density, panels)
        # Integrate the tiny, positive difference DIRECTLY; never F-G.
        L = mp.quad(lambda t: -mp.expm1(-q*t)*density(t) if t>0 else mp.mpf(0), panels)
        s = mp.sqrt(drift**2 + 2*q*sigma**2)
        G_ref = mp.exp(-(drift+s)*x/sigma**2) * _cdf(x, -s, sigma, T)
        G = F - L

        eps = mp.power(10, -(dps//3))
        if not abs(F_quad-F) < eps*max(F, mp.mpf('1e-30')):
            raise ArithmeticError("independent density CDF does not agree with reflection")
        if not (0 < L < F*(-mp.expm1(-q*T)) and 0 < G < F < 1):
            raise ArithmeticError("discount loss violates necessary physical envelope")
        if not abs(G-G_ref) < eps*max(L, mp.mpf('1e-30')):
            raise ArithmeticError("independent discounted reflection mismatch")
        return FirstHitTriple(+F,+G,+L,dps)


def review_float32(triple: FirstHitTriple) -> Float32Review:
    """Fail closed when independent positive loss collapses after f32 casting.

    This tests only the *output* quantization; not FP32 barrier aliasing,
    fused arithmetic, native GPU implementation, or interval rounding.
    """
    f, g, l = (triple.first_probability, triple.discounted_probability,
               triple.discount_loss)
    with mp.workdps(max(80,triple.precision_dps)):
        if not (all(mp.isfinite(v) for v in (f,g,l))
                and 0 <= l <= f <= 1 and 0 <= g <= f
                and mp.almosteq(f-g,l,rel_eps=mp.mpf('1e-35'), abs_eps=mp.mpf('1e-60'))):
            return Float32Review(False,"INVALID_HIGH_PRECISION_TRIPLE",None,None,None)
        ff,gg,ll=map(lambda v: np.float32(str(v)),(f,g,l))
        if not (all(np.isfinite(v) for v in (ff,gg,ll)) and
                0 <= gg <= ff <= 1 and ll >= 0):
            return Float32Review(False,"INVALID_FLOAT32_PHYSICAL_ORDER",None,None,None)
        if l>0 and (gg==ff or ll==0):
            return Float32Review(False,"POSITIVE_LOSS_ERASED_BY_FLOAT32",float(ff),float(gg),float(ll))
        if 0 < f < 1 and (ff==0 or ff==1):
            return Float32Review(False,"NONTRIVIAL_PROBABILITY_COLLAPSED",float(ff),float(gg),float(ll))
        if l>0 and abs(float(ff)-float(gg)-float(ll)) > max(2*float(np.spacing(ff)),.05*float(ll)):
            return Float32Review(False,"FLOAT32_DIFFERENCE_INCONSISTENT",float(ff),float(gg),float(ll))
        return Float32Review(True,"OUTPUT_CAST_DIAGNOSTIC_ONLY",float(ff),float(gg),float(ll))
