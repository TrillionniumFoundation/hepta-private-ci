"""Stable real characteristic roots and analytic parameter derivatives."""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class DiffusionRoots:
    """Backward positive root kappa and forward roots gamma_plus/minus."""

    delta: float
    kappa: float
    gamma_plus: float
    gamma_minus: float
    kappa_derivatives: dict[str, float]


def root_arrays(mu, sigma, rate):
    """Broadcast roots; rate is a nonnegative Laplace rate, not a reset rate.

    The zero-drift/zero-rate root is defined by continuity. Its rate derivative
    is singular, which the scalar derivative API reports explicitly.
    """
    mu, sigma, rate = np.broadcast_arrays(
        np.asarray(mu, dtype=float),
        np.asarray(sigma, dtype=float),
        np.asarray(rate, dtype=float),
    )
    if not all(np.all(np.isfinite(x)) for x in (mu, sigma, rate)):
        raise ValueError("diffusion parameters must be finite")
    if np.any(sigma <= 0) or np.any(rate < 0):
        raise ValueError("sigma must be positive and rate nonnegative")
    delta = np.hypot(mu, math.sqrt(2.0) * np.sqrt(rate) * sigma)
    if not np.all(np.isfinite(delta)):
        raise OverflowError("diffusion discriminant exceeds floating-point range")
    positive_denom = 0.5 * delta + 0.5 * mu
    negative_denom = 0.5 * delta - 0.5 * mu
    small_k = np.divide(
        rate, positive_denom, out=np.zeros_like(rate), where=positive_denom > 0
    )
    small_g = np.divide(
        rate, negative_denom, out=np.zeros_like(rate), where=negative_denom > 0
    )
    kappa = np.where(mu >= 0, small_k, (delta / sigma - mu / sigma) / sigma)
    gamma_plus = np.where(mu <= 0, small_g, (delta / sigma + mu / sigma) / sigma)
    if not all(np.all(np.isfinite(x)) for x in (kappa, gamma_plus)):
        raise OverflowError("characteristic root exceeds floating-point range")
    return delta, kappa, gamma_plus


def stable_roots(mu: float, sigma: float, rate: float) -> DiffusionRoots:
    """Return roots and d(kappa)/d(mu,sigma,rate), preserving cancellation.

    A derivative of infinity at mu=rate=0 is an explicit mathematical
    singularity, not a finite trainable gradient.
    """
    delta, kappa, gp = (float(x) for x in root_arrays(mu, sigma, rate))
    derivatives = (
        {"mu": math.nan, "sigma": 0.0, "rate": math.inf}
        if delta == 0
        else {
            "mu": -kappa / delta,
            "sigma": -kappa * (sigma * kappa / delta),
            "rate": 1.0 / delta,
        }
    )
    return DiffusionRoots(delta, kappa, gp, -kappa, derivatives)


def validate_finite(**values):
    """Shared scalar input validation, including quantities with physical units."""
    if not all(math.isfinite(float(v)) for v in values.values()):
        raise ValueError("parameters must be finite: " + ", ".join(values))
