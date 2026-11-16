"""Frozen fixed-action comparisons and fail-closed pressure census on fresh tasks."""

import time

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import save_arrays, write_json
from cell_field_action_run import branch
from cell_field_experiments_v4 import prepare
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_planner_v5 import make_plan
from cell_field_pressure_v4 import search_pressure
from cell_field_response_v5 import build_response, compress_response
from cell_field_safety_v5 import verify_action
from cell_field_tradeoffs_v4 import summarize_fixed_actions


def fixed_anchor(state, split, plan, projected, retention_indices, old_anchor, output):
    output.mkdir(parents=True, exist_ok=False)
    state.save(output/"initial")
    reference, models, preparation = prepare(state, split, plan)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    analytic = build_response(state, split["current_train"],
        (split["current_probe"], split["old_probe"]), horizon=8, dt=plan["h"])
    maps = analytic.impulse_maps()
    reduced = compress_response(maps, plan["response"]["impulse_compression_relative_tolerance"])
    reconstructed = np.einsum("kir,pr->kip", reduced["coefficients"], reduced["basis"])
    if not np.array_equal(analytic.states, reference.states):
        raise RuntimeError("analytic and finite-difference references differ")
    metadata = {"analytic_cpu_ns": time.process_time_ns()-cpu,
        "analytic_wall_ns": time.perf_counter_ns()-began, "response_rank": reduced["rank"],
        "spectral_residual": reduced["spectral_residual"],
        "singular_values": reduced["singular_values"].tolist(),
        "relative_tolerance": reduced["relative_tolerance"],
        "full_map_absolute_difference": float(np.linalg.norm(maps-models["full"]["loss_maps"])),
        "full_map_relative_difference": float(np.linalg.norm(maps-models["full"]["loss_maps"])/max(np.linalg.norm(maps),1e-30)),
        "basis_and_coefficients_bytes": reduced["basis"].nbytes+reduced["coefficients"].nbytes,
        "scope": reduced["scope"]}
    models.update(analytic={"loss_maps": maps}, response_svd={"loss_maps": reconstructed})
    if list(models) != plan["models"]:
        raise ValueError("fixed model census differs from protocol")
    preparation["response_v5"] = metadata
    save_arrays(output/"reference.npz", reference.arrays())
    save_arrays(output/"response.npz", {"basis": reduced["basis"], "coefficients": reduced["coefficients"]})
    library = fixed_library(state.parameter_count)
    actions = np.asarray([u for _, u in library])
    predictions = np.asarray([np.einsum("kij,aj->aki", model["loss_maps"], actions) for model in models.values()])
    save_arrays(output/"frozen_predictions.npz", {"actions": actions, "predictions": predictions,
        "loss_maps": np.asarray([m["loss_maps"] for m in models.values()])})
    write_json(output/"frozen_plan.json", {"initial_state_sha256": state.digest(),
        "frozen_predictions_sha256": file_hash(output/"frozen_predictions.npz"),
        "models": list(models), "actions": [name for name, _ in library],
        "old_anchor": old_anchor, "preparation": preparation,
        "prediction_scope": "all seven predictions sealed before any fixed-action outcome"})
    rows, observations, states = [], [], []
    scoring = {k: plan["fixed_scoring"][k] for k in ("dt", "effort_price", "direct_coefficient", "current_shift", "feasibility_tolerance")}
    before = state.digest()
    for index, (name, u) in enumerate(library):
        sequence = np.zeros((8, state.parameter_count))
        sequence[0] = u
        record = {"action_id": name, "u": list(u), "status": "execution_failed", "scores": None}
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            actual = branch(state, reference, sequence, projected, retention_indices)
            record.update(status="completed", cpu_ns=actual["cpu_ns"], wall_ns=actual["wall_ns"],
                scores=score_common(actual["fields"], sequence, reference.observations[:, :2], old_anchor, **scoring),
                final_state_sha256=actual["state"].digest(),
                predicted_scores={model: score_common(predictions[m,index], sequence,
                    reference.observations[:, :2], old_anchor, **scoring) for m, model in enumerate(models)})
            observations.append(actual["observations"][:, :2])
            states.append(actual["states"])
        except Exception as error:
            record.update(error={"type": type(error).__name__, "message": str(error)},
                          cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began)
            observations.append(np.full((9,2), np.nan))
            states.append(np.full((9,len(state.vector())), np.nan))
        rows.append(record)
    if state.digest() != before:
        raise RuntimeError("fixed branches changed their common origin")
    save_arrays(output/"actual_trajectories.npz", {"observations": np.asarray(observations),
        "states": np.asarray(states), "real_delta": np.asarray(observations)-reference.observations[:,:2]})
    write_json(output/"branches.json", rows)
    tradeoffs = summarize_fixed_actions(rows, parameters=state.parameter_count)
    write_json(output/"tradeoffs.json", tradeoffs)
    return {"status": "completed" if tradeoffs["completed"]==49 else "incomplete", "registered":49,
            "completed": tradeoffs["completed"], "preparation": preparation, "branch_resources": tradeoffs["resources"]}


