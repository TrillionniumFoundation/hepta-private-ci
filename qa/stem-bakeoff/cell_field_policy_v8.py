"""V8 receding-horizon risk proposals with certified prefixes and exact resume.

Only the committed prefix is certified against actual old losses. Its remaining
H8 forecast tail is retained for provenance and discarded before replanning.
"""

import copy
import time

import numpy as np

from cell_field_controller_v8 import (POLICIES, commit_cursor, digest_json,
    initial_snapshot, install_plan, load_snapshot, make_contract)
from cell_field_proposal_v8 import make_proposal
from cell_field_repair_v7 import panel_losses
from cell_field_safety_v8 import repair_sequence
from cell_field_state import dataset_digest


def _run(initial, snapshot, train, current_panels, old_panels):
    contract = snapshot["contract"]
    config, policy = contract["configuration"], contract["policy"]
    anchors = np.asarray(contract["original_old_anchors"])
    if (dataset_digest(*train) != contract["training_sha256"]
            or [dataset_digest(*p) for p in current_panels] != contract["current_panel_sha256"]
            or [dataset_digest(*p) for p in old_panels] != contract["old_panel_sha256"]):
        raise ValueError("restored controller input identities changed")
    method, horizon = POLICIES[policy]
    before, state = initial.digest(), initial.clone()
    origin_step, prior_cpu = snapshot["absolute_step"], snapshot["counters"]["controller_cpu_ns"]
    states, controllers, actions, receipts, plans, records = [state.clone()], [copy.deepcopy(snapshot)], [], [], [], []
    status, error_record = "completed", None
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        while snapshot["absolute_step"] < config["steps"]:
            at_step = snapshot["absolute_step"]
            pending = snapshot["plan_horizon"]-snapshot["action_cursor"]
            row = {"at_step": at_step, "committed_steps": 0}
            records.append(row)
            if pending:
                # Recheck the whole retained suffix on a prospective clone. No
                # plan, anchor or RNG is changed during crash recovery.
                cursor = snapshot["action_cursor"]
                resolved = np.asarray(snapshot["resolved_actions"])
                prospective, next_states, next_receipts = state.clone(), [], []
                for k in range(cursor, snapshot["plan_horizon"]):
                    receipt = prospective.advance(*train, intervention=config["dt"]*resolved[k])
                    if (prospective.digest() != snapshot["plan_state_sha256"][k+1]
                            or digest_json(receipt) != snapshot["plan_receipt_sha256"][k]
                            or np.any(panel_losses(prospective.head, old_panels) > anchors)):
                        raise RuntimeError("restored pending suffix failed exact full-state/retention replay")
                    next_states.append(prospective.clone())
                    next_receipts.append(receipt)
                snapshot["counters"]["resume_verification_updates"] += pending
                next_actions = resolved[cursor:].copy()
                row.update(status="resumed_verified_suffix", resume_verified_steps=pending)
            else:
                remaining = config["steps"]-at_step
                forecast_horizon = min(horizon, remaining)
                commit_horizon = min(1 if policy == "myopic_h1" else config["commit_stride"], remaining)
                planned = make_proposal(state, train, current_panels, old_panels, anchors,
                    method=method, horizon=forecast_horizon,
                    **{k: config[k] for k in ("dt", "effort_price", "action_bound", "old_weight",
                        "current_dispersion")})
                plans.append(planned)
                row["plan"] = planned["record"]
                row["forecast_actions"] = planned["actions"].tolist()
                row["commit_horizon"] = commit_horizon
                if planned["record"]["status"] != "qualified":
                    status = "not_executed_"+planned["record"]["status"]
                    row["status"] = status
                    break
                intended = planned["actions"][:commit_horizon].copy()
                verified = repair_sequence(state, train, old_panels, intended, anchors,
                    horizon=commit_horizon, dt=config["dt"], action_bound=config["action_bound"])
                row["repair"] = verified["record"]
                if not verified["record"]["certified"]:
                    status = "not_executed_"+verified["record"]["status"]
                    row["status"] = status
                    break
                snapshot = install_plan(snapshot, intended, verified, planned)
                next_states, next_actions, next_receipts = verified["states"][1:], verified["actions"], verified["receipts"]
                row["status"] = "committed_certified"
            prepared, cursor_snapshot = [], snapshot
            for following, receipt in zip(next_states, next_receipts, strict=True):
                cursor_snapshot = commit_cursor(cursor_snapshot, following, receipt,
                    prior_cpu+time.process_time_ns()-cpu)
                prepared.append(cursor_snapshot)
            snapshot, state = prepared[-1], next_states[-1]
            states.extend(s.clone() for s in next_states)
            controllers.extend(copy.deepcopy(prepared))
            actions.extend(a.copy() for a in next_actions)
            receipts.extend(next_receipts)
            row["committed_steps"] = len(next_actions)
    except Exception as error:
        status = "not_executed_unresolved"
        error_record = {"type": type(error).__name__, "message": str(error)}
        records.append({"at_step": snapshot["absolute_step"], "status": status,
            "committed_steps": 0, "error": error_record})
    elapsed_cpu, elapsed_wall = time.process_time_ns()-cpu, time.perf_counter_ns()-began
    snapshot = copy.deepcopy(controllers[-1])
    snapshot["counters"]["controller_cpu_ns"] = prior_cpu+elapsed_cpu
    snapshot["run_status"] = "completed" if status == "completed" else "stopped"
    if status != "completed":
        snapshot["failure_ledger"].append({"origin_absolute_step": origin_step,
            "stopped_absolute_step": snapshot["absolute_step"], "status": status,
            "paid_cpu_ns": elapsed_cpu, "paid_wall_ns": elapsed_wall,
            "execution_record_sha256": digest_json(records), "error": error_record})
    controllers[-1] = snapshot
    if initial.digest() != before:
        raise RuntimeError("controller changed its caller's complete checkpoint")
    a = np.asarray(actions).reshape(-1, state.parameter_count)
    return {"state": state, "states": states, "actions": a, "receipts": receipts,
        "plans": plans, "controllers": controllers,
        "record": {"schema": "hepta.cell-field-panel-policy.v8", "policy": policy,
            "status": status, "error": error_record, "initial_state_sha256": before,
            "terminal_state_sha256": state.digest(), "origin_absolute_step": origin_step,
            "completed_steps": snapshot["absolute_step"], "newly_committed_steps": len(actions),
            "registered_steps": config["steps"], "steps": records,
            "cpu_ns": elapsed_cpu, "wall_ns": elapsed_wall,
            "parameter_action_penalty": float(.5*config["dt"]*config["effort_price"]*np.square(a).sum()),
            "cost_scope": "response, risk-effort proposal, all joint old-filter trials/replays, full-state clones and controller/cursor data; disk and development selection evaluation separate",
            "independent_online_certificate": False, "authority": "DENY_ALL", "production_authority": False}}


def execute_policy(warmup, train, current_panels, old_panels, old_anchors, policy, configuration, *,
                   controller_protocol_sha256=None, controller_source_sha256=None):
    contract = make_contract(warmup, train, current_panels, old_panels, old_anchors, policy, configuration,
        controller_protocol_sha256=controller_protocol_sha256, controller_source_sha256=controller_source_sha256)
    if not np.array_equal(panel_losses(warmup.head, old_panels), np.asarray(old_anchors)):
        raise ValueError("original warmup anchors must match every panel exactly")
    snapshot = initial_snapshot(warmup, contract)
    return _run(warmup, snapshot, train, list(current_panels), list(old_panels))


def resume_policy(state, controller_bytes, expected_contract, train, current_panels, old_panels,
                  *, expected_controller_sha256=None):
    snapshot = load_snapshot(controller_bytes, state, expected_contract,
        expected_sha256=expected_controller_sha256)
    return _run(state, snapshot, train, list(current_panels), list(old_panels))
