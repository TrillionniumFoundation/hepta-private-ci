"""Causal directional sensitivity of the declared fixed-grid delayed-reset task."""

import copy
import numpy as np
from scipy.special import expit

from tools.hcsn.continuous_task_r18_20261101.task import discretization, payoff
from tools.hcsn.continuous_task_r19_20261101.tangent_solver import PARAMETERS
from .directional import derivative, max_direction, mixed_lcp


def perturb(config, direction, step):
    direction = np.asarray(direction, dtype=float)
    if direction.shape != (13,) or not np.isfinite(direction).all() or not np.isfinite(step):
        raise ValueError("Expected thirteen finite fixed-law directional coefficients")
    result = copy.deepcopy(config)
    for name, delta in zip(PARAMETERS, step * direction):
        if name.startswith("retention_"):
            mode = int(name[-1])
            result["content_transition"][mode][mode] += delta
            result["content_transition"][mode][1 - mode] -= delta
        elif name.startswith(("reset_fee_", "reward_base_", "reward_amplitude_")):
            key, index = name.rsplit("_", 1)
            result[key][int(index)] += delta
        else:
            result[name] += delta
    return result


def solve(config, direction, dx, dt):
    d = np.asarray(direction, dtype=float)
    perturb(config, d, 0.)
    x, times, lag = discretization(config, dx, dt)
    boundary_directions = [(config["wait_cost"], d[1]), (config["recovery_cost"], d[2])]
    boundary_directions += list(zip(config["reset_fee"], d[4:6]))
    boundary_directions += list(zip(config["reward_base"], d[8:10]))
    boundary_directions += list(zip(config["reward_amplitude"], d[10:12]))
    if any(value == 0 and delta < 0 for value, delta in boundary_directions):
        raise ValueError("Direction leaves the feasible nonnegative task tangent cone")
    for mode in range(2):
        if config["reward_base"][mode] + config["reward_amplitude"][mode] == 1 and d[8 + mode] + d[10 + mode] > 0:
            raise ValueError("Direction leaves the reward probability tangent cone")
        retention = config["content_transition"][mode][mode]
        if (retention == 0 and d[6 + mode] < 0) or (retention == 1 and d[6 + mode] > 0):
            raise ValueError("Direction leaves the stochastic row tangent cone")
    n, count = len(times), len(x)
    # This exact profile has V=g identically; every WAIT/STOP/reset tie is real.
    exact_tie_profile = (config["reward_base"][0] == config["reward_base"][1]
        and all(v == 0 for v in config["reward_amplitude"] + config["reset_fee"])
        and config["wait_cost"] == config["recovery_cost"] == 0.)
    if not config["lower"] < config["reset_x"] < config["upper"]:
        raise ValueError("Directional reset interpolation currently requires an interior point")
    reward = payoff(config, x)
    s = expit(config["reward_slope"] * x)
    dreward = np.array([d[8 + mode] + d[10 + mode] * s
        + config["reward_amplitude"][mode] * x * s * (1 - s) * d[12] for mode in range(2)])
    values, tangent = np.zeros((n, 2, count)), np.zeros((n, 2, count))
    values[0], tangent[0] = reward, dreward
    left_values, left_tangents, records, jumps = {}, {}, [], []
    rate = config["sigma"] ** 2 / (2 * dx ** 2)
    a = np.full(count, 1 + 2 * dt * rate)
    lower, upper = np.full(count - 1, -dt * rate), np.full(count - 1, -dt * rate)
    lower[-1] *= 2
    upper[0] *= 2
    matrix = np.asarray(config["content_transition"])
    dmatrix = np.array([[d[6], -d[6]], [-d[7], d[7]]])
    fee = np.asarray(config["reset_fee"]) + config["recovery_cost"] * config["recovery"]
    dfee = d[4:6] + d[2] * config["recovery"]

    def reset(source, ds):
        cell = int(np.searchsorted(x, config["reset_x"], side="right") - 1)
        # At an interpolation knot, select the one-sided segment by d(reset_x).
        if config["reset_x"] == x[cell] and d[3] < 0:
            cell -= 1
        width = x[cell + 1] - x[cell]
        weight = (config["reset_x"] - x[cell]) / width
        future = (1 - weight) * source[:, cell] + weight * source[:, cell + 1]
        dfuture = (1 - weight) * ds[:, cell] + weight * ds[:, cell + 1]
        dfuture += d[3] * (source[:, cell + 1] - source[:, cell]) / width
        return matrix @ future - fee, matrix @ dfuture + dmatrix @ future - dfee

    for index in range(1, n):
        jump = index % lag == 0
        right, dright = np.full(2, -np.inf), np.zeros(2)
        if index >= lag:
            right, dright = reset(values[index - lag], tangent[index - lag])
        left, dleft = right, dright
        if jump:
            left, dleft = (np.full(2, -np.inf), np.zeros(2)) if index == lag else reset(left_values[index - lag], left_tangents[index - lag])
        obstacle = np.maximum(reward, left[:, None])
        dobstacle = max_direction(reward, left[:, None], dreward, dleft[:, None])
        rhs = values[index - 1] - config["wait_cost"] * dt
        lv, dlv = np.empty((2, count)), np.empty((2, count))
        for mode in range(2):
            lv[mode], primal_record = mixed_lcp(a, lower, upper, rhs[mode], obstacle[mode])
            curvature = np.r_[2 * (lv[mode, 1] - lv[mode, 0]), np.diff(lv[mode], 2),
                              2 * (lv[mode, -2] - lv[mode, -1])]
            dAv = -dt * config["sigma"] / dx ** 2 * d[0] * curvature
            dlv[mode], record = derivative(a, lower, upper, lv[mode], rhs[mode], obstacle[mode],
                tangent[index - 1, mode] - d[1] * dt, dobstacle[mode], dAv,
                np.full(count, 2) if exact_tie_profile else None)
            record.update(index=index, mode=mode, primal_solver=primal_record)
            records.append(record)
        if jump:
            left_values[index], left_tangents[index] = lv, dlv
            values[index] = np.maximum(lv, right[:, None])
            tangent[index] = max_direction(lv, right[:, None], dlv, dright[:, None])
            jumps.append(dict(index=index, exact_max_ties=int(np.sum(lv == right[:, None])),
                              derivative_jump=float(abs(tangent[index] - dlv).max())))
        else:
            values[index], tangent[index] = lv, dlv
    return dict(x=x, times=times, values=values, tangent=tangent, records=records, jumps=jumps,
                exact_tie_profile=exact_tie_profile, parameters=PARAMETERS,
                classification="one-sided fixed-mesh directional derivative; generic unresolved numerical rows remain unqualified")
