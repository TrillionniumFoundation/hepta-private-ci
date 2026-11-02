"""All 15 declared trainable task coordinates; no probability/cost clipping."""

import copy

import numpy as np
from scipy.special import expit, logit, softmax

from ..continuous_task_r18_20261101.task import DEFAULT, discretization


NAMES = ("log_sigma", "log_wait_cost", "log_recovery_cost", "log_fee_0", "log_fee_1",
         "reset_x", "mode_logit_00", "mode_logit_01", "mode_logit_10", "mode_logit_11",
         "base_logit_0", "base_logit_1", "amplitude_share_logit_0", "amplitude_share_logit_1", "log_reward_slope")
P = len(NAMES)
FIXED = ("lower", "upper", "horizon", "recovery", "dx", "dt")


class Nondifferentiable(ValueError):
    pass


def encode(config):
    base, amplitude = np.asarray(config["reward_base"]), np.asarray(config["reward_amplitude"])
    m = np.asarray(config["content_transition"])
    positives = [config[k] for k in ("sigma", "wait_cost", "recovery_cost", "reward_slope")] + list(config["reset_fee"])
    if min(positives) <= 0 or not (np.all(base > 0) and np.all(base + amplitude < 1) and np.all(amplitude > 0) and np.all(m > 0)):
        raise ValueError("Trainable chart requires strictly interior costs and probabilities")
    return np.r_[np.log(positives[:3]), np.log(config["reset_fee"]), config["reset_x"], np.log(m).ravel(),
                 logit(base), logit(amplitude / (1 - base)), np.log(config["reward_slope"])]


def decode(raw, fixed=DEFAULT):
    raw = np.asarray(raw, dtype=float)
    if raw.shape != (P,) or not np.isfinite(raw).all():
        raise ValueError("Expected all15 finite raw coordinates")
    result = copy.deepcopy(fixed)
    try:
        with np.errstate(over="raise", invalid="raise", under="ignore"):
            sigma, wait, recover, fee0, fee1 = np.exp(raw[:5])
            slope = np.exp(raw[14])
    except FloatingPointError as error:
        raise ValueError("Unrepresentable positive coordinate") from error
    base, share = expit(raw[10:12]), expit(raw[12:14])
    amplitude, matrix = (1 - base) * share, softmax(raw[6:10].reshape(2, 2), axis=1)
    if min(sigma, wait, recover, fee0, fee1, slope) <= 0 or np.any(base <= 0) or np.any(base >= 1) or np.any(share <= 0) or np.any(share >= 1) or np.any(matrix <= 0):
        raise ValueError("Coordinate loses positive representable support")
    result.update(sigma=float(sigma), wait_cost=float(wait), recovery_cost=float(recover), reset_fee=[float(fee0), float(fee1)],
                  reset_x=float(raw[5]), content_transition=matrix.tolist(), reward_base=base.tolist(),
                  reward_amplitude=amplitude.tolist(), reward_slope=float(slope))
    return result


def differentials(raw, x, fixed=DEFAULT):
    config = decode(raw, fixed)
    zero = np.zeros(P)
    m, b, a, slope = (np.asarray(config[k]) for k in ("content_transition", "reward_base", "reward_amplitude", "reward_slope"))
    dm, dfee = np.zeros((P, 2, 2)), np.zeros((P, 2))
    for mode in range(2):
        dfee[3 + mode, mode] = config["reset_fee"][mode]
        for column in range(2):
            dm[6 + 2 * mode + column, mode] = m[mode] * (np.arange(2) == column) - m[mode] * m[mode, column]
    sigma, wait, recovery, reset_x = (zero.copy() for _ in range(4))
    sigma[0], wait[1], recovery[2], reset_x[5] = config["sigma"], config["wait_cost"], config["recovery_cost"], 1.
    x = np.asarray(x)
    s = expit(slope * x)
    reward = b[:, None] + a[:, None] * s
    dreward = np.zeros((P, 2, len(x)))
    for mode in range(2):
        dreward[10 + mode, mode] = b[mode] * (1 - b[mode]) - b[mode] * a[mode] * s
        share = a[mode] / (1 - b[mode])
        dreward[12 + mode, mode] = a[mode] * (1 - share) * s
        dreward[14, mode] = a[mode] * s * (1 - s) * slope * x
    return config, dict(matrix=dm, fee=dfee, sigma=sigma, wait=wait, recovery=recovery,
                        reset_x=reset_x, reward=dreward), reward


def interpolation(x, state, ordinary=True, direction=0.):
    if not np.isfinite(state) or not x[0] <= state <= x[-1]:
        raise ValueError("Physical state is outside the fixed domain")
    nearest = int(np.argmin(abs(x - state)))
    knot = abs(x[nearest] - state) <= 64 * np.finfo(float).eps * max(1., abs(state))
    if knot and ordinary:
        raise Nondifferentiable("Linear interpolation knot has no unique ordinary state derivative")
    if knot:
        if (nearest == 0 and direction < 0) or (nearest == len(x) - 1 and direction > 0):
            raise Nondifferentiable("Direction leaves the physical state tangent cone")
        lower = nearest if direction >= 0 and nearest < len(x) - 1 else max(0, nearest - 1)
    else:
        lower = int(np.searchsorted(x, state) - 1)
    h = x[lower + 1] - x[lower]
    fraction = (state - x[lower]) / h
    return lower, np.array([1 - fraction, fraction]), np.array([-1 / h, 1 / h])


def query(solution, gradient, time_index, mode, state):
    lower, weights, slopes = interpolation(solution["x"], state)
    values = solution["values"][time_index, mode, lower:lower + 2]
    return float(values @ weights), gradient[time_index, mode, lower:lower + 2].T @ weights, float(values @ slopes)


def time_contract(solution, remaining, state, mode):
    interpolation(solution["x"], state, ordinary=False)
    if mode not in (0, 1) or not np.isfinite(remaining):
        raise ValueError("Invalid public mode or time")
    index = int(round(remaining / solution["dt"]))
    if index < 0 or index >= len(solution["times"]) or abs(index * solution["dt"] - remaining) > 1e-11:
        raise Nondifferentiable("Actual solver exposes a time lattice, not a smooth time interpolation")
    values = solution["values"][index, mode]
    right = float(np.interp(state, solution["x"], values))
    left = float(np.interp(state, solution["x"], solution["left_limits"][index][mode])) if index in solution["left_limits"] else None
    return dict(time=remaining, right_value=right, left_value=left, admission_jump=None if left is None else right - left,
                ordinary_time_gradient=None, recovery_gradient=None,
                reason="T/rho/dx/dt/domain are fixed topology; off-lattice changes rejected. Admission left/right limits are not an ordinary derivative.")
