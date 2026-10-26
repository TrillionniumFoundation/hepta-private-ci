"""Shared terminal-J32 diagnostic with a fixed zero-action continuation.

This is an unguarded research diagnostic, never a safe execution candidate.
The one/eight-action controls share a32-step endpoint; the separately named
myopic proposal still optimizes its own one-step risk and is scored at32.
The264->8 field can exceed the108/156-dimensional complete Adam state.
"""

import time

import numpy as np

from cell_field_observable_v7 import FuturePanelField
from cell_field_response_v5 import AdamDerivative, HeadDerivative
from cell_field_response_v7 import PanelResponse, loss2_terminal_maps
from cell_field_state import dataset_digest
from cell_learning_models import normalize_features


BRANCHES = ("zero32", "myopic_h1_zero_tail", "full32_one_action",
            "full32_eight_actions", "field32_eight_actions", "loss2_32_eight_actions")
WEIGHTS = np.r_[np.full(4, .25), np.full(4, .0625)]


def build_long_reference(state, train, panels, *, horizon=32, dt=.02):
    """Differentiate known full-batch Adam along the explicit zero-control tail."""
    if (state.protocol["sampler"] != "full_batch" or state.step_count < 1
            or type(horizon) is not int or not 1 <= horizon <= 32
            or len(panels) != 8 or state.parameter_count not in (36, 52)
            or not np.isfinite(dt) or not 0 < dt <= 1
            or state.contexts.get(state.active_context) != dataset_digest(*train)):
        raise ValueError("warmed36/52 full-batch state, bound context, eight panels and H1..H32 required")
    began, wall, before = time.process_time_ns(), time.perf_counter_ns(), state.digest()
    vectors, observations, gradients, transitions = [state.vector()], [], [], []
    for k in range(horizon+1):
        head = state.head_from_vector(vectors[-1])
        rows = [HeadDerivative(head, *panel) for panel in panels]
        observations.append([row.loss for row in rows])
        gradients.append(np.vstack([row.gradient for row in rows]))
        if k < horizon:
            derivative = AdamDerivative(state, vectors[-1], state.step_count+k, train)
            transitions.append(derivative)
            vectors.append(derivative.next.copy())
    result = PanelResponse(np.asarray(vectors), np.asarray(observations), np.asarray(gradients),
        transitions, np.zeros((horizon, state.parameter_count)),
        tuple(dataset_digest(*panel) for panel in panels), dt,
        time.process_time_ns()-began, time.perf_counter_ns()-wall)
    if state.digest() != before or not all(np.isfinite(x).all() for x in
            (result.states, result.observations, result.gradients)):
        raise RuntimeError("reference mutated its complete origin or produced nonfinite values")
    return result


def long_future_field(reference):
    """Exact finite-window local outputs; full-state coefficients remain charged."""
    began, wall = time.process_time_ns(), time.perf_counter_ns()
    h, q, p = len(reference.transitions), *reference.gradients.shape[1:]
    if not 1 <= h <= 32 or q != 8:
        raise ValueError("eight-output H1..H32 reference required")
    observation, inputs = [None]*(h+1), [None]*h
    observation[h] = np.hstack((reference.gradients[h], np.zeros((q, 2*p))))
    for k in range(h-1, -1, -1):
        inputs[k] = reference.dt*observation[k+1][:, :p]
        current = np.hstack((reference.gradients[k], np.zeros((q, 2*p))))
        observation[k] = np.vstack((current, reference.transitions[k].vjp(observation[k+1].T).T))
    if not all(np.isfinite(x).all() for x in (*observation, *inputs)):
        raise ValueError("nonfinite long-window field")
    return FuturePanelField(observation, inputs,
        time.process_time_ns()-began, time.perf_counter_ns()-wall)


