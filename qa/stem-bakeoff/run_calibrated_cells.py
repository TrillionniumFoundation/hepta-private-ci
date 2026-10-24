"""Generic two-phase calibrated studies on bound frozen feature bundles.

Missing/null task labels mean not applicable, never negative. Preparation for
all declared tasks completes and seals before the evaluation phase can start.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from cell_calibration_v2 import calibration_partition
from cell_calibrated_curve import (bounded_protocol, code_hashes, inventory, prepare_curve,
    sha_file, verify_prepared, write_json)
from cell_calibrated_evaluate import evaluate_curve
from cell_learning_curve import Cohort
from cell_learning_baselines import normalized_text
from cell_learning_models import canonical


def load_inputs(dataset, feature_directory):
    dataset, directory = Path(dataset), Path(feature_directory)
    if dataset.stat().st_size > 256*1024**2:
        raise ValueError("dataset manifest exceeds bounded size")
    data = json.loads(dataset.read_bytes())
    report = json.loads((directory/"report.json").read_bytes())
    rows = data["rows"]
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 16384
            or report["plan"]["dataset_sha256"] != sha_file(dataset)
            or report["plan"]["source_ids"] != [r["source_id"] for r in rows]
            or report["feature_archive_sha256"] != sha_file(directory/"features.npz")):
        raise ValueError("dataset, row order or feature archive differs from receipt")
    with np.load(directory/"features.npz", allow_pickle=False) as archive:
        if archive.files != ["features"]:
            raise ValueError("feature archive must contain only the feature matrix")
        features = archive["features"]
    if (features.dtype != np.float32 or features.ndim != 2 or len(features) != len(rows)
            or features.size > 16_777_216 or not np.isfinite(features).all()
            or list(features.shape) != report["feature_shape"]
            or hashlib.sha256(features.tobytes()).hexdigest() != report["feature_tensor_sha256"]):
        raise ValueError("feature shape, tensor bytes or precision differs")
    if (len({r["source_id"] for r in rows}) != len(rows)
            or any(r["split"] not in ("train", "calibration", "holdout") for r in rows)):
        raise ValueError("unique source IDs and explicit split roles required")
    modalities = {r.get("modality", "text") for r in rows}
    if len(modalities) != 1 or not modalities.issubset({"text", "image", "audio"}):
        raise ValueError("one explicit modality per frozen feature condition required")
    modality = next(iter(modalities))
    identity = {r["source_id"]: r.get("input_content_sha256") for r in rows} if modality != "text" else None
    if identity is not None and any(type(v) is not str or not re.fullmatch(r"[0-9a-f]{64}", v) for v in identity.values()):
        raise ValueError("every media row requires a full input-content SHA256")
    seen_groups, seen_predictors = set(), set()
    for split in ("train", "calibration", "holdout"):
        selected = [r for r in rows if r["split"] == split]
        groups = {r["group_id"] for r in selected}
        predictors = {normalized_text(r["text"]) if modality == "text" else identity[r["source_id"]] for r in selected}
        if groups & seen_groups or predictors & seen_predictors:
            raise ValueError("global cross-task source groups or predictor identities cross splits")
        seen_groups.update(groups)
        seen_predictors.update(predictors)
    features.flags.writeable = False
    return data, features, report, modality, identity


def task_cohort(rows, features, task, split):
    candidates = [i for i, row in enumerate(rows) if row["split"] == split]
    selected = [i for i in candidates if rows[i].get("labels", {}).get(task) is not None]
    counts = {"split_rows": len(candidates), "applicable_rows": len(selected),
              "not_applicable_rows": len(candidates)-len(selected)}
    if not selected:
        return None, counts
    labels = [rows[i]["labels"][task] for i in selected]
    if any(type(y) is not int or y not in (0, 1) for y in labels):
        raise ValueError("applicable task labels must be binary integers")
    public = tuple({k: rows[i][k] for k in ("source_id", "group_id", "text")} for i in selected)
    cohort = Cohort(features[selected], np.asarray(labels, dtype=np.int64), public, split)
    counts.update(groups=len({r["group_id"] for r in public}), class_support=np.bincount(labels, minlength=2).tolist())
    return cohort, counts


def task_family(data, task):
    definitions = data.get("task_definitions", {})
    definition = definitions.get(task, {}) if isinstance(definitions, dict) else next(
        (item for item in definitions if item.get("id", item.get("task_id")) == task), {})
    return definition.get("family_id", definition.get("family",
        data.get("family_id", data.get("protocol", {}).get("family", "unspecified"))))


def compact_summary(task_reports):
    metric_names = ("balanced_accuracy", "positive_recall", "nll", "brier_multiclass_sum",
                    "ece10_equal_width", "coverage", "overall_success", "forced_accuracy")
    groups, selections = {}, {}
    for task, report in task_reports.items():
        for run in report["runs"]:
            selections[(run["budget"], run["selected_arm"])] = selections.get((run["budget"], run["selected_arm"]), 0)+1
            for arm, scored in run["arms"].items():
                for control, result in [("trained", scored), *scored.get("controls", {}).items()]:
                    groups.setdefault((run["budget"], arm, control), []).append((task, result))
    aggregated = []
    for (budget, arm, control), values in sorted(groups.items()):
        metrics = {}
        for metric in metric_names:
            valid = [v["semantic"][metric] for _, v in values if v["semantic"][metric] is not None]
            metrics[metric] = {"mean": float(np.mean(valid)) if valid else None, "observations": len(valid)}
        aggregated.append({"budget": budget, "arm": arm, "control": control,
            "tasks": len({t for t, _ in values}), "task_seed_observations": len(values), "metrics": metrics})
    return {"macro": aggregated,
        "selector_counts": [{"budget": b, "arm": a, "count": n} for (b, a), n in sorted(selections.items())],
        "aggregation_scope": "descriptive equal task-seed means; correlated rows/tasks/seeds are not independent",
        "learning_or_winner_qualification": False}


def run_study(dataset, feature_directory, output, *, phase="prepare", holdout_use,
              condition="declared", protocol=None):
    if phase not in ("prepare", "evaluate", "all"):
        raise ValueError("unknown study phase")
    if holdout_use not in ("legacy_repeated_use_diagnostic", "new_operational_holdout", "new_multimodal_holdout", "fixture"):
        raise ValueError("explicit heldout reuse designation required")
    data, features, receipt, modality, content_identity = load_inputs(dataset, feature_directory)
    tasks = data["selected_tasks"]
    if (not isinstance(tasks, list) or not 1 <= len(tasks) <= 64 or len(set(tasks)) != len(tasks)
            or any(type(t) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", t) for t in tasks)):
        raise ValueError("fixed bounded selected task IDs required")
    configuration = bounded_protocol(protocol)
    plan = {"schema": "hepta.calibrated-multitask-study.v2", "dataset_sha256": sha_file(dataset),
        "feature_receipt_sha256": sha_file(Path(feature_directory)/"report.json"),
        "feature_identity": receipt["feature_identity"], "condition": condition,
        "tasks": tasks, "families": {t: task_family(data, t) for t in tasks},
        "code_sha256": code_hashes(), "protocol": configuration, "holdout_use": holdout_use,
        "input_modality": modality, "target_selection": "dataset predeclared selected_tasks; no heldout target selection",
        "source_authenticity_verified_by_head_runner": False,
        "feature_extraction_cost": {k: receipt.get(k) for k in ("load", "encoding")}}
    root = Path(output)
    if root.exists():
        if json.loads((root/"study-plan.json").read_bytes()) != plan:
            raise ValueError("existing study plan differs; no retuning or overwrite allowed")
    else:
        if phase == "evaluate":
            raise ValueError("evaluation needs an already frozen preparation")
        root.mkdir(parents=True)
        write_json(root/"study-plan.json", plan)
    if phase in ("prepare", "all"):
        preparation_start = time.perf_counter_ns()
        for task in tasks:
            task_root = root/task
            task_root.mkdir(exist_ok=True)
            prepared, unavailable = task_root/"prepared", task_root/"preparation-unavailable.json"
            if unavailable.exists():
                continue
            if prepared.exists():
                verify_prepared(prepared)
                continue
            train, train_count = task_cohort(data["rows"], features, task, "train")
            cal, cal_count = task_cohort(data["rows"], features, task, "calibration")
            reason = None
            if train is None or cal is None:
                reason = "empty applicable training or calibration split"
            else:
                try:
                    calibration_partition(cal.rows, configuration["calibration_partition_seed"], content_identity)
                except ValueError as error:
                    if str(error) != "calibration requires at least two disjoint source components":
                        raise
                    reason = str(error)
            if reason:
                write_json(unavailable, {"task": task, "reason": reason,
                    "train": train_count, "calibration": cal_count, "all_budgets_unavailable": configuration["budgets"]})
                continue
            prepare_curve(train, cal, feature_identity=receipt["feature_identity"], output_dir=prepared,
                task_id=task, family_id=plan["families"][task], protocol=protocol,
                input_modality=modality, input_content_sha256=content_identity)
            print(json.dumps({"phase": "prepared", "task": task, "condition": condition}), flush=True)
        seals = {}
        for task in tasks:
            path = root/task/"prepared/seal.json"
            if not path.exists():
                path = root/task/"preparation-unavailable.json"
            seals[str(path.relative_to(root))] = sha_file(path)
        selection = {"all_declared_tasks_frozen_before_any_evaluation": True, "seals": seals}
        selection_path = root/"selection-seal.json"
        if selection_path.exists():
            if json.loads(selection_path.read_bytes()) != selection:
                raise ValueError("frozen task preparations changed")
        else:
            write_json(selection_path, selection)
            write_json(root/"preparation-timing.json", {"wall_ns": time.perf_counter_ns()-preparation_start})
    if phase == "prepare":
        return {"status": "prepared", "tasks": tasks, "output": str(root)}
    selection = json.loads((root/"selection-seal.json").read_bytes())
    expected_seals = set()
    for task in tasks:
        if (root/task/"prepared").exists():
            verify_prepared(root/task/"prepared")
            expected_seals.add(f"{task}/prepared/seal.json")
        else:
            expected_seals.add(f"{task}/preparation-unavailable.json")
    if set(selection["seals"]) != expected_seals or selection["all_declared_tasks_frozen_before_any_evaluation"] is not True:
        raise ValueError("selection seal does not cover all declared tasks")
    if any(sha_file(root/path) != digest for path, digest in selection["seals"].items()):
        raise ValueError("selection seal changed before evaluation")
    task_reports, unavailable = {}, []
    for task in tasks:
        task_root = root/task
        if (task_root/"preparation-unavailable.json").exists():
            unavailable.append(json.loads((task_root/"preparation-unavailable.json").read_bytes()))
            continue
        holdout, counts = task_cohort(data["rows"], features, task, "holdout")
        if holdout is None:
            unavailable.append({"task": task, "reason": "empty applicable heldout split", "holdout": counts})
            continue
        evaluation = task_root/"evaluation"
        if evaluation.exists():
            if json.loads((evaluation/"seal.json").read_bytes()) != {"schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(evaluation)}:
                raise ValueError("completed evaluation inventory changed")
            task_reports[task] = json.loads((evaluation/"report.json").read_bytes())
        else:
            task_reports[task] = evaluate_curve(holdout, feature_identity=receipt["feature_identity"],
                prepared_dir=task_root/"prepared", output_dir=evaluation, holdout_use=holdout_use,
                input_modality=modality, input_content_sha256=content_identity)
            print(json.dumps({"phase": "evaluated", "task": task, "condition": condition}), flush=True)
    summary = {"plan": plan, "tasks_evaluated": list(task_reports), "unavailable_tasks": unavailable,
        "unavailable_budgets": {t: r["unavailable"] for t, r in task_reports.items()},
        "selection_seal_sha256": sha_file(root/"selection-seal.json"), **compact_summary(task_reports)}
    if (root/"summary.json").exists():
        if json.loads((root/"summary.json").read_bytes()) != summary:
            raise ValueError("existing summary differs")
    else:
        write_json(root/"summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "output", "holdout-use"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--phase", choices=("prepare", "evaluate", "all"), default="prepare")
    parser.add_argument("--condition", default="declared")
    args = parser.parse_args()
    result = run_study(args.dataset, args.features, args.output, phase=args.phase,
                       holdout_use=args.holdout_use, condition=args.condition)
    print(json.dumps({"status": result.get("status", "complete"), "output": args.output}), flush=True)


if __name__ == "__main__":
    main()
