"""Analytic complex-step replay of a certified policy; no derivative imports.

All comparisons are frozen by a separately proved base-policy certificate.
The fixed imaginary increment evaluates an analytic derivative, not a smaller
real one-sided quotient chosen after seeing finite-step errors.
"""

import copy
import numpy as np
from scipy.linalg import solve_banded


def replay(config, direction, geometry, plan, increment):
    c = copy.deepcopy(config)
    d = np.asarray(direction)
    for key in ("sigma", "wait_cost", "recovery_cost", "reset_x", "reward_slope"):
        index = {"sigma": 0, "wait_cost": 1, "recovery_cost": 2, "reset_x": 3, "reward_slope": 12}[key]
        c[key] = c[key] + increment * d[index]
    for key, offset in (("reset_fee", 4), ("reward_base", 8), ("reward_amplitude", 10)):
        c[key] = np.asarray(c[key], dtype=complex) + increment * d[offset:offset + 2]
    matrix = np.asarray(c["content_transition"], dtype=complex) + increment * np.array([[d[6], -d[6]], [-d[7], d[7]]])
    x, dt, dx, lag = geometry["x"], geometry["dt"], geometry["dx"], geometry["lag"]
    n, count = plan["left"].shape[0], len(x)
    value, left = np.zeros((n, 2, count), dtype=complex), np.zeros((n, 2, count), dtype=complex)
    reward = c["reward_base"][:, None] + c["reward_amplitude"][:, None] / (1 + np.exp(-c["reward_slope"] * x))
    value[0], left[0] = reward, reward
    rate = c["sigma"] ** 2 / (2 * dx ** 2)
    diagonal = np.full(count, 1 + 2 * dt * rate, dtype=complex)
    lower, upper = np.full(count - 1, -dt * rate, dtype=complex), np.full(count - 1, -dt * rate, dtype=complex)
    lower[-1] *= 2
    upper[0] *= 2
    cell = int(np.searchsorted(x, config["reset_x"], side="right") - 1)
    if config["reset_x"] == x[cell] and d[3] < 0:
        cell -= 1
    weight = (c["reset_x"] - x[cell]) / (x[cell + 1] - x[cell])

    def reset(source):
        return matrix @ ((1 - weight) * source[:, cell] + weight * source[:, cell + 1]) - c["reset_fee"] - c["recovery_cost"] * config["recovery"]

    for k in range(1, n):
        right_b, left_b = None, None
        if k >= lag:
            right_b = reset(value[k - lag])
            left_b = None if k == lag else reset(left[k - lag]) if k % lag == 0 else right_b
        for mode in range(2):
            rhs = value[k - 1, mode] - c["wait_cost"] * dt
            band = np.zeros((3, count), dtype=complex)
            band[0, 1:], band[1], band[2, :-1] = upper, diagonal, lower
            action = plan["left"][k, mode]
            fixed = np.flatnonzero(action != 0)
            band[1, fixed] = 1
            band[0, fixed[fixed < count - 1] + 1] = 0
            band[2, fixed[fixed > 0] - 1] = 0
            rhs[action == 1] = reward[mode, action == 1]
            if np.any(action == 2):
                if left_b is None:
                    raise ValueError("Policy references an unavailable reset")
                rhs[action == 2] = left_b[mode]
            left[k, mode] = solve_banded((1, 1), band, rhs)
        if k % lag == 0:
            value[k] = np.where(plan["outer"][k] == 1, right_b[:, None], left[k])
        else:
            value[k] = left[k]
    return value, left
