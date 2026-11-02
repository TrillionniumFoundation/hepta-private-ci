"""Additive development kernel: financial values and tangents use one FP32 word.

Quadrature constants are generated independently then rounded once to FP32.
All financial operations retain the inherited FP32 Dual algebra. This candidate
is not qualified; the original five-output/ten-Jacobian-column gates apply.
"""
import math
import numpy as np
from frozen_kernel import Dual, FullHX, exp, expm1, logPhi, Phi, sqrt, exp_phi
from frozen_kernel import LOWER, UPPER


def rule(n):
    x, w = np.polynomial.legendre.leggauss(n)
    return ((x + 1) / 2).astype(np.float32), (w / 2).astype(np.float32)


BN, BW = rule(64)
EN, EW = rule(32)


def pair_sum(items):
    while len(items) > 1:
        items = [items[i] + items[i + 1] for i in range(0, len(items) - 1, 2)] + (items[-1:] if len(items) % 2 else [])
    return items[0]


def exprel(x):
    if abs(x.v) < np.float32(.1):
        result = x.coerce(1 / math.factorial(10))
        for n in range(8, -1, -1):
            result = result * x + 1 / math.factorial(n + 1)
        return result
    return expm1(x) / x


def log1p(x):
    value = np.log1p(x.v)
    return Dual(value, x.g / (np.float32(1) + x.v))


class StableFP32(FullHX):
    def B(self, y):
        # Positive integral for the divided difference of the normal Mills
        # transform. No subtraction of nearly equal normal CDFs is performed.
        ys, zs = y * self.s, self.z * self.s
        delta = (self.z + y) * self.s
        upper = ys + 10 if ys.v > 2 else y.coerce(12)
        negative = delta.v < 0
        d = -delta if negative else delta
        values = []
        for node, weight in zip(BN, BW):
            t = node * upper
            exponent = -.5 * ys * ys - zs * t - .5 * t * t if negative else -.5 * (t - ys) ** 2
            values.append(weight * t * exp(exponent) * exprel(-d * t))
        return self.s * upper * pair_sum(values) / math.sqrt(2 * math.pi)

    def hit_coefficients(self):
        if hasattr(self, '_hit_coefficients'):
            return self._hit_coefficients
        def derivatives(k, argument):
            density = exp_phi(0., argument)
            hermite = [argument.coerce(1.), argument]
            for n in range(1, 11):
                hermite.append(argument * hermite[-1] - n * hermite[-2])
            p = Phi(argument)
            result = [p]
            for n in range(1, 13):
                terms = [math.comb(n, j) * k ** (n - j) * hermite[j - 1] for j in range(1, n + 1)]
                result.append(k ** n * p - density * pair_sum(terms))
            return result
        d, z = self.a * self.s, self.zt * self.s
        fa, fb = derivatives(d.coerce(0.), -d), derivatives(-2 * d, d)
        ga, gb = derivatives(-d + z, -z), derivatives(-d - z, z)
        self._hit_coefficients = [-(fa[n] + fb[n]) / math.factorial(n) for n in range(1, 13)], [
            (fa[n] + fb[n] - ga[n] - gb[n]) / math.factorial(n) for n in range(1, 13)]
        return self._hit_coefficients

    def hit_fields(self, x):
        h = x / self.s
        if abs(h.v) * (1 + abs((self.a * self.s).v) + abs((self.zt * self.s).v)) <= .1:
            coeffs = self.hit_coefficients()
            values = []
            for coeff in coeffs:
                result = coeff[-1]
                for c in reversed(coeff[:-1]):
                    result = result * h + c
                values.append(result * h)
            sf, fg = values
            f = 1 - sf
            return f, f - fg, sf, fg
        f, g = self.first_hit(x, self.m)
        big = logPhi(x / self.s + self.a * self.s)
        small = -2 * self.a * x + logPhi(-x / self.s + self.a * self.s)
        sf = exp(big) * (-expm1(small - big))
        return f, g, sf, f - g

    def flow(self, x):
        _, g, sf, fg = self.hit_fields(x)
        recovery = self.alpha * self.b / self.m
        return (self.delta * self.b * exp(x) - (1 - self.theta[4]) * self.theta[7]
                + (recovery - self.p) * g - self.q * (fg - expm1(-self.R * self.m) * sf))

    def equity(self, x):
        if x.v > .25:
            return self.raw_equity(x)
        values = []
        for node, weight in zip(EN, EW):
            t = node * x
            distance = x - t
            green = exp(-self.gamma * distance) * expm1(2 * self.z * distance)
            values.append(weight * green * self.flow(t))
        return -x * pair_sum(values) / (self.z * self.s2)

    def state(self, state, coordinate='asset'):
        state = np.float32(state)
        if not np.isfinite(state) or (state <= 0 if coordinate == 'asset' else state < 0):
            raise ValueError('Invalid state')
        argument = Dual(state, np.eye(10, dtype=np.float32)[-1])
        x = log1p((argument - self.b) / self.b) if coordinate == 'asset' else argument
        if x.v <= 0 and coordinate == 'asset':
            e, f, g = x.coerce(0.), x.coerce(1.), x.coerce(1.)
            debt = self.alpha * self.b / self.m
        else:
            e = self.equity(x)
            f, g, sf, fg = self.hit_fields(x)
            debt = (self.c / self.R * (-expm1(-self.R * self.m) * sf + fg)
                    + self.p * self.discount * sf + self.alpha * self.b / self.m * g)
        result = [self.b, e, f, g, debt]
        if any(v.g.dtype != np.float32 or not isinstance(v.v, np.float32) for v in result):
            raise ValueError('Financial computation escaped FP32')
        return np.array([v.v for v in result], np.float32), np.array([v.g for v in result], np.float32)


def build(theta):
    values = np.asarray(theta, dtype=np.float32)
    if values.shape != (9,) or not np.all(np.isfinite(values)):
        raise ValueError('Expected nine finite parameters')
    if np.any(values < LOWER.astype(np.float32)) or np.any(values > UPPER.astype(np.float32)):
        raise ValueError('Outside inherited controlled box')
    basis = np.eye(10, dtype=np.float32)
    return StableFP32([Dual(v, basis[i]) for i, v in enumerate(values)])


def evaluate(theta, state, coordinate='asset', mode='float32'):
    if mode != 'float32' or coordinate not in ('asset', 'log_distance'):
        raise ValueError('This development kernel supports FP32 only')
    return build(theta).state(state, coordinate)
