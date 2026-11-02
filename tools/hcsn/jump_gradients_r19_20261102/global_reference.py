"""Independent all-time sparse linear-system derivative on a frozen regular branch.

This does not import the forward tangent engine, its reset Jacobian, its band
matrices or its reward partials. It independently assembles every causal
left/right equation and the physical/chart parameter RHS in one sparse system.
"""

import numpy as np
from scipy.special import expit
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


P = 15


def solve(solution):
    cfg, x, dt, dx, lag = (solution[k] for k in ("config", "x", "dt", "dx", "lag"))
    v, m, n = solution["values"], np.asarray(cfg["content_transition"]), len(x)
    base, amp = np.asarray(cfg["reward_base"]), np.asarray(cfg["reward_amplitude"])
    sigmoid = expit(cfg["reward_slope"] * x)
    reward = base[:, None] + amp[:, None] * sigmoid
    dg = np.zeros((2, n, P))
    for mode in range(2):
        dg[mode, :, 10 + mode] = base[mode] * (1 - base[mode]) - base[mode] * amp[mode] * sigmoid
        dg[mode, :, 12 + mode] = amp[mode] * (1 - amp[mode] / (1 - base[mode])) * sigmoid
        dg[mode, :, 14] = amp[mode] * sigmoid * (1 - sigmoid) * cfg["reward_slope"] * x
    offsets, unknowns = {}, 0
    for time in range(len(v)):
        if time and time % lag == 0:
            offsets[time, "left"] = unknowns
            unknowns += 2 * n
        offsets[time, "right"] = unknowns
        if (time, "left") not in offsets:
            offsets[time, "left"] = unknowns
        unknowns += 2 * n
    rows, cols, data = [], [], []
    rhs = np.zeros((unknowns, P))
    rate = cfg["sigma"] ** 2 / (2 * dx * dx)
    low = int(np.searchsorted(x, cfg["reset_x"]) - 1)
    w = np.array([(x[low + 1] - cfg["reset_x"]) / dx, (cfg["reset_x"] - x[low]) / dx])

    def at(time, side, mode, cell):
        return offsets[time, side] + mode * n + cell

    def add(row, column, coefficient):
        rows.append(row); cols.append(column); data.append(coefficient)

    def reset_row(row, time, side, mode, primal):
        f = primal[:, low:low + 2] @ w
        for destination in range(2):
            for k in range(2):
                add(row, at(time, side, destination, low + k), -m[mode, destination] * w[k])
        rhs[row, 2] = -cfg["recovery"] * cfg["recovery_cost"]
        rhs[row, 3 + mode] = -cfg["reset_fee"][mode]
        rhs[row, 5] = m[mode] @ ((primal[:, low + 1] - primal[:, low]) / dx)
        for column in range(2):
            rhs[row, 6 + 2 * mode + column] = np.sum(m[mode] * ((np.arange(2) == column) - m[mode, column]) * f)

    for mode in range(2):
        for cell in range(n):
            row = at(0, "right", mode, cell)
            add(row, row, 1.); rhs[row] = dg[mode, cell]
    for time in range(1, len(v)):
        is_jump = time % lag == 0
        left = solution["left_limits"].get(time, v[time])
        left_reset = np.full(2, -np.inf)
        future_side = "left" if is_jump else "right"
        if time >= lag and not (is_jump and time == lag):
            past = solution["left_limits"][time - lag] if is_jump else v[time - lag]
            left_reset = m @ (past[:, low:low + 2] @ w) - np.asarray(cfg["reset_fee"]) - cfg["recovery_cost"] * cfg["recovery"]
        for mode in range(2):
            for cell in range(n):
                row = at(time, "left", mode, cell)
                obstacle = max(reward[mode, cell], left_reset[mode])
                if left[mode, cell] - obstacle < 1e-10:
                    add(row, row, 1.)
                    if reward[mode, cell] >= left_reset[mode]:
                        rhs[row] = dg[mode, cell]
                    else:
                        reset_row(row, time - lag, future_side, mode, past)
                else:
                    add(row, row, 1 + 2 * dt * rate)
                    add(row, at(time - 1, "right", mode, cell), -1.)
                    qvalue = -2 * rate * left[mode, cell]
                    for neighbor, multiplier in ((cell - 1, 2 if cell == n - 1 else 1), (cell + 1, 2 if cell == 0 else 1)):
                        if 0 <= neighbor < n:
                            add(row, at(time, "left", mode, neighbor), -dt * rate * multiplier)
                            qvalue += rate * multiplier * left[mode, neighbor]
                    rhs[row, 0] = 2 * dt * qvalue
                    rhs[row, 1] = -dt * cfg["wait_cost"]
        if is_jump:
            for mode in range(2):
                for cell in range(n):
                    row = at(time, "right", mode, cell)
                    add(row, row, 1.)
                    if left[mode, cell] >= solution["reset_values"][time, mode]:
                        add(row, at(time, "left", mode, cell), -1.)
                    else:
                        reset_row(row, time - lag, "right", mode, v[time - lag])
    matrix = coo_matrix((data, (rows, cols)), shape=(unknowns, unknowns)).tocsc()
    answer = spsolve(matrix, rhs, permc_spec="NATURAL")
    residual = float(np.max(abs(matrix @ answer - rhs)))
    result = np.stack([answer[offsets[t, "right"]:offsets[t, "right"] + 2 * n].reshape(2, n, P) for t in range(len(v))])
    left = {t: answer[offsets[t, "left"]:offsets[t, "left"] + 2 * n].reshape(2, n, P) for t in solution["left_limits"]}
    return dict(jacobian=result, left_jacobians=left, maximum_equation_residual=residual,
                equations=unknowns, nonzeros=int(matrix.nnz))
