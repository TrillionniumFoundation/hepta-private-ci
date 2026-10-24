"""Prepare source-disjoint calibrated heads without receiving heldout labels.

Evaluation is a separate module and output directory. The immutable preparation
seal covers every artifact, every selected model, and all calibration choices.
"""

import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np

from cell_calibration_v2 import (calibration_partition, fit_calibrator, group_weights,
    prior_corrected_logits, smoothed_prior, weighted_nll)
from cell_learning_baselines import FrozenBaselines, normalized_text
from cell_learning_curve import training_order
from cell_learning_models import canonical
from cell_regularized_training import fit_path


DEFAULT_PROTOCOL = {"budgets": [8, 32, 128], "seeds": [7, 17, 29],
    "l2_grid": [0.1, 1.0], "checkpoints": [10, 40, 100], "rank": 4,
    "max_parameters": 100000, "learning_rate": 0.02, "early_stop_min_delta": 0.0001,
    "calibration_partition_seed": 20261024, "threshold": 0.7,
    "selected_arm_order": ["prior_only", "prototype", "linear", "gated", "residual"],
    "selection_metric": "group_weighted_prior_corrected_tuning_nll",
    "operating_rule": "accept eligible rows when maximum calibrated probability >=0.7",
    "search_cost_policy": "charge every attempted path and discarded update; never call equal steps equal cost",
    "legacy_holdout_policy": "repeated-use diagnostic only; no confirmatory winner qualification"}
