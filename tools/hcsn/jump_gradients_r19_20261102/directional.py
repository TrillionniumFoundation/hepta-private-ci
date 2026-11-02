"""One-sided Hadamard derivative of discrete min/max at critical branches.

At a strict obstacle row dy=dF; at strict continuation A dy=drhs-dA*y.
At a biactive row min(dy-dF, A*dy-drhs+dA*y)=0. This critical-cone LCP
is solved, not replaced by a straight-through derivative of a hard decision.
"""

import numpy as np
from scipy.linalg import solve_banded

from .coordinates import differentials, interpolation
from .tangent import TOL, coefficients, left_info


def solve(solution, raw, direction):
    config, d, reward = differentials(raw, solution["x"], solution["config"])
    direction = np.asarray(direction, dtype=float)
    if direction.shape != (15,) or not np.isfinite(direction).all():
        raise ValueError("Expected15finite direction coordinates")
    dr = np.einsum("pmi,p->mi", d["reward"], direction)
    dm, dk = np.einsum("pml,p->ml", d["matrix"], direction), direction @ d["fee"]
    dxreset, dc, drec = float(direction @ d["reset_x"]), float(direction @ d["wait"]), float(direction @ d["recovery"])
    lower, diagonal, upper = coefficients(solution)
    values, lag, dt = solution["values"], solution["lag"], solution["dt"]
    derivative = np.zeros_like(values); derivative[0] = dr
    left_derivatives = {}
    low, weights, slopes = interpolation(solution["x"], config["reset_x"], ordinary=False, direction=dxreset)

    def reset(past, dpast):
        f = past[:, low:low + 2] @ weights
        df = dpast[:, low:low + 2] @ weights + (past[:, low:low + 2] @ slopes) * dxreset
        return np.asarray(config["content_transition"]) @ df + dm @ f - dk - config["recovery"] * drec

    for index in range(1, len(values)):
        left, b, choices, critical, tie = left_info(solution, index)
        db, right_db = np.zeros(2), np.zeros(2)
        if index >= lag:
            right_db = reset(values[index - lag], derivative[index - lag])
            if index % lag:
                db = right_db
            elif index > lag:
                db = reset(solution["left_limits"][index - lag], left_derivatives[index - lag])
        dleft = np.zeros_like(left)
        for mode in range(2):
            dg, dreset = dr[mode], np.full(len(solution["x"]), db[mode])
            dobstacle = np.where(reward[mode] > b[mode] + TOL, dg,
                np.where(b[mode] > reward[mode] + TOL, dreset, np.maximum(dg, dreset)))
            rhs = derivative[index - 1, mode] - dt * dc
            curvature = np.r_[2 * (left[mode, 1] - left[mode, 0]), np.diff(left[mode], 2), 2 * (left[mode, -2] - left[mode, -1])]
            rhs += dt * config["sigma"] ** 2 / solution["dx"] ** 2 * curvature * direction[0]
            fixed = (choices[mode] != 0) & ~critical[mode]
            free = critical[mode]
            value = np.zeros(len(solution["x"]))
            active = fixed.copy()
            for _ in range(128):
                band = np.zeros((3, len(value)))
                band[0, 1:], band[1], band[2, :-1] = upper, diagonal, lower
                indices = np.flatnonzero(active)
                band[1, indices] = 1.
                band[0, indices[indices < len(value) - 1] + 1] = 0.
                band[2, indices[indices > 0] - 1] = 0.
                target = rhs.copy(); target[active] = dobstacle[active]
                candidate = solve_banded((1, 1), band, target, check_finite=False)
                residual = diagonal * candidate + np.r_[0., lower * candidate[:-1]] + np.r_[upper * candidate[1:], 0.] - rhs
                new_active = fixed | (free & (candidate - dobstacle <= residual))
                change, value = np.max(abs(candidate - value)), candidate
                if np.array_equal(active, new_active) and change < 2e-11:
                    break
                active = new_active
            else:
                raise RuntimeError("Critical-cone tangent LCP did not converge")
            dleft[mode] = value
        if index % lag == 0:
            left_derivatives[index] = dleft.copy()
            reset_primal = solution["reset_values"][index, :, None]
            derivative[index] = np.where(left > reset_primal + TOL, dleft,
                np.where(reset_primal > left + TOL, right_db[:, None], np.maximum(dleft, right_db[:, None])))
        else:
            derivative[index] = dleft
    return dict(derivative=derivative, left_derivatives=left_derivatives)
