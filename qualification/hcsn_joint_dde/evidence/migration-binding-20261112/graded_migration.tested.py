"""Conservative FP64 initial-law lift into a fixed boundary-graded mesh.

Uniform spatial cells and a shifted exponential tail are integrated against
linear hat functions. Lower-node mass is transferred to the first interior
node, explicitly changing that part of the continuous law. The transfer does
not assert a hit at time zero. Signed channels use exactly the same matrix.
Refractory laws retain their rationalized original remaining-time supports.
"""

from fractions import Fraction
import hashlib
import math

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet


def migration_weights(nodes, endpoint=4.8, cells=16, tail_rate=1.0):
    nodes = np.asarray(nodes, dtype=np.float64)
    if (
        nodes.ndim != 1
        or not 5 <= len(nodes) <= 513
        or not np.isfinite(nodes).all()
        or nodes[0] != 0
        or np.any(np.diff(nodes) <= 0)
        or not 0 < endpoint <= nodes[-1] <= 8
        or type(cells) is not int
        or not 1 <= cells <= 256
        or not math.isfinite(tail_rate)
        or tail_rate <= 0
    ):
        raise ValueError("invalid source reconstruction or target grid")
    weights = np.zeros((cells + 1, len(nodes)))
    edges = np.linspace(0, endpoint, cells + 1)
    for j, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        for i, (a, b) in enumerate(zip(nodes[:-1], nodes[1:])):
            lo, hi = max(left, a), min(right, b)
            if hi > lo:
                mass = (hi - lo) / (right - left)
                weights[j, i] += mass * (b - (lo + hi) / 2) / (b - a)
                weights[j, i + 1] += mass * ((lo + hi) / 2 - a) / (b - a)
    for i, (a, b) in enumerate(zip(nodes[:-1], nodes[1:])):
        lo, hi = max(endpoint, a), b
        if hi > lo:
            width = hi - lo
            start = math.exp(-tail_rate * (lo - endpoint))
            zeroth = -math.expm1(-tail_rate * width)
            first = zeroth / tail_rate - width * math.exp(-tail_rate * width)
            weights[-1, i] += start * ((b - lo) * zeroth - first) / (b - a)
            weights[-1, i + 1] += start * ((lo - a) * zeroth + first) / (b - a)
    overshoot = math.exp(-tail_rate * (nodes[-1] - endpoint))
    weights[-1, -1] += overshoot
    moved = weights[:, 0].copy()
    weights[:, 1] += moved
    weights[:, 0] = 0.0
    residual = weights.sum(1) - 1
    if (
        not np.isfinite(weights).all()
        or weights.min() < 0
        or max(abs(residual)) > 2e-13
    ):
        raise ArithmeticError("nonnegative conservative integration unresolved")
    report = {
        "maximum_basis_mass_residual": float(max(abs(residual))),
        "lower_mass_transferred": moved.tolist(),
        "lower_mean_shift": (moved * nodes[1]).tolist(),
        "tail_upper_overshoot_probability": overshoot,
        "tail_expected_upper_overshoot": overshoot / tail_rate,
    }
    weights.setflags(write=False)
    return weights, report


def migrate(
    model, probability, content, weights, *, identity="graded", phase_cells=8,
    source_endpoint=4.8, source_tail_rate=1.0,
):
    """Transport through the canonical map bound to declared source and target.

    Conserving mass alone does not make a supplied matrix the correct law
    migration. Recompute the declared map and reject substitutions before
    reading out a new state. Nondefault source laws must be explicit.
    """
    p, marks = np.asarray(probability, dtype=float), np.asarray(content, dtype=float)
    weights = np.array(weights, dtype=float, copy=True)
    cells = weights.shape[0] if weights.ndim == 2 else 0
    if (
        type(phase_cells) is not int
        or not 1 <= phase_cells <= 128
        or not isinstance(identity, str)
        or not identity
        or weights.ndim != 2
        or not 2 <= cells <= 257
        or weights.shape[1] != model.spatial.intervals + 1
        or not np.isfinite(weights).all()
        or np.min(weights) < 0
        or np.any(weights[:, 0] != 0)
        or max(abs(weights.sum(1) - 1)) > 2e-13
        or p.shape != (cells + phase_cells,)
        or marks.ndim != 2
        or marks.shape[0] != len(p)
        or not 1 <= marks.shape[1] <= 16
        or not np.isfinite(p).all()
        or np.min(p) < 0
        or not np.isfinite(marks).all()
    ):
        raise ValueError("finite conservative migration shapes/values required")
    canonical, _ = migration_weights(
        model.spatial.nodes, endpoint=source_endpoint, cells=cells-1,
        tail_rate=source_tail_rate,
    )
    if not np.array_equal(weights, canonical):
        raise ValueError("migration weights are not bound to the declared source law and target nodes")
    active, marked = p[:cells] @ weights, weights.T @ marks[:cells]
    phase = []
    delay = Fraction(str(model.delay))
    for j in range(phase_cells):
        mass, channel = p[cells + j], marks[cells + j]
        if mass == 0:
            if np.any(channel != 0):
                raise ValueError("zero-mass marked phase is unsupported by Packet")
            continue
        phase.append(
            Packet(
                f"{identity}-{j}",
                delay * j / phase_cells,
                delay * (j + 1) / phase_cells,
                Fraction(str(float(mass))),
                tuple(Fraction(str(float(x))) for x in channel),
            )
        )
    mass_error = float(active.sum() + sum(float(x.mass) for x in phase) - p.sum())
    mark_error = marked.sum(0) + marks[cells:].sum(0) - marks.sum(0)
    if (
        not np.isfinite(active).all()
        or not np.isfinite(marked).all()
        or abs(mass_error) > 5e-13 * max(1.0, p.sum())
        or np.max(abs(mark_error)) > 5e-13 * max(1.0, np.sum(abs(marks)))
    ):
        raise ArithmeticError("migration changed mass or signed content")
    return (
        active,
        marked,
        tuple(phase),
        {
            "mass_residual": mass_error,
            "content_residual": mark_error.tolist(),
            "lower_atom": float(active[0]),
            "upper_mass": float(active[-1]),
            "binding": {
                "schema": "hcsn-graded-migration-map-v1",
                "source_endpoint": source_endpoint,
                "source_active_cells": cells-1,
                "source_tail_rate": source_tail_rate,
                "phase_cells": phase_cells,
                "delay": model.delay,
                "target_nodes_sha256": hashlib.sha256(
                    np.asarray(model.spatial.nodes, dtype="<f8").tobytes()
                ).hexdigest(),
                "weights_sha256": hashlib.sha256(
                    np.asarray(weights, dtype="<f8").tobytes()
                ).hexdigest(),
            },
        },
    )
