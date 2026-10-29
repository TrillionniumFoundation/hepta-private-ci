"""Independent numerical references for the controlled first-passage task.

The primary model integrates the analytic killed kernel. This module builds a
continuous-time Markov chain from a monotone finite-difference generator and
exponentiates it, so it does not reuse the primary transition construction or
its Bellman loop. The reference shares the published task definition, not
hidden test labels. Both grids are approximations to the same continuous law.
"""

from dataclasses import asdict

import numpy as np
from scipy.integrate import quad
from scipy.linalg import expm, solve
from scipy.special import ndtr

from experiments.continuous_boundary_flow.math_model import TaskSpec, point_distribution


def finite_difference_reference(spec=None, n_grid=160, x_max=4.8):
    """Independent finite-volume/CTMC + Bellman reference, with stop action.

    Zero is absorbing during a window. At the far upper edge the chain has a
    reflecting truncation; callers must check domain convergence. A centered
    generator is used when its rates are nonnegative, otherwise an explicitly
    disclosed monotone upwind drift approximation is used.
    """
    spec = spec or TaskSpec()
    if n_grid < 8 or x_max <= max(
        spec.initial, spec.maintenance_reset, spec.failure_reset
    ):
        raise ValueError("Insufficient reference grid/domain")
    dx = x_max / (n_grid + 1)
    x = np.arange(1, n_grid + 1) * dx
    diff = spec.sigma**2 / (2 * dx**2)
    up, down = diff + spec.mu / (2 * dx), diff - spec.mu / (2 * dx)
    method = "centered_monotone"
    if min(up, down) < 0:
        up, down = diff + max(spec.mu, 0) / dx, diff + max(-spec.mu, 0) / dx
        method = "upwind"
    generator = np.diag(np.full(n_grid, -(up + down)))
    generator += np.diag(np.full(n_grid - 1, up), 1)
    generator += np.diag(np.full(n_grid - 1, down), -1)
    generator[-1, -1] = -down
    killed = expm(generator * spec.dt)
    survival = killed.sum(axis=1)
    failure = 1 - survival
    gamma = np.exp(-spec.discount * spec.dt)
    shifted = generator - spec.discount * np.eye(n_grid)
    occupation = solve(shifted, gamma * survival - np.ones(n_grid), assume_a="gen")
    discounted_failure = 1 - gamma * survival - spec.discount * occupation
    failure_dist = point_distribution(x, spec.failure_reset)
    repair_dist = point_distribution(x, spec.maintenance_reset)
    initial_dist = point_distribution(x, spec.initial)
    transition = killed + failure[:, None] * failure_dist
    reward = spec.production_rate * occupation - spec.failure_cost * discounted_failure
    repair_transition = repair_dist @ transition
    repair_reward = float(repair_dist @ reward - spec.maintenance_cost)
    value = np.zeros((spec.horizon + 1, n_grid))
    actions = np.zeros((spec.horizon, n_grid), dtype=int)
    boundary = []
    for n in range(1, spec.horizon + 1):
        wait = reward + gamma * transition.dot(value[n - 1])
        repair = repair_reward + gamma * repair_transition.dot(value[n - 1])
        q = np.column_stack((wait, np.full(n_grid, repair), np.zeros(n_grid)))
        actions[n - 1] = q.argmax(axis=1)
        value[n] = q.max(axis=1)
        difference = repair - np.maximum(wait, 0)
        positive = difference > 0
        changes = np.flatnonzero(positive[:-1] != positive[1:])
        if not positive.any():
            boundary.append(0.0)
        elif positive.all():
            boundary.append(float(x[-1]))
        elif changes.size == 1 and positive[0]:
            k = int(changes[0])
            weight = difference[k] / (difference[k] - difference[k + 1])
            boundary.append(float(x[k] + weight * (x[k + 1] - x[k])))
        else:
            boundary.append(None)
    return {
        "spec": asdict(spec),
        "x": x,
        "value": value,
        "actions": actions,
        "initial_value": float(initial_dist @ value[-1]),
        "boundaries": boundary,
        "transition": transition,
        "F": failure,
        "S": survival,
        "H": discounted_failure,
        "occupation": occupation,
        "method": method,
        "grid_size": n_grid,
        "x_max": x_max,
        "dx": dx,
        "mass_error": float(np.max(np.abs(transition.sum(axis=1) - 1))),
        "min_transition": float(transition.min()),
        "terminal_value": 0.0,
    }


def reference_density(t, x, mu, sigma):
    """Textbook first-hit density, implemented independently of kernels.py."""
    if t <= 0:
        return 0.0
    return (
        x
        / (sigma * np.sqrt(2 * np.pi * t**3))
        * np.exp(-((x + mu * t) ** 2) / (2 * sigma**2 * t))
    )


def reference_survival(t, x, mu, sigma):
    if t <= 0:
        return 1.0
    scale = sigma * np.sqrt(t)
    return float(
        ndtr((x + mu * t) / scale)
        - np.exp(-2 * mu * x / sigma**2) * ndtr((-x + mu * t) / scale)
    )


def reference_killed_density(y, x, mu, sigma, t):
    if y <= 0:
        return 0.0
    scale = sigma * np.sqrt(t)
    main = np.exp(-0.5 * ((y - x - mu * t) / scale) ** 2)
    image = np.exp(-2 * mu * x / sigma**2 - 0.5 * ((y + x - mu * t) / scale) ** 2)
    return (main - image) / (np.sqrt(2 * np.pi) * scale)


def independent_integrals(spec, x):
    """Adaptive integration independent of the primary analytic F/S/H code."""
    args = (x, spec.mu, spec.sigma)
    F = quad(reference_density, 0, spec.dt, args=args, epsabs=2e-12, epsrel=2e-11)[0]
    H = quad(
        lambda t: np.exp(-spec.discount * t) * reference_density(t, *args),
        0,
        spec.dt,
        epsabs=2e-12,
        epsrel=2e-11,
    )[0]
    S = quad(
        reference_killed_density,
        0,
        np.inf,
        args=(*args, spec.dt),
        epsabs=2e-12,
        epsrel=2e-11,
    )[0]
    A = quad(
        lambda t: np.exp(-spec.discount * t) * reference_survival(t, *args),
        0,
        spec.dt,
        epsabs=2e-12,
        epsrel=2e-11,
    )[0]
    f = reference_density(spec.dt, *args)
    return {
        "F": F,
        "S": S,
        "H": H,
        "occupation": A,
        "f": f,
        "mass_error": abs(F + S - 1),
    }


def comparison_report(model, reference):
    """Compare published grids at common physical coordinates."""
    primary_x = model.x
    errors = {}
    for field in ("F", "S", "H", "occupation"):
        interpolated = np.interp(primary_x, reference["x"], reference[field])
        interior = (primary_x >= reference["x"][0]) & (primary_x < model.x_max * 0.75)
        errors[field] = float(
            np.max(np.abs(getattr(model, field)[interior] - interpolated[interior]))
        )
    return {
        "kernel_max_abs_errors": errors,
        "reference_method": reference["method"],
        "reference_grid_size": reference["grid_size"],
        "reference_mass_error": reference["mass_error"],
    }
