"""Independent dense conditioning and fixed-order continuation references.

This module does not import the production posterior or continuation kernel.
Gaussian conditioning uses multivariate Cholesky solves. Continuation uses
independent bisection and Gauss-Legendre integration, not adaptive quadrature.
Order-doubling differences are diagnostics, not rigorous error certificates.
"""

from functools import lru_cache
import math

import numpy as np
from scipy.integrate import quad
from scipy.linalg import cho_factor, cho_solve
from scipy.special import logsumexp


SCHEMA = 'hepta.conditional-law.v4'
LOG_NORMALIZER = 0.5 * math.log(2 * math.pi)


def components(law):
    if (set(law) != {'schema', 'weights', 'means', 'variances', 'semantics'}
            or law['schema'] != SCHEMA or law['semantics'] != 'terminal'):
        raise ValueError('An explicit terminal Gaussian-mixture law is required')
    weights, means, variances = [np.asarray(law[key], dtype=float)
                                  for key in ('weights', 'means', 'variances')]
    if (weights.ndim != 1 or not 1 <= len(weights) <= 2
            or means.shape != weights.shape or variances.shape != weights.shape
            or not all(np.isfinite(x).all() for x in (weights, means, variances))
            or np.any(weights <= 0) or np.any(variances <= 0)
            or abs(float(weights.sum()) - 1) > 1e-12):
        raise ValueError('One or two finite positive Gaussian components required')
    return weights / weights.sum(), means, variances


def dense_posterior(prior, residuals, variances, noise_scale=1.0):
    weights, means, latent_variances = components(prior)
    observations, sensor_variances = np.asarray(residuals, float), np.asarray(variances, float)
    if (observations.ndim != 1 or not 1 <= len(observations) <= 2
            or observations.shape != sensor_variances.shape
            or not np.isfinite(observations).all() or not np.isfinite(sensor_variances).all()
            or np.any(sensor_variances <= 0) or not math.isfinite(noise_scale) or noise_scale <= 0):
        raise ValueError('One or two acquired observations and positive variances required')
    count = len(observations)
    posterior_means, posterior_variances, log_joint = [], [], []
    for weight, mean, variance in zip(weights, means, latent_variances):
        covariance = variance * np.ones((count, count)) + np.diag(noise_scale * sensor_variances)
        factor = cho_factor(covariance, lower=True)
        residual = observations - mean
        solved = cho_solve(factor, residual)
        cross = np.full(count, variance)
        posterior_means.append(float(mean + cross @ solved))
        posterior_variances.append(float(variance - cross @ cho_solve(factor, cross)))
        log_joint.append(math.log(weight) - count * LOG_NORMALIZER
                         - float(np.log(np.diag(factor[0])).sum()) - 0.5 * float(residual @ solved))
    conditional_weights = np.exp(np.asarray(log_joint) - logsumexp(log_joint))
    result = {'schema': SCHEMA, 'semantics': 'terminal', 'weights': conditional_weights.tolist(),
              'means': posterior_means, 'variances': posterior_variances}
    components(result)
    return result


def posterior_moments_at(law, values, noise_variance):
    """Vectorized one-sensor Cholesky reference, retaining component uncertainty."""
    weights, means, variances = components(law)
    values = np.asarray(values, float)
    if not math.isfinite(noise_variance) or noise_variance <= 0 or not np.isfinite(values).all():
        raise ValueError('Finite sensor arguments and positive variance required')
    component_means, component_variances, log_joint = [], [], []
    for weight, mean, variance in zip(weights, means, variances):
        factor = cho_factor(np.array([[variance + noise_variance]]), lower=True)
        precision = float(cho_solve(factor, np.ones(1))[0])
        difference = values - mean
        component_means.append(mean + variance * precision * difference)
        component_variances.append(variance - variance * variance * precision)
        log_joint.append(math.log(weight) - LOG_NORMALIZER - math.log(float(factor[0][0, 0]))
                         - 0.5 * precision * difference * difference)
    log_joint = np.asarray(log_joint)
    responsibilities = np.exp(log_joint - logsumexp(log_joint, axis=0))
    component_means = np.asarray(component_means)
    posterior_mean = np.sum(responsibilities * component_means, axis=0)
    reshape = (len(weights),) + (1,) * values.ndim
    posterior_variance = np.sum(responsibilities * (
        np.asarray(component_variances).reshape(reshape)
        + (component_means - posterior_mean) ** 2), axis=0)
    return posterior_mean, posterior_variance


def mean_crossing(law, noise_variance, target):
    """Expanding symmetric bracket and bisection; no affine bracket/root solver reuse."""
    _, means, variances = components(law)
    radius = 1 + float(np.max(np.abs(means))) + math.sqrt(float(variances.max()) + noise_variance) + abs(target)
    lower, upper = -radius, radius
    for _ in range(80):
        values, _ = posterior_moments_at(law, [lower, upper], noise_variance)
        if values[0] <= target <= values[1]:
            break
        lower, upper = lower * 2, upper * 2
    else:
        raise ArithmeticError('Could not bracket a posterior-mean crossing')
    for _ in range(100):
        middle = lower + (upper - lower) / 2
        if middle in (lower, upper):
            break
        value = float(posterior_moments_at(law, middle, noise_variance)[0])
        if value < target:
            lower = middle
        else:
            upper = middle
    return lower + (upper - lower) / 2


