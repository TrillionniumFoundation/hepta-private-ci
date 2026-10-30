"""Evaluate a fixed deadline threshold schedule with analytic Brownian laws.

Killed-density quadrature is positive. First-hit rewards and the linear delayed
reset continuation use H and -dH/dq analytically. State/time projections remain
explicit approximations and no transition row is normalized.
"""

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np
from scipy.sparse import coo_matrix

from experiments.first_passage_cell.kernels import (
    first_passage, first_passage_gradients, killed_cdf, killed_density,
)
from experiments.first_passage_operator.free_boundary import NaturalSpikeSpec
from .qvi import aligned_steps, state_grid


@lru_cache(maxsize=8)
def _quadrature(order):
    if not 2 <= order <= 64:
        raise ValueError("quadrature order must be between 2 and 64")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    return (nodes + 1) / 2, weights / 2


def killed_matrix(spec, starts, state, boundary, duration, order=8):
    """Positive interpolation weights; density scale sets adaptive subintervals."""
    starts, state = np.asarray(starts, float), np.asarray(state, float)
    if (duration <= 0 or not np.isfinite(starts).all() or np.any(starts >= boundary)
            or not state[0] < boundary <= state[-1]):
        raise ValueError("positive duration and interior states/barrier required")
    dx = state[1] - state[0]
    scale = spec.sigma * math.sqrt(duration)
    mean = starts + spec.mu * duration
    width = math.ceil(12 * scale / dx) + 2
    centers = np.floor((mean - state[0]) / dx).astype(int)
    bins = centers[:, None] + np.arange(-width, width + 1)[None, :]
    valid = (bins >= 0) & (bins < len(state) - 1)
    clipped = np.clip(bins, 0, len(state) - 2)
    original_left = state[clipped]
    lo = np.maximum(original_left, mean[:, None] - 12 * scale)
    hi = np.minimum(np.minimum(state[clipped + 1], boundary), mean[:, None] + 12 * scale)
    valid &= hi > lo
    rows, columns = np.nonzero(valid)
    j = clipped[rows, columns]
    left, right = lo[rows, columns], hi[rows, columns]
    nodes, weights = _quadrature(order)
    subdivisions = min(24, max(1, math.ceil(dx / scale)))
    nodes = ((np.arange(subdivisions)[:, None] + nodes) / subdivisions).ravel()
    weights = np.broadcast_to(weights / subdivisions,
                              (subdivisions, len(weights))).ravel()
    y = left[:, None] + (right - left)[:, None] * nodes
    distances = boundary - starts[rows]
    density = killed_density(distances[:, None], boundary - y,
                             -spec.mu, spec.sigma, duration)
    weighted = density * (right - left)[:, None] * weights
    fraction = (y - state[j, None]) / dx
    coordinate_error = max(float(np.max(np.maximum(-fraction, 0), initial=0)),
                           float(np.max(np.maximum(fraction - 1, 0), initial=0)))
    if coordinate_error > 2e-10:
        raise ArithmeticError("linear interpolation coordinate outside its interval")
    fraction = np.clip(fraction, 0, 1)
    low_weights = np.sum(weighted * (1 - fraction), axis=1)
    high_weights = np.sum(weighted * fraction, axis=1)
    matrix = coo_matrix((np.r_[low_weights, high_weights],
                         (np.r_[rows, rows], np.r_[j, j + 1])),
                        shape=(len(starts), len(state))).tocsr()
    survival = first_passage(boundary - starts, -spec.mu, spec.sigma, duration)["S"]
    covered = survival.copy()
    # Elsewhere the omitted lower mass is bounded by the unrestricted Gaussian
    # tail beyond 12 standard deviations; only the nearby rows need a CDF call.
    near_lower = mean - state[0] <= 12 * scale
    if np.any(near_lower):
        covered[near_lower] = killed_cdf(
            boundary - starts[near_lower], boundary - state[0],
            -spec.mu, spec.sigma, duration,
        )
    raw_mass = np.asarray(matrix.sum(axis=1)).ravel()
    diagnostics = {
        "mass_defect": float(np.max(np.abs(raw_mass - covered), initial=0)),
        "lower_tail_mass_max": float(np.max(survival - covered, initial=0)),
        "negative_weight_mass": float(-np.sum(matrix.data[matrix.data < 0])),
        "interpolation_coordinate_roundoff": coordinate_error,
        "gaussian_band_omitted_mass_bound": 4e-33,
    }
    return matrix, diagnostics


def _first_hit_value(spec, distance, duration, horizon, time, reset_values, boundary):
    law = first_passage(distance, -spec.mu, spec.sigma, duration, spec.discount)
    value = (boundary - spec.spike_cost) * law["H"]
    if horizon > spec.refractory:
        upper = horizon - spec.refractory
        lower = max(0.0, upper - duration)
        reset_upper = np.interp(upper, time, reset_values)
        slope = (reset_upper - np.interp(lower, time, reset_values)) / duration
        moment = -first_passage_gradients(
            distance, -spec.mu, spec.sigma, duration, spec.discount,
        )["H"]["discount"]
        value = value + math.exp(-spec.discount * spec.refractory) * (
            reset_upper * law["H"] - slope * moment
        )
    return value


