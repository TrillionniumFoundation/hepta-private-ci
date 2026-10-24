"""Execute the availability-derived n122 operational diagnostic supplement.

The original 8/32/128 study remains intact. This wrapper delegates all numerical
work to the frozen learner and selects only the preregistered diagnostic task.
"""

import argparse
import json
from pathlib import Path
import time

from cell_calibrated_curve import (bounded_protocol, code_hashes, inventory,
    prepare_curve, sha_file, verify_prepared, write_json)
from cell_calibrated_evaluate import evaluate_curve
from cell_learning_baselines import normalized_text
from cell_learning_curve import training_order
from operational_head_view import verify_view
from run_calibrated_cells import compact_summary, load_inputs, task_cohort, task_family


def validate_registration(dataset, data, features, registration, reconciliation):
    declared = json.loads(Path(registration).read_bytes())
    linked = json.loads(Path(reconciliation).read_bytes())
    protocol = bounded_protocol({"budgets": [122]})
    if (declared.get("schema") != "hepta.availability-derived-balanced-ceiling-supplement.v1"
            or declared.get("task_id") != "diagnostic_test_selection"
            or declared.get("protocol") != protocol or declared.get("balanced_budget") != 122
            or declared.get("main_code_sha256") != code_hashes()
            or declared.get("before_any_operational_heldout_score") is not True
            or declared.get("no_upsampling_relabelling_or_action_order_changes") is not True
            or declared.get("holdout_use") != "new_operational_holdout"):
        raise ValueError("supplement registration differs from the frozen availability-only plan")
    if (linked.get("schema") != "hepta.operational122-input-reconciliation.v1"
            or linked.get("original_preregistration_sha256") != sha_file(registration)
            or linked.get("definitive_dataset_sha256") != sha_file(dataset)
            or linked.get("superseded_unexecuted_dataset_sha256") != declared["dataset_sha256"]
            or linked.get("balanced_budget") != 122
            or linked.get("training_source_group_predictor_labels_identical") is not True
            or linked.get("no_operational_heldout_scores_observed") is not True
            or linked.get("primary128_remains_unavailable_for_diagnostic") is not True
            or linked.get("main_numerical_protocol_changed") is not False):
        raise ValueError("supplement input reconciliation is missing or does not bind this dataset")
    task = declared["task_id"]
    if task not in data["selected_tasks"]:
        raise ValueError("supplement task was not declared in the original dataset")
    train, counts = task_cohort(data["rows"], features, task, "train")
    if (train is None or counts["groups"] != counts["applicable_rows"]
            or len({normalized_text(r["text"]) for r in train.rows}) != counts["groups"]
            or counts["groups"] != declared["available_training_groups"]
            or counts["class_support"] != declared["training_class_counts"]
            or 2*min(counts["class_support"]) != 122):
        raise ValueError("independent training availability differs from the n122 derivation")
    return declared, linked, train, protocol


def validate_preparation(frozen, train, calibration, task, family, identity, protocol):
    p = frozen["plan"]
    expected = {"task_id": task, "family_id": family, "feature_identity": identity,
        "width": train.features.shape[1], "classes": 2, "input_modality": "text",
        "configuration": protocol, "code_sha256": code_hashes(),
        "cohorts": {"train": train.digest(), "calibration": calibration.digest()}}
    if (any(p.get(key) != value for key, value in expected.items()) or frozen["unavailable"]
            or [(r["seed"], r["budget"]) for r in frozen["runs"]] != [(s, 122) for s in protocol["seeds"]]):
        raise ValueError("sealed supplement preparation differs from registered inputs or n122 protocol")
    for run in frozen["runs"]:
        indices = training_order(train, 2, run["seed"])[:122]
        if (run["training_source_ids"] != [train.rows[i]["source_id"] for i in indices]
                or run["training_group_ids"] != [train.rows[i]["group_id"] for i in indices]
                or run["training_class_counts"] != [61, 61]):
            raise ValueError("sealed supplement source draw differs from registered balanced n122 draw")