def pressure_census(warmup, split, plan, projected, retention_indices, output):
    output.mkdir(parents=True, exist_ok=False)
    development = {k:split[k] for k in ("current_train", "old_probe")}
    search = search_pressure(warmup, development, max_steps=plan["pressure"]["max_search_steps"])
    write_json(output/"search.json", search["record"])
    save_arrays(output/"search.npz", {"states":search["states"], "old_losses":search["old_losses"]})
    write_json(output/"search_receipts.json", search["receipts"])
    rows = []
    for checkpoint, state in search["checkpoints"].items():
        directory = output/checkpoint
        state.save(directory/"initial")
        old_anchor = search["record"]["old_anchor"]
        candidates = [{"id":"zero", "actions":np.zeros((8,state.parameter_count)),
                       "bound":4., "record":{"status":"qualified","method":"zero"}}]
        for method in plan["pressure"]["models"]:
            for bound in plan["pressure"]["budgets"]:
                for hard in plan["pressure"]["hard_retention"]:
                    began = time.process_time_ns()
                    try:
                        candidate = make_plan(state,split,old_anchor,method=method,horizon=8,
                            dt=plan["h"],effort_price=plan["policy_configuration"]["effort_price"],
                            action_bound=bound,old_weight=plan["policy_configuration"]["old_weight"],hard_retention=hard)
                    except Exception as error:
                        candidate = {"actions":None,"record":{"status":"unresolved",
                            "error":{"type":type(error).__name__,"message":str(error)}},
                            "cpu_ns":time.process_time_ns()-began}
                    candidates.append({"id":f"{method}:b{bound:g}:hard{int(hard)}", "actions":candidate["actions"],
                        "record":candidate["record"], "bound":bound, "cpu_ns":candidate["cpu_ns"]})
        for i,candidate in enumerate(candidates):
            if candidate["actions"] is not None:
                save_arrays(directory/f"plans/{i}.npz", {"actions":candidate["actions"]})
        write_json(directory/"frozen_plans.json", {"plans":[{k:v for k,v in c.items() if k!="actions"} for c in candidates],
            "arrays":{str(i):file_hash(directory/f"plans/{i}.npz") for i,c in enumerate(candidates) if c["actions"] is not None}})
        for i,candidate in enumerate(candidates):
            verified = verify_action(state,development,candidate["actions"],old_anchor,horizon=8,dt=plan["h"],
                action_bound=candidate["bound"],backtracking=plan["pressure"]["backtracking"],
                candidate_status=candidate["record"]["status"],commit_steps=8)
            arrays = dict(verified["arrays"])
            arrays["retention_probabilities"] = np.asarray([state.head_from_vector(v).predict_proba(projected[retention_indices]) for v in arrays["states"]])
            arrays["terminal_probabilities"] = verified["state"].head.predict_proba(projected)
            save_arrays(directory/f"verified/{i}.npz",arrays)
            row = {"checkpoint":checkpoint,"candidate_id":candidate["id"],"plan":candidate["record"],
                   "verification":verified["record"],"actual_publication":False}
            rows.append(row)
            write_json(directory/f"verified/{i}.json",row)
    write_json(output/"results.json",rows)
    return {"search":search["record"],"registered_slots":26,"instantiated_slots":len(rows),
            "certified":sum(r["verification"]["certified"] for r in rows),
            "rows":rows,"scope":"prospective exact probe certification; no owner publication"}
