"""Bounded probe-only pressure search and common one-impulse retention census.

Original warmup thresholds remain fixed. Certificates concern only the declared
tangent problem; actual nonlinear violations and unavailable plans stay visible.
No validation/final labels, policy selection, retries or outcome resampling occur.
"""

from collections import deque
import hashlib
import time

import numpy as np

from cell_field_action_control import plan_action, score_common
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import normalize_features


def search_pressure(warmup_state, development, *, max_steps=256, horizon=8):
    """Return first original-threshold crossing and distinct prevention/recovery states.

    ``development`` admits exactly current_train and old_probe pairs. The caller
    supplies an original complete warmup checkpoint, never an outcome-selected
    later anchor. No crossing is a recorded result with no fabricated checkpoints.
    """
    if (type(warmup_state) is not CellTrainingState or warmup_state.step_count < 1
            or warmup_state.protocol["sampler"] != "full_batch"
            or type(max_steps) is not int or not 1 <= max_steps <= 256
            or type(horizon) is not int or not 1 <= horizon <= 8
            or not isinstance(development, dict)
            or set(development) != {"current_train", "old_probe"}):
        raise ValueError("complete warmup and bounded training/probe-only search required")
    train, probe = development["current_train"], development["old_probe"]
    train_id, probe_id = dataset_digest(*train), dataset_digest(*probe)
    if warmup_state.contexts.get("current_train") != train_id:
        raise ValueError("current training bytes must match the declared checkpoint context")
    normalized = normalize_features(probe[0])
    anchor = float(warmup_state.head.loss_gradients(normalized, probe[1], 0.0)[0])
    if not np.isfinite(anchor):
        raise ValueError("finite original warmup old-probe threshold required")
    before = warmup_state.digest()
    state = warmup_state.clone()
    state.select_context("current_train")
    record = {"schema": "hepta.cell-pressure-search.v4", "status": "no_pressure_crossing",
              "warmup_state_sha256": before, "initial_current_context_sha256": state.digest(),
              "old_anchor": anchor, "threshold_rule": "original_warmup_old_probe; strict greater",
              "current_train_sha256": train_id, "old_probe_sha256": probe_id,
              "maximum_steps": max_steps, "prevention_horizon": horizon,
              "completed_steps": 0, "tau": None, "checkpoint_offsets": {},
              "authority": "DENY_ALL", "production_authority": False}
    states, losses, receipts = [state.vector()], [anchor], []
    retained, checkpoints = deque([(0, state.clone())], maxlen=horizon + 1), {}
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        for offset in range(1, max_steps + 1):
            receipts.append(state.advance(*train))
            loss = float(state.head.loss_gradients(normalized, probe[1], 0.0)[0])
            if not np.isfinite(loss):
                raise ValueError("nonfinite pressure probe loss")
            states.append(state.vector())
            losses.append(loss)
            retained.append((offset, state.clone()))
            record["completed_steps"] = offset
            if loss > anchor:
                previous = max(0, offset - horizon)
                checkpoints = {"prevention": next(s for i, s in retained if i == previous),
                               "recovery": state.clone()}
                record.update(status="pressure_crossing", tau=offset,
                              checkpoint_offsets={"prevention": previous, "recovery": offset})
                break
    except Exception as error:
        record.update(status="search_failed", error={"type": type(error).__name__, "message": str(error)})
    record.update(wall_ns=time.perf_counter_ns() - began, cpu_ns=time.process_time_ns() - cpu,
                  checkpoint_sha256={name: s.digest() for name, s in checkpoints.items()},
                  maximum_observed_old_excess=float(max(losses) - anchor))
    if warmup_state.digest() != before:
        raise RuntimeError("pressure search changed its original warmup state")
    return {"record": record, "checkpoints": checkpoints, "states": np.asarray(states),
            "old_losses": np.asarray(losses), "receipts": receipts}


