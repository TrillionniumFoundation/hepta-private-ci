"""Matched panel objectives and bounded actual-trajectory relinearization."""

import time

import numpy as np

from cell_field_observable_v7 import from_response
from cell_field_qp_v7 import objective_weights, solve_terminal
from cell_field_response_v7 import build_response, loss2_terminal_maps
from cell_learning_models import normalize_features


def actual_terminal(state, train, panels, actions, dt):
    vector = state.vector()
    for k, action in enumerate(actions):
        vector = state.transition_vector(vector, state.step_count+k, *train)
        vector[:state.parameter_count] += dt*action
    head = state.head_from_vector(vector)
    return np.asarray([head.loss_gradients(normalize_features(x), y, 0.)[0] for x, y in panels])


def make_plan(state, train, panels, old_anchors, *, method, horizon, dt=.02,
              effort_price=.03, action_bound=4., old_weight=0., current_dispersion=0.,
              relinearizations=0):
    if (method not in ("full", "loss2", "future_field") or type(relinearizations) is not int
            or relinearizations not in (0, 2) or type(horizon) is not int or not 1 <= horizon <= 8):
        raise ValueError("registered response and bounded relinearization count required")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    nominal = np.zeros((horizon, state.parameter_count))
    record = {"schema": "hepta.cell-field-panel-plan.v7", "method": method,
        "horizon": horizon, "status": "unresolved", "rounds": [],
        "relinearizations": relinearizations, "terminal_merit_violation_price": 10.,
        "actual_backtracking": [1., .5, .25], "actual_acceptance_decrease": 1e-12,
        "complete_optimizer_dimension": 3*state.parameter_count,
        "requires_nonlinear_path_verification": True,
        "scope": "inner KKT certifies its full QP proposal; selected actions require separate actual path repair"}
    maps, response, current_merit = None, None, None

    def merit(losses, actions):
        risk, _ = objective_weights(losses, old_weight, current_dispersion)
        effort = float(.5*dt*effort_price*np.square(actions).sum())
        violation = float(np.maximum(losses[4:]-old_anchors, 0.).sum())
        return risk+effort+10.*violation, {"risk": risk, "effort": effort,
            "positive_old_panel_excess": violation, "panel_losses": losses.tolist()}

    for iteration in range(relinearizations+1):
        response = build_response(state, train, panels, horizon=horizon, dt=dt,
            nominal_actions=nominal)
        field = None
        if method == "full":
            maps = response.terminal_sequence_maps()
        elif method == "loss2":
            maps = loss2_terminal_maps(response)
        else:
            field = from_response(response)
            maps = field.terminal_maps()
        planned = solve_terminal(maps, response.observations[-1], old_anchors, nominal,
            dt=dt, effort_price=effort_price, action_bound=action_bound,
            old_weight=old_weight, current_dispersion=current_dispersion)
        row = {"iteration": iteration, "response_cpu_ns": response.cpu_ns,
            "qp": planned["record"], "accepted": False, "trials": []}
        if field is not None:
            row["field_dimensions"] = [len(value) for value in field.observations]
        record["rounds"].append(row)
        if planned["record"]["status"] != "qualified":
            if iteration == 0:
                record["status"] = planned["record"]["status"]
                nominal = None
            else:
                row["reason"] = "relinearization unavailable; prior qualified plan retained"
            break
        proposal = planned["actions"]
        bound = action_bound/np.sqrt(state.parameter_count)
        if np.any(np.abs(nominal) > bound) or np.any(np.abs(proposal) > bound):
            raise ValueError("both interpolation endpoints must already satisfy the original box")
        fractions = [1.] if iteration == 0 else [1., .5, .25]
        for fraction in fractions:
            # Subtraction followed by addition can move even fraction=1 one
            # ulp past its already bounded endpoint. Keep that endpoint exact;
            # partial convex combinations project only onto the identical box.
            raw_trial = proposal.copy() if fraction == 1. else (1.-fraction)*nominal+fraction*proposal
            trial = np.clip(raw_trial, -bound, bound)
            projection = float(np.max(np.abs(trial-raw_trial)))
            losses = actual_terminal(state, train, panels, trial, dt)
            value, parts = merit(losses, trial)
            row["trials"].append({"fraction": fraction, "merit": value,
                "same_box_roundoff_projection_linf": projection, **parts})
            if current_merit is None or value < current_merit-1e-12:
                nominal, current_merit = trial, value
                row.update(accepted=True, accepted_fraction=fraction)
                record.update(selected_proposal_iteration=iteration, selected_fraction=fraction,
                    selected_actions_equal_inner_solution=bool(fraction == 1.))
                record["status"] = "qualified"
                break
        if not row["accepted"]:
            row["reason"] = "bounded actual merit trials supplied no improvement"
            break
    record.update(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began,
        terminal_actual_merit=current_merit,
        actual_rollout_evaluations=sum(len(row["trials"]) for row in record["rounds"]),
        actual_rollout_optimizer_steps=horizon*sum(len(row["trials"]) for row in record["rounds"]))
    return {"record": record, "actions": nominal, "maps": maps,
        "reference_states": None if response is None else response.states,
        "reference_observations": None if response is None else response.observations,
        "nominal_reference_actions": None if response is None else response.nominal_actions}
