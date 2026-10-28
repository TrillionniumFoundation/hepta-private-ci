"""Finite-window first-passage values, distinct from terminal Gaussian tails.

All functions broadcast numpy inputs. `gap` means barrier minus current state.
An already crossed barrier (gap < 0) has probability one and exterior gradient
zero; gap == 0 uses the derivative approached from the continuation region.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import erfcx, log_ndtr

from .roots import root_arrays


@dataclass(frozen=True)
class HitReadout:
    """A physical competing-risk probability and a separately discounted value."""

    probability: np.ndarray
    discounted_value: np.ndarray
    probability_dv: np.ndarray
    discounted_value_dv: np.ndarray


def _mills_terms(x):
    """Normal Mills ratio and 1-x*Mills(x), avoiding large-x subtraction."""
    mills = math.sqrt(math.pi / 2.0) * erfcx(x / math.sqrt(2.0))
    safe = np.maximum(x, 16.0)
    inverse_square = 1.0 / safe**2
    # Alternating asymptotic series, error < 3e-12 relative at x=16.
    coefficients = (1.0, -3.0, 15.0, -105.0, 945.0, -10395.0, 135135.0, -2027025.0)
    polynomial = np.zeros_like(x)
    for coefficient in reversed(coefficients):
        polynomial = coefficient + inverse_square * polynomial
    complement = np.where(x >= 16.0, inverse_square * polynomial, 1.0 - x * mills)
    return mills, complement


def hit_probability_and_gradient(gap, horizon, mu, sigma, *, rate=0.0):
    """Return E[exp(-rate*tau) 1(tau<=T)] and its initial-state derivative.

    `rate` may be killing, discount, or their sum. The returned scalar is a
    physical probability only when rate is a physical independent killing
    hazard. Rates do not model a restart after cancellation.

    Strictly positive horizon is required; the boundary/time-zero corner has
    no single finite derivative. This function is an exact frozen linear-
    diffusion/barrier operator, not a moving-boundary approximation claim.
    """
    gap, horizon, mu, sigma, rate = np.broadcast_arrays(
        *[np.asarray(x, dtype=float) for x in (gap, horizon, mu, sigma, rate)]
    )
    if not np.all(np.isfinite(gap)) or not np.all(np.isfinite(horizon)):
        raise ValueError("gap and horizon must be finite")
    if np.any(horizon <= 0):
        raise ValueError("horizon must be strictly positive")
    delta, kappa, gamma_plus = root_arrays(mu, sigma, rate)
    d = np.maximum(gap, 0.0)
    scale = sigma * np.sqrt(horizon)
    a = (d + delta * horizon) / scale
    z = (delta * horizon - d) / scale
    log_first = -kappa * d + log_ndtr(z)
    log_second = gamma_plus * d + log_ndtr(-a)
    value = np.exp(np.logaddexp(log_first, log_second))
    value = np.minimum(value, 1.0)  # Only floating-point boundary overshoot.
    mills, complement = _mills_terms(a)
    common_log = -0.5 * ((d - mu * horizon) / scale) ** 2 - rate * horizon
    common = np.exp(common_log) / math.sqrt(2.0 * math.pi)
    # Positive decomposition; avoids subtracting two almost equal large terms.
    derivative = kappa * value + 2.0 * common / scale * (complement + d / scale * mills)
    value = np.where(gap <= 0, 1.0, value)
    derivative = np.where(gap < 0, 0.0, derivative)
    if not np.all(np.isfinite(value)) or not np.all(np.isfinite(derivative)):
        raise OverflowError("first-passage evaluation exceeds numeric range")
    return value, derivative


def hit_readout(gap, horizon, mu, sigma, *, killing=0.0, discount=0.0):
    """Keep observed event probability separate from a discounted value."""
    if np.any(np.asarray(discount) < 0) or not np.all(np.isfinite(discount)):
        raise ValueError("discount must be finite and nonnegative")
    probability, probability_dv = hit_probability_and_gradient(
        gap, horizon, mu, sigma, rate=killing
    )
    value, value_dv = hit_probability_and_gradient(
        gap, horizon, mu, sigma, rate=np.asarray(killing) + discount
    )
    return HitReadout(probability, value, probability_dv, value_dv)


def fpt_density(time, gap, mu, sigma):
    """Unkilled first-passage density, including defective negative-drift law."""
    time, gap, mu, sigma = np.broadcast_arrays(
        *[np.asarray(x, dtype=float) for x in (time, gap, mu, sigma)]
    )
    if np.any(time <= 0) or np.any(gap <= 0) or np.any(sigma <= 0):
        raise ValueError("time, gap, sigma must be positive")
    if not all(np.all(np.isfinite(x)) for x in (time, gap, mu, sigma)):
        raise ValueError("density inputs must be finite")
    log_density = (
        np.log(gap)
        - np.log(sigma)
        - 0.5 * math.log(2 * math.pi)
        - 1.5 * np.log(time)
        - (gap - mu * time) ** 2 / (2 * sigma**2 * time)
    )
    return np.exp(log_density)


def hit_sensitivities(gap, horizon, mu, sigma, *, rate=0.0):
    """Scalar gradient oracle from analytic first passage-score integrals.

    Returns derivatives in initial state, horizon, drift, noise, and Laplace
    rate, plus the quadrature error estimate. This slower reference remains
    meaningful at zero drift/rate, where differentiating separate roots is
    singular. It is a verification/adapter API, not a vector training kernel.
    """
    value, dv = hit_probability_and_gradient(gap, horizon, mu, sigma, rate=rate)
    if np.ndim(value):
        raise ValueError("hit_sensitivities is a scalar reference")
    if gap <= 0:
        return {
            "initial_state": float(dv),
            "horizon": 0.0,
            "mu": 0.0,
            "sigma": 0.0,
            "rate": 0.0,
            "quadrature_error": 0.0,
        }
    delta = math.hypot(mu, math.sqrt(2 * rate) * sigma)
    mode = (
        2
        * gap
        * gap
        / (3 * sigma * sigma + math.hypot(3 * sigma * sigma, 2 * delta * gap))
    )

    def integrand(t):
        if t <= 0:
            return np.zeros(3)
        density = float(fpt_density(t, gap, mu, sigma)) * math.exp(-rate * t)
        residual = gap - mu * t
        return density * np.array(
            [residual / sigma**2, -1 / sigma + residual**2 / (sigma**3 * t), -t]
        )

    points = [x for x in (0.5 * mode, mode, 2 * mode) if 0 < x < horizon]
    result, error = quad_vec(
        integrand, 0, horizon, points=points, epsabs=1e-11, epsrel=1e-11
    )
    return {
        "initial_state": float(dv),
        "horizon": float(fpt_density(horizon, gap, mu, sigma))
        * math.exp(-rate * horizon),
        "mu": float(result[0]),
        "sigma": float(result[1]),
        "rate": float(result[2]),
        "quadrature_error": float(error),
    }
