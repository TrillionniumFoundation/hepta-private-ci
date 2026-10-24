"""Score sealed prospective action heads without fitting on evaluation labels."""

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

from cell_action_cohort import ActionBaselines
from cell_action_prepare import (calibration_bindings, cohort_counts, inventory,
    sha_file, verify_action_prepared, write_json)
from cell_calibration_bounded import apply_bounded_calibrator
from cell_group_metrics import group_weighted_metrics
from cell_learning_models import NumpyCellHead, canonical
from cell_regularized_training import matmul_flops


def _probabilities(logits, spec, plan):
    if spec["kind"] == "prior":
        return np.tile(spec["prior"], (len(logits), 1)), spec["prior"][1]
    bindings = calibration_bindings(plan["feature_identity"], spec["predictor_sha256"], plan["cohorts"]["calibration"])
    result = apply_bounded_calibrator(logits[:, 1]-logits[:, 0], spec["calibration"], expected_bindings=bindings)
    return result, spec["calibration"]["prior_positive"]


def _record(location, name, logits, probabilities, holdout, eligible, prior, threshold):
    path = location/f"{name}.npz"
    with path.open("xb") as stream:
        np.savez_compressed(stream, logits=logits, probabilities=probabilities, eligible=eligible)
    return {"semantic": group_weighted_metrics(probabilities, holdout.labels, holdout.rows,
                eligible=eligible, threshold=threshold, calibration_prior=prior),
        "prediction_file": path.name, "prediction_sha256": sha_file(path), "eligible_rows": int(eligible.sum()),
        "exact_source_retrieval": {"status": "not_evaluated", "reason": "action labels are not source-relevance gold"}}


def _fresh_replay(model, output, features, spec, plan, logits, probability):
    calibration = output.with_suffix(".calibration.json")
    descriptor = output.with_suffix(".descriptor.json")
    write_json(calibration, spec["calibration"])
    write_json(descriptor, {"feature_identity": plan["feature_identity"],
        "bindings": calibration_bindings(plan["feature_identity"], spec["predictor_sha256"], plan["cohorts"]["calibration"])})
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--model", str(model),
        "--features", str(features), "--descriptor", str(descriptor), "--calibration", str(calibration),
        "--output", str(output)], check=True, capture_output=True, timeout=60,
        env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    with np.load(output, allow_pickle=False) as saved:
        equal = (set(saved.files) == {"logits", "probabilities"} and np.array_equal(saved["logits"], logits)
                 and np.array_equal(saved["probabilities"], probability))
    if not equal:
        raise ValueError("fresh process changed action logits or calibrated probabilities")
    return {"bitwise_equal_logits_and_probabilities": equal, "wall_ns": time.perf_counter_ns()-start,
        "parent_cpu_ns": time.process_time_ns()-cpu,
        "child_cpu_ns": int(1e9*(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)),
        "test_labels_provided_to_child": False, "output_sha256": sha_file(output),
        "input_allowlist": ["frozen_weights", "features", "feature_and_predictor_bindings", "frozen_calibration_state"],
        "isolation_scope": "argument/file allowlist only; child shares parent filesystem"}


