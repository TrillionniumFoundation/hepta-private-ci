"""Freeze action heads using explicit, independent train/tune/calibration roles."""

import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from cell_action_cohort import ActionBaselines, action_training_order, validate_action_roles
from cell_calibration_bounded import fit_bounded_calibrator
from cell_calibration_v2 import prior_corrected_logits, smoothed_prior, weighted_nll
from cell_group_metrics import independent_group_weights
from cell_learning_models import canonical
from cell_regularized_training import fit_path, matmul_flops


DEFAULT_PROTOCOL = {"budgets": [8, 32, 64], "seeds": [7, 17, 29],
    "unavailable_requested_budgets": [128], "maximum_gradient_budget": 64,
    "l2_grid": [.1, 1.], "checkpoints": [10, 40, 100], "rank": 4,
    "max_parameters": 100000, "learning_rate": .02, "early_stop_min_delta": .0001,
    "threshold": .7, "selected_arm_order": ["prior_only", "prototype", "linear", "gated", "residual"],
    "selection_metric": "group_weighted_prior_corrected_tuning_nll",
    "operating_rule": "accept eligible actions when maximum calibrated probability >=0.7",
    "sampling": "balanced source-hash round robin; one action per distinct bug group; no upsampling",
    "weighting": "each tuning/calibration bug contributes total weight1",
    "calibration": "bounded prior mixture, strength16, alpha in [0,1/16,1/8,1/4,1/2,1]",
    "search_cost_policy": "all paths and discarded updates charged; equal caps are not equal cost"}
CODE_FILES = ("cell_action_prepare.py", "cell_action_evaluate.py", "cell_action_inference.py", "cell_action_cohort.py",
    "cell_group_metrics.py", "cell_calibration_bounded.py", "cell_calibration_v2.py",
    "cell_regularized_training.py", "cell_learning_models.py", "cell_learning_baselines.py",
    "cell_learning_metrics.py", "cell_full_text_lexical.py", "operational_head_view.py",
    "CELL_BOUNDED_CALIBRATION.md")
