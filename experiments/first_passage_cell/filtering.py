"""Finite-grid belief projection for one absorbing cycle, with an event atom.

This is a positive, mass-conserving approximation, not an exact Gaussian filter.
Missing event observations retain both alive mass and an absorbing event atom.
Reset after an observed event belongs to the cell runtime, not this filter.
"""

from enum import Enum

import numpy as np
from scipy.special import logsumexp

from .kernels import first_passage, killed_cdf


class EventObservation(str, Enum):
    OBSERVED_SURVIVAL = "observed_survival"
    OBSERVED_EVENT = "observed_event"
    MISSING = "missing"


def _grid(grid):
    g = np.asarray(grid, dtype=np.float64)
    if (g.ndim != 1 or len(g) < 3 or len(g) > 512
            or not np.all(np.isfinite(g)) or np.any(g <= 0)
            or np.any(np.diff(g) <= 0)):
        raise ValueError("Grid must contain 3..512 strictly increasing positive points")
    return g


def killed_transition_matrix(grid, mu, sigma, horizon):
    """Substochastic matrix between midpoint bins, with infinite final bin.

    Each row sums to its analytic survival probability. Propagating atom masses
    at grid points is an explicit spatial projection and does not preserve the
    continuous semigroup exactly.
    """
    g = _grid(grid)
    if not np.isfinite(horizon) or horizon < 0:
        raise ValueError("Finite nonnegative horizon required")
    if horizon == 0:
        first_passage(g, mu, sigma, 0.0)
        return np.eye(len(g))
    edges = np.r_[0.0, (g[:-1] + g[1:]) / 2.0, np.inf]
    cdf = killed_cdf(g[:, None], edges[None, :], mu, sigma, horizon)
    matrix = np.diff(cdf, axis=1)
    if np.any(matrix < -2e-12):
        raise ArithmeticError("Killed CDF monotonicity lost")
    matrix = np.maximum(matrix, 0.0)
    survival = first_passage(g, mu, sigma, horizon)["S"]
    sums = matrix.sum(axis=1)
    if np.max(np.abs(sums - survival)) > 5e-12:
        raise ArithmeticError("Killed transition mass does not match survival")
    # Roundoff-only row reconciliation; rows with underflowed mass stay zero.
    scale = np.divide(survival, sums, out=np.ones_like(sums), where=sums > 0)
    return matrix * scale[:, None]


def survival_filter(grid, prior_mass, mu, sigma, horizon, *, event_observation,
                    prior_event_mass=0.0, sensor=None, tail_mass_limit=1.0):
    """Advance an absorbing belief and condition only on actual observations.

    OBSERVED_EVENT means the current cycle is known to have been absorbed by
    the observation time, including prior_event_mass; it is not a newly timed
    crossing in this interval. Exact new-event timestamps use the FPT density.
    prior_mass is live probability mass at the grid points, not density; together
    with prior_event_mass it must sum to one. sensor is (value, noise_variance),
    and is accepted only with observed_survival, where a live-state measurement
    has a declared Gaussian likelihood. Missing sensors are represented by None.
    tail_mass_limit optionally rejects excessive mass in the final unbounded bin.
    """
    g = _grid(grid)
    prior = np.asarray(prior_mass, dtype=np.float64)
    if (prior.shape != g.shape or not np.all(np.isfinite(prior))
            or np.any(prior < 0) or not np.isfinite(prior_event_mass)
            or not 0 <= prior_event_mass <= 1
            or abs(prior.sum() + prior_event_mass - 1.0) > 1e-10):
        raise ValueError("Prior live and event masses must be nonnegative and sum to one")
    try:
        observation = EventObservation(event_observation)
    except (ValueError, TypeError) as exc:
        raise ValueError("Explicit survival/event/missing observation required") from exc
    if not np.isfinite(tail_mass_limit) or not 0 <= tail_mass_limit <= 1:
        raise ValueError("Tail mass limit must lie in [0,1]")
    if sensor is not None and observation is not EventObservation.OBSERVED_SURVIVAL:
        raise ValueError("A live sensor likelihood requires explicit observed_survival")
    transition = killed_transition_matrix(g, mu, sigma, horizon)
    alive = prior @ transition
    surviving = float(alive.sum())
    hit = first_passage(g, mu, sigma, horizon)["F"]
    event = min(1.0, max(0.0, prior_event_mass + float(prior @ hit)))
    tail = float(alive[-1])
    if tail > tail_mass_limit + 1e-12:
        raise ValueError("Grid tail projection exceeds its declared mass limit")
    if observation is EventObservation.MISSING:
        evidence, log_likelihood = 1.0, 0.0
    elif observation is EventObservation.OBSERVED_EVENT:
        if event <= 0:
            raise ValueError("Observed event has zero probability under this belief")
        evidence, log_likelihood = event, float(np.log(event))
        alive, event = np.zeros_like(alive), 1.0
    else:
        if surviving <= 0:
            raise ValueError("Observed survival has zero representable probability")
        evidence, log_likelihood = surviving, float(np.log(surviving))
        alive, event = alive / surviving, 0.0
        if sensor is not None:
            value, variance = sensor
            if not np.isfinite(value) or not np.isfinite(variance) or variance <= 0:
                raise ValueError("Finite sensor value and positive variance required")
            with np.errstate(divide="ignore"):
                lw = np.log(alive) - 0.5 * ((g - value) ** 2 / variance
                                           + np.log(2 * np.pi * variance))
            log_sensor_evidence = float(logsumexp(lw))
            if not np.isfinite(log_sensor_evidence):
                raise ValueError("Sensor likelihood has no representable support")
            alive = np.exp(lw - log_sensor_evidence)
            log_likelihood += log_sensor_evidence
    return {
        "alive_mass": alive,
        "event_mass": event,
        "observation": observation.value,
        "observation_probability": evidence,
        "log_likelihood": log_likelihood,
        "precondition_alive_mass": surviving,
        "tail_mass_collapsed": tail,
        "projection": "midpoint_bins_atom_projection_v1",
        "exact_gaussian_posterior": False,
        "continuous_semigroup_preserved": False,
    }
