"""Full HX equations evaluated with explicit compensated two-word FP32.

Each value and each tangent component uses two float32 words. This is an
extended-significand algorithm, not ordinary one-word FP32 or mixed32/FP64.
Standard numerical AD targets the mathematical elementary functions, as in
the inherited kernel; it does not differentiate the rounding map.
"""
import importlib.util
from pathlib import Path
import numpy as np
import float32_pair as fp

ARITHMETIC = 'compensated FP32: two float32 words per value and tangent, approximately 44-48 significand bits'


class Dual:
    __array_priority__ = 2000

    def __init__(self, value, tangent):
        self.v, self.g = fp.Pair(value), fp.Pair(tangent)

    def coerce(self, other):
        return other if isinstance(other, Dual) else Dual(other, np.zeros_like(self.g.hi))

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
            return self.coerce(1)
        return Dual(self.v ** power, power * self.v ** (power - 1) * self.g)

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        if method == '__call__' and ufunc in (np.add, np.subtract, np.multiply, np.divide):
            left, right = map(self.coerce, inputs)
            return {np.add: Dual.__add__, np.subtract: Dual.__sub__,
                    np.multiply: Dual.__mul__, np.divide: Dual.__truediv__}[ufunc](left, right)
        return NotImplemented


def unary(x, function, derivative):
    y = function(x.v)
    return Dual(y, derivative(x.v, y) * x.g)


def exp(x):
    return unary(x, fp.exp, lambda v, y: y)


def expm1(x):
    return unary(x, fp.expm1, lambda v, y: fp.exp(v))


def log(x):
    return unary(x, fp.log, lambda v, y: 1 / v)


def sqrt(x):
    return unary(x, fp.sqrt, lambda v, y: .5 / y)


def Phi(x):
    return unary(x, fp.cdf, lambda v, y: fp.exp(-.5 * v * v) * fp.INV_SQRT2PI)


def logPhi(x):
    return unary(x, fp.logcdf, lambda v, y: fp.exp(-.5 * v * v - fp.LOG_SQRT2PI - y))


# Load the frozen formulas into a private module and replace only their
# arithmetic primitives. No scientific source file is modified on disk.
_path = Path(__file__).with_name('frozen_kernel.py')
_spec = importlib.util.spec_from_file_location('_compensated_hx_formulas', _path)
formulas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(formulas)
for _name in ('Dual', 'exp', 'expm1', 'log', 'sqrt', 'Phi', 'logPhi'):
    setattr(formulas, _name, globals()[_name])


class Model(formulas.FullHX):
    def state(self, state, coordinate='asset'):
        state = np.float32(state)
        if coordinate not in ('asset', 'log_distance') or not np.isfinite(state) or (state <= 0 if coordinate == 'asset' else state < 0):
            raise ValueError('Invalid state coordinate')
        argument = Dual(state, np.eye(10, dtype=np.float32)[-1])
        x = log(argument / self.b) if coordinate == 'asset' else argument
        if x.v <= 0 and coordinate == 'asset':
            e, f, g = x.coerce(0), x.coerce(1), x.coerce(1)
            debt = self.alpha * self.b / self.m
        else:
            e = self.equity(x)
            f, g = self.first_hit(x, self.m)
            debt = self.c / self.R + self.discount * self.q * (1 - f)
            debt += (self.alpha * self.b / self.m - self.c / self.R) * g
        result = [self.b, e, f, g, debt]
        for value in result:
            for part in (value.v.hi, value.v.lo, value.g.hi, value.g.lo):
                if part.dtype != np.float32:
                    raise TypeError('Non-FP32 financial storage')
        return (np.asarray([v.v.rounded() for v in result], dtype=np.float32),
                np.asarray([v.g.rounded() for v in result], dtype=np.float32))


def build(theta):
    values = np.asarray(theta, dtype=np.float32)
    if values.shape != (9,) or not np.all(np.isfinite(values)):
        raise ValueError('Expected nine finite parameters')
    if np.any(values < formulas.LOWER.astype(np.float32)) or np.any(values > formulas.UPPER.astype(np.float32)):
        raise ValueError('Outside inherited controlled box')
    basis = np.eye(10, dtype=np.float32)
    return Model([Dual(v, basis[i]) for i, v in enumerate(values)])


def evaluate(theta, state, coordinate='asset', mode='compensated32'):
    if mode != 'compensated32':
        raise ValueError('Compensated FP32 must be explicitly named')
    return build(theta).state(state, coordinate)
