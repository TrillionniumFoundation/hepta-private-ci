"""Trajectory-grouped terminal heads and complete V3 controlled training paths."""

import json
from pathlib import Path
import time

import numpy as np

from .learning import guarded_block, hard_panel, make_model, new_optimizer, save_checkpoint, save_hard, state_identity
from .training_bank import commit_decision
from .training_common import MODES, Journal, configuration, file_hash, object_hash, require, write_json
from .training_features import NAMES, measure_state


def fit_head(raw, target, mode, ridge, protocol):
    p = configuration(protocol)
    require(mode in MODES and raw.shape[1] == 30 and target.shape == (len(raw), 4), "Invalid terminal head inputs")
    mean, scale = raw.mean(0), np.maximum(raw.std(0), 1e-6)
    standardized = (raw - mean) / scale
    if mode == "generic":
        projection, _ = np.linalg.qr(np.random.default_rng(p["generic_projection_seed"]).normal(size=(30, 12)))
    else:
        projection = np.eye(30)[:, :{"field": 12, "h7": 7, "richer": 30}[mode]]
    projected = standardized @ projection
    projected_mean, projected_scale = projected.mean(0), np.maximum(projected.std(0), 1e-6)
    normalized = (projected - projected_mean) / projected_scale
    design = np.column_stack((np.ones(len(raw)), normalized))
    penalty = float(ridge) * np.eye(design.shape[1])
    penalty[0, 0] = 0.
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ target)
    require(np.isfinite(coefficients).all(), "Nonfinite terminal coefficients")
    return {"schema": "hepta.field-bridge.v3.terminal-head.1", "mode": mode, "ridge": float(ridge),
            "raw_mean": mean.tolist(), "raw_scale": scale.tolist(), "projection": projection.tolist(),
            "projected_mean": projected_mean.tolist(), "projected_scale": projected_scale.tolist(),
            "coefficients": coefficients.tolist(), "dimension": projection.shape[1], "fit_rows": len(raw),
            "feature_names": list(NAMES), "target": "absolute terminal hard utility under the frozen reference continuation",
            "coefficient_count": int(coefficients.size), "prediction_clipping": False}


def predict(controller, raw):
    values = np.asarray(raw, dtype=np.float64)
    projected = ((values - controller["raw_mean"]) / controller["raw_scale"]) @ np.asarray(controller["projection"])
    projected = (projected - controller["projected_mean"]) / controller["projected_scale"]
    design = np.concatenate((np.ones((*projected.shape[:-1], 1)), projected), axis=-1)
    output = design @ np.asarray(controller["coefficients"])
    require(np.isfinite(output).all(), "Nonfinite terminal prediction")
    return output


def fit_bank(bank_path, out, protocol):
    p, out = configuration(protocol), Path(out)
    bank = json.loads(Path(bank_path).read_text())
    require(bank["training_configuration_sha256"] == object_hash(p), "Terminal bank configuration changed")
    rows = bank["records"]
    raw = np.asarray([row["state"] for row in rows], dtype=np.float64)
    target = np.asarray([row["action_values"] for row in rows], dtype=np.float64)
    groups = np.asarray([row["trajectory"] for row in rows], dtype=np.int64)
    require(raw.shape == (24, 30) and target.shape == (24, 4) and set(groups) == {0, 1, 2, 3}, "Incomplete fitting bank")
    require(all(sorted(row["step"] for row in rows if row["trajectory"] == trajectory) == list(range(0, 288, 48))
                for trajectory in range(4)), "Fitting paths do not cover all six decision times")
    candidates, controllers = {}, {}
    for mode in MODES:
        choices = []
        for ridge in p["ridges"]:
            folds, residuals = [], []
            for held_out in range(4):
                train, validation = groups != held_out, groups == held_out
                head = fit_head(raw[train], target[train], mode, ridge, protocol)
                predictions = predict(head, raw[validation])
                error = predictions - target[validation]
                residuals.extend(error.reshape(-1).tolist())
                folds.append({"held_out_trajectory": held_out, "training_trajectories": sorted(set(groups[train].tolist())),
                              "head": head, "predictions": predictions.tolist(), "mse": float(np.square(error).mean())})
            choices.append({"ridge": ridge, "cv_mse": float(np.mean(np.square(residuals))), "folds": folds,
                            "full_fit_head": fit_head(raw, target, mode, ridge, protocol)})
        selected = min(range(len(choices)), key=lambda index: (choices[index]["cv_mse"], index))
        controllers[mode] = choices[selected]["full_fit_head"]
        candidates[mode] = {"selected_index": selected, "candidates": choices}
    result = {"schema": "hepta.field-bridge.v3.fitted-terminal-controllers.1", "seed": bank["seed"],
              "bank_sha256": file_hash(bank_path), "reference_sha256": bank["reference_sha256"],
              "controllers": controllers, "all_candidates": candidates, "normalization_scope": "training fold only; full fit after alpha choice",
              "selection": "mean squared terminal error, whole-trajectory leave-one-out, listed-alpha tie order",
              "training_configuration_sha256": object_hash(p), "development_or_audit_rows_used": 0,
              "resources": {"fold_head_fits": 48, "full_fit_candidate_heads": 12, "linear_system_solves": 60,
                            "terminal_target_values_available": int(target.size), "shared_branch_bank_counted_here": 0}}
    write_json(out / "CONTROLLERS.json", result)
    write_json(out / "COMPLETE.json", {"seed": bank["seed"], "stage": "fit",
               "files": {str(path.relative_to(out)): file_hash(path) for path in sorted(out.rglob("*")) if path.is_file()},
               "resources": result["resources"]})
    return result