@dataclass
class PolicyEvaluation:
    spec: NaturalSpikeSpec
    time: np.ndarray
    state: np.ndarray
    values: np.ndarray
    boundaries: np.ndarray
    reset_index: int
    order: int
    diagnostics: dict

    def value(self, horizon, state, pending_refractory=0.0):
        h, x, eta = float(horizon), float(state), float(pending_refractory)
        if (not np.isfinite([h, x, eta]).all() or not 0 <= h <= self.time[-1] + 1e-12
                or not 0 <= eta <= self.spec.refractory):
            raise ValueError("invalid finite-deadline augmented state")
        if eta > 0:
            if x != self.spec.reset:
                raise ValueError("a refractory state must equal the reset")
            return (0.0 if h <= eta else
                    math.exp(-self.spec.discount * eta) * self.value(h - eta, x))
        if h == 0:
            return max(x - self.spec.spike_cost, 0.0)
        if x <= self.state[0]:
            return 0.0
        dt = self.time[1]
        ratio = h / dt
        exact = abs(ratio - round(ratio)) < 1e-10
        n = round(ratio) if exact else math.ceil(ratio)
        b = self.boundaries[n]
        if x >= b:
            future = (0.0 if h <= self.spec.refractory else
                      math.exp(-self.spec.discount * self.spec.refractory)
                      * np.interp(h - self.spec.refractory, self.time,
                                  self.values[:, self.reset_index]))
            return float(x - self.spec.spike_cost + future)
        position = (x - self.state[0]) / (self.state[1] - self.state[0])
        if exact and abs(position - round(position)) < 1e-9:
            return float(self.values[n, round(position)])
        duration = h - self.time[n - 1]
        matrix, check = killed_matrix(self.spec, [x], self.state, b, duration, self.order)
        self.diagnostics["mass_defect_max"] = max(self.diagnostics["mass_defect_max"], check["mass_defect"])
        self.diagnostics["lower_tail_mass_max"] = max(self.diagnostics["lower_tail_mass_max"], check["lower_tail_mass_max"])
        wait = math.exp(-self.spec.discount * duration) * (matrix @ self.values[n - 1])[0]
        hit = _first_hit_value(self.spec, np.array([b - x]), duration, h,
                               self.time, self.values[:, self.reset_index], b)[0]
        return float(wait + hit)


def evaluate_policy(spec, horizon, boundaries, *, dt=.01, dx=.02,
                    tail_bound=1e-8, order=8):
    steps = aligned_steps(horizon, dt, "horizon")
    lag = aligned_steps(spec.refractory, dt, "refractory duration")
    if lag <= 1:
        raise ValueError("one-event segments require dt strictly below refractory duration")
    boundaries = np.asarray(boundaries, float)
    if boundaries.shape != (steps + 1,) or not np.isfinite(boundaries).all():
        raise ValueError("one finite threshold per positive time layer required")
    x, reset, actual_tail = state_grid(spec, dx, tail_bound)
    if np.any(boundaries[1:] <= x[0]) or np.any(boundaries[1:] > x[-1]):
        raise ValueError("thresholds must lie inside the declared state domain")
    time = np.arange(steps + 1) * dt
    values = np.zeros((steps + 1, len(x)))
    values[0] = np.maximum(x - spec.spike_cost, 0)
    cache = OrderedDict()
    diagnostics = {"mass_defect_max": 0.0, "lower_tail_mass_max": 0.0,
                   "negative_weight_mass_max": 0.0, "cached_matrices_limit": 8,
                   "quadrature_order": order, "dt": dt, "dx": dx,
                   "lower_truncation_value_bound": actual_tail,
                   "projection": "linear state interpolation and linear past reset-value time interpolation",
                   "row_normalization": False}
    for n in range(1, steps + 1):
        b = float(boundaries[n])
        interior = (x > x[0]) & (x < b)
        if b not in cache:
            cache[b] = killed_matrix(spec, x[interior], x, b, dt, order)
            if len(cache) > 8:
                cache.popitem(last=False)
        else:
            cache.move_to_end(b)
        matrix, check = cache[b]
        diagnostics["mass_defect_max"] = max(diagnostics["mass_defect_max"], check["mass_defect"])
        diagnostics["lower_tail_mass_max"] = max(diagnostics["lower_tail_mass_max"], check["lower_tail_mass_max"])
        diagnostics["negative_weight_mass_max"] = max(diagnostics["negative_weight_mass_max"], check["negative_weight_mass"])
        wait = math.exp(-spec.discount * dt) * (matrix @ values[n - 1])
        hit = _first_hit_value(spec, b - x[interior], dt, time[n], time,
                               values[:, reset], b)
        values[n, interior] = wait + hit
        delayed = (math.exp(-spec.discount * spec.refractory) * values[n - lag, reset]
                   if n >= lag else 0.0)
        immediate = x >= b
        values[n, immediate] = x[immediate] - spec.spike_cost + delayed
    return PolicyEvaluation(spec, time, x, values, boundaries, reset, order, diagnostics)
