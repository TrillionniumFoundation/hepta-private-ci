"""Common risk-plus-effort box proposal; actual old safety is a separate filter.

The unique convex quadratic minimizer uses each declared terminal response map.
There are no predicted old hard constraints, actual-risk backtracking trials,
Full-risk fallbacks, or hidden changes to the original action box.
"""

import hashlib
import time

import numpy as np

from cell_field_observable_v7 import from_response
from cell_field_qp_v7 import objective_weights
from cell_field_response_v7 import build_response, loss2_terminal_maps


def make_proposal(state, train, current_panels, old_panels, old_anchors, *, method,
                  horizon, dt=.02, effort_price=.03, action_bound=4., old_weight=0.,
                  current_dispersion=0.):
    anchors = np.asarray(old_anchors, dtype=np.float64)
    if (method not in ("full", "loss2", "future_field") or len(current_panels) != 4
            or len(old_panels) != 4 or anchors.shape != (4,) or not np.isfinite(anchors).all()
            or not np.isfinite([dt, effort_price, action_bound]).all()
            or not 0 < effort_price <= 1e6 or not 0 < action_bound <= 1e6):
        raise ValueError("declared response, eight panels, finite positive effort and action box required")
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    response = build_response(state, train, [*current_panels, *old_panels], horizon=horizon, dt=dt)
    field = None
    if method == "full":
        maps = response.terminal_sequence_maps()
    elif method == "loss2":
        maps = loss2_terminal_maps(response)
    else:
        field = from_response(response)
        maps = field.terminal_maps()
    risk, weights = objective_weights(response.observations[-1], old_weight, current_dispersion)
    linear = np.einsum("hqp,q->hp", maps, weights)
    bound = action_bound/np.sqrt(state.parameter_count)
    actions = np.clip(-linear/(dt*effort_price), -bound, bound)
    if not np.isfinite(actions).all():
        raise ValueError("nonfinite risk-plus-effort proposal")
    stationarity = float(np.max(np.abs(actions-np.clip(
        actions-(linear+dt*effort_price*actions), -bound, bound))))
    record = {"schema": "hepta.cell-field-risk-proposal.v8", "status": "qualified",
        "method": method, "horizon": horizon, "dt": dt, "effort_price": effort_price,
        "action_bound": action_bound, "old_weight": old_weight,
        "current_dispersion": current_dispersion, "relinearizations": 0,
        "baseline_panel_losses": response.observations[-1].tolist(),
        "objective_weights": weights.tolist(), "baseline_terminal_risk": risk,
        "predicted_linear_risk_change": float(np.sum(linear*actions)),
        "effort": float(.5*dt*effort_price*np.square(actions).sum()),
        "projected_stationarity_linf": stationarity,
        "actions_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
        "reference_optimizer_steps": horizon, "response_cpu_ns": response.cpu_ns,
        "actual_risk_backtracking_rollouts": 0, "predicted_old_constraints": False,
        "original_old_anchors": anchors.tolist(), "panel_sha256": list(response.panel_digests),
        "complete_optimizer_dimension": 3*state.parameter_count,
        "scope": "risk forecast only; shared actual-old filter is full-state and separately charged",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
    if field is not None:
        record["field_dimensions"] = [len(value) for value in field.observations]
    return {"actions": actions, "record": record, "maps": maps,
        "reference_states": response.states, "reference_observations": response.observations,
        "nominal_reference_actions": response.nominal_actions}
