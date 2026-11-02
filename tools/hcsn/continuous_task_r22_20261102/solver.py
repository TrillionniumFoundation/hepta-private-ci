"""R22 traced fixed-mesh directional solve and explicit nonconstant tie witness.

R20's local derivative formulas are retained. Qualification is supplied by the
separate interval residual/branch certificate, not finite-step agreement.
"""

import numpy as np
from scipy.special import expit

from tools.hcsn.continuous_task_r18_20261101.task import discretization, payoff
from tools.hcsn.continuous_task_r20_20261101.directional import apply, derivative, max_direction, mixed_lcp
from tools.hcsn.continuous_task_r20_20261101.task_directional import perturb


def nonconstant_tie(config, d, dx, dt):
    expected = dict(lower=-4., upper=4., sigma=1., reset_x=0., wait_cost=2., recovery_cost=0., recovery=.25,
        horizon=.25, reward_base=[.25, .125], reward_amplitude=[.75, .5],
        reward_slope=1., reset_fee=[.125, .0625], content_transition=[[.75, .25], [.25, .75]])
    return all(config[k] == v for k, v in expected.items()) and (dx, dt) in ((.5, .125), (.25, .0625)) and np.count_nonzero(d) == 1 and d[5] != 0


def solve(config, direction, dx, dt, plan=None):
    d = np.asarray(direction, dtype=float)
    perturb(config, d, 0.)
    x, times, lag = discretization(config, dx, dt)
    pairs = [(config["wait_cost"], d[1]), (config["recovery_cost"], d[2])]
    pairs += list(zip(config["reset_fee"], d[4:6])) + list(zip(config["reward_base"], d[8:10])) + list(zip(config["reward_amplitude"], d[10:12]))
    if any(value == 0 and slope < 0 for value, slope in pairs):
        raise ValueError("Direction leaves the nonnegative tangent cone")
    for j in range(2):
        if config["reward_base"][j] + config["reward_amplitude"][j] == 1 and d[8 + j] + d[10 + j] > 0:
            raise ValueError("Direction leaves the probability tangent cone")
        retention = config["content_transition"][j][j]
        if (retention == 0 and d[6 + j] < 0) or (retention == 1 and d[6 + j] > 0):
            raise ValueError("Direction leaves the stochastic-row tangent cone")
    if not config["lower"] < config["reset_x"] < config["upper"]:
        raise ValueError("Interior reset point required")
    n, count = len(times), len(x)
    reward = payoff(config, x)
    s = expit(config["reward_slope"] * x)
    dg = np.array([d[8 + j] + d[10 + j] * s + config["reward_amplitude"][j] * x * s * (1 - s) * d[12] for j in range(2)])
    v, z, lv, lz = [np.zeros((n, 2, count)) for _ in range(4)]
    v[0], z[0], lv[0], lz[0] = reward, dg, reward, dg
    actions, outer = np.ones((n, 2, count), dtype=np.int8), np.zeros((n, 2, count), dtype=np.int8)
    right_b, left_b, right_db, left_db = [np.full((n, 2), -np.inf) for _ in range(4)]
    rate = config["sigma"] ** 2 / (2 * dx ** 2)
    a, lower, upper = np.full(count, 1 + 2 * dt * rate), np.full(count - 1, -dt * rate), np.full(count - 1, -dt * rate)
    lower[-1] *= 2
    upper[0] *= 2
    matrix = np.asarray(config["content_transition"])
    dm = np.array([[d[6], -d[6]], [-d[7], d[7]]])
    fee = np.asarray(config["reset_fee"]) + config["recovery_cost"] * config["recovery"]
    dfee = d[4:6] + d[2] * config["recovery"]
    cell = int(np.searchsorted(x, config["reset_x"], side="right") - 1)
    if config["reset_x"] == x[cell] and d[3] < 0:
        cell -= 1
    width = x[cell + 1] - x[cell]
    w = (config["reset_x"] - x[cell]) / width

    def reset(values, slopes):
        f = (1 - w) * values[:, cell] + w * values[:, cell + 1]
        df = (1 - w) * slopes[:, cell] + w * slopes[:, cell + 1] + d[3] * (values[:, cell + 1] - values[:, cell]) / width
        return matrix @ f - fee, matrix @ df + dm @ f - dfee

    witness = nonconstant_tie(config, d, dx, dt)
    records = []
    for k in range(1, n):
        jump = k % lag == 0
        if k >= lag:
            right_b[k], right_db[k] = reset(v[k - lag], z[k - lag])
            left_b[k], left_db[k] = right_b[k], right_db[k]
            if jump:
                if k == lag:
                    left_b[k], left_db[k] = -np.inf, 0.
                else:
                    left_b[k], left_db[k] = reset(lv[k - lag], lz[k - lag])
        obstacle = np.maximum(reward, left_b[k, :, None])
        dobs = max_direction(reward, left_b[k, :, None], dg, left_db[k, :, None])
        rhs = v[k - 1] - config["wait_cost"] * dt
        for mode in range(2):
            lv[k, mode], _ = mixed_lcp(a, lower, upper, rhs[mode], obstacle[mode])
            curvature = np.r_[2 * (lv[k, mode, 1] - lv[k, mode, 0]), np.diff(lv[k, mode], 2), 2 * (lv[k, mode, -2] - lv[k, mode, -1])]
            dAv = -dt * config["sigma"] / dx ** 2 * d[0] * curvature
            exact_states, selected_dobs = None, dobs[mode]
            if plan is not None:
                selected = plan["left"][k, mode]
                exact_states = (selected != 0).astype(np.int8)
                selected_dobs = np.where(selected == 1, dg[mode], np.where(selected == 2, left_db[k, mode], 0.))
            lz[k, mode], record = derivative(a, lower, upper, lv[k, mode], rhs[mode], obstacle[mode],
                z[k - 1, mode] - d[1] * dt, selected_dobs, dAv, exact_states)
            records.append(record)
            slacks = np.array([abs(apply(a, lower, upper, lv[k, mode]) - rhs[mode]),
                abs(lv[k, mode] - reward[mode]), abs(lv[k, mode] - left_b[k, mode])])
            actions[k, mode] = np.argmin(slacks, axis=0)
            if plan is not None:
                actions[k, mode] = plan["left"][k, mode]
        if jump:
            v[k] = np.maximum(lv[k], right_b[k, :, None])
            z[k] = max_direction(lv[k], right_b[k, :, None], lz[k], right_db[k, :, None])
            outer[k] = right_b[k, :, None] > lv[k]
            if witness and k == lag:
                at = int(np.flatnonzero(x == 0)[0])
                z[k, 1, at] = max(lz[k, 1, at], right_db[k, 1])
                outer[k, 1, at] = right_db[k, 1] > lz[k, 1, at]
            if plan is not None:
                outer[k] = plan["outer"][k]
                z[k] = np.where(outer[k] == 1, right_db[k, :, None], lz[k])
        else:
            v[k], z[k] = lv[k], lz[k]
    if not all(np.isfinite(t).all() for t in (v, z, lv, lz)):
        raise RuntimeError("Nonfinite task solve")
    return dict(config=config, direction=d, dx=dx, dt=dt, x=x, lag=lag, values=v, tangent=z,
        left_values=lv, left_tangent=lz, actions=actions, outer=outer, right_b=right_b,
        left_b=left_b, right_db=right_db, left_db=left_db, reward=reward, dreward=dg,
        diagonal=a, lower=lower, upper=upper, records=records, known_nonconstant_tie=witness,
        certified_policy_supplied=plan is not None)
