"""Conservative independent FBSDE path evidence boundary; research only.

This is a receipt *structure* and exact residual checker for a registered
rational deterministic two-sided law. It is NOT a general SDE solver,
a physical-time verifier, or proof that reported inputs are authenticated.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
from typing import Sequence
from action_gate import q


@dataclass(frozen=True)
class Edge:
    duration: str
    x_start: str
    x_end: str
    y_start: str
    y_end: str


@dataclass(frozen=True)
class PathResult:
    globally_consistent: bool
    reason: str
    max_residual: str
    authority: str = "DENY_ALL"


def check_two_sided_path(
    edges: Sequence[Edge], *, x0: str, terminal_gain: str,
    max_duration: str = "4",
) -> PathResult:
    """Exact special case dX=Y dt, dY=0, Y_T=g X_T.

    The independent endpoint test detects a locally valid wrong-reset.
    A passing result applies only to THIS toy law; it is not qualified
    for neural stochastic-FBSDE admission, model selection, or FinalUse.
    """
    if not isinstance(edges, (list, tuple)) or not 1 <= len(edges) <= 32:
        raise ValueError("bounded path required")
    start = q(x0, signed=True)
    gain = q(terminal_gain, signed=True)
    max_t = q(max_duration)
    elapsed = F(0)
    worst = F(0)
    for edge in edges:
        if type(edge) is not Edge:
            raise ValueError("typed edge required")
        dt = q(edge.duration)
        if dt == 0:
            raise ValueError("zero duration")
        elapsed += dt
        if elapsed > max_t:
            raise ValueError("horizon exceeded")
        xs, xe = q(edge.x_start, signed=True), q(edge.x_end, signed=True)
        ys, ye = q(edge.y_start, signed=True), q(edge.y_end, signed=True)
        worst = max(worst, abs(xs - start), abs(xe - xs - dt * ys),
                    abs(ye - ys))
        # Need BOTH forward state and backward adjoint continuous.
        start = xe
    initial = q(x0, signed=True)
    worst = max(worst, abs(q(edges[0].x_start, signed=True) - initial))
    for previous, current in zip(edges, edges[1:]):
        worst = max(worst,
                    abs(q(previous.x_end, signed=True) - q(current.x_start, signed=True)),
                    abs(q(previous.y_end, signed=True) - q(current.y_start, signed=True)))
    worst = max(worst, abs(q(edges[-1].y_end, signed=True) -
                           gain * q(edges[-1].x_end, signed=True)))
    # For this deterministic law, nonzero worst means at least one
    # explicit global constraint was violated.
    if worst:
        return PathResult(False, "two_sided_or_terminal_residual", str(worst))
    # An algebraic solution may still cross a decoupling-field pole.
    factor = 1 - gain * elapsed
    if factor == 0:
        return PathResult(False, "nonregular_or_nonunique_global_boundary", "0")
    if gain > 0 and gain * elapsed >= 1:
        return PathResult(False, "regular_field_crosses_pole", "0")
    # Check the global solution against the complete initial-boundary system.
    y0 = gain * initial / factor
    if q(edges[0].y_start, signed=True) != y0:
        return PathResult(False, "global_initial_field_mismatch", str(abs(q(edges[0].y_start, signed=True) - y0)))
    return PathResult(True, "exact_special_case_only", "0")
