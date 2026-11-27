"""Finite-volume projection of killed Brownian transitions with renewal reset.

Within each step the drift is frozen at each source-bin centre. The transition
integrates the killed Brownian density exactly over destination bins. Replacing
the surviving density by centre masses and freezing a nonconstant drift are
controlled discretizations, not an exact continuous-time OU/reset solution.

Positive drive and coupling move log margin toward the absorbing boundary x=0.
Firing is absorbed probability / dt. Reset occurs after refractory release at
step end; there is no same-step refiring. Upper-grid escape is retained in an
explicit cemetery account and never silently reinjected or renormalized.
"""

from dataclasses import dataclass
import math
import numpy as np
from scipy.special import log_ndtr, ndtr


@dataclass(frozen=True)
class PopulationConfig:
    bins: int = 64
    x_max: float = 2.5
    dt: float = 0.02
    sigma: float = 0.15
    rest_margin: float = 0.8
    reset_margin: float = 0.8
    leak: float = 3.0
    base_drift: float = 0.0
    refractory: float = 0.24
    recovery_tau: float = 0.6
    recovery_strength: float = 0.2

    def __post_init__(self):
        vals = tuple(getattr(self, n) for n in self.__dataclass_fields__)
        if not all(np.isfinite(vals)):
            raise ValueError("Population parameters must be finite.")
        if not isinstance(self.bins, int) or self.bins < 8:
            raise ValueError("bins must be an integer >= 8.")
        if min(self.x_max, self.dt, self.sigma, self.recovery_tau) <= 0:
            raise ValueError("x_max, dt, sigma and recovery_tau must be positive.")
        if min(self.leak, self.refractory, self.recovery_strength) < 0:
            raise ValueError("leak, refractory and recovery_strength must be nonnegative.")
        lo, hi = self.x_max / (2 * self.bins), self.x_max * (1 - 0.5 / self.bins)
        if not (lo <= self.rest_margin <= hi and lo <= self.reset_margin <= hi):
            raise ValueError("Rest/reset margins must lie between grid centres.")

    @property
    def refractory_steps(self):
        # One ULP handles decimal ratios such as .07/.01 without adding a
        # spurious full step; all other nonintegral durations round upward.
        return int(math.ceil(math.nextafter(self.refractory / self.dt, -math.inf)))

    @property
    def effective_refractory(self):
        return self.refractory_steps * self.dt


@dataclass(frozen=True)
class PopulationState:
    active: np.ndarray
    refractory: np.ndarray
    recovery: np.ndarray
    escaped: np.ndarray

    def total_mass(self):
        return self.active.sum(-1) + self.refractory.sum(-1) + self.escaped


@dataclass(frozen=True)
class PopulationStep:
    state: PopulationState
    rate: np.ndarray
    absorbed: np.ndarray
    escaped: np.ndarray


def _log_interval(a, b):
    """Log Gaussian interval mass; exact empty/full interval conventions."""
    a, b = np.broadcast_arrays(a, b)
    result = np.full(a.shape, -np.inf)
    regular = np.isfinite(a) & np.isfinite(b) & (a < b)
    aa, bb = a[regular], b[regular]
    positive = aa > 0
    lo, hi = np.where(positive, -bb, aa), np.where(positive, -aa, bb)
    log_hi = log_ndtr(hi)
    with np.errstate(divide="ignore", invalid="ignore"):
        result[regular] = log_hi + np.log(-np.expm1(log_ndtr(lo) - log_hi))
    left_open, right_open = np.isneginf(a) & np.isfinite(b), np.isfinite(a) & np.isposinf(b)
    result[left_open] = log_ndtr(b[left_open])
    result[right_open] = log_ndtr(-a[right_open])
    result[np.isneginf(a) & np.isposinf(b)] = 0.0
    result[(a > b) | np.isnan(a) | np.isnan(b)] = np.nan
    return result


def _positive_difference(log_a, log_b):
    """Difference of probabilities; only roundoff-level negatives are clipped."""
    delta = log_b - log_a
    if np.any((delta > 1e-8) & (log_a > -700)):
        raise FloatingPointError("Killed transition became negative beyond roundoff.")
    with np.errstate(invalid="ignore"):
        result = np.exp(log_a) * -np.expm1(np.minimum(delta, 0.0))
    return np.where(np.isneginf(log_a), 0.0, result)


