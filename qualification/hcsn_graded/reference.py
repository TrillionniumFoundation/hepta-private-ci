"""Independent continuum first-cycle integrals for the exposed original gaps.

Only 0<=t<delay is supported here. These formulas integrate the original
uniform/exponential/remaining-time laws, not their migrated nodal versions.
"""

import math

import numpy as np
from scipy.special import ndtr


def killed_cycle(time, distance, mu=-0.12, sigma=0.35, discount=0.15):
    t, x = np.broadcast_arrays(
        np.asarray(time, dtype=float), np.asarray(distance, dtype=float)
    )
    safe = np.where(t > 0, t, 1.0)
    scale = sigma * np.sqrt(safe)
    kappa = math.sqrt(mu**2 + 2 * discount * sigma**2)
    first = ndtr((-x - mu * safe) / scale) + np.exp(-2 * mu * x / sigma**2) * ndtr(
        (-x + mu * safe) / scale
    )
    discounted = np.exp((-mu + kappa) * x / sigma**2) * ndtr(
        (-x - kappa * safe) / scale
    ) + np.exp((-mu - kappa) * x / sigma**2) * ndtr((-x + kappa * safe) / scale)
    occupation = (
        -np.expm1(-discount * safe) / discount
        - (discounted - np.exp(-discount * safe) * first) / discount
    )
    return np.stack(
        [np.where(t > 0, v, 0.0) for v in (first, discounted, occupation)], axis=-1
    )


def original_basis(
    time, reset, *, order=128, delay=0.2, mu=-0.12, sigma=0.35, discount=0.15
):
    if not 0 <= time < delay or not (
        abs(mu + 0.12) < 1e-14 and sigma == 0.35 and discount == 0.15
    ):
        raise ValueError(
            "this independent reference is restricted to the original exposed physics and short gaps"
        )
    u, w = np.polynomial.legendre.leggauss(order)
    result = np.zeros((25, 3))
    edges = np.linspace(0, 4.8, 17)
    for cell, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        result[cell] = (
            w
            @ killed_cycle(
                time, left + (right - left) * (u + 1) / 2, mu, sigma, discount
            )
            / 2
        )
    tail = 4.8 + 35.2 * (u + 1) / 2
    result[16] = (
        w
        @ (
            killed_cycle(time, tail, mu, sigma, discount)
            * np.exp(-(tail - 4.8))[:, None]
        )
        * 35.2
        / 2
    )
    result[16, 2] += math.exp(-35.2) * -math.expm1(-discount * time) / discount
    phases = np.linspace(0, delay, 9)
    for cell, (left, right) in enumerate(zip(phases[:-1], phases[1:])):
        stop = min(time, right)
        if stop <= left:
            continue
        release = left + (stop - left) * (u + 1) / 2
        values = killed_cycle(time - release, reset, mu, sigma, discount)
        values[:, 1:] *= np.exp(-discount * release)[:, None]
        result[17 + cell] = w @ values * (stop - left) / (2 * (right - left))
    return result
