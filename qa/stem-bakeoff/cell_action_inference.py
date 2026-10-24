"""Label-free sealed prediction for all feature-available proposed actions.

Unknown and infrastructure outcomes do not enter this interface. The caller
joins frozen predictions to the complete proposal/execution registry later.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_action_cohort import ActionBaselines, public_rows
from cell_action_evaluate import _fresh_replay, _probabilities
from cell_action_prepare import inventory, sha_file, verify_action_prepared, write_json
from cell_learning_models import NumpyCellHead, canonical, normalize_features
from cell_regularized_training import matmul_flops
from operational_head_view import full_normalized_text


def _input_digest(features, rows):
    digest = hashlib.sha256(canonical([features.dtype.str, features.shape, rows]))
    digest.update(features.tobytes())
    return digest.hexdigest()


def _save_prediction(location, name, logits, probability, eligible):
    path = location/f"{name}.npz"
    with path.open("xb") as stream:
        np.savez_compressed(stream, logits=logits, probabilities=probability, eligible=eligible)
    return {"prediction_file": path.name, "prediction_sha256": sha_file(path),
            "rows": len(probability), "eligible_rows": int(eligible.sum())}


def predict_action_rows(features, rows, *, feature_identity, prepared_dir, output_dir,
                        input_bindings, prediction_role="prospective_external_candidates"):
    """Consume only public inputs; emit predictions/controls without any labels.

    The caller excludes explicitly unavailable feature rows and records that
    exclusion in its full proposal registry. Every provided group must be
    separate from the three preparation roles, even for development replay.
    """
    if prediction_role not in ("prospective_external_candidates", "reused_development_candidates", "fixture"):
        raise ValueError("explicit prospective or repeated-use candidate role required")
    x = np.asarray(features)
    if x.ndim != 2 or x.dtype != np.float32 or len(x) != len(rows):
        raise ValueError("FP32 features and matching public action rows required")
    normalize_features(x)
    rows = public_rows(rows)
    if sum(len(row["text"].encode()) for row in rows) > 128*1024**2:
        raise ValueError("candidate text exceeds128MiB total bound")
    x = x.copy()
    x.flags.writeable = False
    prepared = Path(prepared_dir).resolve()
    frozen = verify_action_prepared(prepared)
    plan = frozen["plan"]
    if feature_identity != plan["feature_identity"] or x.shape[1] != plan["width"] or input_bindings != plan["input_bindings"]:
        raise ValueError("feature identity, width or external input bindings differ")
    context = {"source_ids": sorted(r["source_id"] for r in rows), "group_ids": sorted({r["group_id"] for r in rows}),
        "predictor_sha256": sorted({hashlib.sha256(full_normalized_text(r["text"]).encode()).hexdigest() for r in rows})}
    if any(set(context[key]) & set(other[key]) for other in plan["contexts"].values() for key in context):
        raise ValueError("prediction source/group/full-text overlaps preparation")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    inference_plan = {"schema": "hepta.action-label-free-inference.v1", "task_id": plan["task_id"],
        "family_id": plan["family_id"], "prediction_role": prediction_role, "feature_identity": feature_identity,
        "input_bindings": plan["input_bindings"], "input_sha256": _input_digest(x, rows),
        "prepared_seal_sha256": sha_file(prepared/"seal.json"), "rows": len(rows), "groups": len(context["group_ids"]),
        "labels_or_outcomes_received": False, "metrics_computed": False, "fitting_performed": False,
        "availability_scope": "all caller-supplied feature-available proposals, regardless of outcome availability",
        "unknown_and_infrastructure_denominators": "retained in caller's complete proposal/execution registry"}
    write_json(root/"plan.json", inference_plan)
    features_path = root/"features.npy"
    with features_path.open("xb") as stream:
        np.save(stream, x, allow_pickle=False)
    report = {"plan": inference_plan, "runs": [], "unavailable": frozen["unavailable"],
        "source_ids": [r["source_id"] for r in rows], "group_ids": [r["group_id"] for r in rows],
        "quality_qualified": False, "authority": "DENY_ALL"}
    for run in frozen["runs"]:
        location = root/run["directory"]
        location.mkdir()
        bank_root = prepared/run["directory"]
        bank = {name: sha_file(bank_root/name) for name in ("baseline.npz", "baseline_rows.json")}
        if bank != run["baseline_artifacts_sha256"]:
            raise ValueError("prepared baseline bank differs")
        with np.load(bank_root/"baseline.npz", allow_pickle=False) as archive:
            if set(archive.files) != {"features", "labels"}:
                raise ValueError("unexpected training-bank fields")
            baseline = ActionBaselines(archive["features"], archive["labels"], json.loads((bank_root/"baseline_rows.json").read_bytes()))
        result = {"seed": run["seed"], "budget": run["budget"], "directory": run["directory"], "arms": {},
            "selected_arm": run["selected_arm"], "selection_source": run["selection_source"],
            "baseline_reconstruction_cost": baseline.fit_cost}
        for name, spec in run["arms"].items():
            began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
            head, sources, eligible = None, None, np.ones(len(rows), dtype=bool)
            if spec["kind"] == "prior":
                logits = np.tile(np.log(spec["prior"]), (len(rows), 1))
            elif spec["kind"] == "baseline":
                if spec["predictor_sha256"] != hashlib.sha256(canonical([name, bank, feature_identity])).hexdigest():
                    raise ValueError("baseline/calibrator binding differs")
                predicted = baseline.predict(name, x, rows)
                logits, eligible, sources = (predicted[key] for key in ("logits", "eligible", "retrieved_source_ids"))
            elif spec["kind"] == "head":
                head = NumpyCellHead.load(prepared/spec["artifact"], feature_identity)
                if head.digest() != spec["predictor_sha256"] or head.digest() != spec["tensor_sha256"]:
                    raise ValueError("head/calibrator binding differs")
                logits = head.predict_logits(x)
            else:
                raise ValueError("unknown frozen prediction arm")
            probability, _ = _probabilities(logits, spec, plan)
            cost = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu}
            arm = _save_prediction(location, name, logits, probability, eligible)
            arm.update(prediction_cost=cost, retrieved_source_ids=sources, calibration=spec.get("calibration"),
                       trainable_parameters=spec["trainable_parameters"])
            if spec["kind"] == "baseline":
                arm["baseline_prediction_cost"] = predicted["cost"]
            if head is not None:
                flops = matmul_flops(head.width, 2, head.rank, head.mode, len(rows))
                arm["prediction_cost"]["dense_matmul_flops"] = flops
                arm["tensor_sha256"] = head.digest()
                arm["fresh_process"] = _fresh_replay(prepared/spec["artifact"], location/f"{name}-fresh.npz",
                    features_path, spec, plan, logits, probability)
                arm["controls"] = {}
                for control in ("parameters_off", "shuffled_parameters"):
                    began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
                    changed = NumpyCellHead(head.width, 2, head.mode, head.rank, run["seed"], head.max_parameters)
                    rng = np.random.default_rng(run["seed"])
                    for key, value in sorted(head.params.items()):
                        changed.params[key] = (np.zeros_like(value) if control == "parameters_off"
                            else rng.permutation(value.ravel()).reshape(value.shape))
                    z = changed.predict_logits(x)
                    cp, _ = _probabilities(z, spec, plan)
                    item = _save_prediction(location, f"{name}-{control}", z, cp, eligible)
                    item.update(tensor_sha256=changed.digest(), calibration_refitted=False,
                        retained_calibration_predictor_sha256=spec["predictor_sha256"],
                        prediction_cost={"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu,
                                         "dense_matmul_flops": flops})
                    arm["controls"][control] = item
            result["arms"][name] = arm
        report["runs"].append(result)
    if (_input_digest(x, rows) != inference_plan["input_sha256"] or verify_action_prepared(prepared) != frozen
            or sha_file(prepared/"seal.json") != inference_plan["prepared_seal_sha256"]):
        raise ValueError("inputs, numerical code or sealed preparation changed during prediction")
    report.update(wall_ns=time.perf_counter_ns()-start, cpu_ns=time.process_time_ns()-cpu,
        fresh_process_child_cpu_ns=sum(arm.get("fresh_process", {}).get("child_cpu_ns", 0)
            for run in report["runs"] for arm in run["arms"].values()), prepared_artifacts_unchanged=True)
    write_json(root/"report.json", report)
    write_json(root/"seal.json", {"schema": "hepta.action-label-free-inference-seal.v1", "files": inventory(root)})
    return report
