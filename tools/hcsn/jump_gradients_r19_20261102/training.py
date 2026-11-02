"""Actual analytic-gradient update with frozen physical inputs and fixed targets.

This calibrates the declared value model, not neural language/AV competence.
No derivative of a hard action is taken. Accepted parameter updates may change
active sets; the actual canonical objective is reevaluated by a fixed line search.
"""

import hashlib
import json
import time

import numpy as np

from . import capture, tangent
from .coordinates import decode, encode, query
from ..continuous_task_r18_20261101.task import DEFAULT


DATA = [(t, mode, state) for t in (.3, .5, .9, 1.1) for mode in (0, 1) for state in (-.43, .17, .83)]
DELTA = np.array([.15, .20, .15, .15, -.10, -.11, .15, -.15, -.10, .10, .15, -.10, .10, .10, .15])


def predictions(solution, gradient=None):
    values, rows = [], []
    for remaining, mode, state in DATA:
        index = int(round(remaining / solution["dt"]))
        if gradient is None:
            values.append(float(np.interp(state, solution["x"], solution["values"][index, mode])))
        else:
            value, derivative, _ = query(solution, gradient, index, mode, state)
            values.append(value); rows.append(derivative)
    return np.asarray(values), np.asarray(rows)


def run():
    started = time.process_time()
    raw = encode(DEFAULT)
    teacher = capture.solve(decode(raw + DELTA), .125, .02)
    targets, _ = predictions(teacher)
    contract = dict(data=DATA, targets=targets.tolist())
    fixed_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    initial = capture.solve(decode(raw), .125, .02)
    initial_values, _ = predictions(initial)
    history, accepted = [], 0
    for step in range(20):
        solution = capture.solve(decode(raw), .125, .02)
        differential = tangent.jump(solution, raw)
        predicted, jac = predictions(solution, differential["jacobian"])
        residual = predicted - targets
        loss = float(np.mean(residual ** 2))
        gradient = 2 * np.mean(residual[:, None] * jac, axis=0)
        attempts = []
        for scale in (1., .5, .25, .125):
            candidate = raw - 3 * scale * gradient
            candidate_solution = capture.solve(decode(candidate), .125, .02)
            candidate_prediction, _ = predictions(candidate_solution)
            candidate_loss = float(np.mean((candidate_prediction - targets) ** 2))
            attempts.append(dict(scale=scale, loss=candidate_loss))
            if candidate_loss <= loss:
                raw = candidate; accepted += 1
                break
        else:
            history.append(dict(step=step, loss=loss, gradient_norm=float(np.linalg.norm(gradient)), attempts=attempts, accepted=False))
            break
        history.append(dict(step=step, loss=loss, gradient_norm=float(np.linalg.norm(gradient)), attempts=attempts, accepted=True))
    final = capture.solve(decode(raw), .125, .02)
    final_values, _ = predictions(final)
    initial_loss, final_loss = float(np.mean((initial_values - targets) ** 2)), float(np.mean((final_values - targets) ** 2))
    changed = int(np.sum(final["actions"] != initial["actions"]))
    return dict(classification="Fixed-input value-calibration/parameter-update smoke, no neural quality or independent holdout claim",
        fixed_data_sha256=fixed_hash, data=DATA, targets=targets.tolist(), initial_predictions=initial_values.tolist(),
        final_predictions=final_values.tolist(), initial_loss=initial_loss, final_loss=final_loss,
        accepted_steps=accepted, changed_native_action_cells=changed, final_raw=raw.tolist(), history=history,
        gates=dict(actual_gradient_update=accepted > 0 and all(h["gradient_norm"] > 0 for h in history),
                   fixed_target_fit=final_loss < .95 * initial_loss, actual_boundary_update=changed > 0),
        cpu_seconds=time.process_time() - started)
