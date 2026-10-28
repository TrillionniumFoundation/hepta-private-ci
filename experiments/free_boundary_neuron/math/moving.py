"""Moving barriers: one exact linear case and a mesh-refined Fortet reference."""

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

from .hitting import hit_readout
from .roots import validate_finite


def linear_boundary_readout(
    initial, intercept, speed, horizon, mu, sigma, *, killing=0.0, discount=0.0
):
    """Exact boundary b(t)=intercept+speed*t, via relative drift mu-speed."""
    return hit_readout(
        np.asarray(intercept) - initial,
        horizon,
        np.asarray(mu) - speed,
        sigma,
        killing=killing,
        discount=discount,
    )


@dataclass(frozen=True)
class MovingBoundaryReference:
    times: np.ndarray
    first_hit_masses: np.ndarray
    probability: float
    discounted_value: float
    negative_mass: float
    mesh: int
    method: str = "Fortet_midpoint_first_event_reference"


def moving_boundary_reference(
    boundary, initial, horizon, mu, sigma, *, killing=0.0, discount=0.0, steps=256
):
    """Numerical first-hit law for a supplied smooth deterministic boundary.

    Solve the triangular midpoint discretization of Fortet's first-passage
    integral equation. This is NOT an exact formula for a curved boundary.
    Compare multiple meshes; inspect negative_mass rather than clipping it.
    Abrupt, discontinuous, state-dependent, and adaptive random boundaries
    require a different solver. Positive initial distance is mandatory.
    """
    validate_finite(
        initial=initial,
        horizon=horizon,
        mu=mu,
        sigma=sigma,
        killing=killing,
        discount=discount,
    )
    if horizon <= 0 or sigma <= 0 or min(killing, discount) < 0:
        raise ValueError("positive horizon/sigma and nonnegative rates required")
    if not isinstance(steps, int) or steps < 8:
        raise ValueError("steps must be an integer at least eight")
    dt = horizon / steps
    times = np.arange(1, steps + 1, dtype=float) * dt
    midpoints = times - 0.5 * dt
    end_barriers = np.asarray(boundary(times), dtype=float)
    mid_barriers = np.asarray(boundary(midpoints), dtype=float)
    start_barrier = float(np.asarray(boundary(np.asarray(0.0))))
    if (
        end_barriers.shape != times.shape
        or mid_barriers.shape != times.shape
        or not np.all(np.isfinite(end_barriers))
        or not np.all(np.isfinite(mid_barriers))
        or not np.isfinite(start_barrier)
    ):
        raise ValueError("boundary must return finite arrays matching its time input")
    if start_barrier <= initial:
        raise ValueError("reference requires strictly positive initial boundary gap")
    tail = ndtr((initial + mu * times - end_barriers) / (sigma * np.sqrt(times)))
    masses = np.zeros(steps)
    for j, time in enumerate(times):
        remaining = time - midpoints[: j + 1]
        kernel = ndtr(
            (mid_barriers[: j + 1] + mu * remaining - end_barriers[j])
            / (sigma * np.sqrt(remaining))
        )
        if kernel[-1] <= np.finfo(float).tiny:
            raise ArithmeticError("Fortet diagonal underflow; refine mesh or rescale")
        masses[j] = (tail[j] - np.dot(masses[:j], kernel[:-1])) / kernel[-1]
    probability = float(np.dot(masses, np.exp(-killing * midpoints)))
    value = float(np.dot(masses, np.exp(-(killing + discount) * midpoints)))
    return MovingBoundaryReference(
        midpoints,
        masses,
        probability,
        value,
        float(-np.minimum(masses, 0).sum()),
        steps,
    )
