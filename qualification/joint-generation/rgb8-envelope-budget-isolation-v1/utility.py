"""Fixed entropic recursive utility for a bounded, finite policy tree.

This qualification profile is not a general NDU/FBSDE solver. Its externally
defined outcome table and risk parameter are never trained by the generator.
"""

import math

import numpy as np


def _risk(rho):
    rho = float(rho)
    if not math.isfinite(rho) or not 0 <= rho <= 1e6:
        raise ValueError("rho must be finite and in [0, 1e6]")
    return rho


def _probabilities(probabilities, axis):
    p = np.asarray(probabilities, dtype=np.float64)
    if p.size == 0 or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("invalid probabilities")
    if not np.allclose(p.sum(axis=axis), 1, rtol=0, atol=1e-10):
        raise ValueError("probabilities must sum to one")
    return p


def certainty_equivalent(values, probabilities, rho, axis=-1):
    """Return -log E[exp(-rho * values)] / rho, or E[values] at zero.

    A fixed rho at every boundary obeys the entropic tower recursion. Probability
    and value arrays must have identical shapes; unsupported rows reject.
    """
    rho = _risk(rho)
    v = np.asarray(values, dtype=np.float64)
    p = _probabilities(probabilities, axis)
    if v.shape != p.shape or not np.isfinite(v).all() or (np.abs(v) > 1e6).any():
        raise ValueError("invalid or out-of-profile values")
    if rho == 0:
        return np.sum(p * v, axis=axis)
    # Center before exponentiation. Zero-probability outcomes do not determine
    # the shift, and log1p retains accuracy as rho approaches zero.
    center = np.sum(p * v, axis=axis, keepdims=True)
    scaled = -rho * (v - center)
    if np.max(np.abs(scaled[p > 0]), initial=0) < 0.5:
        return np.squeeze(center, axis=axis) - np.log1p(
            np.sum(p * np.expm1(np.where(p > 0, scaled, 0)), axis=axis)
        ) / rho
    logs = np.full(p.shape, -np.inf)
    np.log(p, out=logs, where=p > 0)
    log_weights = logs - rho * v
    maximum = np.max(log_weights, axis=axis, keepdims=True)
    log_total = maximum + np.log(np.sum(np.exp(log_weights - maximum), axis=axis, keepdims=True))
    return -np.squeeze(log_total, axis=axis) / rho


def joint_value_and_grad(p, q, rewards, rho):
    """Return per-row utility and gradients of negative mean utility wrt logits.

    p and q are softmax distributions [N,K]; rewards is the fixed joint outcome
    table [N,K,K]. The independent behavior law p*q does not imply additive
    utility. No outcome labels are inferred or modified here.
    """
    rho = _risk(rho)
    p, q = np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64)
    r = np.asarray(rewards, dtype=np.float64)
    if p.ndim != 2 or p.shape != q.shape or not 1 <= p.shape[0] <= 65536:
        raise ValueError("expected matching [N,K] policies")
    if not 1 <= p.shape[1] <= 256 or r.shape != (p.shape[0], p.shape[1], p.shape[1]):
        raise ValueError("joint outcome shape is outside the profile")
    _probabilities(p, 1)
    _probabilities(q, 1)
    joint = p[:, :, None] * q[:, None, :]
    n = len(p)
    values = certainty_equivalent(r.reshape(n, -1), joint.reshape(n, -1), rho, axis=1)
    if rho == 0:
        conditional_p = np.sum(q[:, None, :] * r, axis=2)
        conditional_q = np.sum(p[:, :, None] * r, axis=1)
        return values, -p * (conditional_p - values[:, None]) / n, -q * (
            conditional_q - values[:, None]
        ) / n
    # Tilted marginal weights yield the derivative through each softmax. Center
    # around the mean for small rho to avoid catastrophic cancellation.
    centered = r - np.sum(joint * r, axis=(1, 2), keepdims=True)
    if np.max(np.abs(rho * centered), initial=0) < 0.5:
        delta = np.expm1(-rho * centered)
        normalizer = 1 + np.sum(joint * delta, axis=(1, 2))
        delta_p = np.sum(q[:, None, :] * delta, axis=2)
        delta_q = np.sum(p[:, :, None] * delta, axis=1)
        delta_all = normalizer - 1
        gp = p * (delta_p - delta_all[:, None]) / (normalizer[:, None] * rho * n)
        gq = q * (delta_q - delta_all[:, None]) / (normalizer[:, None] * rho * n)
    else:
        logs = np.full(joint.shape, -np.inf)
        np.log(joint, out=logs, where=joint > 0)
        logits = logs - rho * r
        logits -= np.max(logits, axis=(1, 2), keepdims=True)
        tilted = np.exp(logits)
        tilted /= tilted.sum(axis=(1, 2), keepdims=True)
        gp = (tilted.sum(axis=2) - p) / (rho * n)
        gq = (tilted.sum(axis=1) - q) / (rho * n)
    return values, gp, gq
