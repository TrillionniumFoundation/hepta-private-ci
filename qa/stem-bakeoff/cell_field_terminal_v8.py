"""One-action terminal proposals with a fixed zero-control Adam continuation.

The three remaining-horizon models share the absolute terminal target32. H1 is
the explicitly myopic comparator. Full and terminal-field use only terminal
panel derivatives; Loss2 pays for intermediate aggregate-loss observations.
All coefficients come from the complete state. The eight-coordinate terminal
field is a local observable, not an autonomous observer or a safety certificate.
"""

import time
import numpy as np

from cell_field_response_v5 import AdamDerivative, HeadDerivative
from cell_field_state import dataset_digest


METHODS = ("myopic_h1", "loss2_remaining", "full_adjoint_remaining", "terminal_field8_remaining")
WEIGHTS = np.r_[np.full(4, .25), np.full(4, .0625)]


def make_terminal_proposal(state, train, current_panels, old_panels, *, method, remaining,
                           dt=.02, effort_price=.03, action_bound=4.):
    """Solve the separable box quadratic for its first action, charging all work.

    Freeing additional future actions in this linear-risk/diagonal-effort QP
    leaves the first optimum unchanged. Only that first action will be passed
    to the common nonlinear safety portfolio; all future nominal controls are0.
    """
    if (method not in METHODS or type(remaining) is not int or not 1 <= remaining <= 32
            or len(current_panels) != 4 or len(old_panels) != 4
            or state.protocol["sampler"] != "full_batch" or state.step_count < 1
            or state.parameter_count not in (36, 52)
            or state.contexts.get(state.active_context) != dataset_digest(*train)
            or (dt, effort_price, action_bound) != (.02, .03, 4.)):
        raise ValueError("fixed V8 price/box, warmed full-batch context and eight planning panels required")
    cpu, wall, before = time.process_time_ns(), time.perf_counter_ns(), state.digest()
    horizon = 1 if method == "myopic_h1" else remaining
    panels = [*current_panels, *old_panels]
    p = state.parameter_count
    identities = [dataset_digest(*pair) for pair in panels]
    vectors, transitions, observations, gradients = [state.vector()], [], {}, {}
    derivative_count, panel_count = 0, 0
    for k in range(horizon):
        # The first action enters after Adam. Its response does not use A0.
        # Field's arbitrary-initial-perturbation coordinate additionally needs A0.
        if k or method == "terminal_field8_remaining":
            derivative = AdamDerivative(state, vectors[-1], state.step_count+k, train)
            following = derivative.next.copy()
            derivative_count += 1
        else:
            derivative = None
            following = state.transition_vector(vectors[-1], state.step_count+k, *train)
        transitions.append(derivative)
        vectors.append(following)
        if k+1 == horizon or method == "loss2_remaining":
            head = state.head_from_vector(following)
            rows = [HeadDerivative(head, *pair) for pair in panels]
            panel_count += len(rows)
            observations[k+1] = np.asarray([row.loss for row in rows])
            gradients[k+1] = np.vstack([row.gradient for row in rows])
    terminal = observations[horizon]
    terminal_gradient = gradients[horizon]
    initial_observation = None
    if method == "loss2_remaining" and horizon > 1:
        retained = dt*gradients[1].reshape(2, 4, p).mean(axis=1)
        for k in range(1, horizon):
            aggregate = np.hstack((gradients[k].reshape(2, 4, p).mean(axis=1), np.zeros((2, 2*p))))
            lift = np.linalg.pinv(aggregate, rcond=1e-10)
            observed = gradients[k+1] @ transitions[k].jvp(lift)[:p]
            first_map = observed @ retained
            retained = first_map.reshape(2, 4, p).mean(axis=1)
    else:
        adjoint = np.vstack((terminal_gradient.T, np.zeros((2*p, 8))))
        for k in range(horizon-1, 0, -1):
            adjoint = transitions[k].vjp(adjoint)
        first_map = dt*adjoint[:p].T
        if method == "terminal_field8_remaining":
            initial_observation = transitions[0].vjp(adjoint).T
    linear = WEIGHTS @ first_map
    curvature, bound = dt*effort_price, action_bound/np.sqrt(p)
    action = np.clip(-linear/curvature, -bound, bound)
    predicted = terminal+first_map @ action
    effort = float(.5*curvature*np.square(action).sum())
    stationarity = float(np.max(np.abs(action-np.clip(action-(linear+curvature*action), -bound, bound))))
    if (state.digest() != before or not all(np.isfinite(a).all() for a in (first_map, action, predicted))
            or (initial_observation is not None and not np.isfinite(initial_observation).all())):
        raise RuntimeError("nonfinite terminal response or changed complete origin")
    record = {"schema": "hepta.remaining-terminal-proposal.v8", "status": "qualified", "method": method,
        "remaining_physical_steps": remaining, "proposal_horizon": horizon,
        "endpoint_scope": "one-step risk" if method == "myopic_h1" else "fixed absolute terminal32",
        "nominal_continuation": "zero intervention after the first free action",
        "free_actions": 1, "future_free_prefix_equivalence": "separable linear-risk diagonal-effort box QP only",
        "dt": dt, "effort_price": effort_price, "action_bound": action_bound,
        "current_mean_weight": 1., "old_mean_weight": .25, "current_dispersion": 0.,
        "reference_optimizer_updates": horizon, "analytic_adam_derivatives": derivative_count,
        "training_head_gradient_evaluations_from_fixed_calls": horizon+derivative_count,
        "planning_panel_head_evaluations": panel_count,
        "first_action_adjoint_or_jvp_steps": horizon-1,
        "initial_field_extra_adjoint_steps": int(method == "terminal_field8_remaining"),
        "baseline_terminal_panels": terminal.tolist(), "predicted_terminal_panels": predicted.tolist(),
        "predicted_risk_change": float(linear @ action), "proposed_action_effort": effort,
        "predicted_priced_change": float(linear @ action+effort),
        "projected_stationarity_linf": stationarity,
        "panel_sha256": identities, "initial_state_sha256": before,
        "continuous_optimizer_dimension": 3*p, "terminal_field_dimension": 8 if initial_observation is not None else None,
        "retained_loss2_dimension": 2 if method == "loss2_remaining" else None,
        "complete_state_supplies_coefficients": True, "autonomous_observer": False,
        "path_retention_predicted_or_certified": False, "future_adaptive_policy_differentiated": False,
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
    return {"action": action, "first_action_map": first_map, "initial_field_observation": initial_observation,
        "reference_terminal_state": vectors[-1], "reference_terminal_panels": terminal,
        "reference_states": np.asarray(vectors), "record": record}
