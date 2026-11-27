"""Execute the registered real H8 fixed-action and retention-pressure censuses."""

import time

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import save_arrays, write_json
from cell_field_action_run import branch
from cell_field_control import build_reference
from cell_field_dynamics_v4 import build_prediction_models
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_pressure_v4 import execute_pressure, plan_pressure, search_pressure
from cell_field_tradeoffs_v4 import summarize_fixed_actions


def prepare(state, split, plan, names=None, horizon=8):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    reference = build_reference(state, *split["current_train"],
        probes=(split["current_probe"], split["old_probe"]), horizon=horizon, dt=plan["h"])
    reference_cpu, reference_wall = time.process_time_ns() - cpu, time.perf_counter_ns() - began
    models = build_prediction_models(reference, **({"names": names} if names is not None else {}))
    return reference, models, {"reference_cpu_ns": reference_cpu, "reference_wall_ns": reference_wall,
        "total_preparation_cpu_ns": time.process_time_ns() - cpu,
        "total_preparation_wall_ns": time.perf_counter_ns() - began,
        "reference_array_bytes": sum(v.nbytes for v in reference.arrays().values()),
        "models": {name: model["metadata"] for name, model in models.items()}}


def fixed_anchor(state, split, plan, projected, retention_indices, old_anchor, output):
    output.mkdir(parents=True, exist_ok=False)
    state.save(output / "initial")
    reference, models, preparation = prepare(state, split, plan)
    save_arrays(output / "reference.npz", reference.arrays())
    library = fixed_library(state.parameter_count)
    actions = np.asarray([u for _, u in library])
    predictions = np.asarray([np.einsum("kij,aj->aki", model["loss_maps"], actions)
                              for model in models.values()])
    save_arrays(output / "frozen_predictions.npz", {"actions": actions, "predictions": predictions,
        "loss_maps": np.asarray([m["loss_maps"] for m in models.values()])})
    write_json(output / "frozen_plan.json", {"initial_state_sha256": state.digest(),
        "frozen_predictions_sha256": file_hash(output / "frozen_predictions.npz"),
        "models": list(models), "actions": [name for name, _ in library],
        "old_anchor": old_anchor, "preparation": preparation,
        "prediction_scope": "one physical impulse then seven actual zero-intervention Adam steps"})
    rows, observations, states = [], [], []
    before = state.digest()
    for index, (name, u) in enumerate(library):
        sequence = np.zeros((8, state.parameter_count))
        sequence[0] = u
        record = {"action_id": name, "u": list(u), "status": "execution_failed",
                  "scores": None, "cpu_ns": None, "wall_ns": None}
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            actual = branch(state, reference, sequence, projected, retention_indices)
            record.update(status="completed", cpu_ns=actual["cpu_ns"], wall_ns=actual["wall_ns"],
                scores=score_common(actual["fields"], sequence, reference.observations[:, :2], old_anchor),
                final_state_sha256=actual["state"].digest(),
                predicted_scores={model: score_common(predictions[m, index], sequence,
                    reference.observations[:, :2], old_anchor) for m, model in enumerate(models)})
            observations.append(actual["observations"][:, :2])
            states.append(actual["states"])
        except Exception as error:
            record.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - began)
            record["error"] = {"type": type(error).__name__, "message": str(error)}
            observations.append(np.full((9, 2), np.nan))
            states.append(np.full((9, len(state.vector())), np.nan))
        rows.append(record)
    if state.digest() != before:
        raise RuntimeError("fixed branches changed the common checkpoint")
    save_arrays(output / "actual_trajectories.npz", {"observations": np.asarray(observations),
        "states": np.asarray(states), "real_delta": np.asarray(observations) - reference.observations[:, :2]})
    write_json(output / "branches.json", rows)
    tradeoffs = summarize_fixed_actions(rows, parameters=state.parameter_count)
    write_json(output / "tradeoffs.json", tradeoffs)
    return {"status": "completed" if tradeoffs["completed"] == 49 else "incomplete",
            "registered": 49, "completed": tradeoffs["completed"], "preparation": preparation,
            "branch_resources": tradeoffs["resources"], "path": str(output.name)}


def pressure_census(warmup, split, plan, projected, retention_indices, output):
    output.mkdir(parents=True, exist_ok=False)
    search = search_pressure(warmup, {key: split[key] for key in ("current_train", "old_probe")})
    write_json(output / "search.json", search["record"])
    save_arrays(output / "search.npz", {"states": search["states"], "old_losses": search["old_losses"]})
    write_json(output / "search_receipts.json", search["receipts"])
    summaries = {}
    for name, state in search["checkpoints"].items():
        directory = output / name
        directory.mkdir()
        state.save(directory / "initial")
        reference, models, preparation = prepare(state, split, plan)
        save_arrays(directory / "reference.npz", reference.arrays())
        old_anchor = search["record"]["old_anchor"]
        plans = plan_pressure(reference, models, old_anchor)
        for i, candidate in enumerate(plans):
            arrays = dict(candidate["arrays"])
            if candidate["actions"] is not None:
                arrays["actions"] = candidate["actions"]
            save_arrays(directory / f"plans/{i}.npz", arrays)
        write_json(directory / "frozen_plans.json", {"plans": [p["record"] for p in plans],
            "arrays_sha256": {str(i): file_hash(directory / f"plans/{i}.npz") for i in range(len(plans))},
            "preparation": preparation})
        results = execute_pressure(state, reference, plans, old_anchor)
        for i, result in enumerate(results):
            arrays = dict(result["arrays"])
            if result["state"] is not None:
                began, cpu = time.perf_counter_ns(), time.process_time_ns()
                arrays["terminal_probabilities"] = result["state"].head.predict_proba(projected)
                arrays["retention_probabilities"] = np.asarray([
                    state.head_from_vector(vector).predict_proba(projected[retention_indices])
                    for vector in arrays["states"]])
                result["record"].update(audit_prediction_cpu_ns=time.process_time_ns() - cpu,
                                         audit_prediction_wall_ns=time.perf_counter_ns() - began)
            save_arrays(directory / f"actual/{i}.npz", arrays)
            write_json(directory / f"receipts/{i}.json", result["receipts"])
        records = [row["record"] for row in results]
        write_json(directory / "results.json", records)
        summaries[name] = {"registered": len(records), "completed": sum(
            row["execution_status"] == "completed" for row in records), "preparation": preparation}
    return {"search": search["record"], "checkpoints": summaries}
