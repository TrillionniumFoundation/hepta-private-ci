"""Full He--Xiong Eq8/9/12/A5/A7, scalar forward AD and explicit mixed precision.

The derivative algebra differentiates executed arithmetic; no custom surrogate
or finite difference is used. A C2 blending interval replaces the old hard
Taylor/A7 switch. The default-region risk extension remains genuinely non-C1.
The controlled box is not a proof of uniform accuracy or optimal stopping.
"""

import math
import numpy as np
from scipy.special import ndtr, log_ndtr

NAMES = ("r", "delta", "sigma", "alpha", "tax", "liquidity", "maturity", "coupon", "principal")
LOWER = np.array([.04, .01, .08, 0., 0., 1e-4, .01, .5, 20.])
UPPER = np.array([.15, .2, .8, 1., .6, .1, 20., 10., 100.])
BASE = np.array([.08, .02, .23, .6, .27, .01, 1., 6.39, 61.68])
OUTPUTS = ("boundary", "equity", "F", "G", "debt")
_NODES, _WEIGHTS = np.polynomial.legendre.leggauss(8)
_NODES, _WEIGHTS = (_NODES + 1) / 2, _WEIGHTS / 2


class Dual:
    """Scalar value with a dense first-order tangent, in one explicit dtype."""
    __array_priority__ = 1000

    def __init__(self, value, tangent):
        self.g = np.asarray(tangent)
        self.v = self.g.dtype.type(value)

    def coerce(self, other):
        return other if isinstance(other, Dual) else Dual(other, np.zeros_like(self.g))

    def __add__(self, other):
        other = self.coerce(other)
        return Dual(self.v + other.v, self.g + other.g)

    __radd__ = __add__

    def __neg__(self):
        return Dual(-self.v, -self.g)

    def __sub__(self, other):
        return self + (-self.coerce(other))

    def __rsub__(self, other):
        return self.coerce(other) - self

    def __mul__(self, other):
        other = self.coerce(other)
        return Dual(self.v * other.v, self.g * other.v + self.v * other.g)

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.coerce(other)
        value = self.v / other.v
        return Dual(value, (self.g - value * other.g) / other.v)

    def __rtruediv__(self, other):
        return self.coerce(other) / self

    def __pow__(self, power):
        if power == 0:
            return self.coerce(1.)
        return Dual(self.v ** power, power * self.v ** (power - 1) * self.g)


def unary(x, function, derivative):
    value = function(x.v)
    return Dual(value, derivative(x.v, value) * x.g)


def exp(x):
    return unary(x, np.exp, lambda x, y: y)


def expm1(x):
    return unary(x, np.expm1, lambda x, y: np.exp(x))


def log(x):
    return unary(x, np.log, lambda x, y: 1 / x)


def sqrt(x):
    return unary(x, np.sqrt, lambda x, y: .5 / y)


def Phi(x):
    return unary(x, ndtr, lambda x, y: np.exp(-.5 * x * x) / math.sqrt(2 * math.pi))


def logPhi(x):
    return unary(x, log_ndtr, lambda x, y: np.exp(-.5 * x * x - .5 * math.log(2 * math.pi) - y))


def exp_cdf(exponent, argument):
    return exp(argument.coerce(exponent) + logPhi(argument))


def exp_phi(exponent, argument):
    return exp(argument.coerce(exponent) - .5 * argument * argument) / math.sqrt(2 * math.pi)


def cdf_interval(exponent, lo, hi):
    big, small = (logPhi(-lo), logPhi(-hi)) if lo.v > 0 else (logPhi(hi), logPhi(lo))
    return exp(exponent + big) * (-expm1(small - big))


