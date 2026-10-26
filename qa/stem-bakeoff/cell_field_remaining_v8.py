"""Commit-one development controller for a fixed absolute terminal32 target.

The remaining-horizon proposals use a zero-intervention nominal continuation;
they do not differentiate the future adaptive controller. H1 stays explicitly
myopic. All proposals share the same full-state, old-only safety portfolio.
This research trace has no native handoff or production admission authority.
"""

import time

import numpy as np

from cell_field_common_run_v8 import canonical, sha
from cell_field_repair_v7 import panel_losses
from cell_field_safety_portfolio_v8 import repair_sequence
from cell_field_state import CellTrainingState, _array_digest, dataset_digest
from cell_field_terminal_v8 import METHODS, WEIGHTS, make_terminal_proposal


def actual_errors(value):
    if isinstance(value, dict):
        return ([value["error"]] if value.get("error") is not None else []) + [
            error for key, child in value.items() if key != "error" for error in actual_errors(child)]
    if isinstance(value, list):
        return [error for child in value for error in actual_errors(child)]
    return []


def validate_one_step(origin, verified, train, old_panels, anchors):
    """Check the whole prospective receipt before adopting its complete state.

    The bound source verifier computes the actual transition. This boundary
    validates its metadata, receipt and independently remeasures four losses;
    a separate post-run auditor must independently replay the optimizer.
    """
    record, p = verified["record"], origin.parameter_count
    if (not record["certified"] or record["certified_optimizer_steps"] != 1
            or record["committed_optimizer_steps"] != 0 or record["horizon"] != 1
            or record["dt"] != .02 or record["action_bound"] != 4.
            or record["threshold_slack"] != 0. or record["initial_state_sha256"] != origin.digest()
            or record["original_old_anchors"] != anchors.tolist()
            or record["old_panel_sha256"] != [dataset_digest(*pair) for pair in old_panels]
            or len(verified["states"]) != 2 or len(verified["receipts"]) != 1
            or verified["actions"].shape != (1, p) or verified["old_losses"].shape != (2, 4)
            or verified["states"][0].digest() != origin.digest() or actual_errors(record)):
        raise ValueError("complete one-step, error-free, original-anchor certificate required")
    following, receipt = verified["states"][1], verified["receipts"][0]
    action = verified["actions"][0]
    expected_metadata = origin._metadata()
    expected_metadata["step_count"] += 1
    if (canonical(following._metadata()) != canonical(expected_metadata)
            or following.digest() != verified["state"].digest() or following.digest() != record["returned_state_sha256"]
            or not np.isfinite(action).all() or np.any(np.abs(action) > 4./np.sqrt(p))
            or receipt["previous_state_sha256"] != origin.digest() or receipt["state_sha256"] != following.digest()
            or receipt["step"] != following.step_count or receipt["context"] != origin.active_context
            or receipt["dataset_sha256"] != dataset_digest(*train) or receipt["mark_origin"] != "full_batch"
            or receipt["marks"] != list(range(len(train[1]))) or receipt["mask_sha256"] is not None
            or receipt["intervention_sha256"] != _array_digest(.02*action)
            or receipt["intervention_l2"] != float(np.linalg.norm(.02*action))
            or receipt["parameter_update_l2"] != float(np.linalg.norm(following.parameter_vector()-origin.parameter_vector()))
            or receipt["authority"] != "DENY_ALL"):
        raise ValueError("certified state, complete metadata or physical intervention receipt differs")
    losses = panel_losses(following.head, old_panels)
    if not np.isfinite(losses).all() or not np.array_equal(losses, verified["old_losses"][1]) or np.any(losses > anchors):
        raise ValueError("adoption requires exact four-panel, zero-slack retention")
    return following.clone(), action.copy(), receipt, losses


