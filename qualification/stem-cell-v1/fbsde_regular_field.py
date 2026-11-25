"""Globally admitted deterministic fully coupled FBSDE continuation fixture.

dX=Y dt, dY=-c X dt, X(0)=x0, Y(T)=g X(T).
Exact harmonic flow and a backward decoupling field test every interface.
This scalar zero-noise case is independent of finite-tree chance/AND controls,
not a general stochastic FBSDE, neural solver or usable online action policy.
"""
from __future__ import annotations

import math


class NoRegularGlobalField(ValueError):
    pass


def _finite(value, name, *, low=0.0, high=1e6):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise NoRegularGlobalField(f"invalid {name}")
    return float(value)


def _flow(duration, c):
    if c == 0:
        return (1., duration, 0., 1.)
    rate = math.sqrt(c)
    sine, cosine = math.sin(rate * duration), math.cos(rate * duration)
    return (cosine, sine / rate, -rate * sine, cosine)


def _field(qend, coefficients, *, denominator_floor):
    a, b, c, d = coefficients
    denominator = d - qend * b
    if denominator <= denominator_floor:
        raise NoRegularGlobalField("singular or ill-conditioned decoupling field")
    q = (qend * a - c) / denominator
    if not math.isfinite(q):
        raise NoRegularGlobalField("nonfinite decoupling slope")
    return q, denominator


def _regular_horizon(c, g):
    if c == 0:
        return math.inf if g == 0 else 1 / g
    rate = math.sqrt(c)
    return (math.pi / 2 - math.atan(g / rate)) / rate


def examine(*, x0=1.0, c=1.0, g=0.5, horizon=0.5, segments=4,
            pole_margin=1e-6, max_slope=1e6):
    """Reject GLOBAL irregularity before fitting any short-horizon grid.

    Correct segments inherit the next segment's terminal field; the
    wrong-reset control independently reuses original g at every boundary.
    An accepted endpoint or low local residual does not override Y jumps.
    """
    x0 = _finite(x0, "initial state", low=-1e6)
    c = _finite(c, "oscillator curvature", high=100.)
    g = _finite(g, "terminal coefficient", high=100.)
    horizon = _finite(horizon, "horizon", low=1e-9, high=100.)
    pole_margin = _finite(pole_margin, "regularity margin", low=1e-12, high=.1)
    max_slope = _finite(max_slope, "maximum slope", low=1, high=1e12)
    if type(segments) is not int or not 1 <= segments <= 512:
        raise NoRegularGlobalField("bounded segment count required")
    regular_until = _regular_horizon(c, g)
    if horizon >= regular_until - pole_margin:
        raise NoRegularGlobalField("global regularity fails; refinement cannot repair a pole")
    coefficients = _flow(horizon / segments, c)
    fields = [0.] * (segments + 1)
    fields[-1] = g
    denominators = []
    for i in reversed(range(segments)):
        fields[i], denominator = _field(fields[i + 1], coefficients,
                                        denominator_floor=pole_margin)
        denominators.append(denominator)
        if abs(fields[i]) > max_slope:
            raise NoRegularGlobalField("global field slope bound exceeded")
    full_slope, whole_denominator = _field(g, _flow(horizon, c),
                                           denominator_floor=pole_margin)
    if abs(full_slope) > max_slope:
        raise NoRegularGlobalField("full-horizon field slope bound exceeded")
    x, y = x0, x0 * fields[0]
    a, b, cc, d = coefficients
    correct_interfaces = []
    for i in range(segments):
        new_x, new_y = a*x + b*y, cc*x + d*y
        correct_interfaces.append(abs(new_y - fields[i + 1]*new_x))
        x, y = new_x, new_y
    terminal_residual = abs(y - g*x)
    if (max(correct_interfaces) > 1e-9
            or terminal_residual > 1e-9
            or abs(fields[0] - full_slope) > 1e-9):
        raise NoRegularGlobalField("correct short-horizon continuation did not stitch")
    # Wrong control: each local segment separately satisfies Y_end=g X_end;
    # reset Y at the next start, destroying full-interval backward continuity.
    wrong_field, _ = _field(g, coefficients, denominator_floor=pole_margin)
    wx, wy = x0, x0 * wrong_field
    jumps = []
    wrong_segment_terminal_residuals = []
    for i in range(segments):
        new_x, new_y = a*wx + b*wy, cc*wx + d*wy
        wrong_segment_terminal_residuals.append(abs(new_y - g*new_x))
        if i < segments-1:
            reset = wrong_field * new_x
            jumps.append(abs(reset - new_y))
            wy = reset
        else:
            wy = new_y
        wx = new_x
    return {
        "schema": "hepta.fbsde.exact-regular-field.v1",
        "global_regular_until": regular_until if math.isfinite(regular_until) else None,
        "horizon": horizon, "segments": segments,
        "first_field": fields[0], "whole_interval_field": full_slope,
        "max_global_interface_residual": max(correct_interfaces),
        "terminal_residual": terminal_residual,
        "minimum_local_denominator": min(denominators),
        "whole_denominator": whole_denominator,
        "wrong_reset_max_jump": max(jumps, default=0.),
        "wrong_reset_local_terminal_residual": max(wrong_segment_terminal_residuals),
        "same_global_terminal_condition": True,
        "regular_global_decoupling_field_admitted": True,
        "general_stochastic_fbsde_solved": False,
        "independent_reasoning_improvement": False,
        "production_accepted": False
    }
