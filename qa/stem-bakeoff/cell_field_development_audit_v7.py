"""Exact nonlinear trace and controller checks for descriptive V7 development."""

import hashlib
import time

import numpy as np

from cell_field_controller_v7 import digest_json, load_snapshot, make_contract
from cell_field_state import _array_digest
from cell_learning_models import canonical, normalize_features


def nested_errors(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "error" and item:
                yield item
            else:
                yield from nested_errors(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from nested_errors(item)


def per_source_nll(state, pair):
    x, y = pair
    probabilities = state.head.predict_proba(x)
    if (probabilities.shape != (len(y), 4) or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0) or not np.allclose(probabilities.sum(axis=1), 1., atol=1e-12, rtol=0)):
        raise ValueError("finite normalized four-class predictions required")
    return -np.log(np.maximum(probabilities[np.arange(len(y)), y], np.finfo(float).tiny))


def audit_stopped_controller(controller, states, receipts, contract, record):
    """Validate a terminal stop receipt without admitting it for continuation."""
    step, p = len(receipts), states[0].parameter_count
    origin, cursor, horizon = [controller[key] for key in ("plan_origin_step", "action_cursor", "plan_horizon")]
    ledger = [{"origin_absolute_step": 0, "stopped_absolute_step": step, "status": record["status"],
        "paid_cpu_ns": record["cpu_ns"], "paid_wall_ns": record["wall_ns"],
        "execution_record_sha256": digest_json(record["steps"]), "error": record["error"]}]
    if (controller["run_status"] != "stopped" or record["status"] == "completed"
            or canonical(controller["contract"]) != canonical(contract)
            or controller["failure_ledger"] != ledger or controller["absolute_step"] != step
            or controller["full_state_sha256"] != states[-1].digest()
            or any(controller[key] != contract[key] for key in ("policy", "protocol_sha256",
                "original_warmup_state_sha256", "warmup_step_count", "registered_steps"))
            or any(type(v) is not int for v in (origin, cursor, horizon))
            or horizon not in (0, 1 if contract["policy"] == "myopic_h1" else 8)
            or (horizon == 0 and step != 0) or cursor != horizon or origin+cursor != step or origin < 0
            or controller["counters"]["committed_steps"] != step
            or controller["counters"]["controller_cpu_ns"] != record["cpu_ns"]
            or any(type(v) is not int or v < 0 for v in controller["counters"].values())
            or controller["authority"] != "DENY_ALL" or controller["production_authority"] is not False):
        raise ValueError("stopped controller lost its exact state, contract or paid-attempt ledger")
    for kind in ("intended", "resolved"):
        actions = np.asarray(controller[kind+"_actions"], dtype=np.float64).reshape(horizon, p)
        if (not np.isfinite(actions).all() or np.any(np.abs(actions) > contract["configuration"]["action_bound"]/np.sqrt(p))
                or _array_digest(actions) != controller[kind+"_plan_sha256"]):
            raise ValueError("stopped controller retained a changed physical plan")
    if (controller["plan_state_sha256"] != [s.digest() for s in states[origin:]]
            or controller["plan_receipt_sha256"] != [digest_json(r) for r in receipts[origin:]]
            or controller["plan_origin_state_sha256"] != states[origin].digest()
            or len(controller["certificate_chain"]) != controller["counters"]["plans"]):
        raise ValueError("stopped controller retained an incomplete committed-plan census")
    return controller


def audit_policy(warmup, train, current_panels, old_panels, old_anchors, policy, configuration, result,
                 *, controller_identity=None):
    """Recompute every committed Adam step, full-state digest, and old-panel loss.

    Deliberate stopped policies can pass integrity while remaining ineligible for
    selection. Actual errors, including nested repair errors, remain explicit.
    """
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    record, states = result["record"], result["states"]
    actions = np.asarray(result["actions"], dtype=np.float64)
    receipts, controllers = result["receipts"], result["controllers"]
    count, p = len(actions), warmup.parameter_count
    allowed = {"completed", "not_executed_rejected", "not_executed_tangent_infeasible", "not_executed_unresolved"}
    if (record["status"] not in allowed or record["policy"] != policy
            or record["origin_absolute_step"] != 0 or record["completed_steps"] != count
            or record["newly_committed_steps"] != count or record["registered_steps"] != configuration["steps"]
            or not 0 <= count <= configuration["steps"]
            or (record["status"] == "completed" and count != configuration["steps"])
            or actions.shape != (count, p) or not np.isfinite(actions).all()
            or np.any(np.abs(actions) > configuration["action_bound"]/np.sqrt(p))
            or len(states) != count+1 or len(controllers) != count+1 or len(receipts) != count
            or record["initial_state_sha256"] != warmup.digest() or states[0].digest() != warmup.digest()):
        raise ValueError("complete policy census, physical action box, or initial checkpoint differs")
    anchors = np.asarray(old_anchors, dtype=np.float64)
    actual_anchors = np.asarray([warmup.head.loss_gradients(normalize_features(x), y, 0.)[0] for x, y in old_panels])
    if not np.array_equal(anchors, actual_anchors):
        raise ValueError("original warmup panel thresholds changed")
    contract = make_contract(warmup, train, current_panels, old_panels, anchors, policy, configuration,
        **(controller_identity or {}))
    current, chain, maximum = warmup.clone(), {"count": 0, "sha256": digest_json([])}, None
    controller_hashes, state_hashes = [], []
    for step, (state, controller) in enumerate(zip(states, controllers, strict=True)):
        if step:
            receipt = current.advance(*train, intervention=configuration["dt"]*actions[step-1])
            if receipt != receipts[step-1] or current.digest() != state.digest():
                raise ValueError("committed action/receipt/full Adam state failed exact replay")
            chain = {"count": step, "sha256": digest_json([chain["sha256"], digest_json(receipt)])}
            losses = np.asarray([current.head.loss_gradients(normalize_features(x), y, 0.)[0] for x, y in old_panels])
            if not np.isfinite(losses).all() or np.any(losses > anchors):
                raise ValueError("committed state violated a frozen empirical old-panel threshold")
            excess = float(np.max(losses-anchors))
            maximum = excess if maximum is None else max(maximum, excess)
        content = canonical(controller)
        digest = hashlib.sha256(content).hexdigest()
        if controller.get("run_status") == "stopped":
            if step != count:
                raise ValueError("a stopped controller cannot have committed successors")
            restored = audit_stopped_controller(controller, states, receipts, contract, record)
        else:
            restored = load_snapshot(content, state, contract, expected_sha256=digest)
        if restored["absolute_step"] != step or restored["receipt_chain"] != chain:
            raise ValueError("controller absolute cursor or complete receipt chain differs")
        controller_hashes.append(digest)
        state_hashes.append(state.digest())
    penalty = float(.5*configuration["dt"]*configuration["effort_price"]*np.square(actions).sum())
    if (current.digest() != result["state"].digest() or current.digest() != record["terminal_state_sha256"]
            or penalty != record["parameter_action_penalty"]):
        raise ValueError("terminal complete checkpoint or physical action cost differs")
    errors = list(nested_errors(record))
    return {"schema": "hepta.cell-field-development-trace-audit.v7", "passed": not errors,
        "actual_errors": errors, "committed_steps": count, "exact_replayed_steps": count,
        "maximum_empirical_old_panel_excess": maximum, "parameter_action_penalty": penalty,
        "state_sha256": state_hashes, "controller_sha256": controller_hashes,
        "terminal_controller_counters": controllers[-1]["counters"],
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began,
        "independent_online_certificate": False, "scientific_acceptance": False}


def replay_actions(warmup, train, actions, dt, receipts, expected_digests):
    """Recover selected physical checkpoints without rerunning any optimizer plan."""
    states, current = [warmup.clone()], warmup.clone()
    if expected_digests[0] != warmup.digest() or len(expected_digests) != len(actions)+1:
        raise ValueError("selected initial checkpoint commitment differs")
    for step, action in enumerate(actions):
        if (current.advance(*train, intervention=dt*action) != receipts[step]
                or current.digest() != expected_digests[step+1]):
            raise ValueError("selected compact action trace does not restore exact full state")
        states.append(current.clone())
    return states


def full_field_parity(field_actions, field_states, full_result, tolerance=1e-9):
    actions = np.asarray(full_result["actions"])
    if actions.shape != np.asarray(field_actions).shape or len(field_states) != len(full_result["states"]):
        return {"passed": False, "reason": "different committed trace lengths", "absolute_tolerance": tolerance}
    action_error = float(np.max(np.abs(actions-field_actions))) if actions.size else 0.
    state_error = float(max(np.max(np.abs(a.vector()-b.vector()))
        for a, b in zip(field_states, full_result["states"], strict=True)))
    return {"passed": full_result["record"]["status"] == "completed" and action_error <= tolerance and state_error <= tolerance,
        "maximum_action_absolute_error": action_error, "maximum_full_state_absolute_error": state_error,
        "absolute_tolerance": tolerance, "scope": "same selected configuration; no new policy selection"}
