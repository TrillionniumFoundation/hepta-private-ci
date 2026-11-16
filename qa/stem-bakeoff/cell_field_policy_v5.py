"""Execute frozen response planners and preserve every rejected control attempt."""

import time

import numpy as np

from cell_field_planner_v5 import make_plan
from cell_field_safety_v5 import verify_action


POLICIES = {
    "zero": {"method": None, "horizon": 1, "guard": False},
    "myopic_full_h1": {"method": "adjoint", "horizon": 1, "guard": False},
    "myopic_guarded_h1": {"method": "adjoint", "horizon": 1, "guard": True},
    "loss2_h8": {"method": "loss2", "horizon": 8, "guard": True},
    "adjoint_h8": {"method": "adjoint", "horizon": 8, "guard": False},
    "response_h8_guarded": {"method": "adjoint", "horizon": 8, "guard": True},
}


def execute_policy(warmup, split, old_anchor, policy, configuration):
    """Return complete trace. A failed plan stops without advancing or zero substitution.

    Identical frozen per-step boxes and terminal-objective coefficients apply to
    all planners. H8 commits its already verified sequence before re-planning.
    CPU includes response construction, solver, all safety trials and committed
    transitions. Held-out predictions and artifact serialization are separate.
    """
    if policy not in POLICIES:
        raise ValueError("unregistered V5 policy")
    required = {"steps", "dt", "effort_price", "action_bound", "old_weight", "hard_retention", "backtracking"}
    if set(configuration) != required or configuration["steps"] % 8 or not 8 <= configuration["steps"] <= 64:
        raise ValueError("one fully declared bounded policy configuration required")
    spec, state = POLICIES[policy], warmup.clone()
    origin = warmup.digest()
    states, actions, records, receipts = [state.clone()], [], [], []
    plans, status, error_record, cpu_total, wall_total = [], "completed", None, 0, 0
    try:
        while len(actions) < configuration["steps"]:
            began, cpu = time.perf_counter_ns(), time.process_time_ns()
            horizon = spec["horizon"]
            if spec["method"] is None:
                action = np.zeros(state.parameter_count)
                receipt = state.advance(*split["current_train"], intervention=configuration["dt"]*action)
                states.append(state.clone())
                actions.append(action)
                receipts.append(receipt)
                records.append({"status": "fixed_zero", "committed_steps": 1})
            else:
                plan = make_plan(state, split, old_anchor, method=spec["method"], horizon=horizon,
                    **{key: configuration[key] for key in ("dt", "effort_price", "action_bound", "old_weight", "hard_retention")})
                plans.append(plan)
                record = {"at_step": len(actions), "plan": plan["record"], "committed_steps": 0}
                records.append(record)
                if plan["record"]["status"] != "qualified":
                    record["status"] = "not_executed_" + plan["record"]["status"]
                    status = record["status"]
                elif spec["guard"]:
                    verified = verify_action(state,
                        {key: split[key] for key in ("current_train", "old_probe")}, plan["actions"], old_anchor,
                        horizon=horizon, dt=configuration["dt"], action_bound=configuration["action_bound"],
                        backtracking=configuration["backtracking"], commit_steps=horizon)
                    record["safety"] = verified["record"]
                    if not verified["record"]["certified"]:
                        record["status"] = "not_executed_" + verified["record"]["status"]
                        status = record["status"]
                    else:
                        # Reconstruct metadata for every certified checkpoint without
                        # evaluating the optimizer again. Verify the terminal identity.
                        committed, accepted = [], []
                        previous = state.digest()
                        for k, action in enumerate(verified["arrays"]["actions"]):
                            following = state.clone()
                            following.set_vector(verified["arrays"]["states"][k+1])
                            following.step_count = state.step_count+k+1
                            receipt = verified["receipts"][k]
                            if receipt["previous_state_sha256"] != previous or receipt["state_sha256"] != following.digest():
                                raise RuntimeError("prospective receipt chain does not bind each complete checkpoint")
                            previous = following.digest()
                            committed.append(following)
                            accepted.append(action.copy())
                        if committed[-1].digest() != verified["state"].digest():
                            raise RuntimeError("certified metadata reconstruction differs from complete terminal state")
                        state = verified["state"]
                        states.extend(committed)
                        actions.extend(accepted)
                        receipts.extend(verified["receipts"])
                        record.update(status="committed_certified", committed_steps=horizon)
                else:
                    for action in plan["actions"]:
                        receipts.append(state.advance(*split["current_train"], intervention=configuration["dt"]*action))
                        states.append(state.clone())
                        actions.append(action.copy())
                    record.update(status="committed_unverified", committed_steps=horizon)
            elapsed_cpu, elapsed_wall = time.process_time_ns()-cpu, time.perf_counter_ns()-began
            cpu_total += elapsed_cpu
            wall_total += elapsed_wall
            records[-1].update(cpu_ns=elapsed_cpu, wall_ns=elapsed_wall)
            if status != "completed":
                break
    except Exception as error:
        elapsed_cpu, elapsed_wall = time.process_time_ns()-cpu, time.perf_counter_ns()-began
        cpu_total += elapsed_cpu
        wall_total += elapsed_wall
        status = "not_executed_unresolved"
        error_record = {"type": type(error).__name__, "message": str(error)}
        records.append({"at_step": len(actions), "status": status, "committed_steps": 0,
            "error": error_record,
            "cpu_ns": elapsed_cpu, "wall_ns": elapsed_wall, "state_sha256": state.digest()})
    if warmup.digest() != origin:
        raise RuntimeError("policy mutated shared initial checkpoint")
    a = np.asarray(actions).reshape(-1, state.parameter_count)
    return {"state": state, "states": states, "actions": a, "plans": plans, "receipts": receipts,
        "record": {"schema": "hepta.cell-field-policy.v5", "policy": policy, "status": status,
            "error": error_record,
            "completed_steps": len(actions), "registered_steps": configuration["steps"], "steps": records,
            "cpu_ns": cpu_total, "wall_ns": wall_total, "initial_state_sha256": origin,
            "terminal_state_sha256": state.digest(),
            "parameter_action_penalty": float(.5*configuration["dt"]*configuration["effort_price"]*np.square(a).sum()),
            "cost_scope": "own response, solver, all verification trials, committed transitions, checkpoint clones; output serialization/evaluation separate",
            "authority": "DENY_ALL", "production_authority": False}}