def execute_remaining(warmup, train, current_panels, old_panels, old_anchors, method, *,
                      controller_protocol_sha256, controller_source_sha256):
    """Run at most32 physical steps; any failed attempt retains its last prefix."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    anchors = np.asarray(old_anchors, dtype=np.float64)
    pins = (controller_protocol_sha256, controller_source_sha256)
    if (type(warmup) is not CellTrainingState or warmup.protocol["sampler"] != "full_batch"
            or method not in METHODS or len(current_panels) != 4 or len(old_panels) != 4
            or anchors.shape != (4,) or not np.isfinite(anchors).all()
            or warmup.contexts.get(warmup.active_context) != dataset_digest(*train)
            or any(not isinstance(pin, str) or len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin) for pin in pins)):
        raise ValueError("pinned full-batch research controller and eight original panels required")
    initial_losses = panel_losses(warmup.head, old_panels)
    if not np.array_equal(initial_losses, anchors):
        raise ValueError("all four thresholds must equal the original complete warmup losses")
    before, state = warmup.digest(), warmup.clone()
    contract = {"schema": "hepta.remaining-terminal-contract.v8", "method": method,
        "controller_protocol_sha256": pins[0], "controller_source_sha256": pins[1],
        "warmup_state_sha256": before, "optimizer_origin_bindings": warmup.bindings,
        "optimizer_origin_protocol": warmup.protocol, "training_sha256": dataset_digest(*train),
        "current_panel_sha256": [dataset_digest(*pair) for pair in current_panels],
        "old_panel_sha256": [dataset_digest(*pair) for pair in old_panels],
        "original_old_anchors": anchors.tolist(), "registered_steps": 32, "commit_stride": 1,
        "dt": .02, "effort_price": .03, "action_bound": 4., "old_mean_weight": .25,
        "current_mean_weight": 1., "current_dispersion": 0., "production_authority": False}
    states, actions, receipts, plans, rows, losses = [state.clone()], [], [], [], [], [initial_losses]
    status, error_record, adoption_head_attempts = "completed", None, 0
    try:
        for at_step in range(32):
            row = {"at_step": at_step, "committed_steps": 0}
            rows.append(row)
            planned = make_terminal_proposal(state, train, current_panels, old_panels,
                method=method, remaining=32-at_step)
            plans.append(planned)
            row["proposal"] = planned["record"]
            verified = repair_sequence(state, train, old_panels, planned["action"][None, :], anchors, horizon=1)
            row["repair"] = verified["record"]
            nested = actual_errors(verified["record"])
            if nested:
                raise RuntimeError("actual error in a paid safety attempt: "+str(nested))
            if not verified["record"]["certified"]:
                status = "not_executed_"+verified["record"]["status"]
                row["status"] = status
                break
            adoption_head_attempts += 4
            following, action, receipt, measured = validate_one_step(state, verified, train, old_panels, anchors)
            row.update(status="committed_certified", committed_steps=1,
                predicted_zero_tail_panels_on_resolved_action=(planned["reference_terminal_panels"]
                    +planned["first_action_map"]@action).tolist(), resolved_action_sha256=_array_digest(action))
            state = following
            states.append(state.clone())
            actions.append(action)
            receipts.append(receipt)
            losses.append(measured)
    except Exception as error:
        status = "not_executed_unresolved"
        error_record = {"type": type(error).__name__, "message": str(error)}
        rows.append({"at_step": len(actions), "committed_steps": 0, "status": status, "error": error_record})
    a = np.asarray(actions).reshape(-1, warmup.parameter_count)
    terminal = None
    try:
        terminal = panel_losses(state.head, [*current_panels, *old_panels])
        if not np.isfinite(terminal).all():
            terminal = None
            raise ValueError("nonfinite terminal planning-panel losses")
    except Exception as error:
        status = "not_executed_unresolved"
        error_record = {"type": type(error).__name__, "message": str(error)}
        rows.append({"at_step": len(actions), "committed_steps": 0, "status": status, "error": error_record})
    if warmup.digest() != before:
        raise RuntimeError("remaining-terminal controller mutated its original full checkpoint")
    penalty = float(.5*.02*.03*np.square(a).sum())
    record = {"schema": "hepta.remaining-terminal-policy.v8", "method": method, "status": status,
        "error": error_record, "contract": contract, "contract_sha256": sha(contract),
        "initial_state_sha256": before, "terminal_state_sha256": state.digest(),
        "state_sha256": [s.digest() for s in states], "receipts": receipts, "steps": rows,
        "completed_steps": len(actions), "registered_steps": 32, "parameter_action_penalty": penalty,
        "terminal_planning_panels": None if terminal is None else terminal.tolist(),
        "common_J32": float(WEIGHTS@terminal+penalty) if terminal is not None and len(actions) == 32 else None,
        "adoption_old_head_evaluations_upper_bound": adoption_head_attempts,
        "terminal_measurement_head_evaluations_upper_bound": 8, "initial_anchor_head_evaluations": 4,
        "query_scope": "proposal fixed-call counts plus all original safety attempt receipts; exceptional partial head calls can be bounded rather than exact",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began,
        "cost_scope": "whole controller including original anchors, contracts, full-state references, all failed searches, exact adoption checks, terminal planning losses; disk and DEV scoring separate",
        "forecast_scope": "fixed zero-intervention tail; future adaptive replans are not differentiated or scored as forecast errors",
        "retention_scope": "four reused empirical original anchors; no independent population certificate",
        "scientific_acceptance": False, "production_authority": False, "native_handoff_qualified": False}
    return {"state": state, "states": states, "actions": a, "receipts": receipts,
        "old_losses": np.asarray(losses), "plans": plans, "record": record}
