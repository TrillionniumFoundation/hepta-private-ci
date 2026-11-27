"""Five frozen impulse predictors over the real Head/Adam Reference.

Every loss map sends one post-Adam parameter velocity u at step zero to a
physical loss displacement; subsequent interventions are zero. This is a local
tangent forecast, not a measured outcome, online observer, or safety approval.
Dense full-state derivatives are charged preparation even for four-row fields.
"""

import time

import numpy as np

from cell_field_control import Reference
from cell_field_fixed_adapter import fixed_impulse_predictions
from cell_field_fixed_summary import projection_diagnostics


MODEL_NAMES = ("loss2", "q4", "history4", "structured4", "full")
FD_STEP = 2e-5


def adam_direction_observation(reference, vector, step):
    """Losses and probe-gradient dot the next unforced, bias-corrected Adam step.

    Only the frozen training context and controller probes are consulted. The
    terminal observation requires one extra PURE transition, not a deployed step.
    """
    if type(step) is not int or not 0 <= step <= reference.horizon:
        raise ValueError("reference time index required")
    x = np.asarray(vector, dtype=np.float64)
    observation, gradients = reference.observe(x)
    successor = reference.state.transition_vector(
        x, reference.state.step_count + step,
        reference.train_features, reference.train_labels)
    p = reference.state.parameter_count
    displacement = successor[:p] - x[:p]
    result = np.r_[observation[:2], np.asarray(gradients) @ displacement]
    if not np.isfinite(result).all():
        raise ValueError("nonfinite structured observation")
    return result


def adam_direction_jacobians(reference):
    """Fixed-scale Jacobians: theta central FD/half-step, analytic m/v columns."""
    ref, p = reference, reference.state.parameter_count
    rows = np.zeros_like(ref.C)
    audit = []
    protocol = ref.state.protocol
    b1, b2 = protocol["beta1"], protocol["beta2"]
    lr, eps = protocol["learning_rate"], protocol["epsilon"]
    for k, x in enumerate(ref.states):
        rows[k, :2] = ref.C[k, :2]
        _, gradients = ref.observe(x)
        gradients = np.asarray(gradients)
        next_x = ref.state.transition_vector(
            x, ref.state.step_count + k, ref.train_features, ref.train_labels)
        completed = ref.state.step_count + k + 1
        mhat = next_x[p:2*p] / (1 - b1**completed)
        rootv = np.sqrt(next_x[2*p:] / (1 - b2**completed))
        dm = -lr * b1 / (1 - b1**completed) / (rootv + eps)
        dv = np.zeros(p)
        positive = rootv > 0
        if np.any((~positive) & (mhat != 0)):
            raise ValueError("nondifferentiable Adam moment")
        dv[positive] = (lr * mhat[positive] * b2
                        / (2 * (1 - b2**completed) * rootv[positive]
                           * np.square(rootv[positive] + eps)))
        rows[k, 2:, p:2*p] = gradients * dm * ref.scales[p:2*p]
        rows[k, 2:, 2*p:] = gradients * dv * ref.scales[2*p:]
        half = np.zeros((2, p))
        for j in range(p):
            for multiplier in (1.0, 0.5):
                delta = FD_STEP * multiplier * ref.scales[j]
                plus, minus = x.copy(), x.copy()
                plus[j] += delta
                minus[j] -= delta
                derivative = (adam_direction_observation(ref, plus, k)
                              - adam_direction_observation(ref, minus, k))
                derivative /= 2 * FD_STEP * multiplier
                if multiplier == 1:
                    rows[k, 2:, j] = derivative[2:]
                else:
                    half[:, j] = derivative[2:]
        audit.append({"step": k, "scaled_theta_fd_step": FD_STEP,
                      "moment_columns": "analytic; no v perturbation",
                      "theta_half_step_relative_difference": float(
                          np.linalg.norm(rows[k, 2:, :p] - half)
                          / (1 + np.linalg.norm(half))),
                      "zero_next_variance_coordinates": int(np.count_nonzero(~positive))})
    if not np.isfinite(rows).all():
        raise ValueError("nonfinite structured observation Jacobian")
    return rows, audit


def _diagnostic(matrix):
    result = projection_diagnostics(matrix)
    return result["inverse"], {"rank": result["rank"], "cutoff": result["cutoff"],
                               "singular_values": result["singular_values"].tolist()}


def _projected_maps(A, E, C):
    h, _, p = E.shape
    states = np.zeros((h+1, C.shape[1], p))
    ranks = []
    for k in range(h):
        inverse, detail = _diagnostic(C[k])
        ranks.append({"step": k, **detail})
        F = C[k+1] @ A[k] @ inverse
        states[k+1] = F @ states[k]
        if k == 0:
            states[k+1] += C[k+1] @ E[k]
    _, detail = _diagnostic(C[-1])
    ranks.append({"step": h, **detail})
    return states[:, :2], ranks


