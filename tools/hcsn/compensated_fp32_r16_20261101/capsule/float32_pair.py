"""Explicit two-word FP32 arithmetic; no FP64 financial operations.

About 44--48 significand bits in the normal range, with the FP32 exponent range.
This is compensated FP32, not an ordinary single-word FP32 implementation.
Rational normal-CDF coefficients: SciPy v1.14.1 Cephes ndtr.h (BSD-3-Clause);
original Cephes copyright 1984, 1987, 1988, 1992 Stephen L. Moshier.
See SCIPY_LICENSE.txt and SPECIAL_FUNCTION_SOURCE.json in this directory.
"""
from decimal import Decimal, localcontext
import math
import numpy as np

F = np.float32
_CONSTANTS = {}


def two_sum(a, b):
    s = a + b
    v = s - a
    return s, (a - (s - v)) + (b - v)


def two_product(a, b):
    p = a * b
    ac, bc = F(4097) * a, F(4097) * b
    ah, bh = ac - (ac - a), bc - (bc - b)
    al, bl = a - ah, b - bh
    return p, ((ah * bh - p) + ah * bl + al * bh) + al * bl


class Pair:
    __array_priority__ = 1000

    def __init__(self, value, low=None):
        if isinstance(value, Pair):
            self.hi, self.lo = value.hi, value.lo
        elif low is not None or isinstance(value, (np.ndarray, np.float32)):
            if isinstance(value, np.ndarray) and value.dtype != np.float32:
                raise TypeError('Financial arrays must already be float32')
            self.hi = np.asarray(value, dtype=np.float32)
            self.lo = np.zeros_like(self.hi) if low is None else np.asarray(low, dtype=np.float32)
        else:
            # This path is for fixed literal coefficients only. Dynamic inputs
            # enter as np.float32; range-reduction integers also fit exactly.
            key = str(value)
            if key not in _CONSTANTS:
                with localcontext() as ctx:
                    ctx.prec = 80
                    exact = Decimal(value) if isinstance(value, (str, int)) else Decimal.from_float(float(value))
                    hi = F(str(exact))
                    lo = F(str(exact - Decimal.from_float(float(hi))))
                _CONSTANTS[key] = np.asarray(hi), np.asarray(lo)
            self.hi, self.lo = _CONSTANTS[key]

    @property
    def dtype(self):
        return self.hi.dtype

    def __add__(self, other):
        other = Pair(other)
        s, e = two_sum(self.hi, other.hi)
        e = e + (self.lo + other.lo)
        return Pair(*two_sum(s, e))

    __radd__ = __add__

    def __neg__(self):
        return Pair(-self.hi, -self.lo)

    def __sub__(self, other):
        return self + (-Pair(other))

    def __rsub__(self, other):
        return Pair(other) - self

    def __mul__(self, other):
        other = Pair(other)
        p, e = two_product(self.hi, other.hi)
        e = e + self.hi * other.lo + self.lo * other.hi
        e = e + self.lo * other.lo
        return Pair(*two_sum(p, e))

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = Pair(other)
        q = Pair(self.hi / other.hi)
        for _ in range(2):
            residual = self - other * q
            q = q + Pair((residual.hi + residual.lo) / other.hi)
        return q

    def __rtruediv__(self, other):
        return Pair(other) / self

    def __pow__(self, power):
        if not isinstance(power, int):
            raise TypeError('Only integer powers are needed by this kernel')
        if power < 0:
            return 1 / (self ** -power)
        result, base = Pair(1), self
        while power:
            if power % 2:
                result = result * base
            base = base * base
            power //= 2
        return result

    def __abs__(self):
        return -self if self < 0 else self

    def __lt__(self, other):
        other = Pair(other)
        return bool((self.hi < other.hi) | ((self.hi == other.hi) & (self.lo < other.lo)))

    def __le__(self, other):
        return not Pair(other) < self

    def __gt__(self, other):
        return Pair(other) < self

    def __ge__(self, other):
        return not self < other

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        if method == '__call__' and ufunc is np.isfinite:
            return np.isfinite(self.hi) & np.isfinite(self.lo)
        if method == '__call__' and ufunc in (np.add, np.subtract, np.multiply, np.divide):
            left, right = map(Pair, inputs)
            return {np.add: Pair.__add__, np.subtract: Pair.__sub__,
                    np.multiply: Pair.__mul__, np.divide: Pair.__truediv__}[ufunc](left, right)
        return NotImplemented

    def rounded(self):
        return self.hi + self.lo


