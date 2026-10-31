"""One fixed panel-origin translation for a prospective V4 study.

Pure NumPy only. The caller must capture observed_initial at step zero from
the stage's authorized probe/guard measurements, freeze it for that path,
and bind this operation as part of the policy identity. This helper grants
no permission to use a held-out panel and makes no outcome guarantee.
"""

import numpy as np

PANEL_INDICES = (0, 1, 2, 3, 12, 13, 14, 15, 24, 25, 26, 27, 28, 29)


def vector(value, label):
    result = np.array(value, dtype=np.float64, copy=True)
    if result.shape != (30,) or not np.isfinite(result).all():
        raise ValueError(label + " must be a finite 30-vector")
    return result


def fit_origin(bank):
    if bank.get("schema") != "hepta.field-bridge.v3.terminal-reference-bank.1":
        raise ValueError("Expected the frozen V3 terminal-reference bank")
    initial = [row for row in bank["records"] if row["step"] == 0]
    if len(initial) != 4 or {row["trajectory"] for row in initial} != {0, 1, 2, 3}:
        raise ValueError("All four fit-path initial states are required")
    states = np.stack([vector(row["state"], "fit initial") for row in initial])
    selected = states[:, PANEL_INDICES]
    if not np.array_equal(selected, np.broadcast_to(selected[0], selected.shape)):
        raise ValueError("Fit paths have different panel origins; no averaging is allowed")
    return states[0].copy()


def translate(raw, observed_initial, reference_initial):
    values = np.asarray(raw, dtype=np.float64)
    if values.ndim not in (1, 2) or values.shape[-1] != 30 or not np.isfinite(values).all():
        raise ValueError("State must be a finite 30-vector or matrix of 30-vectors")
    observed = vector(observed_initial, "observed initial")
    reference = vector(reference_initial, "reference initial")
    offset = observed[list(PANEL_INDICES)] - reference[list(PANEL_INDICES)]
    result = values.copy()
    result[..., list(PANEL_INDICES)] -= offset
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite translated state")
    return result
