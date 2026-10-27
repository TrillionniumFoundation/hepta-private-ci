"""Complete-policy forecasting consumes actual recovered owner branch receipts."""
import math

import numpy as np

from .client import Q


def forecasts(native, arm, protocol):
    rows = []
    for fault, scalar in enumerate(protocol["numeric_feedback_by_fault"]):
        feedback = 0.0 if arm == "risk_zero" else scalar
        branch = native.call({"command": "Forecast", "feedback_q24": round(feedback * Q),
                              "branch": f"fault-{fault}"})
        if not branch["committed_parent_unchanged"] or not branch["shadow_only"] or branch["media_dispatched"]:
            raise ValueError("Speculative owner branch mutated actual continuation")
        rows.append(branch)
    return rows


def branch_action(branch, fault, budget, arm):
    proposed = fault != 0 if arm == "risk_history" else branch["ticks"][-1]["proposed_repair"]
    native_ok = not any(tick["native_abstain"] for tick in branch["ticks"])
    allowed = native_ok and budget >= 2
    if arm == "mean_blind_future":
        allowed = True
    return {"proposed_repair": bool(proposed), "native_nonabstention": native_ok,
            "host_resource_available": budget >= 2, "executed_repair": bool(proposed and allowed),
            "denied_attempt": bool(proposed and not allowed)}


def outcome_returns(action, fault, choice, protocol):
    native_count = protocol["prefix_native_ticks"] + protocol["forecast_native_ticks"] + protocol["continuation_native_ticks"]
    cost = protocol["initial_action_cost"][action] + protocol["channel_cost_by_fault"][fault]
    cost += native_count * protocol["native_tick_charge"]
    cost += protocol["verification_replay_steps"] * protocol["verification_replay_step_charge"]
    cost += protocol["repair_cost"] * choice["executed_repair"]
    cost += protocol["denied_repair_attempt_cost"] * choice["denied_attempt"]
    final_fault = 0 if choice["executed_repair"] else fault
    values = np.array(protocol["semantic_utility_action_by_target"][action], dtype=float)
    values -= protocol["irreversible_first_delivery_damage"][fault]
    values -= protocol["terminal_mismatch_penalty"][final_fault] + cost
    success = [int(final_fault == 0 and action == target) for target in range(3)]
    return values, success, cost


def plan(cue, budget, arm, branches, current_mask, protocol, forced_action=None):
    target_law = np.array(protocol["target_law_by_cue"][cue])
    actions = []
    for action, fault_law in enumerate(protocol["fault_law_by_action"]):
        moments = mean = success = cost = 0.0
        continuation = []
        for fault, probability in enumerate(fault_law):
            choice = branch_action(branches[fault], fault, budget, arm)
            returns, strict, expense = outcome_returns(action, fault, choice, protocol)
            moments += probability * float(np.exp(-protocol["gamma"] * returns) @ target_law)
            mean += probability * float(returns @ target_law)
            success += probability * float(np.array(strict) @ target_law)
            cost += probability * expense
            continuation.append(choice)
        actions.append({"action": action, "moment": moments, "mean": mean,
            "strict_success_probability": success, "expected_task_charge": cost,
            "ce": -math.log(moments) / protocol["gamma"], "continuation": continuation,
            "current_native_nonabstention": bool(current_mask[action])})
    feasible = [row for row in actions if row["current_native_nonabstention"]]
    if not feasible:
        raise ValueError("No current action passed the actual owner; must retain failure")
    objective = "mean" if arm.startswith("mean") else "entropic"
    selected = (min(feasible, key=lambda row: (-row["mean"], row["action"])) if objective == "mean"
                else min(feasible, key=lambda row: (row["moment"], row["action"])))
    if forced_action is not None:
        selected = actions[forced_action]
        if not selected["current_native_nonabstention"]:
            raise ValueError("Ablation common root was not allowed")
    return {"objective": objective, "actions": actions, "selected": selected,
            "forced_common_root": forced_action is not None,
            "future_native_and_host_rules_consumed": arm != "mean_blind_future"}