@lru_cache(maxsize=4)
def _legendre(order):
    return np.polynomial.legendre.leggauss(order)


def continuation_reference(law, noise_variance, repair_cost, *, order=256, limit=12.0):
    """Fixed Gaussian quadrature on each component, split at independent roots."""
    weights, means, variances = components(law)
    if (not math.isfinite(noise_variance) or noise_variance <= 0
            or not math.isfinite(repair_cost) or repair_cost <= 0
            or type(order) is not int or order < 16 or not 8 <= limit <= 16):
        raise ValueError('Positive finite cost/noise and declared quadrature domain required')
    threshold = math.sqrt(repair_cost)
    roots = [mean_crossing(law, noise_variance, sign * threshold) for sign in (-1, 1)]
    nodes, node_weights = _legendre(order)
    result = 0.0
    for weight, mean, variance in zip(weights, means, variances + noise_variance):
        scale = math.sqrt(float(variance))
        cuts = [-limit] + [(root - mean) / scale for root in roots
                          if -limit < (root - mean) / scale < limit] + [limit]
        for left, right in zip(cuts, cuts[1:]):
            midpoint, radius = (left + right) / 2, (right - left) / 2
            z = midpoint + radius * nodes
            posterior_mean, _ = posterior_moments_at(law, mean + scale * z, noise_variance)
            density = np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
            result += weight * radius * float(node_weights @ (density * np.maximum(posterior_mean ** 2 - repair_cost, 0)))
    return float(result)


def gaussian_continuation(law, noise_variance, repair_cost):
    """Independent truncated-normal second moments for a one-component law."""
    weights, means, variances = components(law)
    if len(weights) != 1 or noise_variance <= 0 or repair_cost <= 0:
        raise ValueError('One Gaussian and positive noise/cost required')
    mean, sigma = float(means[0]), float(variances[0] / math.sqrt(variances[0] + noise_variance))
    threshold = math.sqrt(repair_cost)
    left, right = (-threshold - mean) / sigma, (threshold - mean) / sigma
    phi = lambda x: math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    mass_left = 0.5 * math.erfc(-left / math.sqrt(2))
    mass_right = 0.5 * math.erfc(right / math.sqrt(2))
    left_second = ((mean * mean + sigma * sigma) * mass_left
                   - sigma * (2 * mean + sigma * left) * phi(left))
    right_second = ((mean * mean + sigma * sigma) * mass_right
                    + sigma * (2 * mean + sigma * right) * phi(right))
    return max(0.0, left_second + right_second - repair_cost * (mass_left + mass_right))


def _log_normal_tail(nonnegative):
    integral, _ = quad(lambda offset: math.exp(-nonnegative * offset - offset * offset / 2),
                       0, np.inf, epsabs=1e-13, epsrel=1e-13, limit=100)
    return -0.5 * nonnegative ** 2 - LOG_NORMALIZER + math.log(integral)


def normal_event_logs(mean, variance, lower, upper):
    if not all(math.isfinite(x) for x in (mean, variance, lower, upper)) or variance <= 0 or lower > upper:
        raise ValueError('Finite positive-variance Gaussian and ordered finite bounds required')
    scale = math.sqrt(variance)
    a, b = (lower - mean) / scale, (upper - mean) / scale
    put = _log_normal_tail(-a) if a <= 0 else math.log1p(-math.exp(_log_normal_tail(a)))
    call = _log_normal_tail(b) if b >= 0 else math.log1p(-math.exp(_log_normal_tail(-b)))
    interval = -math.inf
    if a < b:
        midpoint, half_width = a + (b - a) / 2, (b - a) / 2
        anchor = max(a, min(0.0, b))
        integral, _ = quad(lambda u: math.exp(-0.5 * ((midpoint + half_width * u) ** 2 - anchor ** 2)),
                           -1, 1, epsabs=1e-13, epsrel=1e-13)
        interval = -0.5 * anchor ** 2 - LOG_NORMALIZER + math.log(half_width) + math.log(integral)
    return np.array([put, interval, call])


def event_logs(law, lower, upper):
    weights, means, variances = components(law)
    values = np.asarray([normal_event_logs(m, v, lower, upper) for m, v in zip(means, variances)])
    return logsumexp(np.log(weights)[:, None] + values, axis=0)


def noise_objective(log_scale, sensor_errors, declared_variances):
    """Supervised sensor NLL and derivative with respect to log noise scale."""
    errors, variances = np.asarray(sensor_errors, float), np.asarray(declared_variances, float)
    if (errors.shape != variances.shape or errors.size == 0 or not np.isfinite(errors).all()
            or not np.isfinite(variances).all() or np.any(variances <= 0)
            or not math.isfinite(log_scale)):
        raise ValueError('Finite matching supervised sensor errors and positive variances required')
    scale = math.exp(log_scale)
    squared = errors * errors / (scale * variances)
    return (float(0.5 * np.mean(np.log(2 * math.pi * scale * variances) + squared)),
            float(0.5 * np.mean(1 - squared)))
