"""Jump-aware derivatives of a fixed-grid active branch, not continuum gradients.

Both admission left limits and right values carry tangents. Thirteen smooth
coefficients are covered; mesh, time-delay and domain coordinates are excluded.
At an exact action/interpolation tie a derivative can be nonunique. We expose
branch masks and reject reset interpolation knots rather than hiding that fact.
"""

import numpy as np
from scipy.linalg import solve_banded
from scipy.special import expit

from tools.hcsn.continuous_task_r18_20261101.task import discretization, payoff


PARAMETERS = ("sigma", "wait_cost", "recovery_cost", "reset_x",
              "reset_fee_0", "reset_fee_1", "retention_0", "retention_1",
              "reward_base_0", "reward_base_1", "reward_amplitude_0",
              "reward_amplitude_1", "reward_slope")


def solve(config, dx, dt):
    """Return primal and all thirteen branch tangents, including every jump."""
    x, times, lag = discretization(config, dx, dt)
    position = (config["reset_x"] - config["lower"]) / dx
    cell = int(np.floor(position))
    if cell < 0 or cell >= len(x) - 1 or abs(position - round(position)) < 1e-9:
        raise ValueError("reset_x derivative requires an interior non-knot")
    weight = position - cell
    count, n, p = len(x), len(times), len(PARAMETERS)
    reward = payoff(config, x)
    dreward = np.zeros((2, count, p))
    sigmoid = expit(config["reward_slope"] * x)
    for mode in range(2):
        dreward[mode, :, 8 + mode] = 1.
        dreward[mode, :, 10 + mode] = sigmoid
        dreward[mode, :, 12] = config["reward_amplitude"][mode] * x * sigmoid * (1 - sigmoid)
    values = np.zeros((n, 2, count))
    derivatives = np.zeros((n, 2, count, p))
    values[0], derivatives[0] = reward, dreward
    resets = np.full((n, 2), -np.inf)
    branches = np.ones((n, 2, count), dtype=np.int8)
    left_branches = branches.copy()
    left_values, left_derivatives = {}, {}
    jumps = []
    rate = config["sigma"] ** 2 / (2 * dx * dx)
    lower, upper = np.full(count - 1, rate), np.full(count - 1, rate)
    upper[0], lower[-1] = 2 * rate, 2 * rate
    a, l, u = np.full(count, 1 + 2 * dt * rate), -dt * lower, -dt * upper
    matrix = np.asarray(config["content_transition"])
    fee = np.asarray(config["reset_fee"]) + config["recovery_cost"] * config["recovery"]

    def reset_value(source, tangent):
        future = (1 - weight) * source[:, cell] + weight * source[:, cell + 1]
        dfuture = (1 - weight) * tangent[:, cell] + weight * tangent[:, cell + 1]
        dfuture[:, 3] += (source[:, cell + 1] - source[:, cell]) / dx
        value, derivative = matrix @ future - fee, matrix @ dfuture
        derivative[:, 2] -= config["recovery"]
        for mode in range(2):
            derivative[mode, 4 + mode] -= 1.
            derivative[mode, 6 + mode] += future[mode] - future[1 - mode]
        return value, derivative

    for index in range(1, n):
        jump = index % lag == 0
        db = np.zeros((2, p))
        if index >= lag:
            resets[index], db = reset_value(values[index - lag], derivatives[index - lag])
        left_reset, dleft_reset = resets[index].copy(), db.copy()
        if jump:
            if index == lag:
                left_reset[:] = -np.inf
                dleft_reset[:] = 0.
            else:
                left_reset, dleft_reset = reset_value(left_values[index - lag], left_derivatives[index - lag])
        stop_obstacle = reward >= left_reset[:, None]
        obstacle = np.maximum(reward, left_reset[:, None])
        dobstacle = np.where(stop_obstacle[:, :, None], dreward, dleft_reset[:, None, :])
        rhs = values[index - 1] - config["wait_cost"] * dt
        left_value, dleft_value = np.empty((2, count)), np.empty((2, count, p))
        for mode in range(2):
            value = np.maximum(values[index - 1, mode], obstacle[mode])
            active = value - obstacle[mode] <= a * value + np.r_[0., l * value[:-1]] + np.r_[u * value[1:], 0.] - rhs[mode]
            for _ in range(128):
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
                next_active = candidate - obstacle[mode] <= continuation
                change, value = np.max(abs(candidate - value)), candidate
                if np.array_equal(active, next_active) and change < 2e-12:
                    break
                active = next_active
            else:
                raise RuntimeError("Jump-aware tangent policy iteration failed")
            drhs = derivatives[index - 1, mode].copy()
            drhs[:, 1] -= dt
            curvature = np.r_[2 * (value[1] - value[0]), np.diff(value, 2), 2 * (value[-2] - value[-1])]
            drhs[:, 0] += dt * config["sigma"] / dx ** 2 * curvature
            drhs[indices] = dobstacle[mode, indices]
            dleft_value[mode] = solve_banded((1, 1), band, drhs, check_finite=False)
            left_value[mode] = value
            left_branches[index, mode] = np.where(active, np.where(stop_obstacle[mode], 1, 2), 0)
        if jump:
            left_values[index], left_derivatives[index] = left_value, dleft_value
            take_reset = resets[index, :, None] > left_value
            values[index] = np.maximum(left_value, resets[index, :, None])
            derivatives[index] = np.where(take_reset[:, :, None], db[:, None, :], dleft_value)
            branches[index] = np.where(take_reset, 2, left_branches[index])
            jumps.append(dict(time=float(times[index]), maximum_jump=float(np.max(values[index] - left_value)),
                              derivative_jump_norm=float(np.max(abs(derivatives[index] - dleft_value)))))
        else:
            values[index], derivatives[index] = left_value, dleft_value
            branches[index] = left_branches[index]
    return dict(x=x, times=times, values=values, derivatives=derivatives,
                reset_values=resets, branches=branches, left_branches=left_branches,
                jump_records=jumps, parameters=PARAMETERS)


def perturb(config, parameter, offset):
    """Keep each two-state transition row stochastic under its coordinate."""
    import copy
    if parameter not in PARAMETERS:
        raise ValueError("Unsupported moving-time/domain or unknown coordinate")
    result = copy.deepcopy(config)
    if parameter.startswith("retention_"):
        mode = int(parameter[-1])
        result["content_transition"][mode][mode] += offset
        result["content_transition"][mode][1 - mode] -= offset
    elif parameter.startswith(("reset_fee_", "reward_base_", "reward_amplitude_")):
        name, index = parameter.rsplit("_", 1)
        result[name][int(index)] += offset
    else:
        result[parameter] += offset
    return result