class FullHX:
    """One differentiated parameter tuple; complete financial kernel throughout."""

    def __init__(self, theta):
        self.theta = theta
        self.r, self.delta, sigma, self.alpha, tax, liquidity, self.m, C, P = theta
        self.s2, self.R = sigma * sigma, self.r + liquidity
        self.a = (self.r - self.delta - self.s2 / 2) / self.s2
        self.z = sqrt(self.a * self.a + 2 * self.r / self.s2)
        self.zt = sqrt(self.a * self.a + 2 * self.R / self.s2)
        self.eta = 2 * self.r / (self.s2 * (self.z + self.a)) if self.a.v >= 0 else self.z - self.a
        self.gamma = 2 * self.r / (self.s2 * self.eta)
        self.s, self.c, self.p = sigma * sqrt(self.m), C / self.m, P / self.m
        self.q, self.discount = self.p - self.c / self.R, exp(-self.R * self.m)
        self.cost = (1 - tax) * C - expm1(-self.R * self.m) * self.q
        bs = self.B(-self.zt) + self.B(self.zt)
        self.b = (self.cost / self.eta + self.q * self.discount * (self.B(-self.a) + self.B(self.a))
                  + (self.c / self.R) * bs) / (.5 * self.s2 * (self.gamma + 1) + self.alpha / self.m * bs)
        flow = self.delta * self.b - (1 - tax) * C + (self.alpha * self.b - P) / self.m
        scale = abs(self.delta.v * self.b.v) + abs((1 - tax.v) * C.v) + (abs(self.alpha.v * self.b.v) + abs(P.v)) / self.m.v
        if not np.isfinite(self.b.v) or self.b.v <= 0 or flow.v >= -64 * np.finfo(flow.g.dtype).eps * max(1., scale):
            raise ValueError("Unresolved or inadmissible local stopping boundary")

    def B(self, y):
        denominator = self.z + y
        if abs(denominator.v) < 1e-3 * (1 + self.z.v):
            result = y.coerce(0.)
            for node, weight in zip(_NODES, _WEIGHTS):
                at = -self.z + node * denominator
                exponent = .5 * (self.z - at) * (self.z + at) * self.s * self.s
                result += weight * (self.s * exp_phi(0., at * self.s)
                                    + at * self.s * self.s * exp_cdf(exponent, -self.z * self.s))
            return result
        return (Phi(y * self.s) - exp_cdf(.5 * (self.z - y) * (self.z + y) * self.s * self.s,
                                         -self.z * self.s)) / denominator

    def first_hit(self, x, horizon):
        st = self.theta[2] * sqrt(horizon)
        f = Phi(-x / st - self.a * st) + exp_cdf(-2 * self.a * x, -x / st + self.a * st)
        g = exp_cdf((-self.a + self.zt) * x, -x / st - self.zt * st)
        g += exp_cdf((-self.a - self.zt) * x, -x / st + self.zt * st)
        return f, g

    def A(self, x, y):
        def numerator(u, derivative=False):
            exponent = .5 * (self.z * self.z - u * u) * self.s * self.s
            common = -cdf_interval(exponent - self.gamma * x, self.z * self.s - x / self.s, self.z * self.s)
            common += exp_cdf(exponent + self.eta * x, -x / self.s - self.z * self.s)
            positive = exp_cdf(-(self.a + u) * x, -x / self.s + u * self.s)
            negative = exp_cdf(-(self.a - u) * x, -x / self.s - u * self.s)
            if derivative:
                return (self.s * exp_phi(-self.gamma * x, u * self.s) - u * self.s * self.s * common
                        + x * positive - self.s * exp_phi(-(self.a + u) * x, -x / self.s + u * self.s)
                        - x * negative + self.s * exp_phi(-(self.a - u) * x, -x / self.s - u * self.s))
            return exp(-self.gamma * x) * Phi(u * self.s) + common - positive - negative
        result = x.coerce(0.)
        for u in (y, -y):
            denominator = self.z - u
            if abs(denominator.v) < .01 * (1 + self.z.v):
                for node, weight in zip(_NODES, _WEIGHTS):
                    result -= weight * numerator(self.z - node * denominator, derivative=True)
            else:
                result += numerator(u) / denominator
        return result

    def raw_equity(self, x):
        result = self.b * exp(x) - self.delta * self.b / (self.z * self.s2) * exp(-self.gamma * x) / (self.gamma + 1)
        result -= self.cost / (self.z * self.s2) * (1 / self.eta - expm1(-self.gamma * x) / self.gamma)
        result += (self.discount * self.q * self.A(x, self.a)
                   - (self.alpha * self.b / self.m - self.c / self.R) * self.A(x, self.zt)) / (self.z * self.s2)
        return result

    def taylor_equity(self, x):
        """Tenth-order local evaluation of the full equity ODE, E(0)=E'(0)=0.

        For T(x)=exp(k*x)*Phi(A+B*x), derivatives follow Leibniz plus
        Phi^(j)(A)=(-1)^(j-1)*He_(j-1)(A)*phi(A). Coefficients retain AD.
        """
        def derivatives(k, argument):
            density = exp_phi(0., argument)
            hermite = [argument.coerce(1.), argument]
            for n in range(1, 7):
                hermite.append(argument * hermite[-1] - n * hermite[-2])
            result = [Phi(argument)]
            for n in range(1, 9):
                value = k ** n * result[0]
                for j in range(1, n + 1):
                    value += math.comb(n, j) * k ** (n - j) * (-1 / self.s) ** j * (-1) ** (j - 1) * hermite[j - 1] * density
                result.append(value)
            return result

        fparts = [derivatives(x.coerce(0.), -self.a * self.s), derivatives(-2 * self.a, self.a * self.s)]
        gparts = [derivatives(-self.a + self.zt, -self.zt * self.s),
                  derivatives(-self.a - self.zt, self.zt * self.s)]
        recovery = self.alpha * self.b / self.m - self.c / self.R
        flow0 = self.delta * self.b - (1 - self.theta[4]) * self.theta[7] + self.alpha * self.b / self.m - self.p
        e = [x.coerce(0.), x.coerce(0.)]
        for n in range(9):
            flow = flow0 if n == 0 else (self.delta * self.b
                   - self.discount * self.q * (fparts[0][n] + fparts[1][n])
                   + recovery * (gparts[0][n] + gparts[1][n]))
            e.append(2 * self.r / self.s2 * e[n] - 2 * self.a * e[n + 1] - 2 * flow / self.s2)
        value = x.coerce(0.)
        for n in range(10, 1, -1):
            value = value * x + e[n] / math.factorial(n)
        return x * x * value

    def equity(self, x):
        abs_a = self.a if self.a.v >= 0 else -self.a
        limits = [x.coerce(.002), .02 * self.s, .05 / (1 + abs_a + self.zt)]
        limit = min(limits, key=lambda v: v.v)
        if x.v <= .5 * limit.v:
            return self.taylor_equity(x)
        if x.v >= limit.v:
            return self.raw_equity(x)
        u = 2 * x / limit - 1
        weight = u ** 3 * (10 + u * (-15 + 6 * u))
        return (1 - weight) * self.taylor_equity(x) + weight * self.raw_equity(x)


