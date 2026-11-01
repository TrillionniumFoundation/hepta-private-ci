"""Two-FP32 compensated arithmetic; no FP64 arithmetic or special functions.

Fixed hi/lo constants are generated offline in 80-digit arithmetic. Every
runtime value, tangent, elementary operation and transcendental approximation
here is FP32. This is double-single, not a single-FP32 performance claim.
"""

import json
from pathlib import Path

import numpy as np


class DS:
    __array_priority__ = 2000
    dtype = np.dtype(np.float32)

    def __init__(self, hi, lo=0):
        self.h = np.asarray(hi, dtype=np.float32)
        self.l = np.asarray(lo, dtype=np.float32)

    @staticmethod
    def of(x):
        return x if isinstance(x, DS) else DS(x)

    def __array__(self, dtype=None, copy=None):
        return np.asarray(self.h + self.l, dtype=dtype)

    def __add__(self, other):
        if hasattr(other, "g"):
            return NotImplemented
        b = DS.of(other)
        s = self.h + b.h
        v = s - self.h
        e = (self.h - (s-v)) + (b.h-v) + self.l + b.l
        hi = s + e
        return DS(hi, e-(hi-s))

    __radd__ = __add__

    def __neg__(self):
        return DS(-self.h, -self.l)

    def __sub__(self, other):
        return self + (-DS.of(other))

    def __rsub__(self, other):
        return DS.of(other) - self

    def __mul__(self, other):
        if hasattr(other, "g"):
            return NotImplemented
        b = DS.of(other)
        # Dekker split for binary32 (12 significant bits in each piece).
        ca, cb = np.float32(4097)*self.h, np.float32(4097)*b.h
        ah, bh = ca-(ca-self.h), cb-(cb-b.h)
        al, bl = self.h-ah, b.h-bh
        p = self.h*b.h
        e = ((ah*bh-p)+ah*bl+al*bh)+al*bl
        e += self.h*b.l+self.l*b.h+self.l*b.l
        hi = p+e
        return DS(hi, e-(hi-p))

    __rmul__ = __mul__

    def __truediv__(self, other):
        b = DS.of(other)
        q = DS(self.h/b.h)
        rem = self-b*q
        q = q+DS((rem.h+rem.l)/b.h)
        return q

    def __rtruediv__(self, other):
        return DS.of(other)/self

    def __pow__(self, power):
        if not isinstance(power, int):
            raise TypeError("DS supports integer powers only")
        if power < 0:
            return 1/(self**(-power))
        value, factor = DS(1), self
        while power:
            if power & 1:
                value = value*factor
            power >>= 1
            if power:
                factor = factor*factor
        return value

    def __abs__(self):
        return -self if self < 0 else self

    def __lt__(self, other):
        b = DS.of(other)
        return bool((self.h < b.h) | ((self.h == b.h) & (self.l < b.l)))

    def __le__(self, other):
        return not self > other

    def __gt__(self, other):
        return DS.of(other) < self

    def __ge__(self, other):
        return not self < other


TABLE = json.loads((Path(__file__).with_name("CONSTANTS.json")).read_text())
C = {name: DS(*value) for name, value in TABLE["scalars"].items()}
EXP_COEF = [DS(*v) for v in TABLE["exp_coefficients"]]
CHEB = {name: [DS(*v) for v in value] for name, value in TABLE["logcdf_chebyshev"].items()}
GAUSS = [(DS(*x), DS(*w)) for x, w in TABLE["gauss8"]]


def exp(x):
    x = DS.of(x)
    n = np.rint(x.h/C["ln2"].h).astype(np.int32)
    u = x-DS(n)*C["ln2"]
    p = EXP_COEF[-1]
    for c in EXP_COEF[-2::-1]:
        p = c+u*p
    return DS(np.ldexp(p.h, n), np.ldexp(p.l, n))


def expm1(x):
    x = DS.of(x)
    if abs(x) > DS(np.float32(.5)):
        return exp(x)-1
    p = EXP_COEF[-1]
    for c in EXP_COEF[-2:0:-1]:
        p = c+x*p
    return x*p


def log(x):
    x = DS.of(x)
    if x <= 0:
        raise ValueError("log domain")
    _, n = np.frexp(x.h)
    m = DS(np.ldexp(x.h, -n), np.ldexp(x.l, -n))
    u = (m-1)/(m+1)
    u2, term, result = u*u, u, u
    for k in range(3, 42, 2):
        term = term*u2
        result = result+term/k
    return 2*result+DS(n)*C["ln2"]


def sqrt(x):
    x = DS.of(x)
    y = DS(np.sqrt(x.h))
    return y+(x-y*y)/(2*y)


def logcdf(x):
    x = DS.of(x)
    if x < -8:
        t, fraction = -x, DS(0)
        for k in range(64, 0, -1):
            fraction = k/(t+fraction)
        return -x*x/2-C["log_sqrt_2pi"]-log(t+fraction)
    if x > 8:
        # Positive tail is evaluated by symmetry, without a CDF subtraction.
        return log(1-exp(logcdf(-x)))
    name, center = ("negative", -4) if x < 0 else ("positive", 4)
    u, b1, b2 = (x-center)/4, DS(0), DS(0)
    for c in CHEB[name][:0:-1]:
        b0 = c+2*u*b1-b2
        b2, b1 = b1, b0
    return CHEB[name][0]+u*b1-b2
