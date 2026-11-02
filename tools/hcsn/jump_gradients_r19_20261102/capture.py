"""Capture left-limit locals from the unmodified actual R18 jump solver return."""

import hashlib
from pathlib import Path
import sys

import numpy as np

from ..continuous_task_r18_20261101 import jump_solver, positive_reference


SOURCE_PATH = Path(jump_solver.__file__)


def solve(config, dx, dt):
    captured = {}
    prior = sys.getprofile()
    code = jump_solver.solve.__code__

    def observe(frame, event, argument):
        if frame.f_code is code and event == "return" and isinstance(argument, dict):
            local = frame.f_locals
            if "left_limits" not in local or "values" not in local:
                raise RuntimeError("Canonical jump solver no longer exposes the qualified return locals")
            captured["left_limits"] = {key: value.copy() for key, value in local["left_limits"].items()}
            captured["return_values"] = local["values"]
        if prior is not None:
            prior(frame, event, argument)

    sys.setprofile(observe)
    try:
        result = jump_solver.solve(config, dx, dt)
    finally:
        sys.setprofile(prior)
    if result["values"] is not captured.get("return_values"):
        raise RuntimeError("Captured frame is not the actual returned primal")
    expected = set(range(result["lag"], len(result["times"]), result["lag"]))
    if set(captured["left_limits"]) != expected or any(v.shape != result["values"].shape[1:] for v in captured["left_limits"].values()):
        raise RuntimeError("Captured left limits are incomplete")
    if not np.array_equal(captured["left_limits"][result["lag"]], result["first_left_limit"]):
        raise RuntimeError("Canonical returned first left limit differs from capture")
    result["left_limits"] = captured["left_limits"]
    result["canonical_source_sha256"] = hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()
    return result


def reference(config, dx, dt):
    return positive_reference.solve(config, dx, dt)
