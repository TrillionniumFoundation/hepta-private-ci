"""One-shot scoring of sealed calibrated heads; no heldout fitting."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from cell_calibration_v2 import apply_calibrator_logits, discrimination_metrics
from cell_calibrated_curve import context_receipt, inventory, sha_file, verify_prepared, write_json
from cell_learning_baselines import FrozenBaselines
from cell_learning_metrics import probabilities, task_metrics
from cell_learning_models import NumpyCellHead, canonical
from cell_regularized_training import matmul_flops


def _record(location, name, logits, probability, labels, eligible, prior, threshold):
    path = location/f"{name}.npz"
    with path.open("xb") as stream:
        np.savez_compressed(stream, logits=logits, probabilities=probability, eligible=eligible)
    semantic = task_metrics(probability, labels, threshold=threshold, eligible=eligible)
    if any(count == 0 for count in semantic["class_support"]):
        semantic.update(balanced_accuracy=None, balanced_success=None,
                        balanced_accuracy_status="unavailable_missing_holdout_class")
    return {"semantic": semantic,
            "secondary_discrimination": discrimination_metrics(probability, labels, prior),
            "prediction_file": path.name, "prediction_sha256": sha_file(path),
            "eligible_rows": int(eligible.sum()),
            "exact_source_retrieval": {"status": "not_evaluated", "reason": "semantic labels are not source retrieval relevance gold"}}


def _fresh_replay(model_path, output_path, features_path, identity_path, calibrator, logits, p):
    fit_path = output_path.with_suffix(".calibration.json")
    write_json(fit_path, {key: calibrator[key] for key in ("alpha", "bias", "center", "scale")})
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--model", str(model_path),
        "--features", str(features_path), "--identity", str(identity_path),
        "--calibration", str(fit_path), "--output", str(output_path)], check=True,
        capture_output=True, timeout=60,
        env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    with np.load(output_path, allow_pickle=False) as saved:
        same = np.array_equal(saved["logits"], logits) and np.array_equal(saved["probabilities"], p)
    if not same:
        raise ValueError("fresh process changed frozen head or calibrated predictions")
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"bitwise_equal_logits_and_probabilities": same,
            "wall_ns": time.perf_counter_ns()-start, "parent_cpu_ns": time.process_time_ns()-cpu,
            "child_cpu_ns": int(1e9*(children_after.ru_utime+children_after.ru_stime
                                     -children_before.ru_utime-children_before.ru_stime)),
            "output_sha256": sha_file(output_path), "test_labels_provided_to_child": False,
            "input_allowlist": ["head_weights", "feature_identity", "features", "four_calibration_scalars"],
            "isolation_scope": "argument/file allowlist only; child shares parent filesystem"}


def evaluate_curve(holdout, *, feature_identity, prepared_dir, output_dir, holdout_use,
                   input_modality="text", input_content_sha256=None):
    if holdout_use not in ("legacy_repeated_use_diagnostic", "new_operational_holdout", "new_multimodal_holdout", "fixture"):
        raise ValueError("explicit heldout reuse designation required")
    prepared = Path(prepared_dir).resolve()
    frozen = verify_prepared(prepared)
    plan, protocol = frozen["plan"], frozen["plan"]["configuration"]
    if (holdout.split != "holdout" or holdout.features.shape[1] != plan["width"]
            or canonical(feature_identity) != canonical(plan["feature_identity"])
            or input_modality != plan["input_modality"]
            or np.any((holdout.labels < 0) | (holdout.labels > 1))):
        raise ValueError("heldout role, feature identity or binary labels differ")
    context = context_receipt(holdout, input_modality, input_content_sha256)
    if len(context["source_ids"]) != len(set(context["source_ids"])):
        raise ValueError("duplicate heldout source ID")
    if any(set(context[key]) & set(other[key]) for other in plan["contexts"] for key in context):
        raise ValueError("heldout source, group or text overlaps preparation")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    evaluation_plan = {"schema": "hepta.calibrated-evaluation.v2", "task_id": plan["task_id"],
        "family_id": plan["family_id"], "prepared_seal_sha256": sha_file(prepared/"seal.json"),
        "feature_identity": feature_identity, "holdout_sha256": holdout.digest(),
        "input_modality": input_modality,
        "input_content_sha256": ({r["source_id"]: input_content_sha256[r["source_id"]]
            for r in holdout.rows} if input_modality != "text" else None),
        "holdout_use": holdout_use, "threshold": protocol["threshold"],
        "no_calibration_or_hyperparameter_fit_in_evaluation": True,
        "baseline_reconstruction": "sealed training artifacts only",
        "claim_scope": "fixed source corpus and declared target family"}
    write_json(root/"plan.json", evaluation_plan)
    features_path, identity_path = root/"features.npy", root/"feature_identity.json"
    with features_path.open("xb") as stream:
        np.save(stream, holdout.features, allow_pickle=False)
    write_json(identity_path, feature_identity)
    report = {"plan": evaluation_plan, "runs": [], "unavailable": frozen["unavailable"],
        "source_ids": [r["source_id"] for r in holdout.rows],
        "group_ids": [r["group_id"] for r in holdout.rows],
        "labels": holdout.labels.tolist(), "quality_qualified": False, "authority": "DENY_ALL"}
    for run in frozen["runs"]:
        location = root/run["directory"]
        location.mkdir()
        with np.load(prepared/run["directory"]/"baseline.npz", allow_pickle=False) as archive:
            if set(archive.files) != {"features", "labels"}:
                raise ValueError("unexpected baseline artifact fields")
            baseline = FrozenBaselines(archive["features"], archive["labels"],
                json.loads((prepared/run["directory"]/"baseline_rows.json").read_bytes()), 2)
        result = {"seed": run["seed"], "budget": run["budget"], "directory": run["directory"], "arms": {},
                  "baseline_reconstruction_cost": baseline.fit_cost,
                  "selected_arm": run["selected_arm"], "selection_source": run["selection_source"]}
        for name, spec in run["arms"].items():
            began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
            eligible = np.ones(len(holdout.labels), dtype=bool)
            sources, head = None, None
            if spec["kind"] == "prior":
                logits = np.tile(np.log(spec["prior"]), (len(holdout.labels), 1))
                p, prior = probabilities(logits), spec["prior"]
            elif spec["kind"] == "baseline":
                predicted = baseline.predict(name, holdout.features, holdout.rows)
                logits, eligible, sources = (predicted[k] for k in ("logits", "eligible", "retrieved_source_ids"))
                p = probabilities(apply_calibrator_logits(logits, spec["calibration"]))
                prior = spec["calibration"]["prior"]
            else:
                head = NumpyCellHead.load(prepared/spec["artifact"], feature_identity)
                logits = head.predict_logits(holdout.features)
                p = probabilities(apply_calibrator_logits(logits, spec["calibration"]))
                prior = spec["calibration"]["prior"]
            cost = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu}
            scored = _record(location, name, logits, p, holdout.labels, eligible, prior, protocol["threshold"])
            scored.update(prediction_cost=cost, retrieved_source_ids=sources,
                          calibration=spec.get("calibration"), trainable_parameters=spec["trainable_parameters"])
            if spec["kind"] == "baseline":
                scored["baseline_prediction_cost"] = predicted["cost"]
                scored["modality_appropriate"] = spec["modality_appropriate"]
                scored["predictor_scope"] = spec["predictor_scope"]
            if head is not None:
                scored["prediction_cost"]["dense_matmul_flops"] = matmul_flops(head.width, 2, head.rank, head.mode, len(holdout.labels))
                scored["tensor_sha256"] = head.digest()
                scored["fresh_process"] = _fresh_replay(prepared/spec["artifact"],
                    location/f"{name}-fresh.npz", features_path, identity_path, spec["calibration"], logits, p)
                scored["controls"] = {}
                for control in ("parameters_off", "shuffled_parameters"):
                    control_started, control_cpu = time.perf_counter_ns(), time.process_time_ns()
                    altered = NumpyCellHead(head.width, 2, head.mode, head.rank, run["seed"], head.max_parameters)
                    rng = np.random.default_rng(run["seed"])
                    for key, value in sorted(head.params.items()):
                        altered.params[key] = np.zeros_like(value) if control == "parameters_off" else rng.permutation(value.ravel()).reshape(value.shape)
                    z = altered.predict_logits(holdout.features)
                    cp = probabilities(apply_calibrator_logits(z, spec["calibration"]))
                    control_score = _record(location, f"{name}-{control}", z, cp, holdout.labels,
                                            eligible, prior, protocol["threshold"])
                    control_score.update(tensor_sha256=altered.digest(), calibration_refitted=False)
                    control_score["prediction_cost"] = {
                        "wall_ns": time.perf_counter_ns()-control_started,
                        "cpu_ns": time.process_time_ns()-control_cpu,
                        "dense_matmul_flops": matmul_flops(head.width, 2, head.rank, head.mode, len(holdout.labels))}
                    scored["controls"][control] = control_score
            result["arms"][name] = scored
        report["runs"].append(result)
    if holdout.digest() != evaluation_plan["holdout_sha256"] or verify_prepared(prepared) != frozen:
        raise ValueError("heldout inputs or prepared artifacts changed during evaluation")
    report.update(wall_ns=time.perf_counter_ns()-start, cpu_ns=time.process_time_ns()-cpu,
                  fresh_process_child_cpu_ns=sum(a.get("fresh_process", {}).get("child_cpu_ns", 0)
                    for run in report["runs"] for a in run["arms"].values()),
                  prepared_artifacts_unchanged=True)
    write_json(root/"report.json", report)
    write_json(root/"seal.json", {"schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(root)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("model", "features", "identity", "calibration", "output"):
        parser.add_argument(f"--{field}", required=True)
    args = parser.parse_args()
    head = NumpyCellHead.load(args.model, json.loads(Path(args.identity).read_bytes()))
    logits = head.predict_logits(np.load(args.features, allow_pickle=False))
    p = probabilities(apply_calibrator_logits(logits, json.loads(Path(args.calibration).read_bytes())))
    with Path(args.output).open("xb") as stream:
        np.savez_compressed(stream, logits=logits, probabilities=p)


if __name__ == "__main__":
    main()