def run_supplement(dataset, feature_directory, output, *, registration,
                   reconciliation, condition, phase="prepare", source_dataset=None):
    if phase not in ("prepare", "evaluate", "all"):
        raise ValueError("unknown supplement phase")
    data, features, receipt, modality, identity = load_inputs(dataset, feature_directory)
    registration_dataset, view_binding = dataset, None
    if "head_predictor_view" in data:
        if source_dataset is None:
            raise ValueError("lexical head view requires the original complete-source dataset")
        view = verify_view(source_dataset, Path(dataset).parent)
        view_binding = receipt.get("head_predictor_view", {})
        if (view_binding.get("view_receipt_sha256") != sha_file(Path(dataset).with_name("receipt.json"))
                or view_binding.get("source_dataset_sha256") != view["source_dataset_sha256"]
                or view_binding.get("head_view_dataset_sha256") != sha_file(dataset)
                or view_binding.get("feature_tensor_bitwise_unchanged") is not True):
            raise ValueError("supplement feature alias does not bind the complete-source head view")
        registration_dataset = source_dataset
    elif source_dataset is not None and sha_file(source_dataset) != sha_file(dataset):
        raise ValueError("unexpected original dataset without an explicit predictor view")
    declared, linked, train, protocol = validate_registration(
        registration_dataset, data, features, registration, reconciliation)
    if modality != "text" or condition not in declared["conditions"]:
        raise ValueError("supplement is restricted to preregistered operational text conditions")
    task = declared["task_id"]
    calibration, _ = task_cohort(data["rows"], features, task, "calibration")
    if calibration is None:
        raise ValueError("supplement has no applicable calibration cohort")
    plan = {"schema": "hepta.calibrated-multitask-study.v2", "dataset_sha256": sha_file(dataset),
        "feature_receipt_sha256": sha_file(Path(feature_directory)/"report.json"),
        "feature_identity": receipt["feature_identity"], "condition": condition,
        "tasks": [task], "families": {task: task_family(data, task)},
        "code_sha256": code_hashes(), "protocol": protocol,
        "holdout_use": declared["holdout_use"], "input_modality": modality,
        "target_selection": "one availability-derived task declared before operational scoring",
        "source_authenticity_verified_by_head_runner": False,
        "feature_extraction_cost": {k: receipt.get(k) for k in ("load", "encoding")},
        "supplement": {"registration_sha256": sha_file(registration),
            "input_reconciliation_sha256": sha_file(reconciliation),
            "source_dataset_sha256": sha_file(registration_dataset),
            "head_predictor_view": view_binding,
            "wrapper_sha256": sha_file(__file__), "primary_budgets": [8, 32, 128],
            "primary128_status": "unavailable for this diagnostic task; never replaced by n122",
            "original_selected_tasks": data["selected_tasks"],
            "training_class_counts": declared["training_class_counts"],
            "maximum_balanced_independent_training_budget": 122,
            "input_reconciliation": linked}}
    root = Path(output)
    if root.exists():
        if json.loads((root/"study-plan.json").read_bytes()) != plan:
            raise ValueError("existing supplement plan differs; no overwrite or retuning allowed")
    else:
        if phase == "evaluate":
            raise ValueError("supplement evaluation needs an already frozen preparation")
        root.mkdir(parents=True)
        write_json(root/"study-plan.json", plan)
    prepared, evaluation = root/task/"prepared", root/task/"evaluation"
    if phase in ("prepare", "all"):
        started = time.perf_counter_ns()
        if prepared.exists():
            frozen = verify_prepared(prepared)
        else:
            frozen = prepare_curve(train, calibration, feature_identity=receipt["feature_identity"],
                output_dir=prepared, task_id=task, family_id=plan["families"][task],
                protocol={"budgets": [122]}, input_modality=modality, input_content_sha256=identity)
        validate_preparation(frozen, train, calibration, task, plan["families"][task], receipt["feature_identity"], protocol)
        selection = {"all_declared_tasks_frozen_before_any_evaluation": True,
            "seals": {f"{task}/prepared/seal.json": sha_file(prepared/"seal.json")}}
        if (root/"selection-seal.json").exists():
            if json.loads((root/"selection-seal.json").read_bytes()) != selection:
                raise ValueError("supplement preparation changed after selection freeze")
        else:
            write_json(root/"selection-seal.json", selection)
            write_json(root/"preparation-timing.json", {"wall_ns": time.perf_counter_ns()-started})
    if phase == "prepare":
        return {"status": "prepared", "tasks": [task], "output": str(root)}
    validate_preparation(verify_prepared(prepared), train, calibration, task,
                         plan["families"][task], receipt["feature_identity"], protocol)
    selection = {"all_declared_tasks_frozen_before_any_evaluation": True,
        "seals": {f"{task}/prepared/seal.json": sha_file(prepared/"seal.json")}}
    if json.loads((root/"selection-seal.json").read_bytes()) != selection:
        raise ValueError("supplement selection seal changed before evaluation")
    if evaluation.exists():
        if json.loads((evaluation/"seal.json").read_bytes()) != {
                "schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(evaluation)}:
            raise ValueError("completed supplement evaluation inventory changed")
        report = json.loads((evaluation/"report.json").read_bytes())
    else:
        holdout, _ = task_cohort(data["rows"], features, task, "holdout")
        if holdout is None:
            raise ValueError("supplement has no applicable heldout cohort")
        report = evaluate_curve(holdout, feature_identity=receipt["feature_identity"],
            prepared_dir=prepared, output_dir=evaluation, holdout_use=declared["holdout_use"],
            input_modality=modality, input_content_sha256=identity)
    summary = {"plan": plan, "tasks_evaluated": [task], "unavailable_tasks": [],
        "unavailable_budgets": {task: report["unavailable"]},
        "selection_seal_sha256": sha_file(root/"selection-seal.json"),
        **compact_summary({task: report})}
    if (root/"summary.json").exists():
        if json.loads((root/"summary.json").read_bytes()) != summary:
            raise ValueError("existing supplement summary differs")
    else:
        write_json(root/"summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dataset", "features", "output", "registration", "reconciliation", "condition"):
        parser.add_argument(f"--{key}", required=True)
    parser.add_argument("--phase", choices=("prepare", "evaluate", "all"), default="prepare")
    parser.add_argument("--source-dataset")
    args = parser.parse_args()
    result = run_supplement(args.dataset, args.features, args.output,
        registration=args.registration, reconciliation=args.reconciliation,
        condition=args.condition, phase=args.phase, source_dataset=args.source_dataset)
    print(json.dumps({"status": result.get("status", "complete"), "output": args.output}), flush=True)


if __name__ == "__main__":
    main()