LN2 = Pair('0.693147180559945309417232121458176568')
INV_SQRT2 = Pair('0.707106781186547524400844362104849039')
INV_SQRT2PI = Pair('0.398942280401432677939946059934381868')
LOG_SQRT2PI = Pair('0.918938533204672741780329736405617640')


def exp(x):
    x = Pair(x)
    if x < -104:
        return Pair(0)
    if x > 88:
        raise ArithmeticError('FP32 exponential range exceeded')
    k = int(np.rint(x.hi * F(1.4426950408889634)))
    r = x - Pair(F(k)) * LN2
    result = Pair(1) / math.factorial(16)
    for n in range(15, -1, -1):
        result = result * r + Pair(1) / math.factorial(n)
    return Pair(np.ldexp(result.hi, k), np.ldexp(result.lo, k))


def expm1(x):
    x = Pair(x)
    if abs(x) < .5:
        result = Pair(1) / math.factorial(16)
        for n in range(15, 0, -1):
            result = result * x + Pair(1) / math.factorial(n)
        return result * x
    return exp(x) - 1


def sqrt(x):
    x = Pair(x)
    y = Pair(np.sqrt(x.hi))
    return y + (x - y * y) / (2 * y)


def log(x):
    x = Pair(x)
    y = Pair(np.log(x.hi))
    r = x / exp(y) - 1
    return y + r - r * r / 2


def log1p(x):
    x = Pair(x)
    if abs(x) < .1:
        result = Pair(-1) / 16
        for n in range(15, 0, -1):
            result = result * x + Pair(1 if n % 2 else -1) / n
        return result * x
    return log(1 + x)


P = [Pair(v) for v in ['2.46196981473530512524E-10','5.64189564831068821977E-1','7.46321056442269912687','48.6371970985681366614','196.520832956077098242','526.445194995477358631','934.528527171957607540','1027.55188689515710272','557.535335369399327526']]
Q = [Pair(v) for v in ['1','13.2281951154744992508','86.7072140885989742329','354.937778887819891062','975.708501743205489753','1823.90916687909736289','2246.33760818710981792','1656.66309194161350182','557.535340817727675546']]
R = [Pair(v) for v in ['.564189583547755073984','1.27536670759978104416','5.01905042251180477414','6.16021097993053585195','7.40974269950448939160','2.97886665372100240670']]
S = [Pair(v) for v in ['1','2.26052863220117276590','9.39603524938001434673','12.0489539808096656605','17.0814450747565897222','9.60896809063285878198','3.36907645100081516050']]
T = [Pair(v) for v in ['9.60497373987051638749','90.0260197203842689217','2232.00534594684319226','7003.32514112805075473','55592.3013010394962768']]
U = [Pair(v) for v in ['1','33.5617141647503099647','521.357949780152679795','4594.32382970980127987','22629.0000613890934246','49267.3942608635921086']]


def polynomial(x, coefficients):
    result = coefficients[0]
    for c in coefficients[1:]:
        result = result * x + c
    return result


def erfc_ratio(x):
    return polynomial(x, P if x < 8 else R) / polynomial(x, Q if x < 8 else S)


def cdf(x):
    x = Pair(x)
    z = x * INV_SQRT2
    if abs(z) < 1:
        erf = z * polynomial(z * z, T) / polynomial(z * z, U)
        return (1 + erf) / 2
    tail = exp(-z * z) * erfc_ratio(abs(z)) / 2
    return 1 - tail if x > 0 else tail


def logcdf(x):
    x = Pair(x)
    z = x * INV_SQRT2
    if abs(z) < 1:
        return log(cdf(x))
    logtail = -z * z + log(erfc_ratio(abs(z))) - LN2
    return log1p(-exp(logtail)) if x > 0 else logtail
