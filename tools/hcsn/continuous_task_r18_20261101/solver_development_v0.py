"""Implicit finite-difference delayed-reset QVI with reflected diffusion.

V_t = (sigma²/2)V_xx-c in continuation; obstacles are STOP g(x) and
RESET -k-c_rec*rho+M V(t-rho,x_reset). Remaining time is never discarded.
"""

import numpy as np
from scipy.linalg import solve_banded

from .task import discretization, payoff


def solve(config, dx, dt):
    x, times, lag = discretization(config, dx, dt)
    count, n = len(x), len(times)
    reward = payoff(config, x)
    values = np.zeros((n, 2, count))
    values[0] = reward
    reset = np.full((n, 2), -np.inf)
    rate = config["sigma"] ** 2 / (2 * dx * dx)
    lower, upper = np.full(count - 1, rate), np.full(count - 1, rate)
    upper[0], lower[-1] = 2 * rate, 2 * rate
    diagonal = np.full(count, 2 * rate)
    a = 1 + dt * diagonal
    l, u = -dt * lower, -dt * upper
    total_iterations, max_residual = 0, 0.
    matrix = np.asarray(config["content_transition"])
    for index in range(1, n):
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in values[index - lag]])
            reset[index] = matrix @ future - np.asarray(config["reset_fee"]) - config["recovery_cost"] * config["recovery"]
        obstacle = np.maximum(reward, reset[index, :, None])
        rhs = values[index - 1] - config["wait_cost"] * dt
        for mode in range(2):
            value = np.maximum(values[index - 1, mode], obstacle[mode])
            active = value - obstacle[mode] <= a * value + np.r_[0., l * value[:-1]] + np.r_[u * value[1:], 0.] - rhs[mode]
            for iteration in range(128):
                band = np.zeros((3, count))
                band[0, 1:], band[1], band[2, :-1] = u, a, l
                target = rhs[mode].copy()
                indices = np.flatnonzero(active)
                band[1, indices] = 1.
                band[0, indices[indices > 0]] = 0.
                band[2, indices[indices < count - 1]] = 0.
                target[indices] = obstacle[mode, indices]
                candidate = solve_banded((1, 1), band, target, check_finite=False)
                continuation = a * candidate + np.r_[0., l * candidate[:-1]] + np.r_[u * candidate[1:], 0.] - rhs[mode]
                contact = candidate - obstacle[mode]
                next_active = contact <= continuation
                change = np.max(abs(candidate - value))
                value = candidate
                if np.array_equal(active, next_active) and change < 2e-12:
                    break
                active = next_active
            else:
                raise RuntimeError("Delayed-reset obstacle policy iteration failed")
            values[index, mode] = value
            residual = np.max(abs(np.minimum(contact, continuation)))
            max_residual = max(max_residual, float(residual))
            total_iterations += iteration + 1
    return dict(x=x, times=times, values=values, reset_values=reset, lag=lag,
                maximum_lcp_residual=max_residual, total_policy_iterations=total_iterations,
                dt=dt, dx=dx, config=config)


def choose(solution, index, x, mode):
    if not index:
        return "STOP"
    grid, value = solution["x"], solution["values"][index, mode]
    stop = float(payoff(solution["config"], x)[mode])
    reset = solution["reset_values"][index, mode]
    fitted = float(np.interp(x, grid, value))
    # Contact tolerance only resolves discretization-level equality. It does
    # not change value iteration, payoff or the continuous law.
    tolerance = 2e-8 + .15 * solution["dx"] ** 2
    if stop >= reset and fitted - stop <= tolerance:
        return "STOP"
    if index >= solution["lag"] and reset >= stop and fitted - reset <= tolerance:
        return "RESET"
    return "WAIT"
