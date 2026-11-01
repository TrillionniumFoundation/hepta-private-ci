"""Explicitly bounded training interface for the unchanged historical R11 core.

The old general evaluator remains available under upstream/kernel.py for audits.
This interface admits FP64 and an FP32 interface with an FP64 kernel only. The
parameter box is inherited unchanged, and finite fixtures do not certify every
point in that box. A finite output check is a numerical refusal, not a proof.
"""

import math

import numpy as np

from experiments.hcsn_validation_r12_20261031.numerics.upstream import kernel


def evaluate(theta, state, *, coordinate="log_distance", mode="float64"):
    if mode not in ("float64", "mixed32"):
        raise ValueError("Unqualified internal precision; pure FP32 is audit-only")
    if coordinate not in ("asset", "log_distance"):
        raise ValueError("Unknown coordinate")
    dtype = np.float64 if mode == "float64" else np.float32
    if not math.isfinite(float(state)):
        raise ValueError("Finite state required")
    if abs(float(state)) > float(np.finfo(dtype).max):
        raise ValueError("State is not representable at the requested interface precision")
    represented = dtype(state)
    if not np.isfinite(represented):
        raise ValueError("State is not representable at the requested interface precision")
    if coordinate == "log_distance" and not 0 <= represented <= 2:
        raise ValueError("Outside the declared log-distance training domain [0,2]")
    with np.errstate(over="raise", divide="raise", invalid="raise", under="ignore"):
        represented_theta = np.asarray(theta, dtype=dtype).astype(np.float64)
        boundary, _ = kernel.evaluate(represented_theta, 0.0, coordinate="log_distance", mode="float64")
        if coordinate == "asset":
            if represented <= 0:
                raise ValueError("Positive asset required")
            distance = math.log(float(represented)) - math.log(float(boundary[0]))
            if not 0 <= distance <= 2:
                raise ValueError("Asset outside the continuation training domain 0<=log(V/B)<=2")
        values, jacobian = kernel.evaluate(theta, represented, coordinate=coordinate, mode=mode)
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(jacobian)):
        raise ArithmeticError("Nonfinite full-kernel value or derivative")
    return values, jacobian
