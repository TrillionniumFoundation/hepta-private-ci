"""Research-only proved slope bounds for an *explicit* piecewise-linear barrier.

The caller must use straight-line interpolation between supplied binary64
knots throughout the observation window. These knot values alone do NOT prove
any bound for an independently learned/curved/updated boundary between knots.

The segment slopes and their extrema are computed as exact rational numbers
of the stored binary64 knot values. The output slopes are rounded *outward*
to finite binary64 numbers, or refused. Analytic first-hit outputs are still
mpmath approximations, NOT rigorously enclosed FP probabilities.
"""
from collections import namedtuple
from fractions import Fraction
import math

from .moving_boundary_enclosure import slope_bounded_first_hit

PiecewiseHitEnvelope = namedtuple(
    "PiecewiseHitEnvelope", "lower_slope upper_slope lower upper"
)


def _fraction_of_f64(value):
    # Do not silently round external decimal or large-integer knot values.
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("knots must be finite binary64 floats")
    return Fraction.from_float(value)


def _outward_float(value: Fraction, *, upward: bool) -> float:
    """Enclose one exact rational by one binary64 endpoint, or refuse."""
    try:
        rounded = float(value)
    except OverflowError as exc:
        raise ArithmeticError("piecewise slope exceeds finite f64") from exc
    if not math.isfinite(rounded):
        raise ArithmeticError("piecewise slope exceeds finite f64")
    exact_rounded = Fraction.from_float(rounded)
    if upward and exact_rounded < value:
        rounded = math.nextafter(rounded, math.inf)
    elif not upward and exact_rounded > value:
        rounded = math.nextafter(rounded, -math.inf)
    if not math.isfinite(rounded):
        raise ArithmeticError("piecewise slope enclosure exceeds finite f64")
    return rounded


def certified_slope_bounds(knots: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """Finite outward bounds on all a.e. slopes of exact f64-knot interpolation.

    The piecewise-linear curve is continuous between strictly increasing
    times and has derivative almost everywhere. At knots, derivatives need
    not exist; the bound holds in the Lipschitz/pathwise comparison sense.
    The first time must be exactly 0, and the final time > 0 defines T.
    """
    if not isinstance(knots, (tuple, list)) or not 2 <= len(knots) <= 4096:
        raise ValueError("require 2..4096 piecewise boundary knots")
    coords = []
    for knot in knots:
        if not isinstance(knot, (tuple, list)) or len(knot) != 2:
            raise ValueError("each knot must contain exactly (time, boundary)")
        coords.append((_fraction_of_f64(knot[0]), _fraction_of_f64(knot[1])))
    if coords[0][0] != 0:
        raise ValueError("piecewise boundary must start at t=0")
    slopes = []
    for (ta, ba), (tb, bb) in zip(coords, coords[1:]):
        if tb <= ta:
            raise ValueError("piecewise times must be strictly increasing")
        slopes.append((bb - ba) / (tb - ta))
    return (_outward_float(min(slopes), upward=False),
            _outward_float(max(slopes), upward=True))


def piecewise_linear_first_hit_envelope(x, mu, sigma, knots, q=0, *, dps=100):
    """Enclose first hit for the explicitly declared piecewise-linear barrier.

    Requires that *this interpolation is the actual barrier path* and that
    the Brownian drift/volatility remain frozen. Rates are finite f64 slope
    enclosures. Probabilities are numerical approximations rather than
    directed-rounding interval certifications.
    """
    if type(dps) is not int or not 50 <= dps <= 300:
        raise ValueError("dps outside [50,300]")
    c_lo, c_hi = certified_slope_bounds(knots)
    result = slope_bounded_first_hit(
        x, knots[0][1], mu, sigma, c_lo, c_hi, knots[-1][0], q, dps=dps
    )
    return PiecewiseHitEnvelope(c_lo, c_hi, result.lower, result.upper)
