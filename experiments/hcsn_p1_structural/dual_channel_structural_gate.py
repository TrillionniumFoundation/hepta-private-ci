"""Research-only HCSN dual-channel structural-identifiability and first-hit oracle.

NO_GO: the simplified one-shot perpetual stop solution is not original coupled
He-Xiong financial debt/equity and is not an independently validated neuron.
Normalized Call, Put, and safety margin are functions solely of V/K for fixed
r, delta, sigma. They do not produce three independent physical coordinates.
"""
from __future__ import annotations

import math
from typing import NamedTuple

from scipy.integrate import quad
from scipy.special import log_ndtr, logsumexp
import torch


class Refusal(ValueError):
    """Scientific/domain admission is denied rather than silently corrected."""


class Channels(NamedTuple):
    call: torch.Tensor
    put: torch.Tensor
    margin: torch.Tensor
    boundary: torch.Tensor
    call_normalized: torch.Tensor
    put_normalized: torch.Tensor


def _params(r: float, delta: float, sigma: float) -> None:
    if not (all(type(x) in (float, int) and math.isfinite(x)
                for x in (r, delta, sigma)) and
            0.001 <= r <= 0.30 and 0.001 <= delta <= 0.20 and
            0.01 <= sigma <= 1.0):
        raise Refusal('Unsupported bounded one-shot GBM parameters')


def power_boundary(r: float, delta: float, sigma: float):
    _params(r, delta, sigma)
    q = r - delta - 0.5 * sigma * sigma
    disc = math.hypot(q, math.sqrt(2 * r * sigma * sigma))
    beta = 2 * r / (disc - q) if q < 0 else (disc + q) / (sigma * sigma)
    if not (math.isfinite(beta) and beta > 0):
        raise Refusal('Invalid r-harmonic power')
    return beta, beta / (1 + beta)


def channels(v: torch.Tensor, k: torch.Tensor, *,
             r: float = 0.05, delta: float = 0.03,
             sigma: float = 0.2) -> Channels:
    """Autodifferentiable f64 scalar/same-shaped channels; parameter domain guarded.

    Exposes both raw values and normalized features, without pretending that
    normalized features preserve absolute V/K common-mode scale information.
    """
    beta, ratio = power_boundary(r, delta, sigma)
    if not (isinstance(v, torch.Tensor) and isinstance(k, torch.Tensor)
            and v.shape == k.shape and v.dtype == k.dtype == torch.float64
            and v.device.type == k.device.type == 'cpu'
            and v.numel() > 0 and torch.isfinite(v).all().item()
            and torch.isfinite(k).all().item()
            and torch.all(v > 0).item() and torch.all(k > 0).item()
            and torch.all(v < 1e8).item() and torch.all(k < 1e8).item()):
        raise Refusal('Expected positive finite same-shaped CPU f64 V,K')
    b = ratio * k
    m = torch.log(v / b)
    # The continuation closed form is b[expm1(m) + expm1(-beta*m)/beta].
    # Direct summation cancels at small m; the m**2 Taylor is local, guarded.
    # Do not evaluate an unselected stop-region exponential: for high beta
    # it could overflow and poison reverse-mode with 0*inf -> NaN.
    m_safe = torch.where(m > 0, m, torch.zeros_like(m))
    near = (m_safe < 1e-4) & (beta * m_safe < 1e-3)
    stable = b * (m_safe.square() * ((1 + beta) / 2 +
                 (1 - beta * beta) * m_safe / 6 +
                 (1 + beta ** 3) * m_safe.square() / 24 +
                 (1 - beta ** 4) * m_safe.pow(3) / 120))
    direct = b * (torch.expm1(m_safe) + torch.expm1(-beta * m_safe) / beta)
    call = torch.where(m > 0, torch.where(near, stable, direct),
                       torch.zeros_like(v))
    put = torch.where(m > 0, (k - b) * torch.exp(-beta * m_safe), k - v)
    if not (torch.isfinite(call).all().item() and
            torch.isfinite(put).all().item()):
        raise Refusal('Nonfinite output; candidate cannot be admitted')
    return Channels(call, put, m, b, call / k, put / k)


def first_hit_probability(v: float, b: float, horizon: float, *,
                          r: float = 0.05, delta: float = 0.03,
                          sigma: float = 0.2) -> float:
    """Constant-boundary GBM P(tau_b<=T), not default Put value.

    Numerically stabilized reflection formula, not a financial coupled
    endogenous-boundary proof. No derivative of physical FIRE event time.
    """
    _params(r, delta, sigma)
    if not (all(type(z) in (float, int) and math.isfinite(z)
                for z in (v, b, horizon)) and v > 0 and b > 0
            and 0 < horizon <= 100 and max(v, b) < 1e8):
        raise Refusal('Invalid first-hit probability inputs')
    if v <= b:
        return 1.0
    m = math.log(v / b)
    nu = r - delta - 0.5 * sigma * sigma
    den = sigma * math.sqrt(horizon)
    x = (-m - nu * horizon) / den
    y = (-m + nu * horizon) / den
    log_probability = float(logsumexp((log_ndtr(x),
                              -2 * nu * m / (sigma * sigma) + log_ndtr(y))))
    p = math.exp(log_probability)
    if not (-5e-13 <= p <= 1 + 5e-13):
        raise Refusal('Probability outside physically valid [0,1]')
    return min(1., max(0., p))


def independent_first_hit_density_integral(v: float, b: float,
                                            horizon: float, *,
                                            r: float = 0.05,
                                            delta: float = 0.03,
                                            sigma: float = 0.2) -> tuple[float,float]:
    """Independent inverse-Gaussian first-passage density quadrature.

    It never calls the reflection-CDF first_hit_probability implementation.
    The returned absolute quad-error estimate is not a rigorous interval.
    """
    _params(r, delta, sigma)
    if not (0 < b < v < 1e8 and 0 < horizon <= 100):
        raise Refusal('Only positive strictly-above-barrier density integration')
    m = math.log(v / b)
    nu = r - delta - 0.5 * sigma * sigma
    def density(t):
        if t <= 0:
            return 0.
        log_f = (math.log(m) - math.log(sigma) - 0.5 * math.log(2*math.pi)
                 - 1.5 * math.log(t)
                 - ((m + nu*t)**2)/(2*sigma*sigma*t))
        return math.exp(log_f) if log_f > -744 else 0.
    val, err = quad(density, 0., horizon,
                    epsabs=3e-12, epsrel=2e-12, limit=250)
    return val, err
