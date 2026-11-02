"""Joint finite renewal dynamics and cyclic content-transition likelihood."""

import numpy as np
from scipy.special import log_ndtr, ndtr

CAP = 24
CLASSES = 5
MODES = ("original", "mean_two_point", "single_transition")


def softmax(logits):
    values = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
    return values / values.sum(axis=-1, keepdims=True)


def count_law(theta, packets, mode):
    """Return N x CAP probabilities and derivatives w.r.t. log drift/sigma.

    Mean-two-point has its declared piecewise derivative away from integer mean
    knots. Single-transition support remains exactly {0, 1}, even after fitting.
    """
    if mode not in MODES:
        raise ValueError("unknown intervention")
    x, horizon, nu, sigma, reset, refractory = packets.T
    nu, sigma = nu * np.exp(theta[0]), sigma * np.exp(theta[1])
    n = np.arange(1, CAP+1)
    elapsed = horizon[:, None] - (n[None]-1) * refractory[:, None]
    distance = x[:, None] + (n[None]-1) * reset[:, None]
    active = elapsed > 0
    elapsed = np.where(active, elapsed, 1.0)
    root = np.sqrt(elapsed)
    drift, volatility = nu[:, None], sigma[:, None]
    a = (-distance-drift*elapsed)/(volatility*root)
    b = (-distance+drift*elapsed)/(volatility*root)
    logpdf_a = -0.5*a*a-0.5*np.log(2*np.pi)
    logpdf_b = -0.5*b*b-0.5*np.log(2*np.pi)
    reflected = np.exp(np.minimum(-2*drift*distance/volatility**2+log_ndtr(b), 0))
    mills = np.exp(logpdf_b-log_ndtr(b))
    tails = np.where(active, ndtr(a)+reflected, 0)
    derivative_nu = (np.exp(logpdf_a)*(-root/volatility)
        + reflected*(-2*distance/volatility**2+mills*root/volatility))
    derivative_sigma = (np.exp(logpdf_a)*(distance+drift*elapsed)/(volatility**2*root)
        + reflected*(4*drift*distance/volatility**3
        + mills*(distance-drift*elapsed)/(volatility**2*root)))
    derivative = np.stack([derivative_nu*drift, derivative_sigma*volatility], axis=-1)
    derivative *= active[:, :, None]
    if np.max(np.abs(tails[:, -1])) > 1e-10:
        raise ArithmeticError("count support exceeds declared cap")
    p = np.concatenate([np.ones((len(packets), 1)), tails[:, :-1]], axis=1)-tails
    dp = np.concatenate([np.zeros((len(packets), 1, 2)), derivative[:, :-1]], axis=1)-derivative
    if p.min() < -1e-10 or np.max(np.abs(p.sum(1)-1)) > 1e-10:
        raise ArithmeticError("count probability mass invalid")
    # Only remove roundoff-scale negative differences; corresponding derivatives
    # are zeroed at those saturated boundaries and checked by finite differences.
    negative = p < 0
    p[negative] = 0
    dp[negative] = 0
    if mode == "single_transition":
        result, grad = np.zeros_like(p), np.zeros_like(dp)
        result[:, 0], result[:, 1] = p[:, 0], 1-p[:, 0]
        grad[:, 0], grad[:, 1] = dp[:, 0], -dp[:, 0]
        return result, grad
    if mode == "mean_two_point":
        mean = p @ np.arange(CAP)
        dmean = np.einsum("nck,c->nk", dp, np.arange(CAP))
        lower = np.floor(mean).astype(int)
        if lower.max() >= CAP-1:
            raise ArithmeticError("two-point count approximation exceeds cap")
        result, grad = np.zeros_like(p), np.zeros_like(dp)
        rows = np.arange(len(p))
        fraction = mean-lower
        result[rows, lower], result[rows, lower+1] = 1-fraction, fraction
        grad[rows, lower], grad[rows, lower+1] = -dmean, dmean
        return result, grad
    return p, dp


def content_powers(theta):
    """One common dense cyclic transition; derivatives for its four logits.

    T's displacement probabilities can adapt during every model's fit. A fitted
    single-transition model may thereby approximate a multi-event marginal with
    ONE new content step; it still never executes more than one transition.
    """
    weights = softmax(np.r_[0.0, theta[2:]])
    dw = np.stack([weights*((np.arange(CLASSES)==k)-weights[k])
                   for k in range(1, CLASSES)], axis=1)
    q, dq = np.zeros((CAP, CLASSES)), np.zeros((CAP, CLASSES, CLASSES-1))
    q[0, 0] = 1.0
    for n in range(1, CAP):
        for displacement in range(CLASSES):
            rolled = np.roll(q[n-1], displacement)
            q[n] += weights[displacement]*rolled
            dq[n] += (dw[displacement][None, :]*rolled[:, None]
                + weights[displacement]*np.roll(dq[n-1], displacement, axis=0))
    return q, dq, weights


def predict(theta, packets, mode):
    """Distribution of displacement from the perfectly revealed initial class."""
    counts, dc = count_law(theta, packets, mode)
    q, dq, _ = content_powers(theta)
    p = counts @ q
    dp = np.concatenate([np.einsum("nck,cd->ndk", dc, q),
                         np.einsum("nc,cdk->ndk", counts, dq)], axis=-1)
    if p.min() < -1e-10 or np.max(np.abs(p.sum(1)-1)) > 1e-9:
        raise ArithmeticError("content probability mass invalid")
    return p, dp


def objective(theta, packets, labels, mode, l2):
    p, dp = predict(theta, packets, mode)
    rows = np.arange(len(labels))
    selected = p[rows, labels]
    safe = np.maximum(selected, 1e-15)
    loss = -np.log(safe).mean()+0.5*l2*np.square(theta).sum()
    active = selected > 1e-15
    gradient = -(dp[rows, labels]*active[:, None]/safe[:, None]).mean(axis=0)+l2*theta
    return float(loss), gradient


def metrics(probabilities, labels):
    return {"nll": float(-np.log(np.maximum(probabilities[np.arange(len(labels)), labels], 1e-15)).mean()),
            "accuracy": float((np.argmax(probabilities, axis=1)==labels).mean()),
            "brier": float(np.square(probabilities-np.eye(CLASSES)[labels]).sum(1).mean())}
