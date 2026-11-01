"""80-digit literal A5/A7 oracle, independent of the differentiated regrouping.

The parameter Jacobian is a step-halved symmetric finite difference of the
high-precision literal formulas, never the implementation's derivative rules.
"""

import numpy as np
from mpmath import mp


def fields(theta, state, coordinate="asset", digits=80):
    ctx = mp.clone()
    ctx.dps = digits
    cv = lambda v: ctx.mpf(str(v))
    r, delta, sigma, alpha, tax, liquidity, m, C, P = map(cv, theta)
    arg = cv(state)
    R, s2 = r + liquidity, sigma * sigma
    a = (r - delta - s2 / 2) / s2
    z, zt = ctx.sqrt(a * a + 2 * r / s2), ctx.sqrt(a * a + 2 * R / s2)
    eta, gamma, s = z - a, z + a, sigma * ctx.sqrt(m)
    c, p = C / m, P / m
    q, discount = p - c / R, ctx.exp(-R * m)
    cost = (1 - tax) * C + (1 - discount) * q
    Phi = lambda t: ctx.erfc(-t / ctx.sqrt(2)) / 2

    def B(y):
        return (Phi(y * s) - ctx.exp((z * z - y * y) * s * s / 2) * Phi(-z * s)) / (z + y)

    bs = B(zt) + B(-zt)
    b = (cost / eta + q * discount * (B(a) + B(-a)) + c / R * bs)
    b /= delta / (eta - 1) + alpha / m * bs
    x = ctx.log(arg / b) if coordinate == "asset" else arg
    if x <= 0 and coordinate == "asset":
        return [b, ctx.mpf(0), ctx.mpf(1), ctx.mpf(1), alpha * b / m]

    def K(v, y, power):
        factor = ctx.exp(((power - a) ** 2 - y * y) * s * s / 2)
        return ((Phi(y * s) - factor * Phi((power - a) * s)) * ctx.exp(-power * v)
                + factor * ctx.exp(-power * v) * Phi(-v / s + (power - a) * s)
                - ctx.exp(-(a + y) * v) * Phi(-v / s + y * s))

    def little_k(v, y):
        factor = ctx.exp(((-eta - a) ** 2 - y * y) * s * s / 2)
        return (factor * ctx.exp(eta * v) * Phi(-v / s + (-eta - a) * s)
                - ctx.exp(-(a + y) * v) * Phi(-v / s + y * s))

    def A(y):
        return ((K(x, y, gamma) + little_k(x, -y)) / (z - y)
                + (K(x, -y, gamma) + little_k(x, y)) / (z + y))

    e = b * ctx.exp(x) - delta * b / (z * s2) * ctx.exp(-gamma * x) / (gamma + 1)
    e -= cost / (z * s2) * (1 / eta + (1 - ctx.exp(-gamma * x)) / gamma)
    e += (discount * q * A(a) - (alpha * b / m - c / R) * A(zt)) / (z * s2)
    f = Phi(-x / s - a * s) + ctx.exp(-2 * a * x) * Phi(-x / s + a * s)
    g = ctx.exp((-a + zt) * x) * Phi(-x / s - zt * s) + ctx.exp((-a - zt) * x) * Phi(-x / s + zt * s)
    debt = c / R + discount * q * (1 - f) + (alpha * b / m - c / R) * g
    return [b, e, f, g, debt]


def jacobian(theta, state, coordinate="asset", step="1e-18"):
    ctx = mp.clone()
    ctx.dps = 80
    values = [ctx.mpf(str(v)) for v in theta] + [ctx.mpf(str(state))]
    result = []
    for i, value in enumerate(values):
        h = ctx.mpf(step) * max(ctx.mpf(".01"), abs(value))
        plus, minus = values.copy(), values.copy()
        plus[i] += h
        minus[i] -= h
        a, b = fields(plus[:9], plus[-1], coordinate), fields(minus[:9], minus[-1], coordinate)
        result.append([float((u - v) / (2 * h)) for u, v in zip(a, b)])
    return np.asarray(result).T