def evaluate(theta, state, *, coordinate="asset", mode="float64"):
    """Return outputs and Jacobian with columns [9 parameters, state].

    mixed32 quantizes caller inputs once, computes complete values/tangents in
    FP64, and casts outputs/tangents to FP32. Cast tangents use the standard
    numerical-AD convention, not a derivative of the discontinuous rounding map.
    Native float32 is an audit mode and is not admitted for training.
    """
    if mode not in ("float64", "float32", "mixed32") or coordinate not in ("asset", "log_distance"):
        raise ValueError("Unknown precision mode or state coordinate")
    input_dtype = np.float64 if mode == "float64" else np.float32
    internal_dtype = np.float32 if mode == "float32" else np.float64
    values = np.asarray(theta, dtype=input_dtype)
    if values.shape != (9,) or not np.all(np.isfinite(values)):
        raise ValueError("Expected nine finite parameters")
    if np.any(values < LOWER.astype(input_dtype)) or np.any(values > UPPER.astype(input_dtype)):
        raise ValueError("Outside the registered controlled parameter box")
    state = input_dtype(state)
    if not np.isfinite(state) or (state <= 0 if coordinate == "asset" else state < 0):
        raise ValueError("Invalid state")
    basis = np.eye(10, dtype=internal_dtype)
    p = [Dual(v, basis[i]) for i, v in enumerate(values)]
    argument = Dual(state, basis[-1])
    model = FullHX(p)
    x = log(argument / model.b) if coordinate == "asset" else argument
    if x.v <= 0 and coordinate == "asset":
        e, f, g = x.coerce(0.), x.coerce(1.), x.coerce(1.)
        debt = model.alpha * model.b / model.m
    else:
        e = model.equity(x)
        f, g = model.first_hit(x, model.m)
        debt = model.c / model.R + model.discount * model.q * (1 - f)
        debt += (model.alpha * model.b / model.m - model.c / model.R) * g
    result = [model.b, e, f, g, debt]
    output_dtype = np.float32 if mode == "mixed32" else internal_dtype
    return (np.asarray([v.v for v in result], dtype=output_dtype),
            np.asarray([v.g for v in result], dtype=output_dtype))
