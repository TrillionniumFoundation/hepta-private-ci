"""Finite categorical objective geometry; no neural model, optimizer or RNG."""

import numpy as np
from numpy.polynomial import Polynomial


ALPHA = .2
RHO = 1.5


def softmax(z):
    z = np.asarray(z, dtype=np.float64)
    v = np.exp(z - z.max())
    return v / v.sum()


def covariance(p):
    return np.diag(p) - np.outer(p, p)


def probability_geometry(s, eta, reward, arm):
    """Loss, ambient probability gradient/Hessian, expected reward, per-Y CE.

    eta is a HAND specified conditional label distribution, not an estimated
    posterior for any real request. Label averaging stays OUTSIDE each log.
    """
    s, eta, reward = [np.asarray(v, dtype=np.float64) for v in (s, eta, reward)]
    k = len(s)
    if (s.shape != (k,) or eta.shape != (k,) or reward.shape != (k, k)
            or not np.isfinite(reward).all() or not np.isfinite(s).all()
            or not np.isfinite(eta).all() or np.any(s <= 0) or np.any(eta < 0)
            or not np.isclose(s.sum(), 1) or not np.isclose(eta.sum(), 1)
            or arm not in ("A", "N")):
        raise ValueError("interior categorical law, label law and reward matrix required")
    ce = -np.sum(eta * np.log(s))
    g = -ALPHA * eta / s
    h = np.diag(ALPHA * eta / (s * s))
    expected = float(eta @ reward @ s)
    if arm == "A":
        loss = ALPHA * ce - expected
        g = g - eta @ reward
        return float(loss), g, h
    shift = reward.min(1)
    kernel = np.exp(-RHO * (reward - shift[:, None]))
    normalizer = kernel @ s
    values = shift - np.log(normalizer) / RHO
    loss = ALPHA * ce - eta @ values
    g = g + (eta / normalizer) @ kernel / RHO
    h = h - (kernel.T * (eta / normalizer**2)) @ kernel / RHO
    return float(loss), g, h


def logit_geometry(z, eta, reward, arm):
    s = softmax(z)
    eta, reward = np.asarray(eta), np.asarray(reward)
    ce = float(-eta @ np.log(s))
    base = ALPHA * covariance(s)
    if arm == "A":
        v = eta @ reward
        value = float(s @ v)
        a = s * (v - value)
        g = ALPHA * (s - eta) - a
        h = base - np.diag(a) + np.outer(a, s) + np.outer(s, a)
        return ALPHA * ce - value, g, h
    if arm != "N":
        raise ValueError("fixed A or N objective required")
    shift = reward.min(1)
    kernel = np.exp(-RHO * (reward - shift[:, None]))
    weighted = kernel * s[None, :]
    normalizer = weighted.sum(1)
    tilted = weighted / normalizer[:, None]
    values = shift - np.log(normalizer) / RHO
    g = ALPHA * (s - eta) + (eta @ tilted - s) / RHO
    h = (ALPHA - 1 / RHO) * covariance(s)
    for weight, t in zip(eta, tilted):
        h += weight * covariance(t) / RHO
    return float(ALPHA * ce - eta @ values), g, h


def additive_population_optimum(eta, reward):
    """Unique interior A optimum when every eta_c is strictly positive."""
    eta, reward = np.asarray(eta), np.asarray(reward)
    if np.any(eta <= 0) or not np.isclose(eta.sum(), 1):
        raise ValueError("strictly positive hand label law required")
    values = eta @ reward
    low, high = float(values.max()), float(values.max() + ALPHA)
    for _ in range(128):
        mid = (low + high) / 2
        if np.sum(ALPHA * eta / (mid - values)) > 1:
            low = mid
        else:
            high = mid
    lam = high
    s = ALPHA * eta / (lam - values)
    return s, lam


def symmetric_binary(delta=.9):
    """Closed global optima on the equal-reward two-label ambiguity face."""
    kappa = float(np.exp(-RHO * delta))
    difference = 1 - kappa
    threshold = float(np.tanh(RHO * delta / 2)**2)
    if ALPHA * RHO < threshold:
        product = ALPHA * RHO * kappa / ((1 - ALPHA * RHO) * difference**2)
        root = np.sqrt(1 - 4 * product)
        optima = [(1 - root) / 2, (1 + root) / 2]
    else:
        optima = [.5]
    return dict(delta=delta, kappa=kappa, N_optima=optima, A_optimum=.5,
        N_center_probability_curvature=4 * (ALPHA - threshold / RHO),
        A_center_probability_curvature=4 * ALPHA,
        N_over_A_utility_ratio_at_p0=difference / (RHO * delta),
        N_over_A_utility_ratio_at_p1=(1 / kappa - 1) / (RHO * delta),
        utility_ratio_crossing=1 / difference - 1 / (RHO * delta))


def binary_face_geometry(p, reward2, arm):
    reward2 = np.asarray(reward2)
    s, eta = np.array([p, 1 - p]), np.array([.5, .5])
    loss, g, h = probability_geometry(s, eta, reward2, arm)
    d = np.array([1., -1.])
    return loss, float(g @ d), float(d @ h @ d)


def binary_population_stationary(reward2):
    """All cubic N stationary points; not neural training or parameter search."""
    r = np.asarray(reward2)
    da = 1 - np.exp(-RHO * (r[0, 0] - r[0, 1]))
    db = 1 - np.exp(-RHO * (r[1, 1] - r[1, 0]))
    kb = 1 - db
    p = Polynomial([0., 1.])
    equation = (ALPHA * (p - .5) * (1 - da * p) * (kb + db * p)
        + p * (1 - p) * (db - da * kb - 2 * da * db * p) / (2 * RHO))
    rows = []
    for root in equation.roots():
        if abs(root.imag) <= 1e-10 and 0 < root.real < 1:
            value = float(root.real)
            loss, grad, curvature = binary_face_geometry(value, r, "N")
            rows.append(dict(p=value, loss=loss, gradient=grad, curvature=curvature,
                             kind="minimum" if curvature > 0 else "maximum"))
    rows.sort(key=lambda x: x["p"])
    v = .5 * (r[0] + r[1])
    contrast = v[0] - v[1]
    pa = ALPHA / (np.sqrt(ALPHA**2 + contrast**2) + ALPHA - contrast)
    return dict(A_optimum=float(pa), A_loss=binary_face_geometry(float(pa), r, "A")[0],
                N_stationary=rows, N_center_curvature=binary_face_geometry(.5, r, "N")[2])


def maximal_coupling(p, q):
    """Parameter-free joint LAW only. No sampler or trained-model evaluation."""
    p, q = np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64)
    if (p.ndim != 1 or p.shape != q.shape or np.any(p < 0) or np.any(q < 0)
            or not np.isclose(p.sum(), 1) or not np.isclose(q.sum(), 1)):
        raise ValueError("two categorical marginals required")
    common = np.minimum(p, q)
    remainder = float(np.sum(p - common))
    joint = np.diag(common)
    if remainder > 0:
        joint += np.outer(p - common, q - common) / remainder
    return joint