def rollout(context, policy, out, stage, schedule_id, endpoints):
    """One full path; all methods measure the common30 before the chosen block."""
    p, out, started = configuration(context.protocol), Path(out), time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    model = make_model(context.original, context.seed, context.protocol)
    optimizer = new_optimizer(model, context.protocol)
    before_cost, decisions = context.costs.snapshot(), []
    controller = policy.get("controller")
    controller_identity = None if controller is None else object_hash(controller)
    with Journal(out / "decisions-and-outcomes.jsonl.gz") as journal:
        for step in range(0, p["steps"], p["macro_steps"]):
            vector, current, feature_receipt = measure_state(context, model, optimizer, step, schedule_id)
            predictions = None if controller is None else predict(controller, vector).tolist()
            chosen = policy["action_index"] if controller is None else int(np.argmax(predictions))
            decision = commit_decision(journal, context, model, optimizer, stage=stage,
                trajectory=schedule_id, step=step, schedule_id=schedule_id, action_index=chosen,
                method=policy["name"], state=vector, predictions=predictions, controller_sha256=controller_identity,
                current_reward_values=current["values"]["reward"].tolist(),
                current_output_sha256=current["output_sha256"], feature_receipt=feature_receipt)
            receipt = guarded_block(context, model, optimizer, step, chosen, schedule_id)
            journal.append({"kind": "block_outcome", "decision_sha256": decision, "receipt": receipt})
            decisions.append({"step": step, "action_index": chosen, "accepted": receipt["accepted"],
                              "before": receipt["before"], "after": receipt["after"], "decision_sha256": decision})
    scores, output_records = {}, {}
    for name, panel in endpoints.items():
        scores[name] = hard_panel(model, panel, context.observers, context.action, context.protocol,
                                  context.costs, stage + "_endpoint_" + name, retain=True)
        output_records[name] = save_hard(out / (name + ".npz"), scores[name])
    metadata = {"seed": context.seed, "stage": stage, "method": policy["name"], "group": context.group,
                "schedule_id": schedule_id, "fixed_output_action": context.action,
                "controller_sha256": controller_identity, "source_roles": list(context.corpus.splits)}
    checkpoint = save_checkpoint(out / "checkpoint.pt", model, optimizer, context.protocol, metadata)
    record = {"schema": "hepta.field-bridge.v3.closed-loop-path.1", **metadata, "decisions": decisions,
              "checkpoint": checkpoint, "endpoint_files": output_records,
              "trace_sha256": file_hash(out / "decisions-and-outcomes.jsonl.gz"),
              "final_identity": state_identity(model, optimizer), "resources": context.costs.since(before_cost),
              "wall_ns": time.perf_counter_ns() - started, "final_step": p["steps"], "best_step_selection": False}
    write_json(out / "COMPLETE.json", record)
    return scores, record
