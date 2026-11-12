"""Independent half-line first-hit formulas; no CTMC or DDE code is called."""

import math

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.special import ndtr


def first_excursion(duration, x, mu, sigma, discount):
    t, x = np.broadcast_arrays(
        np.asarray(duration, dtype=float), np.asarray(x, dtype=float)
    )
    if (
        np.any(t < 0)
        or np.any(x < 0)
        or not np.isfinite(t).all()
        or not np.isfinite(x).all()
    ):
        raise ValueError("nonnegative finite continuum arguments required")
    safe = np.where(t > 0, t, 1.0)
    q = discount
    scale = sigma * np.sqrt(safe)
    k = math.sqrt(mu * mu + 2 * q * sigma * sigma)
    f = ndtr((-x - mu * safe) / scale) + np.exp(-2 * mu * x / sigma**2) * ndtr(
        (-x + mu * safe) / scale
    )
    g = np.exp((-mu + k) * x / sigma**2) * ndtr((-x - k * safe) / scale) + np.exp(
        (-mu - k) * x / sigma**2
    ) * ndtr((-x + k * safe) / scale)
    active = -np.expm1(-q * safe) / q - (g - np.exp(-q * safe) * f) / q
    return np.stack([np.where(t > 0, v, 0.0) for v in (f, g, active)], axis=-1)


def basis(model, duration, *, order=128):
    """Original 16 uniform cells, exponential tail, 8 phase cells.

    Fixed source domain only. Tail beyond x=40 has exp(-35.2) mass; its
    active occupation is included and its negligible hits are omitted.
    """
    if not 0 <= duration <= min(0.2, model.delay):
        raise ValueError("reference is a short-gap first-excursion calculation")
    u, w = leggauss(order)
    physics = (model.spatial.mu, model.spatial.sigma, model.discount)
    result = []
    edges = np.linspace(0, 4.8, 17)
    for left, right in zip(edges[:-1], edges[1:]):
        x = left + (right - left) * (u + 1) / 2
        result.append(w @ first_excursion(duration, x, *physics) / 2)
    x = 4.8 + 35.2 * (u + 1) / 2
    tail = (
        w
        @ (first_excursion(duration, x, *physics) * np.exp(-(x - 4.8))[:, None])
        * 35.2
        / 2
    )
    tail[2] += (
        math.exp(-35.2) * -math.expm1(-model.discount * duration) / model.discount
    )
    result.append(tail)
    edges = np.linspace(0, model.delay, 9)
    for left, right in zip(edges[:-1], edges[1:]):
        stop = min(right, duration)
        if stop <= left:
            result.append(np.zeros(3))
            continue
        release = left + (stop - left) * (u + 1) / 2
        value = first_excursion(duration - release, model.reset, *physics)
        value[:, 1:] *= np.exp(-model.discount * release)[:, None]
        result.append(w @ value * (stop - left) / (2 * (right - left)))
    return np.asarray(result)
