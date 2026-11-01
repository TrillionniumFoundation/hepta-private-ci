"""Delayed-reset QVI with causal admission jumps at multiples of recovery rho.

Within each open interval the reflected finite-difference obstacle problem is
implicit. At t=k*rho the new RESET option is applied *after* evolving the left
limit. This avoids smearing a newly feasible reset backward through one step.
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
    actions = np.ones((n, 2, count), dtype=np.int8)
    left_limits, jump_records = {}, []
    rate = config["sigma"] ** 2 / (2 * dx * dx)
    lower, upper = np.full(count - 1, rate), np.full(count - 1, rate)
    upper[0], lower[-1] = 2 * rate, 2 * rate
    a, l, u = np.full(count, 1 + 2 * dt * rate), -dt * lower, -dt * upper
    matrix, fee = np.asarray(config["content_transition"]), np.asarray(config["reset_fee"]) + config["recovery_cost"] * config["recovery"]
    total_iterations, max_residual = 0, 0.
    for index in range(1, n):
        jump = index % lag == 0
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in values[index - lag]])
            reset[index] = matrix @ future - fee
        left_reset = reset[index].copy()
        if jump:
            if index == lag:
                left_reset[:] = -np.inf
            else:
                future = np.array([np.interp(config["reset_x"], x, row) for row in left_limits[index - lag]])
                left_reset = matrix @ future - fee
        obstacle = np.maximum(reward, left_reset[:, None])
        rhs = values[index - 1] - config["wait_cost"] * dt
        left_value = np.empty((2, count))
        for mode in range(2):
            value = np.maximum(values[index - 1, mode], obstacle[mode])
            active = value - obstacle[mode] <= a * value + np.r_[0., l * value[:-1]] + np.r_[u * value[1:], 0.] - rhs[mode]
            for iteration in range(128):
                band = np.zeros((3, count))
                band[0, 1:], band[1], band[2, :-1] = u, a, l
                target = rhs[mode].copy()
                indices = np.flatnonzero(active)
                band[1, indices] = 1.
                band[0, indices[indices < count - 1] + 1] = 0.
                band[2, indices[indices > 0] - 1] = 0.
                target[indices] = obstacle[mode, indices]
                candidate = solve_banded((1, 1), band, target, check_finite=False)
                continuation = a * candidate + np.r_[0., l * candidate[:-1]] + np.r_[u * candidate[1:], 0.] - rhs[mode]
                contact = candidate - obstacle[mode]
                next_active = contact <= continuation
                change, value = np.max(abs(candidate - value)), candidate
                if np.array_equal(active, next_active) and change < 2e-12:
                    break
                active = next_active
            else:
                raise RuntimeError("Jump-aware QVI policy iteration failed")
            left_value[mode] = value
            max_residual = max(max_residual, float(np.max(abs(np.minimum(contact, continuation)))))
            total_iterations += iteration + 1
        if jump:
            left_limits[index] = left_value.copy()
            values[index] = np.maximum(left_value, reset[index, :, None])
            jump_records.append(dict(time=float(times[index]), maximum_jump=float(np.max(values[index] - left_value)),
                                     jump_condition_error=float(np.max(abs(values[index] - np.maximum(left_value, reset[index, :, None]))))))
        else:
            values[index] = left_value
        final_obstacle = np.maximum(reward, reset[index, :, None])
        contact_active = values[index] - final_obstacle < 1e-10
        actions[index] = np.where(contact_active, np.where(reward >= reset[index, :, None], 1, 2), 0)
    return dict(x=x, times=times, values=values, reset_values=reset, lag=lag, actions=actions,
                maximum_lcp_residual=max_residual, total_policy_iterations=total_iterations,
                dt=dt, dx=dx, config=config, jump_records=jump_records,
                first_left_limit=left_limits[lag])
