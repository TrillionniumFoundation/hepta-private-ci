"""Declared continuous evidence-quality/content impulse task, not full He--Xiong.

The state x is publicly observed retrieval quality, not a hidden label/belief.
Content mode is observed; STOP attempts a typed retrieval whose success has the
specified current propensity. No success label enters control before STOP.
"""

import numpy as np
from scipy.special import expit


DEFAULT = dict(lower=-4., upper=4., sigma=1., horizon=1.2, recovery=.2,
               reset_x=.6, wait_cost=.03, recovery_cost=.02,
               reset_fee=[.035, .025], content_transition=[[.90, .10], [.25, .75]],
               reward_base=[.20, .10], reward_amplitude=[.75, .40], reward_slope=1.3)


def payoff(config, x):
    x = np.asarray(x)
    shape = (2,) + (1,) * x.ndim
    return np.asarray(config["reward_base"]).reshape(shape) + np.asarray(
        config["reward_amplitude"]).reshape(shape) * expit(config["reward_slope"] * x)


def payoff_gradient(config, x):
    x = np.asarray(x)
    s = expit(config["reward_slope"] * x)
    return np.asarray(config["reward_amplitude"]).reshape((2,) + (1,) * x.ndim) * config["reward_slope"] * s * (1 - s)


def reflected(config, x):
    """Fold an unconstrained Brownian endpoint into the reflecting interval."""
    width = config["upper"] - config["lower"]
    offset = (np.asarray(x) - config["lower"]) % (2 * width)
    return config["lower"] + np.where(offset <= width, offset, 2 * width - offset)


def discretization(config, dx, dt):
    scalars = [config[k] for k in ("lower", "upper", "sigma", "horizon", "recovery", "reset_x", "wait_cost", "recovery_cost", "reward_slope")]
    if (not np.isfinite(scalars).all() or not np.isfinite([dx, dt]).all()
            or min(dx, dt, config["sigma"], config["horizon"], config["recovery"], config["reward_slope"]) <= 0
            or config["lower"] >= config["upper"] or not config["lower"] <= config["reset_x"] <= config["upper"]
            or min(config["wait_cost"], config["recovery_cost"]) < 0):
        raise ValueError("Invalid finite task law or mesh")
    base, amplitude, fee = (np.asarray(config[k], dtype=float) for k in ("reward_base", "reward_amplitude", "reset_fee"))
    if any(a.shape != (2,) or not np.isfinite(a).all() for a in (base, amplitude, fee)) or (base < 0).any() or (amplitude < 0).any() or (base + amplitude > 1).any() or (fee < 0).any():
        raise ValueError("Invalid content reward or reset fee")
    intervals = int(round((config["upper"] - config["lower"]) / dx))
    steps, lag = int(round(config["horizon"] / dt)), int(round(config["recovery"] / dt))
    if (min(intervals, steps, lag) <= 0
            or abs(intervals * dx - config["upper"] + config["lower"]) > 1e-11
            or abs(steps * dt - config["horizon"]) > 1e-11
            or abs(lag * dt - config["recovery"]) > 1e-11):
        raise ValueError("Space, horizon and recovery must fit the registered meshes")
    matrix = np.asarray(config["content_transition"], dtype=float)
    if matrix.shape != (2, 2) or not np.isfinite(matrix).all() or (matrix < 0).any() or not np.allclose(matrix.sum(1), 1, rtol=0, atol=1e-14):
        raise ValueError("Content transition must be stochastic")
    return np.linspace(config["lower"], config["upper"], intervals + 1), np.arange(steps + 1) * dt, lag
