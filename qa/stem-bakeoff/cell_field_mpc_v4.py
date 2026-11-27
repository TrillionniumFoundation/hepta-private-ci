"""Causal receding-horizon execution with complete preparation costs charged."""

import time

import numpy as np

from cell_field_action_control import plan_action
from cell_field_action_io import save_arrays, write_json
from cell_field_experiments_v4 import prepare
from cell_field_features import file_hash


def execute_policy(warmup, split, plan, projected, old_anchor, policy, output):
    if policy not in plan["mpc"]["policies"]:
        raise ValueError("unregistered online policy")
    output.mkdir(parents=True, exist_ok=False)
    state = warmup.clone()
    initial_digest = state.digest()
    state.save(output / "initial")
    horizon = 1 if policy == "myopic_full_h1" else 8
    model_name = "full" if policy == "myopic_full_h1" else policy.removesuffix("_h8")
    states, probabilities, actions, steps, receipts = [state.vector()], [], [], [], []
    probabilities.append(state.head.predict_proba(projected))
    total_cpu, total_wall = 0, 0
    status, error = "completed", None
    for k in range(plan["mpc"]["steps"]):
        charged = False
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            if policy == "zero":
                u, preparation = np.zeros(state.parameter_count), {}
                solver = {"status": "fixed_zero", "record": {"optimality_claim": False}}
            else:
                reference, models, preparation = prepare(state, split, plan, names=(model_name,), horizon=horizon)
                model = {**models[model_name], "reference_observations": reference.observations[:, :2]}
                solver = plan_action(model, objective="direct_soft", lookahead=horizon,
                    old_anchor=old_anchor, dt=plan["h"], effort_price=plan["effort_price"],
                    action_bound=plan["mpc"]["action_bound"])
                if solver["status"] != "qualified":
                    steps.append({"step": k, "preparation": preparation, "solver": solver["record"],
                                  "status": solver["status"]})
                    total_cpu += time.process_time_ns() - cpu
                    total_wall += time.perf_counter_ns() - began
                    status = "unresolved"
                    break
                u = solver["u"].copy()
            if (u.shape != (state.parameter_count,) or not np.isfinite(u).all()
                    or np.any(np.abs(u) > plan["mpc"]["action_bound"] / np.sqrt(state.parameter_count))):
                raise ValueError("no action clipping or undeclared budget permitted")
            # The plan exists on disk before its actual transition is executed.
            save_arrays(output / f"plans/{k}.npz", {"u": u, **({"loss_maps": model["loss_maps"]}
                                                         if policy != "zero" else {})})
            write_json(output / f"plans/{k}.json", {"initial_state_sha256": state.digest(),
                "plan_sha256": file_hash(output / f"plans/{k}.npz"), "solver": solver["record"]})
            receipts.append(state.advance(*split["current_train"], intervention=plan["h"] * u))
            actions.append(u)
            states.append(state.vector())
            probabilities.append(state.head.predict_proba(projected))
            elapsed_cpu, elapsed_wall = time.process_time_ns() - cpu, time.perf_counter_ns() - began
            total_cpu += elapsed_cpu
            total_wall += elapsed_wall
            charged = True
            steps.append({"step": k, "status": "completed", "preparation": preparation,
                          "solver": solver["record"], "cpu_ns": elapsed_cpu, "wall_ns": elapsed_wall,
                          "physical_impulse_norm": float(np.linalg.norm(plan["h"] * u))})
            if k == 3:
                state.save(output / "midpoint")
        except Exception as exc:
            status, error = "execution_failed", {"type": type(exc).__name__, "message": str(exc)}
            if not charged:
                elapsed_cpu, elapsed_wall = time.process_time_ns() - cpu, time.perf_counter_ns() - began
                total_cpu += elapsed_cpu
                total_wall += elapsed_wall
            steps.append({"step": k, "status": "execution_failed", "error": error,
                          "cpu_ns": elapsed_cpu, "wall_ns": elapsed_wall,
                          "actual_state_sha256": state.digest()})
            break
    terminal_probabilities = (probabilities[-1] if len(probabilities) == len(states)
                              else np.full((len(projected), 4), np.nan))
    save_arrays(output / "trajectory.npz", {"states": np.asarray(states), "actions": np.asarray(actions),
        "probabilities": np.asarray(probabilities), "terminal_probabilities": terminal_probabilities})
    state.save(output / "terminal")
    write_json(output / "receipts.json", receipts)
    record = {"policy": policy, "status": status, "error": error, "steps": steps,
        "completed_steps": len(actions), "registered_steps": plan["mpc"]["steps"],
        "cpu_ns": total_cpu, "wall_ns": total_wall, "initial_state_sha256": initial_digest,
        "terminal_state_sha256": state.digest(), "cost_scope": plan["mpc"]["cost"],
        "parameter_action_penalty": float(0.5 * plan["h"] * plan["effort_price"] * np.square(actions).sum()),
        "authority": "DENY_ALL", "production_authority": False}
    write_json(output / "result.json", record)
    if warmup.digest() != initial_digest:
        raise RuntimeError("online policy mutated its shared warmup")
    return record