def plan_pressure(reference, models, old_anchor, *, budgets=(0.25, 1.0, 4.0),
                  effort_price=0.1, feasibility_tolerance=1e-9, gap_tolerance=1e-9):
    """Freeze zero plus every model/budget/soft-hard candidate before execution."""
    horizon, p, dt = reference.horizon, reference.state.parameter_count, reference.dt
    if (horizon != 8 or tuple(budgets) != (0.25, 1.0, 4.0)
            or not isinstance(models, dict) or not 1 <= len(models) <= 8
            or not np.isfinite(old_anchor)):
        raise ValueError("registered H8, three budgets and finite original threshold required")
    for name, model in models.items():
        if (not isinstance(name, str) or not name or len(name) > 64
                or np.shape(model.get("loss_maps")) != (9, 2, p)
                or not np.isfinite(model["loss_maps"]).all()
                or not np.array_equal(model.get("reference_observations", reference.observations[:, :2]),
                                      reference.observations[:, :2])):
            raise ValueError("all models must use identical reference losses and action coordinates")
    models = {name: {**model, "reference_observations": reference.observations[:, :2]}
              for name, model in models.items()}
    before, candidates = reference.state.digest(), []
    declarations = [("zero", None, "zero")]
    declarations += [(name, budget, objective) for name in models for budget in budgets
                     for objective in ("direct_soft", "direct_hard")]
    for name, budget, objective in declarations:
        record = {"candidate_id": "zero" if name == "zero" else f"{name}:b{budget:g}:{objective}",
                  "model": name, "budget_multiplier": budget, "objective": objective,
                  "registered_candidates": len(declarations),
                  "initial_state_sha256": before, "old_anchor": float(old_anchor),
                  "horizon": horizon, "dt": dt, "effort_price": effort_price,
                  "feasibility_tolerance": feasibility_tolerance, "gap_tolerance": gap_tolerance,
                  "status": "unresolved", "inherited_old_excess": float(reference.observations[0, 1] - old_anchor)}
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        arrays, actions = {}, None
        try:
            if name == "zero":
                actions = np.zeros((horizon, p))
                record.update(status="planned", solver_status="fixed_zero", optimality_claim=False)
            else:
                result = plan_action(models[name], objective=objective, lookahead=horizon,
                                     old_anchor=old_anchor, dt=dt, effort_price=effort_price,
                                     action_bound=budget, feasibility_tolerance=feasibility_tolerance,
                                     gap_tolerance=gap_tolerance)
                record.update(solver_status=result["status"], solver_record=result["record"])
                arrays = {k: v.copy() for k, v in result.items() if isinstance(v, np.ndarray)}
                arrays.update({"problem__" + k: np.asarray(v) for k, v in result["problem"].items()})
                if result["status"] == "qualified":
                    actions = result["actions"].copy()
                    if (actions.shape != (horizon, p) or not np.isfinite(actions).all()
                            or np.any(actions[1:] != 0)
                            or np.any(np.abs(actions[0]) > budget / np.sqrt(p))):
                        raise ValueError("qualified action violates the frozen impulse box")
                    record["status"] = "planned"
                elif result["status"] == "tangent_infeasible_with_box_witness":
                    record["status"] = "tangent_infeasible"
            if actions is not None:
                record["actions_sha256"] = hashlib.sha256(actions.tobytes()).hexdigest()
                record["predicted_scores"] = {}
                for critic, model in models.items():
                    fields = np.einsum("kij,j->ki", model["loss_maps"], actions[0])
                    arrays["predicted_" + critic + "_fields"] = fields
                    record["predicted_scores"][critic] = score_common(fields, actions,
                        reference.observations[:, :2], old_anchor, dt=dt,
                        effort_price=effort_price, feasibility_tolerance=feasibility_tolerance)
        except Exception as error:
            actions = None
            record.update(status="unresolved", error={"type": type(error).__name__, "message": str(error)})
        record.update(planning_wall_ns=time.perf_counter_ns() - began,
                      planning_cpu_ns=time.process_time_ns() - cpu)
        candidates.append({"record": record, "arrays": arrays, "actions": actions})
    if reference.state.digest() != before:
        raise RuntimeError("planning mutated the common checkpoint")
    return candidates


def execute_pressure(state, reference, candidates, old_anchor):
    """Execute all frozen plans once; preserve failed and infeasible slots unchanged.

    Returned terminal states support later label-free prediction sealing. Costs
    and retention below concern only the supplied development probes.
    """
    before, p, horizon = state.digest(), state.parameter_count, reference.horizon
    if before != reference.state.digest() or horizon != 8:
        raise ValueError("exact common H8 checkpoint required")
    if (not candidates or len({row["record"]["candidate_id"] for row in candidates}) != len(candidates)
            or any(row["record"]["registered_candidates"] != len(candidates) for row in candidates)
            or sum(row["record"]["model"] == "zero" for row in candidates) != 1):
        raise ValueError("complete frozen candidate census required")
    results = []
    for candidate in candidates:
        record = dict(candidate["record"])
        row = {"record": record, "arrays": {}, "state": None, "receipts": []}
        results.append(row)
        if record["status"] != "planned":
            record["execution_status"] = "not_executed_" + record["status"]
            continue
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        current, vectors, observations = state.clone(), [], []
        try:
            actions = np.asarray(candidate["actions"], dtype=np.float64)
            if (record["initial_state_sha256"] != before or record["old_anchor"] != old_anchor
                    or record["horizon"] != horizon or record["dt"] != reference.dt
                    or actions.shape != (horizon, p) or not np.isfinite(actions).all()
                    or np.any(actions[1:] != 0)
                    or hashlib.sha256(actions.tobytes()).hexdigest() != record["actions_sha256"]
                    or (record["model"] == "zero" and np.any(actions != 0))
                    or (record["model"] != "zero" and
                        np.any(np.abs(actions[0]) > record["budget_multiplier"] / np.sqrt(p)))):
                raise ValueError("frozen candidate identity or action budget changed")
            for k in range(horizon + 1):
                vectors.append(current.vector())
                observations.append(reference.observe(current.vector())[0][:2])
                if k < horizon:
                    row["receipts"].append(current.advance(reference.train_features, reference.train_labels,
                        intervention=reference.dt * actions[k]))
            observations = np.asarray(observations)
            fields = observations - reference.observations[:, :2]
            score = score_common(fields, actions, reference.observations[:, :2], old_anchor,
                dt=reference.dt, effort_price=record["effort_price"],
                feasibility_tolerance=record["feasibility_tolerance"])
            row.update(state=current, arrays={"states": np.asarray(vectors), "observations": observations,
                                              "fields": fields, "actions": actions.copy()})
            predicted = record["predicted_scores"].get(record["model"])
            record.update(execution_status="completed", actual_scores=score,
                terminal_state_sha256=current.digest(), physical_impulse_norm=float(np.linalg.norm(reference.dt * actions[0])),
                predicted_feasible_actual_violation=bool(predicted is not None and
                    predicted["future_retention_within_tolerance"] and not score["future_retention_within_tolerance"]))
        except Exception as error:
            row["arrays"] = {"partial_states": np.asarray(vectors), "partial_observations": np.asarray(observations)}
            record.update(execution_status="execution_failed", error={"type": type(error).__name__, "message": str(error)})
        record.update(execution_wall_ns=time.perf_counter_ns() - began,
                      execution_cpu_ns=time.process_time_ns() - cpu)
    if state.digest() != before:
        raise RuntimeError("pressure execution mutated the shared initial state")
    return results
