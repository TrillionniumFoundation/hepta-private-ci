"""Post-confirmation numerical candidate; the frozen controller is unchanged."""

import importlib.util
import numbers
from pathlib import Path

import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "control" / "controller.py"
SPEC = importlib.util.spec_from_file_location("hcsn_frozen_tie_controller", SOURCE)
CONTROLLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLLER)


def _tolerance(tol):
    if isinstance(tol, (bool, np.bool_)) or not isinstance(tol, numbers.Real):
        raise ValueError("tol must be a real, finite, nonnegative scalar")
    value = float(tol)
    if not np.isfinite(value) or value < 0:
        raise ValueError("tol must be a real, finite, nonnegative scalar")
    return value


def resolve_action(qvalues, tol=1e-12):
    """Choose the first finite action whose Q loss from the maximum is <= tol.

    Accept [actions] or [batch, actions]; return int or an int64 batch vector.
    Negative infinity masks unavailable actions. NaN, positive infinity, and
    rows without a finite action are rejected. Q inputs are never modified.
    The comparison operates on represented FP64 Q values and an absolute tol.
    A TwoSum remainder resolves the rare rounded-gap == tol boundary correctly.
    """
    tolerance = _tolerance(tol)
    raw = np.asarray(qvalues)
    if raw.dtype.kind not in "fiu" or raw.ndim not in (1, 2) or raw.shape[-1] == 0:
        raise ValueError("Q must be a real numeric vector or matrix with actions")
    q = np.asarray(raw, dtype=np.float64)
    single = q.ndim == 1
    if single:
        q = q[None, :]
    finite = np.isfinite(q)
    if np.isnan(q).any() or np.isposinf(q).any() or not finite.any(axis=1).all():
        raise ValueError("Each Q row needs a finite action; only -inf may mask others")
    maximum = q.max(axis=1, keepdims=True)
    with np.errstate(over="ignore", invalid="ignore"):
        gap = maximum - q
        virtual = gap - maximum
        remainder = (maximum - (gap - virtual)) + (-q - virtual)
        eligible = finite & ((gap < tolerance) | ((gap == tolerance) & (remainder <= 0)))
    if not eligible.any(axis=1).all():
        raise ArithmeticError("No eligible finite maximum")
    action = eligible.argmax(axis=1).astype(np.int64)
    return int(action[0]) if single else action


def wrapped_plan(*args, tol=1e-12, **kwargs):
    """Use unchanged plan Q-values, then return the selected action's true Q.

    This only resolves the returned root action. The original Bellman recursion
    and its optimal continuation values remain unchanged; no frozen run uses it.
    """
    tolerance = _tolerance(tol)
    result = CONTROLLER.plan(*args, **kwargs)
    action = resolve_action(result.qvalues, tolerance)
    selected_value = result.qvalues[np.arange(len(action)), action]
    return CONTROLLER.PlanResult(action, selected_value, result.qvalues)
