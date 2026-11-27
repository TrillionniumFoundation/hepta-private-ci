"""Causal finite-history closures for the frozen one-impulse Cell experiment.

All arms use the same complete-state calibration. History consumes predicted
observations and the known past input; it never observes future branch labels.
The calibration cost and retained input history are reported, not hidden.
"""

import time

import numpy as np

from cell_field_action_control import build_action_model

ARMS = ("loss2", "history2", "history4", "moment4", "full")


def fixed_actions(parameters, *, seed=431025, directions=8, radius=0.1):
    """One zero and eight fixed, paired antipodal Rademacher directions."""
    if parameters not in (36, 52) or directions != 8 or radius != 0.1:
        raise ValueError("registered dimension, direction count and radius required")
    rng = np.random.default_rng(seed + parameters)
    signs = rng.integers(0, 2, (directions, parameters)) * 2 - 1
    paired = np.stack((signs, -signs), axis=1).reshape(2 * directions, parameters)
    actions = np.vstack((np.zeros(parameters), radius * paired / np.sqrt(parameters)))
    if len(np.unique(actions, axis=0)) != len(actions):
        raise ValueError("fixed directions collide; preserve failure, do not resample")
    if np.any(np.abs(actions) > 1 / np.sqrt(parameters)):
        raise ValueError("registered coordinate box exceeded")
    return actions


def history_maps(reference, lag):
    """ARX observation-window reconstruction with explicit known input forcing.

At each k, reconstruct the state at the start of the retained window from
its predicted outputs after subtracting the known input response. Propagate
that reconstruction once. No branch execution value enters this function.
Lag one reduces to the original Loss2 projection. Lag H retains the entire
input window and reproduces the full linear one-impulse response.
"""
    ref = reference
    if type(lag) is not int or not 1 <= lag <= ref.horizon:
        raise ValueError("bounded positive history length required")
    _, E = ref.action_matrix("all")
    C, A = ref.C[:, :2], ref.A
    dimension, parameters = A.shape[1], E.shape[2]
    maps = np.zeros((ref.horizon + 1, 2, parameters))
    audits = []
    for k in range(ref.horizon):
        start = max(0, k - lag + 1)
        phi, forcing = np.eye(dimension), np.zeros((dimension, parameters))
        observations, residuals = [], []
        for j in range(start, k + 1):
            observations.append(C[j] @ phi)
            residuals.append(maps[j] - C[j] @ forcing)
            forcing = A[j] @ forcing + (E[j] if j == 0 else 0)
            phi = A[j] @ phi
        stacked = np.vstack(observations)
        reconstruction = np.linalg.pinv(stacked, rcond=1e-10) @ np.vstack(residuals)
        maps[k + 1] = C[k + 1] @ (phi @ reconstruction + forcing)
        singular = np.linalg.svd(stacked, compute_uv=False)
        rank = int(np.count_nonzero(singular > (singular[0] * 1e-10 if len(singular) else 0)))
        audits.append({"step": k + 1, "window_start": start,
                       "observation_rows": len(stacked), "rank": rank})
    return maps, audits


def closure_maps(reference, arm):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if arm not in ARMS:
        raise ValueError("unregistered closure arm")
    ref, audit = reference, []
    parameters = ref.state.parameter_count
    if arm in ("loss2", "full"):
        maps = build_action_model(ref, observation=arm)["loss_maps"]
        outputs = 2 if arm == "loss2" else 3 * parameters
        history_inputs, history_outputs = 0, outputs
    elif arm == "moment4":
        C = ref.C.copy()
        _, E = ref.action_matrix("all")
        response = np.zeros((ref.horizon + 1, 4, parameters))
        response[1] = C[1] @ E[0]
        for k in range(1, ref.horizon):
            response[k + 1] = C[k + 1] @ ref.A[k] @ np.linalg.pinv(C[k], rcond=1e-10) @ response[k]
        maps, outputs = response[:, :2], 4
        history_inputs, history_outputs = 0, 4
    else:
        lag = int(arm[-1])
        maps, audit = history_maps(ref, lag)
        outputs = 2 * lag
        history_inputs, history_outputs = parameters * (lag - 1), 2 * lag
    if maps.shape != (ref.horizon + 1, 2, parameters) or not np.isfinite(maps).all():
        raise ValueError("invalid finite closure response")
    return maps, {"arm": arm, "projected_dimension": outputs,
                  "retained_output_scalars": history_outputs,
                  "retained_action_scalars_upper_bound": history_inputs,
                  "common_full_state_dimension": 3 * parameters,
                  "full_state_calibration_required": True,
                  "map_bytes": int(maps.nbytes), "history_audit": audit,
                  "wall_ns": time.perf_counter_ns() - began,
                  "cpu_ns": time.process_time_ns() - cpu,
                  "scope": "one-impulse local tangent; no lightweight whole-system claim"}