def killed_transition(centres, edges, drift, sigma, dt):
    """Return (survivor matrix, lower absorption, upper escape).

    drift has shape (..., source); matrix has (..., source, destination).
    The reflected kernel includes paths that crossed and returned within dt.
    """
    x = np.asarray(centres, dtype=np.float64)
    drift = np.asarray(drift, dtype=np.float64)
    scale = sigma * np.sqrt(dt)
    reflection = -2 * drift * x / sigma**2
    mean, image_mean = x + drift * dt, -x + drift * dt
    lo, hi = np.asarray(edges[:-1]), np.asarray(edges[1:])
    log_a = _log_interval((lo - mean[..., None]) / scale,
                         (hi - mean[..., None]) / scale)
    log_b = reflection[..., None] + _log_interval(
        (lo - image_mean[..., None]) / scale,
        (hi - image_mean[..., None]) / scale)
    matrix = _positive_difference(log_a, log_b)
    absorbed = ndtr((-x - drift * dt) / scale) + np.exp(
        reflection + log_ndtr((-x + drift * dt) / scale))
    escaped = _positive_difference(log_ndtr((mean - edges[-1]) / scale),
                                   reflection + log_ndtr((image_mean - edges[-1]) / scale))
    err = np.max(np.abs(matrix.sum(-1) + absorbed + escaped - 1))
    if err > 2e-10:
        raise FloatingPointError(f"Transition mass error {err:g} exceeds tolerance.")
    return matrix, absorbed, escaped


class Population:
    """Fixed-boundary population. State is explicit and may be batched."""

    def __init__(self, config=PopulationConfig()):
        self.config = config
        self.edges = np.linspace(0, config.x_max, config.bins + 1)
        self.centres = 0.5 * (self.edges[:-1] + self.edges[1:])
        self.reset_weights = self._deposit(config.reset_margin)
        self.initial_weights = self._deposit(config.rest_margin)

    def _deposit(self, margin):
        coordinate = margin / (self.edges[1] - self.edges[0]) - 0.5
        lower = min(int(np.floor(coordinate)), self.config.bins - 2)
        fraction = coordinate - lower
        weights = np.zeros(self.config.bins)
        weights[lower], weights[lower + 1] = 1 - fraction, fraction
        return weights

    def initial_state(self, shape=()):
        shape = tuple(shape)
        return PopulationState(
            np.broadcast_to(self.initial_weights, shape + (self.config.bins,)).copy(),
            np.zeros(shape + (self.config.refractory_steps,)),
            np.zeros(shape), np.zeros(shape))

    def step(self, state, drive=0.0, coupling=0.0):
        """Advance one dt; releases occur after this step's propagation.

        Mass absorbed at interval n's end waits m complete steps in the queue.
        It is released at the end of interval n+m and can first fire again
        during interval n+m+1. For m=0, reset is at interval n's end. Rounding
        and event-within-step timing can lengthen the physical refractory delay.
        """
        cfg = self.config
        drive, coupling = np.asarray(drive), np.asarray(coupling)
        if not np.all(np.isfinite(drive)) or not np.all(np.isfinite(coupling)):
            raise ValueError("Drive and coupling must be finite.")
        shape = state.recovery.shape
        if state.active.shape != shape + (cfg.bins,) or state.refractory.shape != shape + (cfg.refractory_steps,):
            raise ValueError("State shape does not match the population grid.")
        if np.any(state.active < 0) or np.any(state.refractory < 0) or np.any(state.escaped < 0):
            raise ValueError("Population masses cannot be negative.")
        if not all(np.all(np.isfinite(v)) for v in (state.active, state.refractory, state.recovery, state.escaped)):
            raise ValueError("Population state must be finite.")
        drift = cfg.base_drift + cfg.leak * (cfg.rest_margin - self.centres)
        drift = drift - np.broadcast_to(drive + coupling, shape)[..., None] + state.recovery[..., None]
        matrix, hit, escape = killed_transition(self.centres, self.edges, drift, cfg.sigma, cfg.dt)
        absorbed = np.sum(state.active * hit, axis=-1)
        escaped = np.sum(state.active * escape, axis=-1)
        active = np.einsum("...i,...ij->...j", state.active, matrix)
        if cfg.refractory_steps:
            active = active + state.refractory[..., 0, None] * self.reset_weights
            queue = np.concatenate((state.refractory[..., 1:], absorbed[..., None]), axis=-1)
        else:
            active = active + absorbed[..., None] * self.reset_weights
            queue = state.refractory.copy()
        recovery = state.recovery * np.exp(-cfg.dt / cfg.recovery_tau) + cfg.recovery_strength * absorbed
        new_state = PopulationState(active, queue, recovery, state.escaped + escaped)
        return PopulationStep(new_state, absorbed / cfg.dt, absorbed, escaped)
