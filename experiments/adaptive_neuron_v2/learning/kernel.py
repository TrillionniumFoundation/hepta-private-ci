"""Bounded first-passage surrogate and analytic mixed parameter derivatives.

The cancellation parameter belongs to the backward surrogate, not to the
resource price or the Bernoulli task's physical transition law. Hard inference
does not call this module.
"""

import math

import numpy as np
from scipy.special import erfcx, expit, log_ndtr, logit


PARAMETER_NAMES = ("mu", "sigma", "lambda")
RAW_LIMIT = 6.0


def initial_raw():
    return np.array([np.arctanh(0.25 / 1.25), logit(0.65 / 1.65), logit(0.09 / 0.99)])


def physical(raw):
    """Map three finite raw scalars into a compact, nondegenerate domain."""
    raw = np.asarray(raw, dtype=float)
    if raw.shape != (3,) or not np.all(np.isfinite(raw)):
        raise ValueError("three finite surrogate parameters required")
    if np.any(np.abs(raw) > RAW_LIMIT + 1e-12):
        raise ValueError("raw surrogate parameters exceed the registered box")
    sigmoid = expit(raw)
    tanh = np.tanh(raw[0])
    values = np.array([1.25 * tanh, 0.35 + 1.65 * sigmoid[1], 0.01 + 0.99 * sigmoid[2]])
    jacobian = np.array(
        [
            1.25 * (1 - tanh**2),
            1.65 * sigmoid[1] * (1 - sigmoid[1]),
            0.99 * sigmoid[2] * (1 - sigmoid[2]),
        ]
    )
    return values, jacobian


def _mills(a):
    mills = math.sqrt(math.pi / 2) * erfcx(a / math.sqrt(2))
    complement = 1 - a * mills
    derivative = a - (1 + a**2) * mills
    safe = np.maximum(a, 16.0)
    coefficients = (1.0, -3.0, 15.0, -105.0, 945.0, -10395.0, 135135.0, -2027025.0)
    tail = np.zeros_like(a)
    tail_derivative = np.zeros_like(a)
    for index, coefficient in enumerate(coefficients):
        tail += coefficient / safe ** (2 * index + 2)
        tail_derivative -= (2 * index + 2) * coefficient / safe ** (2 * index + 3)
    return (
        mills,
        np.where(a >= 16, tail, complement),
        np.where(a >= 16, tail_derivative, derivative),
    )


def activation(value, raw, family, *, soft=False, mixed=False):
    """Return forward activation, backward slope and optional d(slope)/d(raw).

    The hard forward is a strict threshold. The first-passage primitive is used
    only for the explicitly softened mathematical fixture; its upper extension
    is constant and its threshold derivative is the continuation-side limit.
    """
    value = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(value)):
        raise FloatingPointError("nonfinite neural activation")
    if family == "standard":
        primitive = expit(value / 0.5)
        slope = primitive * (1 - primitive) / 0.5
        tangent = np.zeros(value.shape + (3,)) if mixed else None
    elif family == "first_passage":
        (mu, sigma, rate), raw_jacobian = physical(raw)
        delta = math.hypot(mu, math.sqrt(2 * rate) * sigma)
        kappa = 2 * rate / (delta + mu) if mu >= 0 else (delta - mu) / sigma**2
        gamma = 2 * rate / (delta - mu) if mu <= 0 else (delta + mu) / sigma**2
        d = np.maximum(-value, 0)
        a, z = (d + delta) / sigma, (delta - d) / sigma
        first = np.exp(-kappa * d + log_ndtr(z))
        second = np.exp(gamma * d + log_ndtr(-a))
        primitive = first + second
        common = np.exp(-0.5 * ((d - mu) / sigma) ** 2 - rate) / math.sqrt(2 * math.pi)
        mills, complement, complement_a = _mills(a)
        ratio = d / sigma
        bracket = complement + ratio * mills
        slope = kappa * primitive + 2 * common / sigma * bracket
        tangent = None
        if mixed:
            delta_p = np.array([mu, 2 * rate * sigma, sigma**2]) / delta
            kappa_p = np.array([-kappa, -sigma * kappa**2, 1.0]) / delta
            gamma_p = np.array([gamma, -sigma * gamma**2, 1.0]) / delta
            scale_p = np.array([0.0, 1.0, 0.0])
            a_p = delta_p / sigma - a[..., None] * scale_p / sigma
            z_p = delta_p / sigma - z[..., None] * scale_p / sigma
            primitive_p = (
                -d[..., None] * first[..., None] * kappa_p
                + d[..., None] * second[..., None] * gamma_p
                + common[..., None] * (z_p - a_p)
            )
            common_p = common[..., None] * np.stack(
                ((d - mu) / sigma**2, (d - mu) ** 2 / sigma**3, np.full_like(d, -1)),
                axis=-1,
            )
            ratio_p = -ratio[..., None] * scale_p / sigma
            bracket_p = (complement_a - ratio * complement)[..., None] * a_p + mills[
                ..., None
            ] * ratio_p
            tangent = (
                primitive[..., None] * kappa_p
                + kappa * primitive_p
                + 2
                * (common_p / sigma - common[..., None] * scale_p / sigma**2)
                * bracket[..., None]
                + 2 * common[..., None] / sigma * bracket_p
            ) * raw_jacobian
            tangent = np.where(value[..., None] > 0, 0.0, tangent)
        primitive = np.where(value >= 0, 1.0, np.minimum(primitive, 1.0))
        slope = np.where(value > 0, 0.0, slope)
    else:
        raise ValueError("unknown surrogate family")
    if not np.all(np.isfinite(slope)) or (
        tangent is not None and not np.all(np.isfinite(tangent))
    ):
        raise FloatingPointError("nonfinite surrogate derivative")
    return primitive if soft else (value > 0).astype(float), slope, tangent
