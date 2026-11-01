"""Independent continuous Neumann-heat semigroup plus Bermudan impulse DP.

The eigenvalues are continuous Laplacian -(k*pi/width)^2, not the FD spectrum.
DCT-I interpolates on cosine collocation nodes with endpoint weighting handled
by the non-orthogonal forward/inverse pair. Constant/cosine tests are separate.
"""

import numpy as np
from scipy.fft import dct, idct

from .task import discretization, payoff


def heat(values, sigma, width, duration):
    frequencies = np.arange(values.shape[-1]) * np.pi / width
    return idct(dct(values, type=1, axis=-1) * np.exp(-.5 * sigma ** 2 * frequencies ** 2 * duration), type=1, axis=-1)


def solve(config, dx, dt):
    x, times, lag = discretization(config, dx, dt)
    reward = payoff(config, x)
    values = np.zeros((len(times), 2, len(x)))
    values[0] = reward
    reset = np.full((len(times), 2), -np.inf)
    matrix = np.asarray(config["content_transition"])
    for index in range(1, len(times)):
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in values[index - lag]])
            reset[index] = matrix @ future - np.asarray(config["reset_fee"]) - config["recovery_cost"] * config["recovery"]
        waiting = heat(values[index - 1], config["sigma"], config["upper"] - config["lower"], dt) - config["wait_cost"] * dt
        values[index] = np.maximum(np.maximum(reward, reset[index, :, None]), waiting)
    return dict(x=x, times=times, values=values, reset_values=reset, lag=lag, dt=dt, dx=dx, config=config)


def semigroup_check():
    x = np.linspace(0., 8., 513)
    values = 1.3 + .17 * np.cos(3 * np.pi * x / 8)
    reference = 1.3 + .17 * np.cos(3 * np.pi * x / 8) * np.exp(-.5 * (3 * np.pi / 8) ** 2 * .37)
    computed = heat(values, 1., 8., .37)
    composed = heat(heat(values, 1., 8., .13), 1., 8., .24)
    return dict(cosine_error=float(abs(computed - reference).max()),
                semigroup_error=float(abs(computed - composed).max()),
                constant_error=float(abs(heat(np.ones(513), 1., 8., .37) - 1).max()))


def solve_fixed(config, dx, dt, thresholds):
    x, times, lag = discretization(config, dx, dt)
    reward = payoff(config, x)
    values = np.zeros((len(times), 2, len(x)))
    values[0] = reward
    low, high = thresholds
    matrix = np.asarray(config["content_transition"])
    for index in range(1, len(times)):
        waiting = heat(values[index - 1], config["sigma"], config["upper"] - config["lower"], dt) - config["wait_cost"] * dt
        values[index] = waiting
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in values[index - lag]])
            reset = matrix @ future - np.asarray(config["reset_fee"]) - config["recovery_cost"] * config["recovery"]
            values[index][:, x <= low] = reset[:, None]
        stop = x >= high
        if index < lag:
            stop |= x <= low
        values[index][:, stop] = reward[:, stop]
    return dict(x=x, times=times, values=values, lag=lag, dt=dt, dx=dx, config=config)
