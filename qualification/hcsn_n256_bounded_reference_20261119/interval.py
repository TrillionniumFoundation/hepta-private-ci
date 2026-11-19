"""Exact-integer outward enclosures of finite signed Metzler actions.

No NumPy/SciPy/Torch, floating-point arithmetic, Decimal transcendental, or
external interval package participates in the enclosure calculation.
"""

from fractions import Fraction as F
import math


def require(test, message):
    if not test:
        raise ValueError(message)


def ceil_div(n, d):
    require(d > 0, "positive divisor")
    return -((-n)//d)


def fixed(value, scale):
    value = F(value)
    return value.numerator*scale//value.denominator, ceil_div(value.numerator*scale, value.denominator)


def tail_majorant(next_upper, index, bound):
    """Fixed-point upper of sum_{j=index+1}^infty bound**j/j!."""
    require(index+2 > bound >= 0, "geometric tail regime")
    return ceil_div(next_upper*(index+2), index+2-bound)


def exp_positive(argument, bits, terms):
    """Rational bounds for exp(x), x>=0; no transcendental is called."""
    x, scale = F(argument), 1 << bits
    require(x >= 0 and x < terms+2, "bounded positive exponential")
    low = high = total_low = total_high = scale
    for k in range(1, terms+1):
        den = x.denominator*k
        low = low*x.numerator//den
        high = ceil_div(high*x.numerator, den)
        total_low += low
        total_high += high
    next_high = ceil_div(high*x.numerator, x.denominator*(terms+1))
    tail = ceil_div(next_high*x.denominator*(terms+2), x.denominator*(terms+2)-x.numerator)
    return F(total_low, scale), F(total_high+tail, scale)


def multiply_intervals(left, right):
    points = [a*b for a in left for b in right]
    return min(points), max(points)


def uniformization(rows, initial, bits, terms, progress=None):
    """Enclose row initial @ exp(B) for exact rational Metzler matrix B.

q is an integer >= every negative diagonal. D=B+qI is nonnegative.
Signed fixed-point endpoints propagate monotonically through D. A scalar
majorant w>=||D||_infinity bounds each component of the omitted signed series
by input TV*sum_{k>K} w**k/k!. Both exp(q) and all vector terms have outward
integer rounding at every recurrence. Its reciprocal stays rational.
"""
    n, channels, scale = len(rows), len(initial), 1 << bits
    require(1 <= n <= 259 and channels == 5, "pilot dimensions")
    require(all(len(v) == n for v in initial), "initial shape")
    require(all(all(type(j) is int and 0 <= j < n and (j == i or a >= 0)
                    for j, a in row.items()) for i, row in enumerate(rows)), "Metzler rows")
    q = max(0, *(ceil_div((-row.get(i, F(0))).numerator, (-row.get(i, F(0))).denominator)
                  for i, row in enumerate(rows)))
    require(q <= 600, "predeclared warm-1 shift bound")
    d_rows = []
    for i, row in enumerate(rows):
        d = dict(row)
        d[i] = d.get(i, F(0))+q
        require(all(v >= 0 for v in d.values()), "nonnegative shifted matrix")
        d_rows.append({j: v for j, v in d.items() if v})
    maximum = max(sum(row.values(), F(0)) for row in d_rows)
    w = ceil_div(maximum.numerator, maximum.denominator)
    require(w <= 601 and terms+2 > w, "majorant bound and tail regime")
    denominators = [a.denominator for row in d_rows for a in row.values()]
    common = max(denominators, default=1)
    require(common & (common-1) == 0 and all(common % d == 0 for d in denominators), "dyadic matrix")
    columns = [[] for _ in range(n)]
    for i, row in enumerate(d_rows):
        for j, a in row.items():
            columns[j].append((i, a.numerator*(common//a.denominator)))
    lower, upper = [], []
    for vector in initial:
        pair = [fixed(value, scale) for value in vector]
        lower.append([a for a, _ in pair])
        upper.append([b for _, b in pair])
    summed_lower, summed_upper = [v.copy() for v in lower], [v.copy() for v in upper]
    exp_low = exp_high = exp_sum_low = exp_sum_high = majorant = scale
    for k in range(1, terms+1):
        divisor = common*k
        for c in range(channels):
            lo, hi = lower[c], upper[c]
            new_lo, new_hi = [], []
            for column in columns:
                a = sum(lo[i]*coefficient for i, coefficient in column)
                b = sum(hi[i]*coefficient for i, coefficient in column)
                new_lo.append(a//divisor)
                new_hi.append(ceil_div(b, divisor))
            lower[c], upper[c] = new_lo, new_hi
            summed_lower[c] = [a+b for a, b in zip(summed_lower[c], new_lo)]
            summed_upper[c] = [a+b for a, b in zip(summed_upper[c], new_hi)]
        exp_low = exp_low*q//k
        exp_high = ceil_div(exp_high*q, k)
        exp_sum_low += exp_low
        exp_sum_high += exp_high
        majorant = ceil_div(majorant*w, k)
        if progress is not None and k % 256 == 0:
            progress({"terms_completed": k, "dimension": n, "bits": bits})
    exp_tail = tail_majorant(ceil_div(exp_high*q, terms+1), terms, q)
    exp_lower, exp_upper = F(exp_sum_low, scale), F(exp_sum_high+exp_tail, scale)
    inverse = (1/exp_upper, 1/exp_lower)
    require(inverse[0] > 0, "strictly positive rational reciprocal")
    series_tail = F(tail_majorant(ceil_div(majorant*w, terms+1), terms, w), scale)
    tv = [sum(map(abs, vector), F(0)) for vector in initial]
    tail_errors = [inverse[1]*norm*series_tail for norm in tv]
    result = []
    for c in range(channels):
        vector = []
        for lo, hi in zip(summed_lower[c], summed_upper[c]):
            a, b = multiply_intervals((F(lo, scale), F(hi, scale)), inverse)
            lo_fixed = fixed(a-tail_errors[c], scale)[0]
            hi_fixed = fixed(b+tail_errors[c], scale)[1]
            require(lo_fixed <= hi_fixed, "ordered output enclosure")
            vector.append((F(lo_fixed, scale), F(hi_fixed, scale)))
        result.append(vector)
    receipt = {"dimension": n, "channels": channels, "bits": bits, "highest_series_index": terms,
               "q": q, "w": w, "maximum_shifted_row_sum": str(maximum), "common_dyadic_denominator": str(common),
               "input_total_variation": list(map(str, tv)), "exp_positive_bounds": list(map(str, (exp_lower, exp_upper))),
               "exp_negative_bounds": list(map(str, inverse)), "series_tail_upper": str(series_tail),
               "signed_output_tail_upper": list(map(str, tail_errors)),
               "integer_rounding_included": True, "transcendental_calls": 0,
               "vector_recurrences": terms*channels, "nonzero_shifted_entries": sum(map(len, d_rows))}
    return result, receipt


def rounded_fraction(value):
    """Independent integer roundTiesToEven to finite binary64 bits."""
    value = F(value)
    if not value:
        return 0
    sign = (1 << 63) if value < 0 else 0
    a, b = abs(value.numerator), value.denominator
    exponent = a.bit_length()-b.bit_length()
    if exponent >= 0:
        exponent -= a < (b << exponent)
    else:
        exponent -= (a << -exponent) < b
    shift = 1074 if exponent < -1022 else 52-exponent
    num, den = (a << shift, b) if shift >= 0 else (a, b << -shift)
    quotient, remainder = divmod(num, den)
    quotient += 2*remainder > den or (2*remainder == den and quotient & 1)
    if exponent < -1022:
        require(quotient <= 1 << 52, "subnormal conversion")
        return sign | quotient
    if quotient == 1 << 53:
        quotient >>= 1
        exponent += 1
    require(exponent <= 1023, "no binary64 overflow")
    return sign | ((exponent+1023) << 52) | (quotient-(1 << 52))


def exact_from_bits(bits):
    sign = -1 if bits >> 63 else 1
    exponent, mantissa = (bits >> 52) & 2047, bits & ((1 << 52)-1)
    require(exponent != 2047, "finite binary64")
    if exponent:
        mantissa += 1 << 52
        power = exponent-1075
    else:
        power = -1074
    return sign*(F(mantissa << power) if power >= 0 else F(mantissa, 1 << -power))


def rn(value):
    return exact_from_bits(rounded_fraction(value))


def scalar_occupation(initial_upper, rho, duration, bits):
    """Old permanent upper, separately from newly escaped upper state.

The declared scalar target is u*(1-exp(-z))/rho, z=RN(rho*duration).
This isolates the executed FP64 scalar argument from exact rho*duration.
"""
    require(rho > 0 and duration > 0 and len(initial_upper) == 5,
            "positive discount/duration and five upper channels")
    z = rn(rho*duration)
    positive = exp_positive(z, bits, 64)
    integral = ((1-1/positive[0])/rho, (1-1/positive[1])/rho)
    return [multiply_intervals((u, u), integral) for u in initial_upper], {
        "argument": str(z), "exact_argument_before_rounding": str(rho*duration),
        "exp_positive_bounds": list(map(str, positive)), "integral_bounds": list(map(str, integral)),
        "signed_upper_total_variation": list(map(lambda x: str(abs(x)), initial_upper)), "terms": 64}


def scaling_perturbation(unscaled_rows, scaled_rows, duration, initial, bits):
    """Duhamel bound from exact A_fp*dt_fp to entrywise rounded B.

For row-vector l1, exp growth is bounded by the maximum row sum of a
Metzler matrix. This avoids the useless exp(||B||) bound at stiff grids.
"""
    n = len(unscaled_rows)
    require(duration > 0 and len(scaled_rows) == n and all(len(v) == n for v in initial),
            "Duhamel equal dimensions and positive duration")
    for rows in (unscaled_rows, scaled_rows):
        require(all(all(type(j) is int and 0 <= j < n and (j == i or v >= 0)
                        for j, v in row.items()) for i, row in enumerate(rows)), "Duhamel Metzler operators")
    exact_rows = [{j: v*duration for j, v in row.items()} for row in unscaled_rows]
    delta = max(sum((abs(row.get(j, F(0))-rounded.get(j, F(0)))
                     for j in set(row) | set(rounded)), F(0))
                for row, rounded in zip(exact_rows, scaled_rows))
    growth = max(F(0), *(sum(row.values(), F(0)) for row in exact_rows),
                 *(sum(row.values(), F(0)) for row in scaled_rows))
    factor = exp_positive(growth, bits, 64)[1]
    tv = [sum(map(abs, vector), F(0)) for vector in initial]
    return {"operator_infinity_difference": str(delta), "maximum_row_sum_growth_bound": str(growth),
            "exponential_growth_upper": str(factor), "per_channel_output_l1_bound": [str(v*delta*factor) for v in tv],
            "scope": "Exact A_fp*dt_fp versus RN(A_fp*dt_fp) only; does not bound spatial discretization or earlier generator assembly."}
