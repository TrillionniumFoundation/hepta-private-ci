"""Recover four stationary He–Xiong coefficients from two controlled quotations.

All cash quantities use the units of the contract. Surface supplies the known
rate, payout, volatility, maturity and liquidity premium. recover returns raw
estimates so that callers can detect infeasible or noise-dominated quotations.
"""
from dataclasses import dataclass
import math

import numpy as np
from scipy.special import log_ndtr, ndtr


@dataclass(frozen=True)
class Surface:
    rate: float
    payout: float
    sigma: float
    maturity: float
    premium: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError("contract rates, maturity and volatility must be finite")
        if min(self.rate, self.payout, self.sigma, self.maturity) <= 0 or self.premium < 0:
            raise ValueError("positive rate, payout, volatility and maturity; nonnegative premium")


def _normal_tail_integral(k, center, width):
    """Integral of exp(-k*y) Phi((center-y)/width) on the positive half-line."""
    z = center / width
    if abs(k) * max(abs(center), width, 1.) < 1e-5:
        cdf = ndtr(z)
        pdf = math.exp(-z*z/2) / math.sqrt(2*math.pi)
        m0 = center*cdf + width*pdf
        m1 = ((center**2 + width**2)*cdf + center*width*pdf) / 2
        m2 = ((center**3 + 3*center*width**2)*cdf
              + (center**2 + 2*width**2)*width*pdf) / 3
        return m0 - k*m1 + k*k*m2/2
    log_a = log_ndtr(z)
    log_b = -k*center + (k*width)**2/2 + log_ndtr(z-k*width)
    if log_b < log_a:
        return math.exp(log_a)*(-math.expm1(log_b-log_a)) / k
    return math.exp(log_b)*math.expm1(log_a-log_b) / k


@dataclass(frozen=True)
class Probe:
    maturity: float
    q: float
    eta: float
    d0: float
    a: float
    g: float
    h: float
    hit_discounted: float

    @classmethod
    def at(cls, surface, margin):
        if not math.isfinite(margin) or margin < 0:
            raise ValueError("probe needs a finite, nonnegative log margin")
        s = surface
        q = s.rate + s.premium
        variance = s.sigma**2
        drift = s.rate - s.payout - variance/2
        width = s.sigma * math.sqrt(s.maturity)
        root = math.hypot(drift, s.sigma*math.sqrt(2*s.rate))
        eta = (root-drift)/variance if drift < 0 else 2*s.rate/(root+drift)
        # delta/(eta-1) = rate/eta + variance/2 by the characteristic equation.
        d0 = s.rate/eta + variance/2

        def kernel(discount):
            speed = math.hypot(drift, s.sigma*math.sqrt(2*discount))
            parts, integrals = [], []
            for signed_speed in (speed, -speed):
                b = (drift+signed_speed)/variance
                center = signed_speed*s.maturity
                parts.append(math.exp(-b*margin + log_ndtr((center-margin)/width)))
                integrals.append(_normal_tail_integral(eta+b, center, width))
            return sum(parts), sum(integrals)

        f, jf = kernel(0.)
        g_x, jg = kernel(q)
        discount = math.exp(-q*s.maturity)
        a = -math.expm1(-q*s.maturity)/eta + discount*jf
        return cls(s.maturity, q, eta, d0, a, jg, discount*f, g_x)

    def recover(self, scales, quotations):
        """Read rows (B, monetary credit loss) at one common log margin."""
        scales = np.asarray(scales, dtype=float)
        y = np.asarray(quotations, dtype=float)
        if scales.shape != (2,) or y.shape != (2, 2):
            raise ValueError("expected two principal scales and two (boundary,loss) rows")
        if not np.isfinite(y).all() or not np.isfinite(scales).all() or min(scales) <= 0:
            raise ValueError("quotations must be finite and principal scales positive")
        ds = scales[1] - scales[0]
        db, dl = y[1] - y[0]
        if ds == 0 or db == 0:
            raise ValueError("two distinguishable principal interventions are required")
        separation = self.h*self.g/self.a - self.hit_discounted
        cash_spread = self.hit_discounted - self.h
        if separation >= 0 or cash_spread <= 0:
            raise ArithmeticError("first-passage kernels are indistinguishable at this precision")

        recovery = self.maturity*(dl/db - self.h*self.d0/self.a) / separation
        den = self.d0 + recovery*self.g/self.maturity
        principal = self.maturity*den*db/(self.a*ds)
        b, loss = y[0]
        coupon_over_q = (self.maturity*loss - self.h*scales[0]*principal
                         + self.hit_discounted*recovery*b) / cash_spread
        coupon = self.q*coupon_over_q
        if coupon == 0:
            raise ValueError("tax cannot be recovered when the calculated coupon is zero")
        after_tax = self.eta*(b*den - (self.a*scales[0]*principal
                                      + (self.g-self.a)*coupon_over_q)/self.maturity)
        return np.array([coupon, principal, recovery, 1-after_tax/coupon])
