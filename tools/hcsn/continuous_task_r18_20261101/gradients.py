"""Exact derivative of the fixed-grid active branch; active changes are disclosed."""

import numpy as np
from scipy.linalg import solve_banded


PARAMETERS = ("sigma", "wait_cost", "reset_fee_0", "retention_0")


def tangent(solution, parameter):
    x, times, value = solution["x"], solution["times"], solution["values"]
    config, dt, dx, lag = solution["config"], solution["dt"], solution["dx"], solution["lag"]
    derivative = np.zeros_like(value)
    count, matrix = len(x), np.asarray(config["content_transition"])
    rate, drate = config["sigma"] ** 2 / (2 * dx ** 2), config["sigma"] / dx ** 2
    lower, upper = np.full(count - 1, rate), np.full(count - 1, rate)
    lower[-1], upper[0] = 2 * rate, 2 * rate
    l, u, a = -dt * lower, -dt * upper, np.full(count, 1 + 2 * dt * rate)
    for index in range(1, len(times)):
        db = np.zeros(2)
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in value[index - lag]])
            dfuture = np.array([np.interp(config["reset_x"], x, row) for row in derivative[index - lag]])
            db = matrix @ dfuture
            if parameter == "reset_fee_0":
                db[0] -= 1
            if parameter == "retention_0":
                db[0] += future[0] - future[1]
        for mode in range(2):
            rhs = derivative[index - 1, mode].copy()
            if parameter == "wait_cost":
                rhs -= dt
            if parameter == "sigma":
                curvature = np.r_[2 * (value[index, mode, 1] - value[index, mode, 0]),
                                  np.diff(value[index, mode], 2),
                                  2 * (value[index, mode, -2] - value[index, mode, -1])]
                rhs += dt * drate * curvature
            band = np.zeros((3, count))
            band[0, 1:], band[1], band[2, :-1] = u, a, l
            active = solution["actions"][index, mode]
            indices = np.flatnonzero(active)
            band[1, indices] = 1.
            band[0, indices[indices < count - 1] + 1] = 0.
            band[2, indices[indices > 0] - 1] = 0.
            rhs[active == 1], rhs[active == 2] = 0., db[mode]
            derivative[index, mode] = solve_banded((1, 1), band, rhs, check_finite=False)
    return derivative


def perturb(config, parameter, offset):
    import copy
    result = copy.deepcopy(config)
    if parameter == "reset_fee_0":
        result["reset_fee"][0] += offset
    elif parameter == "retention_0":
        result["content_transition"][0][0] += offset
        result["content_transition"][0][1] -= offset
    else:
        result[parameter] += offset
    return result
