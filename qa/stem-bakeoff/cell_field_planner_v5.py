"""Matched terminal-risk planners with complete action and retention accounting.

The two output response rows parameterize a bounded strictly convex action
problem. A scalar dual search supplies an independently checked KKT certificate.
The safety module separately checks the actual nonlinear future path.
"""

import time

import numpy as np

from cell_field_response_v5 import build_response


def solve_terminal(maps, baseline, old_anchor, *, dt=.02, effort_price=.1,
                   action_bound=1., old_weight=0., hard_retention=True):
    """Minimize current+weighted-old terminal tangent NLL plus parameter effort."""
    rows, initial = np.asarray(maps, dtype=np.float64), np.asarray(baseline, dtype=np.float64)
    if (rows.ndim != 3 or rows.shape[1] != 2 or initial.shape != (2,)
            or not np.isfinite(rows).all() or not np.isfinite(initial).all()
            or not np.isfinite([old_anchor, dt, effort_price, action_bound, old_weight]).all()
            or min(dt, effort_price, action_bound) <= 0 or old_weight < 0
            or type(hard_retention) is not bool):
        raise ValueError("finite two-loss action response and declared cost required")
    horizon, _, p = rows.shape
    c = (rows[:, 0] + old_weight*rows[:, 1]).ravel()
    n = rows[:, 1].ravel()
    q = float(old_anchor - initial[1])
    regularization, bound = dt*effort_price, action_bound/np.sqrt(p)
    if (not np.isfinite([regularization, bound, q]).all() or regularization <= 0 or bound <= 0
            or not np.isfinite(c).all() or not np.isfinite(n).all()):
        raise ValueError("derived objective and action bounds must remain finite and positive")
    record = {"schema": "hepta.cell-field-terminal-plan.v5", "status": "unresolved",
        "horizon": horizon, "control_dimension": horizon*p, "response_coordinates": 2,
        "effort_price": effort_price, "old_weight": old_weight, "action_bound": action_bound,
        "hard_terminal_retention": hard_retention, "original_old_anchor": old_anchor,
        "scope": "strictly convex tangent terminal objective; nonlinear verifier separate"}

    def optimum(multiplier):
        return np.clip(-(c+multiplier*n)/regularization, -bound, bound)

    multiplier, u = 0., optimum(0.)
    minimum = -bound*float(np.abs(n).sum())
    if not np.isfinite(minimum) or not np.isfinite(u).all():
        raise ValueError("derived candidate and feasibility bound must remain finite")
    if hard_retention and minimum > q:
        record.update(status="tangent_infeasible", minimum_possible_old_displacement=minimum,
                      required_old_displacement=q, infeasibility_margin=minimum-q)
        return {"actions": None, "record": record}
    if hard_retention and n @ u > q:
        low, high = 0., 1.
        for _ in range(64):
            if n @ optimum(high) <= q:
                break
            high *= 2
        else:
            record["reason"] = "bounded dual bracket exhausted"
            return {"actions": None, "record": record}
        for _ in range(80):
            middle = (low+high)/2
            if n @ optimum(middle) > q:
                low = middle
            else:
                high = middle
        multiplier, u = high, optimum(high)
    gradient = c + regularization*u + multiplier*n
    stationarity = float(np.linalg.norm(u - np.clip(u-gradient, -bound, bound), np.inf))
    violation = max(0., float(n@u-q)) if hard_retention else 0.
    gap = float(multiplier*(q-n@u)) if hard_retention else 0.
    objective = float(c@u + .5*regularization*(u@u))
    predicted = initial+np.einsum("kip,kp->i", rows, u.reshape(horizon, p))
    if (not np.isfinite(u).all() or not np.isfinite(predicted).all()
            or not np.isfinite([stationarity, violation, gap, objective, multiplier]).all()):
        record["reason"] = "nonfinite derived KKT certificate"
        return {"actions": None, "record": record}
    if stationarity > 1e-10 or violation > 1e-12 or not -1e-12 <= gap <= 1e-9:
        record.update(reason="KKT certificate failed", stationarity=stationarity, violation=violation, gap=gap)
        return {"actions": None, "record": record}
    actions = u.reshape(horizon, p)
    record.update(status="qualified", stationarity=stationarity, violation=violation, gap=max(0., gap),
                  dual_multiplier=float(multiplier), tangent_objective=objective,
                  predicted_terminal_losses=predicted.tolist(),
                  parameter_penalty=float(.5*regularization*(u@u)),
                  response_storage_bytes=rows.nbytes)
    return {"actions": actions, "record": record}


def loss2_terminal_maps(response):
    """Same two-loss projection family; complete coefficients and costs retained."""
    h, p = len(response.transitions), response.gradients.shape[-1]
    maps, backward = np.zeros((h, 2, p)), np.eye(2)
    for k in range(h-1, -1, -1):
        maps[k] = backward @ (response.dt*response.gradients[k+1])
        observation = np.hstack((response.gradients[k], np.zeros((2, 2*p))))
        reconstruction = np.linalg.pinv(observation, rcond=1e-10)
        advanced = response.transitions[k].jvp(reconstruction)
        transition = response.gradients[k+1] @ advanced[:p]
        backward = backward @ transition
    return maps


def make_plan(state, split, old_anchor, *, method, horizon, dt=.02,
              effort_price=.1, action_bound=1., old_weight=0., hard_retention=True):
    if method not in ("adjoint", "loss2"):
        raise ValueError("registered response family required")
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    response = build_response(state, split["current_train"],
        (split["current_probe"], split["old_probe"]), horizon=horizon, dt=dt)
    maps = response.terminal_sequence_maps() if method == "adjoint" else loss2_terminal_maps(response)
    planned = solve_terminal(maps, response.observations[-1], old_anchor, dt=dt,
        effort_price=effort_price, action_bound=action_bound, old_weight=old_weight,
        hard_retention=hard_retention)
    planned.update(maps=maps, reference_states=response.states,
                   reference_observations=response.observations,
                   cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall)
    planned["record"].update(method=method, reference_cpu_ns=response.cpu_ns,
                              complete_optimizer_dimension=3*state.parameter_count)
    return planned