def prepare_proposals(reference, *, effort_price=.03, action_bound=4.):
    """Six frozen proposals. The box quadratic is solved without old constraints.

    No safety filter, old-gradient fallback, line search or nonlinear objective
    optimization is hidden here. All proposed actions retain their full identity.
    Shared coefficient preparation is timed separately; these are not fair-cost
    closed-loop controller benchmarks or admissions to a safety policy.
    """
    began, wall = time.process_time_ns(), time.perf_counter_ns()
    h, q, p = len(reference.transitions), *reference.gradients.shape[1:]
    if h != 32 or q != 8 or not np.isfinite([effort_price, action_bound]).all() or min(effort_price, action_bound) <= 0:
        raise ValueError("fixed H32, positive finite effort price and common box required")
    maps = {"full": reference.terminal_sequence_maps()}
    field = long_future_field(reference)
    maps["field"], maps["loss2"] = field.terminal_maps(), loss2_terminal_maps(reference)
    bound, curvature = action_bound/np.sqrt(p), reference.dt*effort_price
    plans = {}
    for name in BRANCHES:
        count = 0 if name == "zero32" else 1 if name in BRANCHES[1:3] else 8
        model = "loss2" if name.startswith("loss2") else "field" if name.startswith("field") else "full"
        endpoint = 1 if name == "myopic_h1_zero_tail" else 32
        local = (reference.dt*reference.gradients[1])[None] if endpoint == 1 else maps[model][:count]
        actions = np.zeros((32, p))
        linear = np.einsum("q,kqp->kp", WEIGHTS, local)
        if count:
            actions[:count] = np.clip(-linear/curvature, -bound, bound)
        penalty = float(.5*curvature*np.square(actions).sum())
        full_forecast = reference.observations[-1]+np.einsum("kqp,kp->q", maps["full"], actions)
        projected = actions[:count]-np.clip(actions[:count]-(linear+curvature*actions[:count]), -bound, bound)
        record = {"branch": name, "proposal_endpoint": endpoint, "evaluation_endpoint": 32,
            "free_action_steps": count, "tail": "exactly zero after the free prefix",
            "action_bound_coordinate": bound, "parameter_penalty": penalty,
            "box_quadratic_stationarity": float(np.max(np.abs(projected))) if count else 0.,
            "tangent_proposal_objective": float(WEIGHTS@reference.observations[endpoint]
                +np.sum(linear*actions[:count])+penalty),
            "full_tangent_common_objective": float(WEIGHTS@full_forecast+penalty),
            "scope": "local box-quadratic proposal; true J32 and old violations measured separately",
            "historical_v7_hard_constraints_or_repair": False, "scientific_acceptance": False}
        plans[name] = {"actions": actions, "record": record}
    if not all(np.isfinite(x).all() for x in maps.values()):
        raise ValueError("nonfinite action-response maps")
    coefficient_bytes = sum(x.nbytes for x in (*field.observations, *field.inputs))
    return {"plans": plans, "maps": maps, "field": field,
        "record": {"cpu_ns": time.process_time_ns()-began, "wall_ns": time.perf_counter_ns()-wall,
            "reference_cpu_ns": reference.cpu_ns, "reference_wall_ns": reference.wall_ns,
            "field_dimensions": [len(x) for x in field.observations],
            "complete_optimizer_dimension": 3*p, "field_coefficient_bytes": coefficient_bytes,
            "full_field_map_max_abs": float(np.max(np.abs(maps["full"]-maps["field"]))),
            "cost_scope": "shared reference/maps preparation; branch rollout costs are separate",
            "compactness_claimed": False}}


def rollout32(state, train, panels, actions, old_anchors, *, dt=.02,
              effort_price=.03, action_bound=4.):
    """Execute all32 steps on a clone even when the original old bound is violated."""
    actions, anchors = np.asarray(actions, dtype=np.float64), np.asarray(old_anchors, dtype=np.float64)
    if (actions.shape != (32, state.parameter_count) or anchors.shape != (4,) or len(panels) != 8
            or not np.isfinite(actions).all() or not np.isfinite(anchors).all()
            or not np.isfinite([dt, effort_price, action_bound]).all()
            or not 0 < dt <= 1 or min(effort_price, action_bound) <= 0
            or np.any(np.abs(actions) > action_bound/np.sqrt(state.parameter_count))
            or state.protocol["sampler"] != "full_batch"
            or state.contexts.get(state.active_context) != dataset_digest(*train)):
        raise ValueError("finite same-box32-step diagnostic, original anchors and selected training context required")
    began, wall, before = time.process_time_ns(), time.perf_counter_ns(), state.digest()
    actual, states, losses, receipts = state.clone(), [state.clone()], [], []
    prepared = [(normalize_features(x), y) for x, y in panels]
    for k in range(33):
        losses.append([actual.head.loss_gradients(x, y, 0.)[0] for x, y in prepared])
        if k < 32:
            receipts.append(actual.advance(*train, intervention=dt*actions[k]))
            states.append(actual.clone())
    losses = np.asarray(losses)
    if state.digest() != before or not np.isfinite(losses).all():
        raise RuntimeError("diagnostic mutated its origin or produced nonfinite losses")
    excess = losses[1:, 4:]-anchors
    penalty = float(.5*dt*effort_price*np.square(actions).sum())
    record = {"status": "completed_unguarded_diagnostic", "completed_steps": 32,
        "initial_state_sha256": before, "terminal_state_sha256": actual.digest(),
        "state_sha256": [x.digest() for x in states], "receipts": receipts,
        "current_terminal_risk": float(losses[-1, :4].mean()),
        "old_terminal_risk": float(losses[-1, 4:].mean()), "parameter_penalty": penalty,
        "actual_common_objective": float(WEIGHTS@losses[-1]+penalty),
        "old_anchors": anchors.tolist(), "initial_old_excess": (losses[0, 4:]-anchors).tolist(),
        "old_violating_steps": int(np.count_nonzero(np.any(excess > 0., axis=1))),
        "maximum_old_excess": float(np.max(excess)), "safe_execution_candidate": False,
        "safety_filter_used": False, "scientific_acceptance": False, "production_authority": False,
        "cpu_ns": time.process_time_ns()-began, "wall_ns": time.perf_counter_ns()-wall}
    return {"record": record, "states": states, "losses": losses, "actions": actions.copy()}