def evaluate_action_curve(holdout, *, feature_identity, prepared_dir, output_dir, holdout_use):
    if holdout_use not in ("prospective_external_holdout", "reused_development_diagnostic", "fixture"):
        raise ValueError("explicit prospective or repeated-use evaluation designation required")
    prepared = Path(prepared_dir).resolve()
    frozen = verify_action_prepared(prepared)
    plan, config = frozen["plan"], frozen["plan"]["configuration"]
    if (holdout.split != "holdout" or holdout.features.shape[1] != plan["width"]
            or feature_identity != plan["feature_identity"]):
        raise ValueError("holdout role, feature identity or width differs")
    context = holdout.context()
    if any(set(context[key]) & set(other[key]) for other in plan["contexts"].values() for key in context):
        raise ValueError("holdout source, group or full-predictor overlaps preparation")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    evaluation_plan = {"schema": "hepta.prospective-action-evaluation.v1", "task_id": plan["task_id"],
        "family_id": plan["family_id"], "feature_identity": feature_identity, "holdout_use": holdout_use,
        "prepared_seal_sha256": sha_file(prepared/"seal.json"), "holdout_sha256": holdout.digest(),
        "input_bindings": plan["input_bindings"], "labelled_holdout": cohort_counts(holdout),
        "threshold": config["threshold"], "no_calibration_or_hyperparameter_fit_in_evaluation": True,
        "unknown_outcomes_are_labels": False, "availability_scope": "available labelled actions only",
        "all_proposed_group_ranking_and_infrastructure_costs": "separate execution-registry analysis required"}
    write_json(root/"plan.json", evaluation_plan)
    features_path = root/"features.npy"
    with features_path.open("xb") as stream:
        np.save(stream, holdout.features, allow_pickle=False)
    report = {"plan": evaluation_plan, "runs": [], "unavailable": frozen["unavailable"],
        "source_ids": [r["source_id"] for r in holdout.rows], "group_ids": [r["group_id"] for r in holdout.rows],
        "labels": holdout.labels.tolist(), "quality_qualified": False, "authority": "DENY_ALL"}
    for run in frozen["runs"]:
        location = root/run["directory"]
        location.mkdir()
        bank_path = prepared/run["directory"]
        bank = {name: sha_file(bank_path/name) for name in ("baseline.npz", "baseline_rows.json")}
        if bank != run["baseline_artifacts_sha256"]:
            raise ValueError("sealed baseline bank differs")
        with np.load(bank_path/"baseline.npz", allow_pickle=False) as archive:
            if set(archive.files) != {"features", "labels"}:
                raise ValueError("unexpected baseline bank fields")
            baseline = ActionBaselines(archive["features"], archive["labels"], json.loads((bank_path/"baseline_rows.json").read_bytes()))
        result = {"seed": run["seed"], "budget": run["budget"], "directory": run["directory"], "arms": {},
            "baseline_reconstruction_cost": baseline.fit_cost, "selected_arm": run["selected_arm"],
            "selection_source": run["selection_source"]}
        for name, spec in run["arms"].items():
            began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
            eligible, head, sources = np.ones(len(holdout.labels), dtype=bool), None, None
            if spec["kind"] == "prior":
                logits = np.tile(np.log(spec["prior"]), (len(holdout.labels), 1))
            elif spec["kind"] == "baseline":
                if spec["predictor_sha256"] != hashlib.sha256(canonical([name, bank, feature_identity])).hexdigest():
                    raise ValueError("calibrator/baseline predictor binding differs")
                predicted = baseline.predict(name, holdout.features, holdout.rows)
                logits, eligible, sources = (predicted[key] for key in ("logits", "eligible", "retrieved_source_ids"))
            elif spec["kind"] == "head":
                head = NumpyCellHead.load(prepared/spec["artifact"], feature_identity)
                if head.digest() != spec["predictor_sha256"] or head.digest() != spec["tensor_sha256"]:
                    raise ValueError("calibrator/head tensor binding differs")
                logits = head.predict_logits(holdout.features)
            else:
                raise ValueError("unknown prepared action arm")
            probability, prior = _probabilities(logits, spec, plan)
            cost = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu}
            scored = _record(location, name, logits, probability, holdout, eligible, prior, config["threshold"])
            scored.update(prediction_cost=cost, retrieved_source_ids=sources, calibration=spec.get("calibration"),
                          trainable_parameters=spec["trainable_parameters"])
            if spec["kind"] == "baseline":
                scored.update(baseline_prediction_cost=predicted["cost"], predictor_scope=spec["predictor_scope"])
            if head is not None:
                flops = matmul_flops(head.width, 2, head.rank, head.mode, len(holdout.labels))
                scored["prediction_cost"]["dense_matmul_flops"] = flops
                scored["tensor_sha256"] = head.digest()
                scored["fresh_process"] = _fresh_replay(prepared/spec["artifact"], location/f"{name}-fresh.npz",
                    features_path, spec, plan, logits, probability)
                scored["controls"] = {}
                for control in ("parameters_off", "shuffled_parameters"):
                    began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
                    altered = NumpyCellHead(head.width, 2, head.mode, head.rank, run["seed"], head.max_parameters)
                    rng = np.random.default_rng(run["seed"])
                    for key, value in sorted(head.params.items()):
                        altered.params[key] = (np.zeros_like(value) if control == "parameters_off"
                            else rng.permutation(value.ravel()).reshape(value.shape))
                    z = altered.predict_logits(holdout.features)
                    cp, _ = _probabilities(z, spec, plan)
                    changed = _record(location, f"{name}-{control}", z, cp, holdout, eligible, prior, config["threshold"])
                    changed.update(tensor_sha256=altered.digest(), calibration_refitted=False,
                        retained_calibration_predictor_sha256=spec["predictor_sha256"],
                        prediction_cost={"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-began_cpu,
                                         "dense_matmul_flops": flops})
                    scored["controls"][control] = changed
            result["arms"][name] = scored
        selected = result["arms"][run["selected_arm"]]
        result["selected_policy"] = {"arm": run["selected_arm"], "semantic": selected["semantic"],
            "prior_only_output": run["selected_arm"] == "prior_only" or selected["calibration"]["prior_only_selected"],
            "selection_or_prior_fallback_is_learning_evidence": False}
        report["runs"].append(result)
    if (holdout.digest() != evaluation_plan["holdout_sha256"] or verify_action_prepared(prepared) != frozen
            or sha_file(prepared/"seal.json") != evaluation_plan["prepared_seal_sha256"]):
        raise ValueError("evaluation input, implementation or frozen artifacts changed")
    report.update(wall_ns=time.perf_counter_ns()-start, cpu_ns=time.process_time_ns()-cpu,
        fresh_process_child_cpu_ns=sum(arm.get("fresh_process", {}).get("child_cpu_ns", 0)
            for run in report["runs"] for arm in run["arms"].values()), prepared_artifacts_unchanged=True)
    write_json(root/"report.json", report)
    write_json(root/"seal.json", {"schema": "hepta.action-evaluation-seal.v1", "files": inventory(root)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("model", "features", "descriptor", "calibration", "output"):
        parser.add_argument(f"--{field}", required=True)
    args = parser.parse_args()
    descriptor = json.loads(Path(args.descriptor).read_bytes())
    head = NumpyCellHead.load(args.model, descriptor["feature_identity"])
    if head.digest() != descriptor["bindings"]["predictor_sha256"]:
        raise ValueError("replay head binding differs")
    logits = head.predict_logits(np.load(args.features, allow_pickle=False))
    probabilities = apply_bounded_calibrator(logits[:, 1]-logits[:, 0], json.loads(Path(args.calibration).read_bytes()),
        expected_bindings=descriptor["bindings"])
    with Path(args.output).open("xb") as stream:
        np.savez_compressed(stream, logits=logits, probabilities=probabilities)


if __name__ == "__main__":
    main()
