"""Post-lock modality-off intervention with unchanged heads and calibration."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_calibration_v2 import apply_calibrator_logits
from cell_calibrated_curve import inventory, sha_file, verify_prepared, write_json
from cell_calibrated_evaluate import _record
from cell_learning_baselines import FrozenBaselines
from cell_learning_metrics import probabilities
from cell_learning_models import NumpyCellHead, canonical
from run_calibrated_cells import compact_summary, load_inputs, task_cohort


def run_modality_off(dataset, feature_directory, main_study, control_features,
                     control_receipt, output):
    data, original, feature_report, modality, _ = load_inputs(dataset, feature_directory)
    if modality not in ("image", "audio"):
        raise ValueError("modality-off intervention requires declared media inputs")
    parent = Path(main_study)
    parent_plan = json.loads((parent/"study-plan.json").read_bytes())
    parent_summary = json.loads((parent/"summary.json").read_bytes())
    if (parent_plan["dataset_sha256"] != sha_file(dataset)
            or parent_plan["feature_identity"] != feature_report["feature_identity"]
            or parent_plan["holdout_use"] != "new_multimodal_holdout"):
        raise ValueError("completed primary media study binding differs")
    receipt = json.loads(Path(control_receipt).read_bytes())
    control = np.load(control_features, allow_pickle=False)
    if (receipt["dataset_sha256"] != sha_file(dataset)
            or receipt["source_ids"] != [r["source_id"] for r in data["rows"]]
            or receipt["parent_feature_identity"] != feature_report["feature_identity"]
            or receipt["feature_archive_sha256"] != sha_file(control_features)
            or control.dtype != np.float32 or control.shape != original.shape
            or receipt["feature_shape"] != list(control.shape) or not np.isfinite(control).all()
            or receipt["feature_tensor_sha256"] != hashlib.sha256(control.tobytes()).hexdigest()
            or receipt["input_fields"] != ["text"] or receipt["media_inputs_present"] is not False
            or canonical(receipt["encoder_identity"]) != canonical(feature_report["encoder_identity"])):
        raise ValueError("modality-off feature bytes, order, owner or input scope differs")
    if not np.array_equal(control, np.broadcast_to(control[:1], control.shape)):
        raise ValueError("neutral-text-only intervention must repeat one identical global vector")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.modality-off-study.v1", "dataset_sha256": sha_file(dataset),
        "feature_identity": feature_report["feature_identity"], "input_modality": modality,
        "tasks": parent_plan["tasks"], "families": parent_plan["families"],
        "protocol": parent_plan["protocol"], "condition": "modality_off_features",
        "holdout_use": "new_multimodal_holdout", "parent_study_plan_sha256": sha_file(parent/"study-plan.json"),
        "parent_summary_sha256": sha_file(parent/"summary.json"), "control_receipt": receipt,
        "control_receipt_sha256": sha_file(control_receipt), "source_sha256": sha_file(__file__),
        "intervention": "heldout features only; original training features and fitted calibration retained",
        "normal_profile_feature_identity_claimed": False,
        "fitting_or_selection": False, "optimizer_steps": 0, "encoder_forwards_in_scorer": 0}
    write_json(root/"study-plan.json", plan)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    reports = {}
    for task in parent_summary["tasks_evaluated"]:
        prepared, main_eval = parent/task/"prepared", parent/task/"evaluation"
        frozen = verify_prepared(prepared)
        main = json.loads((main_eval/"report.json").read_bytes())
        expected_seal = {"schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(main_eval)}
        if json.loads((main_eval/"seal.json").read_bytes()) != expected_seal:
            raise ValueError("primary evaluation artifact inventory changed")
        cohort, _ = task_cohort(data["rows"], control, task, "holdout")
        if (main["source_ids"] != [r["source_id"] for r in cohort.rows]
                or main["labels"] != cohort.labels.tolist()):
            raise ValueError("paired intervention source IDs or gold differ")
        evaluation = root/task/"evaluation"
        evaluation.mkdir(parents=True)
        report = {"plan": {"schema": "hepta.modality-off-evaluation.v1", "task_id": task,
            "family_id": frozen["plan"]["family_id"], "prepared_seal_sha256": sha_file(prepared/"seal.json"),
            "primary_evaluation_seal_sha256": sha_file(main_eval/"seal.json"),
            "feature_identity": feature_report["feature_identity"], "holdout_use": "new_multimodal_holdout",
            "tuning_source_ids": frozen["plan"]["tuning_source_ids"],
            "calibration_source_ids": frozen["plan"]["calibration_source_ids"],
            "counterfactual_input_scope": "neutral_text_only_no_media", "calibration_refitted": False},
            "runs": [], "source_ids": main["source_ids"], "group_ids": main["group_ids"],
            "labels": main["labels"], "unavailable": frozen["unavailable"], "quality_qualified": False,
            "authority": "DENY_ALL"}
        for run in frozen["runs"]:
            location = evaluation/run["directory"]
            location.mkdir()
            with np.load(prepared/run["directory"]/"baseline.npz", allow_pickle=False) as bank:
                baseline = FrozenBaselines(bank["features"], bank["labels"],
                    json.loads((prepared/run["directory"]/"baseline_rows.json").read_bytes()), 2)
            result = {"seed": run["seed"], "budget": run["budget"], "directory": run["directory"],
                "training_source_ids": run["training_source_ids"],
                "selected_arm": run["selected_arm"], "selection_source": run["selection_source"], "arms": {}}
            for name, spec in run["arms"].items():
                eligible = np.ones(len(cohort.labels), dtype=bool)
                head = None
                if spec["kind"] == "prior":
                    z = np.tile(np.log(spec["prior"]), (len(cohort.labels), 1))
                    p, prior = probabilities(z), spec["prior"]
                else:
                    if spec["kind"] == "head":
                        head = NumpyCellHead.load(prepared/spec["artifact"], feature_report["feature_identity"])
                        before = head.digest()
                        z = head.predict_logits(cohort.features)
                    else:
                        prediction = baseline.predict(name, cohort.features, cohort.rows)
                        z, eligible = prediction["logits"], prediction["eligible"]
                    p = probabilities(apply_calibrator_logits(z, spec["calibration"]))
                    prior = spec["calibration"]["prior"]
                arm = _record(location, name, z, p, cohort.labels, eligible, prior, parent_plan["protocol"]["threshold"])
                arm.update(calibration=spec.get("calibration"), calibration_refitted=False,
                    trainable_parameters=spec["trainable_parameters"], intervention="modality_off_features")
                if head is not None:
                    if head.digest() != before or before != spec["tensor_sha256"]:
                        raise ValueError("head parameters changed during intervention")
                    arm.update(tensor_sha256=before, parameters_unchanged=True)
                result["arms"][name] = arm
            report["runs"].append(result)
        verify_prepared(prepared)
        write_json(evaluation/"report.json", report)
        write_json(evaluation/"seal.json", {"schema": "hepta.modality-off-evaluation-seal.v1", "files": inventory(evaluation)})
        reports[task] = report
    if sha_file(control_features) != receipt["feature_archive_sha256"] or sha_file(parent/"summary.json") != plan["parent_summary_sha256"]:
        raise ValueError("control source or completed primary changed")
    summary = {"plan": plan, "tasks_evaluated": list(reports), **compact_summary(reports),
        "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu,
        "main_preparations_unchanged": True, "no_new_model_selection": True}
    write_json(root/"summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "study", "control-features", "control-receipt", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    run_modality_off(args.dataset, args.features, args.study, args.control_features, args.control_receipt, args.output)


if __name__ == "__main__":
    main()