CODE_FILES = ("cell_calibration_v2.py", "cell_regularized_training.py", "cell_calibrated_curve.py",
    "cell_calibrated_evaluate.py", "cell_learning_models.py", "cell_learning_baselines.py",
    "cell_learning_metrics.py", "cell_learning_curve.py", "run_calibrated_cells.py",
    "CELL_CALIBRATED_PROTOCOL.md")


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes():
    return {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("sealed artifacts cannot use symbolic links")
        if path.is_file() and path != Path(root)/"seal.json":
            result[str(path.relative_to(root))] = {"bytes": path.stat().st_size, "sha256": sha_file(path)}
    return result


def verify_prepared(root):
    root = Path(root)
    seal = json.loads((root/"seal.json").read_bytes())
    if seal != {"schema": "hepta.calibrated-preparation-seal.v1", "files": inventory(root)}:
        raise ValueError("prepared artifact inventory changed")
    frozen = json.loads((root/"frozen.json").read_bytes())
    if frozen["plan"]["code_sha256"] != code_hashes():
        raise ValueError("prepared numerical implementation changed")
    return frozen


def context_receipt(cohort, input_modality="text", input_content_sha256=None):
    if input_modality not in ("text", "image", "audio"):
        raise ValueError("explicit supported predictor modality required")
    if input_modality != "text":
        if not isinstance(input_content_sha256, dict) or any(
                type(input_content_sha256.get(row["source_id"])) is not str
                or len(input_content_sha256[row["source_id"]]) != 64
                or any(c not in "0123456789abcdef" for c in input_content_sha256[row["source_id"]])
                for row in cohort.rows):
            raise ValueError("media cohorts require one full input content SHA256 per source")
    return {"source_ids": sorted(r["source_id"] for r in cohort.rows),
            "groups": sorted({r["group_id"] for r in cohort.rows}),
            "predictor_identity_sha256": sorted({
                hashlib.sha256(normalized_text(r["text"]).encode()).hexdigest() if input_modality == "text"
                else input_content_sha256[r["source_id"]] for r in cohort.rows})}


def validate_preparation(train, calibration, input_modality="text", input_content_sha256=None):
    if (train.split != "train" or calibration.split != "calibration"
            or train.features.shape[1] != calibration.features.shape[1]):
        raise ValueError("matching train/calibration cohorts required")
    contexts = [context_receipt(c, input_modality, input_content_sha256) for c in (train, calibration)]
    for c in (train, calibration):
        if np.any((c.labels < 0) | (c.labels > 1)) or len({r["source_id"] for r in c.rows}) != len(c.rows):
            raise ValueError("binary labels and unique event IDs required")
    if any(set(contexts[0][key]) & set(contexts[1][key]) for key in contexts[0]):
        raise ValueError("train/calibration source, group or normalized text overlap")
    return contexts


def bounded_protocol(overrides):
    protocol = json.loads(canonical(DEFAULT_PROTOCOL))
    if overrides is not None:
        allowed = {"budgets", "seeds", "l2_grid", "checkpoints", "rank", "max_parameters"}
        if not set(overrides).issubset(allowed):
            raise ValueError("unregistered protocol override")
        protocol.update(overrides)
    for key, lower, upper in (("budgets", 2, 128), ("seeds", 0, 2**32-1), ("checkpoints", 1, 100)):
        values = protocol[key]
        if (not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 3
                or len(set(values)) != len(values)
                or any(type(v) is not int or not lower <= v <= upper for v in values)):
            raise ValueError("invalid bounded protocol sequence")
    if (any(v % 2 for v in protocol["budgets"])
            or sorted(protocol["checkpoints"]) != list(protocol["checkpoints"])
            or not isinstance(protocol["l2_grid"], (list, tuple)) or not 1 <= len(protocol["l2_grid"]) <= 2
            or any(type(x) not in (int, float) or not np.isfinite(x) or not 0 < x <= 1 for x in protocol["l2_grid"])
            or len(set(protocol["l2_grid"])) != len(protocol["l2_grid"])
            or type(protocol["rank"]) is not int or not 1 <= protocol["rank"] <= 4
            or type(protocol["max_parameters"]) is not int or not 8 <= protocol["max_parameters"] <= 100000):
        raise ValueError("invalid finite search grid or parameter ceiling")
    return protocol


def _calibrate(logits, labels, weights):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    fitted = fit_calibrator(logits, labels, weights)
    if not fitted["converged"]:
        raise ValueError("calibration optimizer did not converge; no heldout scoring permitted")
    fitted["wall_ns"], fitted["cpu_ns"] = time.perf_counter_ns()-start, time.process_time_ns()-cpu
    return fitted


def prepare_curve(train, calibration, *, feature_identity, output_dir, task_id,
                  family_id="unspecified", protocol=None, input_modality="text", input_content_sha256=None):
    """Fit and freeze all choices. There is deliberately no holdout argument."""
    contexts = validate_preparation(train, calibration, input_modality, input_content_sha256)
    configuration = bounded_protocol(protocol)
    if any(type(v) is not str or not 1 <= len(v.encode()) <= 512 for v in (task_id, family_id)):
        raise ValueError("bounded task and family identifiers required")
    if not feature_identity or len(canonical(feature_identity)) > 65536:
        raise ValueError("bounded feature identity required")
    media_identity = input_content_sha256 if input_modality != "text" else None
    tune_ids, cal_ids = calibration_partition(calibration.rows, configuration["calibration_partition_seed"], media_identity)
    tx, ty = calibration.features[tune_ids], calibration.labels[tune_ids]
    cx, cy = calibration.features[cal_ids], calibration.labels[cal_ids]
    tune_rows, cal_rows = [calibration.rows[i] for i in tune_ids], [calibration.rows[i] for i in cal_ids]
    tw, cw = group_weights(tune_rows), group_weights(cal_rows)
    tune_prior, cal_prior = smoothed_prior(ty, tw), smoothed_prior(cy, cw)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.calibrated-curve.v2", "task_id": task_id, "family_id": family_id,
        "feature_identity": feature_identity, "width": train.features.shape[1], "classes": 2,
        "input_modality": input_modality,
        "input_content_sha256": ({r["source_id"]: media_identity[r["source_id"]]
            for cohort in (train, calibration) for r in cohort.rows} if media_identity else None),
        "source_byte_authenticity_verified_by_head_runner": False,
        "configuration": configuration, "code_sha256": code_hashes(),
        "cohorts": {"train": train.digest(), "calibration": calibration.digest()},
        "contexts": contexts, "tuning_source_ids": [r["source_id"] for r in tune_rows],
        "calibration_source_ids": [r["source_id"] for r in cal_rows],
        "tuning_groups": len({r["group_id"] for r in tune_rows}),
        "calibration_groups": len({r["group_id"] for r in cal_rows}),
        "tuning_class_support": np.bincount(ty, minlength=2).tolist(),
        "calibration_class_support": np.bincount(cy, minlength=2).tolist(),
        "calibration_group_weighting": "each group mass1, each row mass1/rows_in_group",
        "tuning_prior": tune_prior.tolist(), "calibration_prior": cal_prior.tolist(),
        "holdout_supplied_to_preparation": False, "quality_qualified": False}
    write_json(root/"plan.json", plan)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    runs, unavailable = [], []
    for seed in configuration["seeds"]:
        sampling = (SimpleNamespace(labels=train.labels, rows=tuple(dict(r, text="sha256:"+media_identity[r["source_id"]])
                    for r in train.rows)) if media_identity else train)
        order = training_order(sampling, 2, seed)
        for budget in configuration["budgets"]:
            indices = order[:budget]
            counts = np.bincount(train.labels[indices], minlength=2)
            if len(indices) != budget or np.any(counts != budget//2):
                unavailable.append({"seed": seed, "budget": budget, "selected_unique_groups": len(indices),
                    "class_counts": counts.tolist(), "reason": "fixed sampler cannot supply balanced independent groups; no upsampling"})
                continue
            name = f"seed-{seed}_n-{budget}"
            location = root/name
            location.mkdir()
            x, y = train.features[indices], train.labels[indices]
            rows = [train.rows[i] for i in indices]
            with (location/"baseline.npz").open("xb") as stream:
                np.savez_compressed(stream, features=x, labels=y)
            write_json(location/"baseline_rows.json", rows)
            baseline = FrozenBaselines(x, y, rows, 2)
            arms = {"prior_only": {"kind": "prior", "prior": cal_prior.tolist(),
                "selection_score": weighted_nll(np.tile(np.log(tune_prior), (len(ty), 1)), ty, tw),
                "trainable_parameters": 0, "fitted_degrees_of_freedom": 1,
                "learning_evidence_claimed": False}}
            for arm in ("exact", "bm25", "dense_nearest", "prototype"):
                tuning = baseline.predict(arm, tx, tune_rows)
                cal = baseline.predict(arm, cx, cal_rows)
                fit = _calibrate(cal["logits"], cy, cw)
                arms[arm] = {"kind": "baseline", "calibration": fit,
                    "modality_appropriate": input_modality == "text" or arm not in ("exact", "bm25"),
                    "predictor_scope": "neutral text metadata only" if input_modality != "text" and arm in ("exact", "bm25") else "declared source input",
                    "selection_score": weighted_nll(prior_corrected_logits(tuning["logits"], [.5, .5], tune_prior), ty, tw),
                    "tuning_eligible": int(tuning["eligible"].sum()),
                    "calibration_eligible": int(cal["eligible"].sum()),
                    "tuning_prediction_cost": tuning["cost"], "calibration_prediction_cost": cal["cost"],
                    "trainable_parameters": 0, "fitted_prototype_scalars": 2*x.shape[1] if arm == "prototype" else 0}
            paths = []
            for mode in ("linear", "gated", "residual"):
                choices = []
                for l2 in configuration["l2_grid"]:
                    head, report = fit_path(x, y, tx, ty, tw, mode=mode, seed=seed, l2=l2,
                        checkpoints=configuration["checkpoints"], rank=configuration["rank"],
                        max_parameters=configuration["max_parameters"], learning_rate=configuration["learning_rate"],
                        min_delta=configuration["early_stop_min_delta"])
                    paths.append({"mode": mode, **report})
                    choices.append((report["selection_score"], l2, head, report))
                _, chosen_l2, head, report = min(choices, key=lambda v: (v[0], -v[1]))
                fit = _calibrate(head.predict_logits(cx), cy, cw)
                head.save(location/mode, feature_identity)
                arms[mode] = {"kind": "head", "artifact": f"{name}/{mode}",
                    "calibration": fit, "selection_score": report["selection_score"], "l2": chosen_l2,
                    "training": report, "tensor_sha256": head.digest(),
                    "trainable_parameters": head.parameter_count}
            candidates = configuration["selected_arm_order"]
            selected = min(enumerate(candidates), key=lambda item: (arms[item[1]]["selection_score"], item[0]))[1]
            runs.append({"seed": seed, "budget": budget, "directory": name, "arms": arms,
                "selected_arm": selected, "selection_source": "tuning_half_only",
                "training_source_ids": [r["source_id"] for r in rows],
                "training_group_ids": [r["group_id"] for r in rows], "training_class_counts": counts.tolist(),
                "search_paths": paths, "all_search_optimizer_steps": sum(p["optimizer_steps"] for p in paths),
                "all_search_wall_ns": sum(p["wall_ns"] for p in paths),
                "all_search_cpu_ns": sum(p["cpu_ns"] for p in paths),
                "all_search_matmul_flops": sum(p["executed_dense_matmul_flops"] for p in paths),
                "baseline_fit_once_cost": baseline.fit_cost, "baseline_retained_state": baseline.memory})
    if code_hashes() != plan["code_sha256"] or train.digest() != plan["cohorts"]["train"] or calibration.digest() != plan["cohorts"]["calibration"]:
        raise ValueError("preparation inputs or code changed")
    frozen = {"plan": plan, "runs": runs, "unavailable": unavailable,
        "status": "complete" if not unavailable else "complete_with_unavailable_budgets",
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "all_choices_frozen_before_heldout_scoring": True, "authority": "DENY_ALL"}
    write_json(root/"frozen.json", frozen)
    write_json(root/"seal.json", {"schema": "hepta.calibrated-preparation-seal.v1", "files": inventory(root)})
    return frozen
