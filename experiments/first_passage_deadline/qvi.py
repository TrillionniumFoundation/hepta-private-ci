"""Monotone implicit obstacle solve for a scalar diffusion with a fixed lag.

This is a finite-grid approximation. A small complementarity residual certifies
the discrete system, not the continuous problem's optimality gap.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import solve_banded

from experiments.first_passage_operator.free_boundary import (
    NaturalSpikeSpec, optimal_value, solve_boundary,
)


def aligned_steps(duration, step, name):
    if not math.isfinite(duration) or not math.isfinite(step) or duration <= 0 or step <= 0:
        raise ValueError(f"positive finite {name} and step required")
    count = round(duration / step)
    if count < 1 or abs(duration - count * step) > 1e-10 * max(1.0, duration):
        raise ValueError(f"{name} must be an integer multiple of the time step")
    return count


def state_grid(spec, spacing, tail_bound):
    if not math.isfinite(spacing) or spacing <= 0 or not 0 < tail_bound < .01:
        raise ValueError("positive finite spacing and a small positive tail budget required")
    stationary = solve_boundary(spec)
    lam = spec.exponent
    lower = min(spec.reset - 2 * spacing,
                stationary["boundary"] + math.log(lam * tail_bound) / lam)
    single = spec.spike_cost + 1 / lam
    left = math.ceil((spec.reset - lower) / spacing)
    right = math.ceil((single - spec.reset) / spacing) + 2
    if left + right > 100000:
        raise ValueError("state grid exceeds the bounded research interface")
    x = spec.reset + np.arange(-left, right + 1) * spacing
    return x, left, float(optimal_value(spec, x[0]))


@dataclass
class DeadlineSolution:
    spec: NaturalSpikeSpec
    time: np.ndarray
    state: np.ndarray
    values: np.ndarray
    boundaries: np.ndarray
    reset_index: int
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
        delayed = (0.0 if h <= self.spec.refractory else
                   math.exp(-self.spec.discount * self.spec.refractory)
                   * np.interp(h - self.spec.refractory, self.time,
                               self.values[:, self.reset_index]))
        if x >= self.state[-1]:
            return x - self.spec.spike_cost + delayed
        column = np.array([np.interp(x, self.state, row) for row in self.values])
        return float(np.interp(h, self.time, column))


def solve_deadline(spec, horizon, *, dt=.01, dx=.02, tail_bound=1e-8,
                   maximum_iterations=100):
    steps = aligned_steps(horizon, dt, "horizon")
    lag = aligned_steps(spec.refractory, dt, "refractory duration")
    if lag <= 1:
        raise ValueError("time step must be strictly smaller than refractory duration")
    x, reset, actual_tail = state_grid(spec, dx, tail_bound)
    count = len(x)
    times = np.arange(steps + 1) * dt
    values = np.zeros((steps + 1, count))
    values[0] = np.maximum(x - spec.spike_cost, 0.0)
    boundaries = np.zeros(steps + 1)
    boundaries[0] = spec.spike_cost
    diffusion = .5 * spec.sigma ** 2 / dx ** 2
    central = diffusion >= abs(spec.mu) / (2 * dx)
    down = diffusion - spec.mu / (2 * dx) if central else diffusion + max(-spec.mu, 0) / dx
    up = diffusion + spec.mu / (2 * dx) if central else diffusion + max(spec.mu, 0) / dx
    diagonal = 1 + dt * (spec.discount + down + up)
    beta = math.exp(-spec.discount * spec.refractory)
    stop = x >= spec.spike_cost
    stop[0], stop[-1] = False, True
    residual_max, iterations_max = 0.0, 0
    for n in range(1, steps + 1):
        delayed = beta * values[n - lag, reset] if n >= lag else 0.0
        obstacle = x - spec.spike_cost + delayed
        previous = values[n - 1]
        for iteration in range(maximum_iterations):
            band = np.zeros((3, count))
            band[1] = np.where(stop, 1.0, diagonal)
            band[1, 0] = band[1, -1] = 1.0
            continuing = ~stop[1:-1]
            band[0, 2:] = np.where(continuing, -dt * up, 0.0)
            band[2, :-2] = np.where(continuing, -dt * down, 0.0)
            rhs = np.where(stop, obstacle, previous)
            rhs[0], rhs[-1] = 0.0, obstacle[-1]
            value = solve_banded((1, 1), band, rhs, check_finite=False)
            wait = (previous[1:-1] + dt * (down * value[:-2] + up * value[2:])) / diagonal
            updated = stop.copy()
            updated[1:-1] = obstacle[1:-1] >= wait
            if np.array_equal(updated, stop):
                break
            stop = updated
        else:
            raise ArithmeticError(f"LCP policy iteration failed at time layer {n}")
        equation = diagonal * value[1:-1] - dt * (down * value[:-2] + up * value[2:]) - previous[1:-1]
        gap = value[1:-1] - obstacle[1:-1]
        residual = max(float(np.max(np.maximum(-equation, 0))),
                       float(np.max(np.maximum(-gap, 0))),
                       float(np.max(np.abs(np.minimum(equation, gap)))))
        indices = np.flatnonzero(stop[1:]) + 1
        if not len(indices) or not np.all(stop[indices[0]:]):
            raise ArithmeticError("computed stopping set is not an upper ray")
        values[n] = value
        boundaries[n] = x[indices[0]]
        residual_max = max(residual_max, residual)
        iterations_max = max(iterations_max, iteration + 1)
    return DeadlineSolution(spec, times, x, values, boundaries, reset, {
        "dt": dt, "dx": dx, "time_steps": steps, "state_points": count,
        "drift_scheme": "central_monotone" if central else "upwind_monotone",
        "generator_down": down, "generator_up": up,
        "complementarity_residual_max": residual_max,
        "policy_iterations_max": iterations_max,
        "lower": float(x[0]), "upper": float(x[-1]),
        "lower_truncation_value_bound": actual_tail,
        "single_stop_boundary": spec.spike_cost + 1 / spec.exponent,
        "boundary_terminal": spec.spike_cost,
        "boundary_positive_time_limit": spec.spike_cost + max(spec.mu, 0) / spec.discount,
        "finite_grid_only": True,
    })
