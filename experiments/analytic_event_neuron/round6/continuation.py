"""One-step value integration for an acquired terminal residual law.

The residual is constant over this task. This is neither a first-passage
probability nor a propagation operator for a resetting physical neuron.
"""

import math

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import ndtr

from ..round3.feedback import positive_square_expectation
from ..round4.runtime_law import Q24, validate_law
from ..round4.runtime_owner import validate_public


NORMAL_LIMIT = 12.0
ABSOLUTE_TOLERANCE = 1e-11
RELATIVE_TOLERANCE = 2e-10
ROUNDING_LOSS_BOUND = 1.0 / (4 * Q24 * Q24)


def _conditioning(weights, means, variances, noise):
    predictive = variances + noise
    gains = variances / predictive
    intercepts = means * (1 - gains)
    log_weights = np.log(weights) - .5 * np.log(2 * math.pi * predictive)
    tuples = tuple(zip(log_weights, means, predictive, gains, intercepts))

    def mean_at(value):
        logs = [logw - .5 * (value - mean) ** 2 / variance
                for logw, mean, variance, _, _ in tuples]
        largest = max(logs)
        scaled = [math.exp(logw - largest) for logw in logs]
        return sum(weight * (intercept + gain * value)
                   for weight, (_, _, _, gain, intercept) in zip(scaled, tuples)) / sum(scaled)

    def crossing(target):
        # Each component posterior mean is affine with positive slope. Their
        # crossing locations bracket the mixture crossing, regardless of its
        # observation-dependent posterior component weights.
        locations = (target - intercepts) / gains
        lower, upper = float(locations.min()), float(locations.max())
        if lower == upper:
            return lower
        padding = 64 * np.finfo(float).eps * (1 + abs(lower) + abs(upper)) / float(gains.min())
        return float(brentq(lambda value: mean_at(value) - target,
                           lower - padding, upper + padding,
                           xtol=1e-11, rtol=8 * np.finfo(float).eps, maxiter=150))

    return predictive, intercepts, mean_at, crossing


def continuation_value(law, noise_variance, repair_cost):
    """Return E[(E[E | next acquired sensor]**2 - cost)+] and diagnostics.

    The supplied law is already conditioned on acquired observations. No
    unacquired observation or private target is an input. The returned SciPy
    quadrature estimate is explicitly distinct from an analytic truncation
    upper bound and is not an interval-arithmetic certificate.
    """
    weights, means, variances = validate_law(law)
    if (not math.isfinite(noise_variance) or noise_variance <= 0
            or not math.isfinite(repair_cost) or repair_cost <= 0):
        raise ValueError("Positive finite sensor variance and repair cost required")
    if len(weights) == 1:
        updated_mean_variance = float(variances[0] ** 2 / (variances[0] + noise_variance))
        value = positive_square_expectation(float(means[0]), updated_mean_variance, repair_cost)
        return value, {"method": "normal-positive-square-closed-form",
                       "quadrature_error_estimate": 0.0, "truncation_upper_bound": 0.0,
                       "quadrature_evaluations": 0, "crossings": None,
                       "floating_point_error_bound_claimed": False}

    predictive, intercepts, mean_at, crossing = _conditioning(weights, means, variances, noise_variance)
    cutoff = math.sqrt(repair_cost)
    roots = (crossing(-cutoff), crossing(cutoff))
    if not roots[0] < roots[1]:
        raise ArithmeticError("Positive-cost posterior crossings must be ordered")
    value, error, evaluations, truncation = 0.0, 0.0, 0, 0.0
    tail_probability = 2 * float(ndtr(-NORMAL_LIMIT))
    density_at_limit = math.exp(-.5 * NORMAL_LIMIT ** 2) / math.sqrt(2 * math.pi)
    second_tail_moment = 2 * (NORMAL_LIMIT * density_at_limit + float(ndtr(-NORMAL_LIMIT)))
    intercept_bound = float(np.max(np.abs(intercepts)))
    for weight, mean, variance in zip(weights, means, predictive):
        sigma = math.sqrt(float(variance))
        cutpoints = [(root - float(mean)) / sigma for root in roots]

        def integrand(standardized):
            posterior_mean = mean_at(float(mean) + sigma * standardized)
            payoff = max(posterior_mean * posterior_mean - repair_cost, 0.0)
            return payoff * math.exp(-.5 * standardized * standardized) / math.sqrt(2 * math.pi)

        intervals = ((-NORMAL_LIMIT, min(NORMAL_LIMIT, cutpoints[0])),
                     (max(-NORMAL_LIMIT, cutpoints[1]), NORMAL_LIMIT))
        for lower, upper in intervals:
            if lower >= upper:
                continue
            result = quad(integrand, lower, upper, epsabs=ABSOLUTE_TOLERANCE,
                          epsrel=RELATIVE_TOLERANCE, limit=150, full_output=1)
            if len(result) != 3:
                raise ArithmeticError("Continuation quadrature did not converge: " + str(result[3]))
            part, estimate, information = result
            value += float(weight) * part
            error += float(weight) * estimate
            evaluations += information["neval"]
        # |posterior mean(y)| <= |y| + max_j |m_j (1-gain_j)|.
        # For y=m_i+s_i Z, square <= 3(m_i^2+s_i^2 Z^2+B^2).
        truncation += 3 * float(weight) * (
            (float(mean) ** 2 + intercept_bound ** 2) * tail_probability
            + float(variance) * second_tail_moment)
    if not math.isfinite(value) or value < 0 or not math.isfinite(error):
        raise ArithmeticError("Invalid continuation integral")
    return value, {"method": "posterior-crossing-split-adaptive-quadrature",
                   "quadrature_error_estimate": error,
                   "truncation_upper_bound": truncation,
                   "quadrature_evaluations": evaluations, "crossings": list(roots),
                   "standard_normal_limit": NORMAL_LIMIT,
                   "floating_point_error_bound_claimed": False}


def action_values(law, public, noise_scale):
    """Shared task values; physical repair, observation cost and codec differ."""
    validate_public(public)
    weights, means, _ = validate_law(law)
    if not math.isfinite(noise_scale) or noise_scale <= 0:
        raise ValueError("Positive finite learned sensor-noise scale required")
    mean = float(weights @ means)
    amount = round(mean * Q24) / Q24
    repair = 2 * amount * mean - amount * amount - public["repair_cost"]
    wait, diagnostics = None, None
    if len(public["residuals"]) == 1:
        expectation, diagnostics = continuation_value(
            law, noise_scale * public["wait_variance"], public["repair_cost"])
        wait = expectation - public["wait_cost"]
    return {"repair_amount": amount, "repair_gain": repair, "wait_gain": wait,
            "continuation_rule": "one-paid-sensor-continuous-optimal-repair.v6",
            "integration": diagnostics,
            "continuous_to_q24_repair_loss_bound": ROUNDING_LOSS_BOUND,
            "future_transport_quantization_included_in_bound": False,
            "learned_future_readout_policy_included_in_integral": False}
