"""An explicit asymmetric nested risk objective, not original joint NDU.

text-neutral: V = sum_t p_t CE_rho(q, R[t,:]). image-neutral swaps roles.
Both retain the same independent serving law. No outcome is removed, frozen,
inferred, or relabeled. At rho=0 both recover ordinary expected reward.
Returned gradients are derivatives of negative batch-mean V wrt softmax logits.
"""
import numpy as np
from utility import _risk, _probabilities, certainty_equivalent, joint_value_and_grad


def conditional_value_and_grad(p, q, rewards, rho, mode):
    if mode not in ('text-neutral', 'image-neutral'):
        raise ValueError('explicit conditional risk direction required')
    rho = _risk(rho)
    p, q, r = (np.asarray(x, dtype=np.float64) for x in (p, q, rewards))
    if p.ndim != 2 or p.shape != q.shape or not 1 <= len(p) <= 65536:
        raise ValueError('matching [N,K] policies required')
    if not 1 <= p.shape[1] <= 256 or r.shape != (len(p), p.shape[1], p.shape[1]):
        raise ValueError('joint outcome shape outside profile')
    _probabilities(p, 1); _probabilities(q, 1)
    if not np.isfinite(r).all() or np.any(np.abs(r) > 1e6):
        raise ValueError('finite bounded external rewards required')
    if rho == 0:
        return joint_value_and_grad(p, q, r, 0)
    if mode == 'image-neutral':
        value, gq, gp = conditional_value_and_grad(q, p, r.transpose(0, 2, 1), rho, 'text-neutral')
        return value, gp, gq
    n = len(p)
    inner_q = np.broadcast_to(q[:, None, :], r.shape)
    inner = certainty_equivalent(r, inner_q, rho, axis=2)
    value = np.sum(p * inner, axis=1)
    gp = -p * (inner - value[:, None]) / n
    centered = r - np.sum(inner_q * r, axis=2, keepdims=True)
    if np.max(np.abs(rho * centered), initial=0) < .5:
        delta = np.expm1(-rho * centered)
        total_delta = np.sum(inner_q * delta, axis=2, keepdims=True)
        conditional_gq = inner_q * (delta - total_delta) / ((1 + total_delta) * rho)
    else:
        logs = np.full(q.shape, -np.inf)
        np.log(q, out=logs, where=q > 0)
        logits = logs[:, None, :] - rho * r
        logits = logits - np.max(logits, axis=2, keepdims=True)
        tilt = np.exp(logits); tilt /= tilt.sum(axis=2, keepdims=True)
        conditional_gq = (tilt - inner_q) / rho
    gq = np.sum(p[:, :, None] * conditional_gq, axis=1) / n
    return value, gp, gq