BASELINES, MODES = ("exact", "bm25", "dense_nearest", "prototype"), ("linear", "gated", "residual")


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def code_hashes():
    return {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("sealed action artifacts cannot use symbolic links")
        if path.is_file() and path != Path(root)/"seal.json":
            result[str(path.relative_to(root))] = {"bytes": path.stat().st_size, "sha256": sha_file(path)}
    return result


def verify_action_prepared(root):
    root = Path(root)
    seal = json.loads((root/"seal.json").read_bytes())
    if seal != {"schema": "hepta.action-preparation-seal.v1", "files": inventory(root)}:
        raise ValueError("prepared action inventory changed")
    frozen = json.loads((root/"frozen.json").read_bytes())
    if frozen["plan"]["code_sha256"] != code_hashes():
        raise ValueError("prepared action numerical implementation changed")
    return frozen


def action_protocol(overrides=None):
    config = json.loads(canonical(DEFAULT_PROTOCOL))
    if overrides is not None:
        if not set(overrides).issubset({"budgets", "seeds", "l2_grid", "checkpoints", "rank", "max_parameters"}):
            raise ValueError("unregistered action protocol override")
        config.update(overrides)
    for key, lower, upper in (("budgets", 2, 64), ("seeds", 0, 2**32-1), ("checkpoints", 1, 100)):
        values = config[key]
        if (not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 3
                or any(type(v) is not int or not lower <= v <= upper for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("invalid finite action protocol sequence")
    if (any(n % 2 for n in config["budgets"]) or sorted(config["checkpoints"]) != list(config["checkpoints"])
            or not isinstance(config["l2_grid"], (list, tuple)) or not 1 <= len(config["l2_grid"]) <= 2
            or any(type(v) not in (float, int) or not np.isfinite(v) or not 0 < v <= 1 for v in config["l2_grid"])
            or len(set(config["l2_grid"])) != len(config["l2_grid"])
            or type(config["rank"]) is not int or not 1 <= config["rank"] <= 4
            or type(config["max_parameters"]) is not int or not 8 <= config["max_parameters"] <= 100000):
        raise ValueError("invalid action grid or common parameter ceiling")
    return config


def cohort_counts(cohort):
    weights, groups = independent_group_weights(cohort.rows)
    return {"rows": len(cohort.rows), "groups": len(groups),
        "class_support_rows": np.bincount(cohort.labels, minlength=2).tolist(),
        "group_weighted_class_mass": [float(weights[cohort.labels == label].sum()) for label in (0, 1)],
        "groups_with_class": [len({row["group_id"] for row, y in zip(cohort.rows, cohort.labels) if y == label})
                              for label in (0, 1)]}


def calibration_bindings(feature_identity, predictor_sha256, calibration_context_sha256):
    return dict(feature_identity=feature_identity, predictor_sha256=predictor_sha256,
                calibration_context_sha256=calibration_context_sha256)


def prepare_action_curve(train, tuning, calibration, *, feature_identity, output_dir,
                         task_id, family_id, input_bindings, protocol=None):
    """No holdout argument. Source-file authenticity is verified by the caller."""
    contexts = validate_action_roles(train, tuning, calibration)
    config = action_protocol(protocol)
    if any(type(v) is not str or not 1 <= len(v.encode()) <= 512 for v in (task_id, family_id)):
        raise ValueError("bounded task/family identifiers required")
    if type(feature_identity) is not str or not re.fullmatch(r"[0-9a-f]{64}", feature_identity):
        raise ValueError("exact feature identity SHA256 required")
    required = {"dataset_sha256", "feature_report_sha256", "proposal_plan_sha256"}
    if (not isinstance(input_bindings, dict) or set(input_bindings) != required
            or any(type(v) is not str or not re.fullmatch(r"[0-9a-f]{64}", v) for v in input_bindings.values())):
        raise ValueError("explicit dataset, feature-report and prospective proposal-plan pins required")
    cohorts = {c.split: c for c in (train, tuning, calibration)}
    tw, _ = independent_group_weights(tuning.rows)
    tune_prior = smoothed_prior(tuning.labels, tw)
    forbidden = sorted({r["group_id"] for c in (train, tuning) for r in c.rows})
    cal_context = calibration.digest()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    plan = {"schema": "hepta.prospective-action-preparation.v1", "task_id": task_id, "family_id": family_id,
        "feature_identity": feature_identity, "width": int(train.features.shape[1]), "classes": 2,
        "feature_dtype": "float32", "private_parameter_dtype": "float64", "configuration": config,
        "input_bindings": json.loads(canonical(input_bindings)), "code_sha256": code_hashes(),
        "cohorts": {key: c.digest() for key, c in cohorts.items()},
        "contexts": dict(zip(cohorts, contexts)), "labelled_pools": {key: cohort_counts(c) for key, c in cohorts.items()},
        "tuning_source_ids": [r["source_id"] for r in tuning.rows],
        "calibration_source_ids": [r["source_id"] for r in calibration.rows], "tuning_prior": tune_prior.tolist(),
        "label_budget_scope": "gradient budget plus whole labelled train pool for stratification, tuning and calibration pools",
        "source_byte_authenticity_verified_by_head_runner": False, "holdout_supplied_to_preparation": False,
        "unknown_outcomes_are_labels": False, "quality_qualified": False}
    write_json(root/"plan.json", plan)
    prior_fit = fit_bounded_calibrator(np.zeros(len(calibration.labels)), calibration.labels, calibration.rows,
        effective_training_prior=[.5, .5], forbidden_groups=forbidden,
        bindings=calibration_bindings(feature_identity, hashlib.sha256(b"explicit-prior-only").hexdigest(), cal_context))
    runs, unavailable = [], []
    for seed in config["seeds"]:
        order = action_training_order(train, seed)
        for budget in config["unavailable_requested_budgets"]:
            unavailable.append({"seed": seed, "budget": budget, "available_training_groups": len(contexts[0]["group_ids"]),
                "reason": "predeclared maximum gradient budget64;128 is not executed or silently replaced"})
        for budget in config["budgets"]:
            indices = order[:budget]
            counts = np.bincount(train.labels[indices], minlength=2)
            if len(indices) != budget or np.any(counts != budget//2):
                unavailable.append({"seed": seed, "budget": budget, "selected_unique_groups": len(indices),
                    "class_counts": counts.tolist(), "reason": "fixed sampler lacks balanced independent groups; no upsampling"})
                continue
            name = f"seed-{seed}_n-{budget}"
            location = root/name
            location.mkdir()
            x, y, rows = train.features[indices], train.labels[indices], [train.rows[i] for i in indices]
            with (location/"baseline.npz").open("xb") as stream:
                np.savez_compressed(stream, features=x, labels=y)
            write_json(location/"baseline_rows.json", rows)
            bank = {path: sha_file(location/path) for path in ("baseline.npz", "baseline_rows.json")}
            baseline = ActionBaselines(x, y, rows)
            arms = {"prior_only": {"kind": "prior", "prior": prior_fit["prior"],
                "selection_score": weighted_nll(np.tile(np.log(tune_prior), (len(tuning.labels), 1)), tuning.labels, tw),
                "trainable_parameters": 0, "fitted_prior_parameters": 1, "learning_evidence_claimed": False}}
            for arm in BASELINES:
                tuned = baseline.predict(arm, tuning.features, tuning.rows)
                cal = baseline.predict(arm, calibration.features, calibration.rows)
                predictor = hashlib.sha256(canonical([arm, bank, feature_identity])).hexdigest()
                fit = fit_bounded_calibrator(cal["logits"][:, 1]-cal["logits"][:, 0], calibration.labels, calibration.rows,
                    effective_training_prior=[.5, .5], forbidden_groups=forbidden,
                    bindings=calibration_bindings(feature_identity, predictor, cal_context))
                arms[arm] = {"kind": "baseline", "calibration": fit, "predictor_sha256": predictor,
                    "selection_score": weighted_nll(prior_corrected_logits(tuned["logits"], [.5, .5], tune_prior), tuning.labels, tw),
                    "tuning_eligible_rows": int(tuned["eligible"].sum()), "calibration_eligible_rows": int(cal["eligible"].sum()),
                    "tuning_prediction_cost": tuned["cost"], "calibration_prediction_cost": cal["cost"],
                    "trainable_parameters": 0, "fitted_prototype_scalars": 2*x.shape[1] if arm == "prototype" else 0,
                    "predictor_scope": "complete supplied text <=128KiB" if arm in ("exact", "bm25") else "frozen field features"}
            paths = []
            for mode in MODES:
                choices = []
                for l2 in config["l2_grid"]:
                    head, report = fit_path(x, y, tuning.features, tuning.labels, tw, mode=mode, seed=seed, l2=l2,
                        checkpoints=config["checkpoints"], rank=config["rank"], max_parameters=config["max_parameters"],
                        learning_rate=config["learning_rate"], min_delta=config["early_stop_min_delta"])
                    paths.append({"mode": mode, **report})
                    choices.append((report["selection_score"], -l2, head, report))
                _, negative_l2, head, report = min(choices, key=lambda item: item[:2])
                began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
                logits = head.predict_logits(calibration.features)
                prediction_cost = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu,
                    "dense_matmul_flops": matmul_flops(head.width, 2, head.rank, mode, len(calibration.labels))}
                fit = fit_bounded_calibrator(logits[:, 1]-logits[:, 0], calibration.labels, calibration.rows,
                    effective_training_prior=report["effective_training_prior"], forbidden_groups=forbidden,
                    bindings=calibration_bindings(feature_identity, head.digest(), cal_context))
                head.save(location/mode, feature_identity)
                arms[mode] = {"kind": "head", "artifact": f"{name}/{mode}", "calibration": fit,
                    "selection_score": report["selection_score"], "l2": -negative_l2, "training": report,
                    "tensor_sha256": head.digest(), "predictor_sha256": head.digest(),
                    "trainable_parameters": head.parameter_count, "calibration_prediction_cost": prediction_cost}
            selected = min(enumerate(config["selected_arm_order"]),
                key=lambda item: (arms[item[1]]["selection_score"], item[0]))[1]
            runs.append({"seed": seed, "budget": budget, "directory": name, "arms": arms,
                "selected_arm": selected, "selection_source": "independent_tuning_repositories_only",
                "training_source_ids": [r["source_id"] for r in rows], "training_group_ids": [r["group_id"] for r in rows],
                "training_class_counts": counts.tolist(), "training_rows": len(rows), "training_groups": len(rows),
                "baseline_artifacts_sha256": bank, "search_paths": paths,
                "all_search_optimizer_steps": sum(p["optimizer_steps"] for p in paths),
                "all_search_wall_ns": sum(p["wall_ns"] for p in paths), "all_search_cpu_ns": sum(p["cpu_ns"] for p in paths),
                "all_search_matmul_flops": sum(p["executed_dense_matmul_flops"] for p in paths),
                "baseline_fit_once_cost": baseline.fit_cost, "baseline_retained_state": baseline.memory})
    if code_hashes() != plan["code_sha256"] or any(c.digest() != plan["cohorts"][key] for key, c in cohorts.items()):
        raise ValueError("preparation source, features, labels or numerical code changed")
    frozen = {"plan": plan, "runs": runs, "unavailable": unavailable, "prior_fit_once": prior_fit,
        "status": "complete_with_explicit_unavailable_budgets", "wall_ns": time.perf_counter_ns()-start,
        "cpu_ns": time.process_time_ns()-cpu, "all_choices_frozen_before_heldout_scoring": True, "authority": "DENY_ALL"}
    write_json(root/"frozen.json", frozen)
    write_json(root/"seal.json", {"schema": "hepta.action-preparation-seal.v1", "files": inventory(root)})
    return frozen
