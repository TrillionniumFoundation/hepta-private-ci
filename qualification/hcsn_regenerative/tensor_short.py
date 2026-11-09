"""Positive short-time integrals for the same killed diffusion generator.

The numerical rule is fixed: q*T < 1e-3, Gauss orders 64/128, t=T*u**2.
All continuous arithmetic and the accepted graph retain the input dtype.
Order agreement is a diagnostic, not a certified continuum error bound.
"""

from functools import lru_cache

import numpy as np
import torch

from .tensor import TensorDiffusion, _as, _nonnegative, _probability


SHORT_QT = 1e-3


@lru_cache(maxsize=2)
def _rule(order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    return (nodes+1)/2, weights/2


def short_mask(x, horizon, discount, *, include_atom=False):
    distance = (x >= 0) if include_atom else (x > 0)
    return distance & (horizon > 0) & (discount*horizon < SHORT_QT)


def _scale_guard(distance, horizon, sigma):
    # The inherited CDF-difference survivor has no relative-precision promise
    # arbitrarily close to its boundary. Reject that unresolved regular scale.
    minimum = 1e-3 if distance.dtype == torch.float32 else 1e-8
    relative = distance/(sigma*torch.sqrt(horizon))
    if bool(((distance > 0) & (relative < minimum)).any()):
        raise FloatingPointError("short survivor scale unresolved for relative occupation accuracy")


def _integrals(distance, horizon, mu, sigma, q, order, upper_distance=None):
    """Return positive occupation and the nonnegative hit-discount correction."""
    nodes, weights = _rule(order)
    u, w = _as(nodes, distance), _as(weights, distance)
    time = horizon[..., None]*u.square()
    process = TensorDiffusion(mu[..., None], sigma[..., None], q[..., None])
    survival = process.survival(distance[..., None], time)
    weight = 2*horizon[..., None]*u*w*torch.exp(-q[..., None]*time)
    if upper_distance is not None:
        upper = process.survival(upper_distance[..., None], time)
        integrand = _nonnegative("short release occupation integrand", upper-survival)
        return (weight*integrand).sum(-1)
    terminal = TensorDiffusion(mu, sigma, q).survival(distance, horizon)
    correction = _nonnegative("short hit correction integrand", survival-terminal[..., None])
    return torch.stack(((weight*survival).sum(-1), (weight*correction).sum(-1)), dim=-1)


def _resolved(distance, horizon, mu, sigma, q, upper_distance=None):
    _scale_guard(distance, horizon, sigma)
    if upper_distance is not None:
        _scale_guard(upper_distance, horizon, sigma)
    # The coarser graph is only a convergence diagnostic. The returned fine
    # graph differentiates every physical input, including quadrature times.
    with torch.no_grad():
        coarse = _integrals(distance, horizon, mu, sigma, q, 64, upper_distance)
    fine = _integrals(distance, horizon, mu, sigma, q, 128, upper_distance)
    _nonnegative("short positive integral", fine)
    error = (fine.detach()-coarse).abs()
    scale = horizon if upper_distance is not None else horizon[..., None]
    rtol = 2e-4 if distance.dtype == torch.float32 else 1e-7
    tolerance = rtol*fine.detach().abs()+32*torch.finfo(distance.dtype).eps*scale
    if bool((error > tolerance).any()):
        raise FloatingPointError("short-time positive quadrature unresolved at fixed orders 64/128")
    return fine, error


def discounted_hit(distance, horizon, mu, sigma, q):
    """G=F-q*integral exp(-q*t)*(S(t)-S(T)) dt, without near-equal G/F logs."""
    integral, error = _resolved(distance, horizon, mu, sigma, q)
    process = TensorDiffusion(mu, sigma, q)
    first_hit = process.hit_probability(distance, horizon)
    value = first_hit-q*integral[..., 1]
    _probability("short discounted hit", value)
    if bool((value > first_hit).any()):
        raise FloatingPointError("short discounted hit exceeds its first-hit measure")
    return value, q*error[..., 1]


def occupation(process, distance, horizon, analytical):
    """Replace only the short regular subset; preserve exact boundary atoms."""
    distance, horizon, mu, sigma, q = process.inputs(distance, horizon)
    mask = short_mask(distance, horizon, q)
    error = torch.zeros_like(analytical)
    if not bool(mask.any()):
        return analytical, error
    result, estimate = _resolved(distance[mask], horizon[mask], mu[mask], sigma[mask], q[mask])
    return analytical.masked_scatter(mask, result[..., 0]), error.masked_scatter(mask, estimate[..., 0])


def release_occupation(process, distance, remaining, margin, analytical):
    """Integral of e^-qt*(S_(distance+a)(t)-S_distance(t)) after release."""
    distance, remaining, mu, sigma, q = torch.broadcast_tensors(
        distance, remaining, process.mu, process.sigma, process.discount)
    mask = short_mask(distance, remaining, q, include_atom=True)
    error = torch.zeros_like(analytical)
    if not bool(mask.any()):
        return analytical, error
    xx, tt, mm, ss, qq = (v[mask] for v in (distance, remaining, mu, sigma, q))
    result, estimate = _resolved(xx, tt, mm, ss, qq, xx+margin)
    return analytical.masked_scatter(mask, result), error.masked_scatter(mask, estimate)
