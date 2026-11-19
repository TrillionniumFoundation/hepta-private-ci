"""Frozen controller checkpoints, including verified pending actions and cursors.

Complete Adam state is stored separately and must match this snapshot exactly.
The expected immutable contract comes from the caller's admitted experiment,
not from an untrusted checkpoint. Native admission additionally binds the exact
canonical bytes. Inner solver iterations are not supported checkpoint points.
"""

import copy
import hashlib
import json

import numpy as np

from cell_field_state import _array_digest, dataset_digest
from cell_learning_models import canonical


SCHEMA = "hepta.cell-field-controller.v8"
POLICIES = {"myopic_h1": ("full", 1), "loss2_h8": ("loss2", 8),
    "full_h8": ("full", 8), "future_field_h8": ("future_field", 8)}
CONFIG_KEYS = {"steps", "dt", "effort_price", "action_bound", "old_weight",
    "current_dispersion", "relinearizations", "commit_stride"}


def digest_json(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def make_contract(warmup, train, current_panels, old_panels, anchors, policy, config, *,
                  controller_protocol_sha256=None, controller_source_sha256=None):
    if (policy not in POLICIES or set(config) != CONFIG_KEYS
            or type(config["steps"]) is not int or config["steps"] != 32
            or type(config["commit_stride"]) is not int or config["commit_stride"] not in (1, 2, 4, 8)
            or type(config["relinearizations"]) is not int or config["relinearizations"] != 0
            or len(current_panels) != 4 or len(old_panels) != 4
            or not 0 < config["dt"] <= 1 or not 0 < config["effort_price"] <= 100
            or not 0 < config["action_bound"] <= 1e6
            or not 0 <= config["old_weight"] <= 10 or not 0 <= config["current_dispersion"] <= .5
            or warmup.protocol["sampler"] != "full_batch"
            or warmup.contexts.get(warmup.active_context) != dataset_digest(*train)):
        raise ValueError("bounded frozen complete-state full-batch policy contract required")
    values = np.asarray(anchors, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("four finite original warmup anchors required")
    protocol = controller_protocol_sha256 or warmup.bindings["protocol_sha256"]
    for value in (protocol, controller_source_sha256):
        if value is not None and (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("controller protocol and source closure require exact SHA256 identities")
    return {"schema": "hepta.cell-field-controller-contract.v8", "policy": policy,
        "protocol_sha256": protocol, "controller_source_sha256": controller_source_sha256,
        "optimizer_origin_protocol_sha256": warmup.bindings["protocol_sha256"],
        "original_warmup_state_sha256": warmup.digest(), "warmup_step_count": warmup.step_count,
        "registered_steps": config["steps"], "parameter_count": warmup.parameter_count,
        "configuration": copy.deepcopy(config), "training_sha256": dataset_digest(*train),
        "current_panel_sha256": [dataset_digest(*panel) for panel in current_panels],
        "old_panel_sha256": [dataset_digest(*panel) for panel in old_panels],
        "original_old_anchors": values.tolist(), "independent_online_certificate": False,
        "checkpoint_boundary": "committed step inside certified prefix; forecast tail is discarded at next plan",
        "forecast_tail_safety_claimed": False, "safety_filter": "single_ray_then_joint_v8",
        "proposal_rule": "risk_effort_box_v8"}


def initial_snapshot(warmup, contract):
    p = warmup.parameter_count
    empty = np.zeros((0, p))
    return {"schema": SCHEMA, "contract": copy.deepcopy(contract),
        "policy": contract["policy"], "protocol_sha256": contract["protocol_sha256"],
        "original_warmup_state_sha256": contract["original_warmup_state_sha256"],
        "warmup_step_count": contract["warmup_step_count"], "registered_steps": contract["registered_steps"],
        "full_state_sha256": warmup.digest(), "absolute_step": 0,
        "plan_origin_step": 0, "plan_origin_state_sha256": warmup.digest(),
        "plan_horizon": 0, "action_cursor": 0, "intended_actions": [], "resolved_actions": [],
        "forecast_horizon": 0, "forecast_actions": [], "forecast_plan_sha256": _array_digest(empty),
        "intended_plan_sha256": _array_digest(empty), "resolved_plan_sha256": _array_digest(empty),
        "plan_state_sha256": [warmup.digest()], "plan_receipt_sha256": [],
        "certificate_chain": [], "receipt_chain": {"count": 0, "sha256": digest_json([])},
        "run_status": "active", "failure_ledger": [],
        "counter_scope": "installed certified plans and committed steps; failed attempts remain in paid stop ledger",
        "counters": {"plans": 0, "proposal_calls": 0, "response_optimizer_steps": 0,
            "qp_calls": 0, "actual_merit_rollout_steps": 0,
            "repair_optimizer_updates": 0, "repair_panel_evaluations": 0,
            "resume_verification_updates": 0, "committed_steps": 0, "controller_cpu_ns": 0},
        "authority": "DENY_ALL", "production_authority": False}


def install_plan(snapshot, intended, verified, plan):
    result = copy.deepcopy(snapshot)
    actions = verified["actions"]
    p, h = snapshot["contract"]["parameter_count"], len(actions)
    contract, origin = snapshot["contract"], snapshot["absolute_step"]
    remaining = contract["registered_steps"]-origin
    forecast_horizon = min(POLICIES[contract["policy"]][1], remaining)
    commit_horizon = min(1 if contract["policy"] == "myopic_h1" else contract["configuration"]["commit_stride"], remaining)
    forecast = np.asarray(plan["actions"], dtype=np.float64)
    if (not verified["record"]["certified"] or h != commit_horizon
            or forecast.shape != (forecast_horizon, p) or not np.isfinite(forecast).all()
            or np.any(np.abs(forecast) > contract["configuration"]["action_bound"]/np.sqrt(p))
            or not np.array_equal(np.asarray(intended), forecast[:h])
            or np.asarray(actions).shape != (h, p) or np.asarray(intended).shape != (h, p)
            or len(verified["states"]) != h+1 or len(verified["receipts"]) != h
            or verified["states"][0].digest() != snapshot["full_state_sha256"]
            or verified["state"].digest() != verified["states"][-1].digest()):
        raise ValueError("only a completely verified finite block may be checkpointed")
    result.update(plan_origin_step=snapshot["absolute_step"],
        plan_origin_state_sha256=snapshot["full_state_sha256"], plan_horizon=len(actions), action_cursor=0,
        forecast_horizon=forecast_horizon, forecast_actions=forecast.tolist(),
        forecast_plan_sha256=_array_digest(forecast),
        intended_actions=np.asarray(intended).tolist(), resolved_actions=actions.tolist(),
        intended_plan_sha256=_array_digest(np.asarray(intended)), resolved_plan_sha256=_array_digest(actions),
        plan_state_sha256=[s.digest() for s in verified["states"]],
        plan_receipt_sha256=[digest_json(r) for r in verified["receipts"]])
    result["certificate_chain"].append({"origin_step": result["plan_origin_step"],
        "origin_state_sha256": result["plan_origin_state_sha256"],
        "plan_sha256": digest_json(plan["record"]), "repair_sha256": digest_json(verified["record"]),
        "resolved_plan_sha256": result["resolved_plan_sha256"],
        "forecast_plan_sha256": result["forecast_plan_sha256"]})
    counters = result["counters"]
    counters["plans"] += 1
    counters["proposal_calls"] += 1
    counters["response_optimizer_steps"] += plan["record"]["reference_optimizer_steps"]
    counters["repair_optimizer_updates"] += verified["record"]["verified_optimizer_steps"]
    counters["repair_panel_evaluations"] += verified["record"]["panel_head_evaluations"]
    return result


def commit_cursor(snapshot, state, receipt, cpu_ns):
    result = copy.deepcopy(snapshot)
    cursor = result["action_cursor"]
    resolved = np.asarray(result["resolved_actions"], dtype=np.float64)
    if (cursor >= result["plan_horizon"] or receipt["previous_state_sha256"] != result["full_state_sha256"]
            or receipt["state_sha256"] != state.digest() or receipt["step"] != state.step_count
            or receipt["step"] != result["warmup_step_count"]+result["absolute_step"]+1
            or receipt["dataset_sha256"] != result["contract"]["training_sha256"]
            or receipt["context"] != state.active_context
            or receipt["intervention_sha256"] != _array_digest(result["contract"]["configuration"]["dt"]*resolved[cursor])
            or digest_json(receipt) != result["plan_receipt_sha256"][cursor]
            or state.digest() != result["plan_state_sha256"][cursor+1]):
        raise ValueError("committed transition differs from frozen verified plan")
    result.update(action_cursor=cursor+1, absolute_step=result["absolute_step"]+1,
        full_state_sha256=state.digest())
    result["receipt_chain"] = {"count": result["absolute_step"],
        "sha256": digest_json([result["receipt_chain"]["sha256"], digest_json(receipt)])}
    result["counters"].update(committed_steps=result["absolute_step"], controller_cpu_ns=int(cpu_ns))
    return result


def load_snapshot(data, state, expected_contract, *, expected_sha256=None):
    if not isinstance(data, bytes) or len(data) > 2_097_152:
        raise ValueError("bounded exact controller bytes required")
    if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("controller snapshot differs from admitted byte commitment")
    result = json.loads(data)
    if canonical(result) != data or result.get("schema") != SCHEMA:
        raise ValueError("exact canonical controller encoding required")
    if canonical(result.get("contract")) != canonical(expected_contract):
        raise ValueError("original controller contract changed; reanchoring is forbidden")
    if result.get("run_status") == "stopped" or result.get("failure_ledger"):
        raise ValueError("stopped controller cannot be retried outside the frozen attempt budget")
    contract = result["contract"]
    for name in ("policy", "protocol_sha256", "original_warmup_state_sha256", "warmup_step_count", "registered_steps"):
        if result.get(name) != contract[name]:
            raise ValueError("controller contract duplicate differs")
    p, absolute, origin, cursor, horizon = [result[name] for name in
        ("contract", "absolute_step", "plan_origin_step", "action_cursor", "plan_horizon")]
    p = p["parameter_count"]
    if (any(type(v) is not int for v in (absolute, origin, cursor, horizon))
            or not 0 <= absolute <= contract["registered_steps"] or not 0 <= origin <= absolute
            or horizon not in (0, 1 if contract["policy"] == "myopic_h1" else contract["configuration"]["commit_stride"])
            or not 0 <= cursor <= horizon
            or origin % (1 if contract["policy"] == "myopic_h1" else contract["configuration"]["commit_stride"])
            or absolute != origin+cursor or origin+horizon > contract["registered_steps"]
            or (horizon == 0 and absolute != 0) or (absolute == contract["registered_steps"] and cursor != horizon)
            or state.parameter_count != p or state.digest() != result["full_state_sha256"]
            or state.step_count != contract["warmup_step_count"]+absolute
            or state.bindings["protocol_sha256"] != contract["optimizer_origin_protocol_sha256"]
            or state.contexts.get(state.active_context) != contract["training_sha256"]
            or result.get("run_status") != ("completed" if absolute == contract["registered_steps"] else "active")
            or result.get("authority") != "DENY_ALL" or result.get("production_authority") is not False):
        raise ValueError("complete state, optimizer clock or frozen plan cursor differs")
    if ((absolute == 0 and state.digest() != contract["original_warmup_state_sha256"])
            or (origin == 0 and result["plan_origin_state_sha256"] != contract["original_warmup_state_sha256"])):
        raise ValueError("original warmup checkpoint cannot be substituted")
    for kind in ("intended", "resolved"):
        actions = np.asarray(result[kind+"_actions"], dtype=np.float64).reshape(horizon, p)
        if (not np.isfinite(actions).all()
                or np.any(np.abs(actions) > contract["configuration"]["action_bound"]/np.sqrt(p))
                or _array_digest(actions) != result[kind+"_plan_sha256"]):
            raise ValueError("resolved action bytes or immutable action box differ")
    forecast_horizon = result["forecast_horizon"]
    expected_horizon = min(POLICIES[contract["policy"]][1], contract["registered_steps"]-origin) if horizon else 0
    forecast = np.asarray(result["forecast_actions"], dtype=np.float64).reshape(forecast_horizon, p)
    if (type(forecast_horizon) is not int or forecast_horizon != expected_horizon
            or not np.isfinite(forecast).all()
            or np.any(np.abs(forecast) > contract["configuration"]["action_bound"]/np.sqrt(p))
            or _array_digest(forecast) != result["forecast_plan_sha256"]
            or not np.array_equal(forecast[:horizon], np.asarray(result["intended_actions"]).reshape(horizon, p))
            or result["counters"]["qp_calls"] != 0 or result["counters"]["actual_merit_rollout_steps"] != 0):
        raise ValueError("V8 forecast identity, prefix relation or charged proposal counters differ")
    states, receipts = result["plan_state_sha256"], result["plan_receipt_sha256"]
    if (len(states) != horizon+1 or len(receipts) != horizon
            or states[0] != result["plan_origin_state_sha256"] or states[cursor] != state.digest()
            or result["receipt_chain"]["count"] != absolute
            or result["counters"]["committed_steps"] != absolute
            or len(result["certificate_chain"]) != result["counters"]["plans"]
            or any(type(v) is not int or v < 0 for v in result["counters"].values())):
        raise ValueError("verified state/receipt chain or cumulative counters differ")
    if horizon and (not result["certificate_chain"]
            or result["certificate_chain"][-1]["resolved_plan_sha256"] != result["resolved_plan_sha256"]
            or result["certificate_chain"][-1]["forecast_plan_sha256"] != result["forecast_plan_sha256"]):
        raise ValueError("current resolved plan differs from its retained certificate")
    return result
