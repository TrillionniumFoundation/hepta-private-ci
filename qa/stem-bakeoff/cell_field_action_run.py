"""Freeze every common-state candidate, then execute identical one-action branches."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

import numpy as np

from cell_field_action_control import build_action_model, plan_action, score_common
from cell_field_action_io import (deny_withheld_labels, environment, load_inputs, project,
                                  save_arrays, source_hashes, split_arrays, write_json)
from cell_field_control import build_reference
from cell_field_features import file_hash
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def methods(plan):
    yield {"method_id": "zero", "observation": "zero", "lookahead": 0, "objective": "zero"}
    for objective in plan["objectives"]:
        for observation in plan["observations"]:
            for horizon in plan["lookaheads"]:
                yield {"method_id": f"{observation}_h{horizon}_{objective}",
                       "observation": observation, "lookahead": horizon, "objective": objective}


def planner_options(plan, method, old_anchor):
    return {"objective": method["objective"], "lookahead": method["lookahead"],
            "old_anchor": old_anchor, "dt": plan["h"], "effort_price": plan["effort_price"],
            "action_bound": plan["action_bound"], "current_shift": plan["current_shift"],
            "direct_coefficient": plan["direct_coefficient"],
            "feasibility_tolerance": plan["feasibility_tolerance"],
            "gap_tolerance": plan["solver"]["gap_tolerance"],
            "max_iterations": plan["solver"]["max_iterations"], "ftol": plan["solver"]["ftol"]}


def common_score(plan, fields, actions, reference, old_anchor):
    return score_common(fields, actions, reference.observations[:, :2], old_anchor,
                        dt=plan["h"], effort_price=plan["effort_price"],
                        current_shift=plan["current_shift"], direct_coefficient=plan["direct_coefficient"],
                        feasibility_tolerance=plan["feasibility_tolerance"])


def branch(state, reference, actions, projected, retention_indices):
    """Apply an already frozen action sequence; do not choose from branch outcomes."""
    actions = np.asarray(actions, dtype=np.float64)
    horizon, p = reference.horizon, state.parameter_count
    if (state.digest() != reference.state.digest() or actions.shape != (horizon, p)
            or not np.isfinite(actions).all() or np.any(actions[1:] != 0)):
        raise ValueError("exact common checkpoint and one first intervention required")
    current, initial_digest = state.clone(), state.digest()
    states, observations, retained, receipts = [], [], [], []
    midpoint = None
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    for k in range(horizon + 1):
        states.append(current.vector())
        observations.append(reference.observe(current.vector())[0])
        probabilities = current.head.predict_proba(projected)
        retained.append(probabilities[retention_indices])
        if k == horizon // 2:
            midpoint = current.clone()
        if k < horizon:
            receipts.append(current.advance(reference.train_features, reference.train_labels,
                            intervention=reference.dt * actions[k], mask=np.ones(p, dtype=bool)))
    if state.digest() != initial_digest:
        raise ValueError("a counterfactual branch mutated its common checkpoint")
    observations = np.asarray(observations)
    return {"state": current, "midpoint_state": midpoint, "states": np.asarray(states),
            "observations": observations, "fields": observations[:, :2] - reference.observations[:, :2],
            "actions": actions.copy(), "retention_probabilities": np.asarray(retained),
            "terminal_probabilities": probabilities, "receipts": receipts,
            "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu}


def _failure(output, name, error):
    detail = {"type": type(error).__name__, "message": str(error)}
    write_json(output / f"failures/{name}.json", {"error": detail, "traceback": traceback.format_exc()})
    return detail


def _candidate(output, initial, method, state, reference, models, plan):
    run_id = initial["initial_id"] + "-" + method["method_id"]
    record = {**method, "run_id": run_id, "seed": initial["seed"], "head": initial["head"],
              "anchor_offset": initial["anchor_offset"], "initial_index": initial["initial_index"],
              "warmup_index": initial["warmup_index"], "status": "solver_failure",
              "old_probe_anchor": initial.get("old_probe_anchor"), "paths": {}}
    if state is None:
        return {**record, "status": "initial_failure", "error": initial.get("error")}, None
    paths = {"candidate": f"candidates/{run_id}.npz", "candidate_record": f"candidates/{run_id}.json",
             "reference": initial["reference_path"],
             "model": initial["model_paths"]["loss2" if method["observation"] == "zero" else method["observation"]],
             "trajectory": f"trajectories/{run_id}.npz", "receipts": f"receipts/{run_id}.json",
             "checkpoint": f"checkpoints/{run_id}", "head": f"heads/{run_id}"}
    record["paths"] = paths
    try:
        before = state.digest()
        if method["method_id"] == "zero":
            p = state.parameter_count
            result = {"status": "qualified", "u": np.zeros(p),
                      "actions": np.zeros((plan["evaluation_horizon"], p)),
                      "fields": np.zeros((plan["evaluation_horizon"] + 1, 2)),
                      "problem": {}, "record": {"status": "fixed_zero", "optimality_claim": False}}
        else:
            record["planner_options"] = planner_options(plan, method, initial["old_probe_anchor"])
            result = plan_action(models[method["observation"]], **record["planner_options"])
        arrays = {key: value for key, value in result.items() if isinstance(value, np.ndarray)}
        arrays.update({"problem__" + key: np.asarray(value) for key, value in result["problem"].items()})
        if result["status"] == "qualified":
            bound = plan["action_bound"] / np.sqrt(state.parameter_count)
            if (result["u"].shape != (state.parameter_count,) or not np.isfinite(result["u"]).all()
                    or np.any(np.abs(result["u"]) > bound)
                    or result["actions"].shape != (plan["evaluation_horizon"], state.parameter_count)
                    or not np.array_equal(result["actions"][0], result["u"])
                    or np.any(result["actions"][1:] != 0)):
                raise ValueError("qualified candidate violates exact common action budget")
            record["predicted_scores"] = {}
            for observation, model in models.items():
                fields = np.einsum("kij,j->ki", model["loss_maps"], result["u"])
                arrays[f"predicted_{observation}_fields"] = fields
                record["predicted_scores"][observation] = common_score(
                    plan, fields, result["actions"], reference, initial["old_probe_anchor"])
            record["status"] = "planned"
        elif result["status"] == "tangent_infeasible_with_box_witness":
            record["status"] = "tangent_infeasible"
        else:
            record["status"] = "solver_failure"
        if state.digest() != before:
            raise ValueError("candidate construction changed the common state")
        save_arrays(output / paths["candidate"], arrays)
        write_json(output / paths["candidate_record"], {"status": result["status"], "record": result["record"]})
        record["solver_status"], record["solver_record"] = result["status"], result["record"]
        record["initial_state_sha256"] = before
        return record, arrays if record["status"] == "planned" else None
    except Exception as error:
        record["status"] = "solver_failure"
        record["error"] = _failure(output, run_id + "-planning", error)
        return record, None


def _anchors(output, inputs, projected, split, feature_identity, hashes):
    plan, warmups, initials, runtime = inputs["plan"], [], [], []
    contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
    warm_predictions = np.full((plan["registered_warmups"], len(projected), plan["classes"]), np.nan)
    initial_predictions = np.full((plan["registered_anchors"], len(projected), plan["classes"]), np.nan)
    for seed in plan["seeds"]:
        for head_mode in plan["head_modes"]:
            wi = len(warmups)
            name = f"seed{seed}-{head_mode}"
            warm = {"seed": seed, "head": head_mode, "warmup_index": wi, "status": "initial_failure",
                    "checkpoint_path": f"warmup/{name}/checkpoint"}
            state, error = None, None
            try:
                bindings = {"protocol_sha256": inputs["protocol_sha256"], "feature_identity": feature_identity,
                            "sources_sha256": inputs["receipt"]["files"]["sources.json"]["sha256"],
                            "train_labels_sha256": inputs["receipt"]["files"]["train_labels.json"]["sha256"],
                            "task": plan["task"], "seed": seed, "head_mode": head_mode,
                            "topology": "one fixed Cell with shared frozen Encoder", "executed_code_sha256": hashes}
                state = CellTrainingState(NumpyCellHead(plan["projection"]["width"], plan["classes"],
                                          head_mode, seed=seed), bindings=bindings,
                                          protocol=plan["optimizer"], seed=seed,
                                          contexts=contexts, active_context="old_train")
                began, cpu, values, receipts = time.perf_counter_ns(), time.process_time_ns(), [state.vector()], []
                for _ in range(plan["warmup_steps"]):
                    receipts.append(state.advance(*split["old_train"]))
                    values.append(state.vector())
                state.select_context("current_train")
                state.save(output / warm["checkpoint_path"])
                warm_predictions[wi] = state.head.predict_proba(projected)
                old_x, old_y = split["old_probe"]
                old_anchor = state.head.loss_gradients(normalize_features(old_x), old_y, 0.0)[0]
                save_arrays(output / f"warmup/{name}.npz", {"states": np.asarray(values)})
                write_json(output / f"warmup/{name}-receipts.json", receipts)
                warm.update(status="completed", state_sha256=state.digest(), old_probe_anchor=old_anchor,
                            wall_ns=time.perf_counter_ns() - began, cpu_ns=time.process_time_ns() - cpu)
            except Exception as exc:
                error = _failure(output, name + "-warmup", exc)
                warm["error"], state = error, None
                warm_predictions[wi] = np.nan
            warmups.append(warm)
            current_offset, baseline_states, baseline_receipts = 0, [], []
            if state is not None:
                baseline_states.append(state.vector())
            for offset in plan["anchor_offsets"]:
                initial_id, index = f"{name}-step{offset}", len(initials)
                initial = {"initial_id": initial_id, "seed": seed, "head": head_mode,
                           "anchor_offset": offset, "initial_index": index, "warmup_index": wi,
                           "status": "initial_failure", "checkpoint_path": f"initial/{initial_id}"}
                anchor, reference, models_at_anchor = None, None, {}
                try:
                    if state is None:
                        raise ValueError("warmup or uncontrolled anchor path unavailable")
                    while current_offset < offset:
                        baseline_receipts.append(state.advance(*split["current_train"]))
                        baseline_states.append(state.vector())
                        current_offset += 1
                    anchor = state.clone()
                    anchor.save(output / initial["checkpoint_path"])
                    initial_predictions[index] = anchor.head.predict_proba(projected)
                    reference = build_reference(anchor, *split["current_train"],
                        probes=(split["current_probe"], split["old_probe"]),
                        horizon=plan["evaluation_horizon"], dt=plan["h"])
                    reference_path = f"references/{initial_id}.npz"
                    save_arrays(output / reference_path, reference.arrays())
                    model_paths = {}
                    for observation in plan["observations"]:
                        model = build_action_model(reference, observation=observation)
                        model_paths[observation] = f"models/{initial_id}-{observation}.npz"
                        save_arrays(output / model_paths[observation], model)
                        models_at_anchor[observation] = model
                    initial.update(status="completed", state_sha256=anchor.digest(), old_probe_anchor=old_anchor,
                                   reference_path=reference_path, model_paths=model_paths,
                                   reference_build_wall_ns=reference.build_wall_ns,
                                   derivative_audit=reference.derivative_audit,
                                   parameter_count=anchor.parameter_count, numeric_state_dimension=len(anchor.vector()))
                except Exception as exc:
                    initial["error"] = error or _failure(output, initial_id + "-reference", exc)
                    anchor, reference, models_at_anchor = None, None, {}
                    initial_predictions[index] = np.nan
                initials.append(initial)
                runtime.append((anchor, reference, models_at_anchor))
            if baseline_states:
                save_arrays(output / f"baseline/{name}.npz", {"states": np.asarray(baseline_states)})
                write_json(output / f"baseline/{name}-receipts.json", baseline_receipts)
    return warmups, initials, runtime, warm_predictions, initial_predictions


def execute(data, features, protocol, output):
    sys.addaudithook(deny_withheld_labels)
    started, began, cpu = datetime.now(timezone.utc).isoformat(), time.perf_counter_ns(), time.process_time_ns()
    output, protocol, hashes = Path(output), Path(protocol), source_hashes()
    inputs = load_inputs(data, features, protocol)
    plan, sources = inputs["plan"], inputs["sources"]
    output.mkdir(parents=True, exist_ok=False)
    projected, projection = project(inputs["features"], plan)
    split = split_arrays(projected, inputs["labels"])
    save_arrays(output / "projected_features.npz", {"features": projected, "projection": projection})
    save_arrays(output / "train_inputs.npz", {role + "_" + suffix: value for role, pair in split.items()
                                             for suffix, value in zip(("x", "y"), pair)})
    projection_identity = {"method": plan["projection"],
        "matrix_sha256": hashlib.sha256(projection.tobytes()).hexdigest(),
        "projected_tensor_sha256": hashlib.sha256(projected.tobytes()).hexdigest(),
        "input_feature_sha256": inputs["feature_report"]["tensor_sha256"]}
    feature_identity = {"shared_feature_identity": inputs["feature_report"]["feature_identity"],
                        "encoder_identity": inputs["feature_report"]["encoder_identity"],
                        "projection": projection_identity}
    for name in hashes:
        (output / "source").mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).parent / name, output / "source" / name)
    (output / "inputs").mkdir(exist_ok=True)
    for name in ("data_receipt.json", "sources.json", "train_labels.json", "predictors.json"):
        shutil.copyfile(Path(data) / name, output / "inputs" / name)
    shutil.copyfile(protocol, output / "inputs/protocol.json")
    shutil.copyfile(Path(features) / "report.json", output / "inputs/feature-report.json")
    warmups, initials, runtime, warm_probs, initial_probs = _anchors(
        output, inputs, projected, split, feature_identity, hashes)
    count, horizon = plan["registered_conditions"], plan["evaluation_horizon"]
    retention_indices = np.array([i for i, row in enumerate(sources)
                                  if row["role"] in ("old_validation", "old_test")], dtype=np.int64)
    terminal = np.full((count, len(projected), plan["classes"]), np.nan)
    retention = np.full((count, horizon + 1, len(retention_indices), plan["classes"]), np.nan)
    records, candidates = [], []
    for initial, (state, reference, models_at_anchor) in zip(initials, runtime):
        for method in methods(plan):
            record, candidate = _candidate(output, initial, method, state, reference, models_at_anchor, plan)
            records.append(record)
            candidates.append(candidate)
        write_json(output / "planning_progress.json", {"registered_so_far": len(records), "records": records})
        print(json.dumps({"phase": "planning", "anchor": initial["initial_id"], "count": len(records)}), flush=True)
    if len(records) != count or len(initials) != plan["registered_anchors"]:
        raise ValueError("frozen candidate census is incomplete")
    write_json(output / "candidate_index.json", {"records": records, "initial_order": initials,
                                                "warmup_order": warmups, "protocol_sha256": inputs["protocol_sha256"]})
    inventory = {p.relative_to(output).as_posix(): {"bytes": p.stat().st_size, "sha256": file_hash(p)}
                 for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "candidate_freeze.json", {"schema": "hepta.cell-action-candidate-freeze.v3",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "files": inventory,
        "record_count": count, "candidate_branches_executed": 0,
        "protocol_sha256": inputs["protocol_sha256"], "sourcecode_hashes": hashes,
        "validation_labels_opened": False, "final_labels_opened": False})
    for row, (record, candidate) in enumerate(zip(records, candidates)):
        if record["status"] != "planned":
            continue
        initial = initials[record["initial_index"]]
        state, reference, _ = runtime[record["initial_index"]]
        try:
            rollout = branch(state, reference, candidate["actions"], projected, retention_indices)
            arrays = {key: rollout[key] for key in ("states", "actions", "observations", "fields")}
            arrays.update({"predicted_" + obs + "_fields": candidate["predicted_" + obs + "_fields"]
                           for obs in plan["observations"]})
            save_arrays(output / record["paths"]["trajectory"], arrays)
            write_json(output / record["paths"]["receipts"], rollout["receipts"])
            rollout["state"].save(output / record["paths"]["checkpoint"])
            rollout["state"].head.save(output / record["paths"]["head"], feature_identity)
            reloaded = NumpyCellHead.load(output / record["paths"]["head"], feature_identity)
            if not np.array_equal(reloaded.predict_proba(projected), rollout["terminal_probabilities"]):
                raise ValueError("existing serving Head roundtrip differs")
            if (record["method_id"] == plan["replay"]["method_id"]
                    and record["anchor_offset"] == plan["replay"]["anchor_offset"]):
                record["paths"]["midpoint"] = f"midpoints/{record['run_id']}"
                rollout["midpoint_state"].save(output / record["paths"]["midpoint"])
            terminal[row], retention[row] = rollout["terminal_probabilities"], rollout["retention_probabilities"]
            record.update(status="completed", actual_scores=common_score(plan, rollout["fields"],
                          candidate["actions"], reference, initial["old_probe_anchor"]),
                          final_state_sha256=rollout["state"].digest(), serving_roundtrip_equal=True,
                          wall_ns=rollout["wall_ns"], cpu_ns=rollout["cpu_ns"],
                          physical_intervention_squared_norm=float(np.square(plan["h"] * candidate["actions"]).sum()))
        except Exception as error:
            record.update(status="execution_failure", error=_failure(output, record["run_id"] + "-execution", error))
            terminal[row], retention[row] = np.nan, np.nan
        if (row + 1) % plan["registered_candidates_per_anchor"] == 0:
            print(json.dumps({"phase": "execution", "records_seen": row + 1}), flush=True)
    write_json(output / "execution_result_before_replay.json", {"records": records,
               "record_count": len(records), "validation_labels_opened": False, "final_labels_opened": False})
    from cell_field_action_replay import verify_action_replays
    replays = []
    for record in records:
        if (record["method_id"] == plan["replay"]["method_id"]
                and record["anchor_offset"] == plan["replay"]["anchor_offset"]):
            if record["status"] == "completed":
                try:
                    replays.extend(verify_action_replays(output, record, initials[record["initial_index"]],
                                   plan, hashes, Path(__file__).parent))
                except Exception as error:
                    replays.append({"run_id": record["run_id"], "status": "failed",
                                    "error": _failure(output, record["run_id"] + "-replay", error)})
            else:
                replays.append({"run_id": record["run_id"], "status": "unavailable", "reason": record["status"]})
    if source_hashes() != hashes or file_hash(protocol) != inputs["protocol_sha256"]:
        raise ValueError("source or protocol changed during formal execution")
    if {key: file_hash(path) for key, path in inputs["input_paths"].items()} != inputs["input_hashes"]:
        raise ValueError("training inputs changed during formal execution")
    for name, identity in inventory.items():
        if file_hash(output / name) != identity["sha256"]:
            raise ValueError("a frozen candidate input changed: " + name)
    save_arrays(output / "predictions.npz", {"terminal_probabilities": terminal,
                "retention_probabilities": retention, "warmup_probabilities": warm_probs,
                "initial_probabilities": initial_probs})
    census = dict(Counter(record["status"] for record in records))
    report = {"schema": "hepta.cell-action-runs.v3", "protocol": plan,
        "protocol_sha256": inputs["protocol_sha256"], "data_receipt_sha256": file_hash(Path(data) / "data_receipt.json"),
        "feature_report_sha256": file_hash(Path(features) / "report.json"),
        "source_ids": [r["source_id"] for r in sources], "row_roles": [r["role"] for r in sources],
        "retention_indices": retention_indices.tolist(), "initial_order": initials, "warmup_order": warmups,
        "records": records, "replays": replays, "record_count": len(records), "status_census": census,
        "completed": census.get("completed", 0), "not_completed": len(records) - census.get("completed", 0),
        "unexecuted": sum(census.get(key, 0) for key in
             ("initial_failure", "solver_failure", "tangent_infeasible")),
        "attempted_branches": census.get("completed", 0) + census.get("execution_failure", 0),
        "numerical_or_execution_failures": sum(census.get(key, 0) for key in
             ("initial_failure", "solver_failure", "execution_failure")),
        "candidate_freeze_sha256": file_hash(output / "candidate_freeze.json"), "sourcecode_hashes": hashes,
        "input_hashes": inputs["input_hashes"], "feature_identity": feature_identity,
        "projection_identity": projection_identity, "feature_report": inputs["feature_report"],
        "environment": environment(), "execution": {"started_at_utc": started,
        "wall_ns": time.perf_counter_ns() - began, "parent_cpu_ns": time.process_time_ns() - cpu,
        "recovery_child_cpu_measured": False}, "validation_labels_opened": False,
        "final_labels_opened": False, "authority": "DENY_ALL", "production_authority": False}
    write_json(output / "runs.json", report)
    inventory = {p.relative_to(output).as_posix(): {"bytes": p.stat().st_size, "sha256": file_hash(p)}
                 for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "pre_evaluation_seal.json", {"schema": "hepta.cell-action-pre-evaluation-seal.v3",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(), "files": inventory,
        "protocol_sha256": inputs["protocol_sha256"], "sourcecode_hashes": hashes,
        "record_count": len(records), "data_receipt_sha256": report["data_receipt_sha256"],
        "validation_labels_opened": False, "final_labels_opened": False, "authority": "DENY_ALL"})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "features", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    result = execute(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("record_count", "status_census", "protocol_sha256")}))
