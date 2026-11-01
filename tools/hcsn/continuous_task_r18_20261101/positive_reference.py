"""Positive Gaussian-image heat integration of an even linear interpolant.

An even 2L-periodic extension represents reflecting Brownian motion. Positive
Gauss quadrature integrates Gaussian density against each nonnegative hat.
There is no spectral sign repair, clipping or row renormalization. Repeated
linear projection is an explicitly refined approximation, not an exact finite
semigroup. Continuous heat dynamics, interpolation and decisions are separate.
"""

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.special import log_ndtr

from .task import discretization, payoff


def kernel(sigma, width, intervals, duration, nodes=8):
    h, sd = width / intervals, sigma * np.sqrt(duration)
    offsets = np.arange(2 * intervals) * h
    offsets = np.where(offsets <= width, offsets, offsets - 2 * width)
    points, weights = leggauss(nodes)
    probabilities = np.zeros(2 * intervals)
    for direction in (-1, 1):
        u = direction * (points + 1) * h / 2
        w = weights * h / 2 * (1 - abs(u) / h)
        for image in range(-2, 3):
            distance = offsets[:, None] + u[None, :] + 2 * image * width
            density = np.exp(-.5 * (distance / sd) ** 2) / (np.sqrt(2 * np.pi) * sd)
            probabilities += density @ w
    return dict(weights=probabilities, fft=np.fft.rfft(probabilities),
        minimum_weight=float(probabilities.min()), mass_error=float(abs(probabilities.sum() - 1)),
        log_omitted_image_tail_bound=float(np.log(4.) + log_ndtr(-(5 * width - h) / sd)),
        dx=h, dt=duration, quadrature_nodes_per_half_hat=nodes)


def heat(values, operator):
    extended = np.concatenate((values, values[..., -2:0:-1]), axis=-1)
    return np.fft.irfft(np.fft.rfft(extended, axis=-1) * operator["fft"], n=extended.shape[-1], axis=-1)[..., :values.shape[-1]]


def solve(config, dx, dt, thresholds=None, nodes=8):
    x, times, lag = discretization(config, dx, dt)
    reward = payoff(config, x)
    values = np.zeros((len(times), 2, len(x)))
    values[0] = reward
    reset = np.full((len(times), 2), -np.inf)
    matrix = np.asarray(config["content_transition"])
    operator = kernel(config["sigma"], config["upper"] - config["lower"], len(x) - 1, dt, nodes)
    for index in range(1, len(times)):
        if index >= lag:
            future = np.array([np.interp(config["reset_x"], x, row) for row in values[index - lag]])
            reset[index] = matrix @ future - np.asarray(config["reset_fee"]) - config["recovery_cost"] * config["recovery"]
        waiting = heat(values[index - 1], operator) - config["wait_cost"] * dt
        if thresholds is None:
            values[index] = np.maximum(np.maximum(reward, reset[index, :, None]), waiting)
        else:
            values[index] = waiting
            for mode, (low, high) in enumerate(thresholds):
                if index >= lag:
                    values[index, mode, x <= low] = reset[index, mode]
                stop = x >= high
                if index < lag:
                    stop |= x <= low
                values[index, mode, stop] = reward[mode, stop]
    return dict(x=x, times=times, values=values, reset_values=reset, lag=lag, dt=dt, dx=dx,
                config=config, operator=operator)