def _history_maps(A, E, C):
    """Causal two-time reconstruction with known previous-action subtraction.

    Reconstruct z_(k-1) from [y_k-C_k E_(k-1) u_(k-1), y_(k-1)]
    through O_k=[C_k A_(k-1); C_(k-1)], then transport with A_(k-1)
    and re-add the known previous action. Unlike an independent lifted-state
    pseudoinverse, this uses the transition relation between successive states.
    No future observation is used. At k=0 the displacement is known to be zero.
    """
    h, _, p = E.shape
    loss_maps = np.zeros((h+1, 2, p))
    loss_maps[1] = C[1] @ E[0]
    diagnostics = []
    for k in range(1, h):
        observation = np.vstack((C[k] @ A[k-1], C[k-1]))
        inverse, detail = _diagnostic(observation)
        known_action = E[k-1] if k == 1 else np.zeros_like(E[k-1])
        delay = np.vstack((loss_maps[k] - C[k] @ known_action, loss_maps[k-1]))
        previous_estimate = inverse @ delay
        current_estimate = A[k-1] @ previous_estimate + known_action
        loss_maps[k+1] = C[k+1] @ A[k] @ current_estimate
        diagnostics.append({"step": k, **detail})
    return loss_maps, diagnostics


def build_prediction_models(reference, names=MODEL_NAMES):
    """Return loss2/q4/history4/structured4/full maps of shape (H+1, 2, p).

    Prediction: ``np.einsum('kij,j->ki', model['loss_maps'], u)``. The
    caller freezes/charges the same impulse u for all models. Metadata contains
    JSON-compatible diagnostics and measured adapter cost, excluding the common
    dense Reference construction and its storage. No inputs are mutated.
    """
    if (not isinstance(names, (tuple, list)) or not names
            or tuple(names) != tuple(name for name in MODEL_NAMES if name in names)):
        raise ValueError("nonempty canonical ordered subset of registered model names required")
    if not isinstance(reference, Reference):
        raise ValueError("actual Head/Adam Reference required")
    # Reuse the exact inherited coordinate, anchor and post-Adam-map validation.
    fixed_impulse_predictions(reference, "zero", mode="full")
    ref, p, h = reference, reference.state.parameter_count, reference.horizon
    _, E = ref.action_matrix("all")
    result = {}
    for name in names:
        began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
        width = 2 if name == "loss2" else 3*p if name == "full" else 4
        metadata = {
            "schema": "hepta.cell-field-five-predictors.v4", "mode": name,
            "prediction": "one dt*u post-Adam theta impulse; zero suffix",
            "field_dimension": width, "full_optimizer_dimension": 3*p,
            "horizon": h, "previous_action_memory_dimension": p if name == "history4" else 0,
            "previous_action_memory_bytes": 8*p if name == "history4" else 0,
            "known_time_index": "original Adam step_count + reference step",
            "cost_scope": "adapter only; dense Reference preparation charged separately",
            "scope": "fixed reference tangent forecast; nonlinear and future outcomes separate",
        }
        if name == "full":
            state_maps = np.zeros((h+1, 3*p, p))
            for k in range(h):
                state_maps[k+1] = ref.A[k] @ state_maps[k]
                if k == 0:
                    state_maps[k+1] += E[k]
            maps = np.einsum("kij,kjl->kil", ref.C[:, :2], state_maps)
            metadata["observation"] = "complete scaled theta,m,v; deterministic clock"
        elif name == "history4":
            maps, ranks = _history_maps(ref.A, E, ref.C[:, :2])
            metadata.update(
                observation="current two losses and previous two losses",
                reconstruction="transition-consistent previous-state least squares, known-action correction",
                initialization="zero full-state displacement at frozen reference anchor",
                projection_diagnostics=ranks,
                coefficient_dependency="dense A and loss Jacobians, not a learned cheap observer")
        else:
            if name == "structured4":
                C, audit = adam_direction_jacobians(ref)
                metadata.update(
                    observation="two losses; two probe gradients dotted with next unforced Adam theta step",
                    derivative_audit=audit,
                    extra_terminal_pure_transition=True,
                    coefficient_dependency="full training gradients, probe gradients and dense derivatives")
            else:
                C = ref.C[:, :width]
                metadata["observation"] = ("two losses" if name == "loss2"
                                           else "two losses and two probe-gradient dot raw-momentum summaries")
            maps, ranks = _projected_maps(ref.A, E, C)
            metadata["projection_diagnostics"] = ranks
        if maps.shape != (h+1, 2, p) or not np.isfinite(maps).all():
            raise ValueError("finite impulse loss maps required")
        metadata.update(build_wall_ns=time.perf_counter_ns()-began,
                        build_cpu_ns=time.process_time_ns()-cpu_began,
                        retained_loss_map_bytes=maps.nbytes,
                        online_field_and_action_memory_bytes=8*(width+(p if name == "history4" else 0)))
        result[name] = {"loss_maps": maps, "metadata": metadata}
    return result
