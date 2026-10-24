"""Fixed real-event learning curves, followed by independent dispatch scaling.

Completed tasks resume only under an identical source/feature/code plan and an
unchanged artifact inventory. Incomplete task directories are preserved and
rejected. The CLI keeps 8/32/128 examples, three seeds, and 200 updates fixed.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from cell_learning_curve import Cohort, run_curve
from cell_learning_models import NumpyCellHead, canonical
from cell_scale_probe import measure_scale

CURVE_CODE = ("real_cell_study.py", "real_cell_features.py", "cell_learning_curve.py",
              "cell_learning_models.py", "cell_learning_baselines.py", "cell_learning_metrics.py")
METRICS = ("forced_accuracy", "balanced_accuracy", "positive_recall", "overall_success",
           "coverage", "selective_accuracy", "nll", "brier_multiclass_sum", "ece10_equal_width")


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    temporary.replace(path)


def code_hashes(names):
    return {name: sha_file(Path(__file__).with_name(name)) for name in names}


def inventory_digest(root):
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("study artifacts may not traverse linked files")
        if path.is_file():
            files.append([str(path.relative_to(root)), path.stat().st_size, sha_file(path)])
    return hashlib.sha256(canonical(files)).hexdigest()


def source_files(paths):
    resolved = sorted({Path(path).resolve() for path in paths})
    if any(not path.is_file() for path in resolved):
        raise ValueError("source preservation requires explicit existing files")
    return [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha_file(path)} for path in resolved]


def cohorts_for_task(rows, features, task):
    result = []
    for split in ("train", "calibration", "holdout"):
        indices = [i for i, row in enumerate(rows) if row["split"] == split]
        labels = [rows[i]["labels"][task] for i in indices]
        if any(type(label) is not int or label not in (0, 1) for label in labels):
            raise ValueError("binary task labels must be exact integers")
        public = tuple({key: rows[i][key] for key in ("source_id", "group_id", "text")} for i in indices)
        result.append(Cohort(features[indices], np.array(labels, dtype=np.int64), public, split))
    return tuple(result)


def metric_rows(task, report):
    rows = []
    for run in report["runs"]:
        for name, arm in run["arms"].items():
            for control, scored in [("trained", arm), *arm.get("controls", {}).items()]:
                train = arm.get("training", {}) if control == "trained" else {}
                evaluation = arm.get("evaluation_cost", {}) if control == "trained" else {}
                rows.append({"task": task, "seed": run["seed"], "budget": run["budget"],
                    "arm": name, "control": control,
                    **{metric: scored["semantic"][metric] for metric in METRICS},
                    "trainable_parameters": train.get("trainable_parameters", arm.get("trainable_parameters")),
                    "training_wall_ns": train.get("wall_ns"), "training_cpu_ns": train.get("cpu_ns"),
                    "prediction_wall_ns": evaluation.get("wall_ns", arm.get("prediction_wall_ns") if control == "trained" else None),
                    "prediction_cpu_ns": evaluation.get("cpu_ns"),
                    "fresh_process_match": arm.get("fresh_process", {}).get("matched") if control == "trained" else None})
    return rows


def compact_summary(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["budget"], row["arm"], row["control"]), []).append(row)
    result = []
    for (budget, arm, control), values in sorted(groups.items()):
        metrics = {}
        for metric in METRICS:
            present = [r[metric] for r in values if r[metric] is not None]
            metrics[metric] = {"mean": float(np.mean(present)) if present else None,
                               "std": float(np.std(present)) if present else None,
                               "observations": len(present)}
        result.append({"budget": budget, "arm": arm, "control": control, "metrics": metrics,
                       "task_count": len({v["task"] for v in values}), "rows": len(values)})
    return result


def _finish(root, data, features, feature_report, task_reports, plan, source_paths, source_recovery):
    from real_cell_study_queue import run_queue_stage
    phase_code = code_hashes(("real_cell_study_queue.py", "cell_training_queue.py",
                             "cell_batch_runtime.py", "cell_scale_probe.py"))
    phase_plan = {"study_plan_sha256": hashlib.sha256(canonical(plan)).hexdigest(),
                  "code": phase_code, "source_files": source_files(source_paths),
                  "source_recovery_report_sha256": None if source_recovery is None else source_recovery["report_sha256"]}
    if source_recovery is not None and not any(
            record["sha256"] == source_recovery["archive_sha256"]
            and record["bytes"] == source_recovery["compressed_archive_bytes"] for record in phase_plan["source_files"]):
        raise ValueError("source recovery archive must be provided unchanged as a source path")
    receipt_path = root / "finalization.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_bytes())
        if (previous["plan"] != phase_plan
                or any(sha_file(root / name) != digest for name, digest in previous["reports"].items())
                or inventory_digest(root / "queue") != previous["queue_inventory_sha256"]):
            raise ValueError("completed queue/scale evidence or its implementation changed")
        return previous
    identity, rows, tasks = plan["feature_identity"], data["rows"], data["selected_tasks"]
    by_id = {row["source_id"]: i for i, row in enumerate(rows)}
    heads, keys, training_ids = [], [], {}
    for task in tasks:
        curve = task_reports[task]
        large = next(run for run in curve["runs"] if run["seed"] == 7 and run["budget"] == 128)
        small = next(run for run in curve["runs"] if run["seed"] == 7 and run["budget"] == 32)
        heads.append(NumpyCellHead.load(root / "curves" / task / large["arms"]["gated"]["artifact"], identity))
        positive = [by_id[source] for source in large["training_source_ids"] if rows[by_id[source]]["labels"][task] == 1]
        if not positive or any(rows[index]["split"] != "train" for index in positive):
            raise ValueError("router prototypes require actual positive training sources")
        keys.append(features[positive].mean(axis=0))
        training_ids[task] = small["training_source_ids"]
    queue_report = run_queue_stage(root / "queue", tasks, training_ids, rows, features,
                                  feature_report["source_record_digests"], identity, steps=plan["steps"])
    write_json(root / "queue-report.json", queue_report)
    selected = [i for i, row in enumerate(rows) if row["split"] == "holdout"
                and any(row["labels"][task] for task in tasks)][:16]
    if not selected:
        raise ValueError("positive task-routing evaluation cohort is empty")
    encoder = {"feature_identity": identity, "observation_kind": "measured", **feature_report["encoding"],
               "model_parameter_bytes": feature_report["load"]["loaded_model"]["resident_tensor_storage_bytes"],
               "modality_parameter_bytes": 0, "scope": "text profile; complete corpus encoding before dispatch"}
    scale = measure_scale(heads, tasks, features[selected],
        [feature_report["source_record_digests"][i] for i in selected], identity,
        router_keys=np.stack(keys), relevant_task_ids=[{task for task in tasks if rows[i]["labels"][task]} for i in selected],
        encoder_receipt=encoder, source_paths=source_paths, queue_report=queue_report)
    scale["routing_evaluation"] = {"selection": "first 16 holdout events with at least one positive task",
        "source_ids": [rows[i]["source_id"] for i in selected],
        "relevance": "positive target labels used only for cohort eligibility and scoring",
        "prototype_sources": "only positive rows among each head's actual seed7 n128 training IDs",
        "task_families": data["protocol"]["task_family_count"]}
    for result in scale["results"]:
        result["cost_ledger"]["recovery"] = {"training_queue": result["cost_ledger"]["recovery"],
                                               "source_archive": source_recovery}
    write_json(root / "scale-report.json", scale)
    if code_hashes(tuple(phase_code)) != phase_code or source_files(source_paths) != phase_plan["source_files"]:
        raise ValueError("queue/scale implementation or preserved sources changed during finalization")
    result = {"plan": phase_plan, "reports": {name: sha_file(root / name) for name in
              ("queue-report.json", "scale-report.json")},
              "queue_inventory_sha256": inventory_digest(root / "queue")}
    write_json(receipt_path, result)
    return result


def run_study(dataset, feature_directory, output, *, resume=False, phase="all",
              source_paths=(), source_report=None, budgets=(8, 32, 128), seeds=(7, 17, 29), steps=200):
    from real_cell_features import load_features
    if phase not in ("all", "curves", "finalize"):
        raise ValueError("unknown study phase")
    dataset, feature_directory, root = Path(dataset), Path(feature_directory), Path(output)
    data = json.loads(dataset.read_bytes())
    features, feature_report = load_features(feature_directory, dataset)
    tasks, rows = data["selected_tasks"], data["rows"]
    if (not 1 <= len(tasks) <= 64 or len(set(tasks)) != len(tasks)
            or any(type(task) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", task) is None for task in tasks)
            or len(rows) != len(features)
            or [r["source_id"] for r in rows] != feature_report["plan"]["source_ids"]
            or len(feature_report["source_record_digests"]) != len(rows)):
        raise ValueError("task plan, source order or feature rows differ")
    plan = {"schema": "hepta.real-cell-study.v1", "dataset_sha256": sha_file(dataset),
        "feature_archive_sha256": feature_report["feature_archive_sha256"],
        "feature_receipt_sha256": sha_file(feature_directory / "report.json"),
        "feature_identity": feature_report["feature_identity"], "selected_tasks": tasks,
        "task_definition_sha256": data["protocol"]["definition_sha256"],
        "task_family_count": data["protocol"]["task_family_count"], "budgets": list(budgets),
        "seeds": list(seeds), "steps": steps, "rank": 8, "max_parameters": 100000,
        "threshold": 0.7, "source_code_sha256": code_hashes(CURVE_CODE)}
    source_recovery = None
    if source_report is not None:
        recovered = json.loads(Path(source_report).read_bytes())
        if (recovered.get("schema") != "hepta.exact-source-recovery.v1"
                or recovered.get("dataset_sha256") != plan["dataset_sha256"]
                or any(type(recovered.get(key)) is not int for key in
                       ("source_count", "byte_exact_recoveries", "missing_or_stale_rejections", "compressed_archive_bytes"))
                or recovered["source_count"] != len(rows) or recovered["byte_exact_recoveries"] != len(rows)
                or recovered["missing_or_stale_rejections"] < 2 or recovered["compressed_archive_bytes"] <= 0
                or recovered.get("fresh_process") is not True
                or type(recovered.get("archive_sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", recovered["archive_sha256"]) is None):
            raise ValueError("source-recovery receipt does not bind this event corpus")
        source_recovery = {key: value for key, value in recovered.items() if key != "read_results"}
        source_recovery.update(report_path=str(Path(source_report).resolve()), report_sha256=sha_file(source_report))
    plan_path = root / "study-plan.json"
    if root.exists():
        if not resume or not plan_path.is_file() or json.loads(plan_path.read_bytes()) != plan:
            raise ValueError("resume requires an identical dataset, feature, numerical and driver plan")
    else:
        root.mkdir(parents=True)
        write_json(plan_path, plan)
    (root / "curves").mkdir(exist_ok=True)
    (root / "completed").mkdir(exist_ok=True)
    binding = hashlib.sha256(canonical(plan)).hexdigest()
    reports, metrics = {}, []
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    for position, task in enumerate(tasks):
        target, completed = root / "curves" / task, root / "completed" / (task + ".json")
        if completed.exists():
            seal = json.loads(completed.read_bytes())
            if (seal["plan_sha256"] != binding or seal["task"] != task
                    or seal["inventory_sha256"] != inventory_digest(target)):
                raise ValueError("completed task artifacts changed; refusing resume")
            report = json.loads((target / "report.json").read_bytes())
        else:
            if target.exists() or phase == "finalize":
                raise ValueError("incomplete task retained; only sealed completed tasks can resume")
            cohorts = cohorts_for_task(rows, features, task)
            report = run_curve(*cohorts, feature_identity=plan["feature_identity"], classes=2,
                               output_dir=target, budgets=budgets, seeds=seeds, steps=steps,
                               rank=plan["rank"], max_parameters=plan["max_parameters"], threshold=plan["threshold"])
            if report["status"] != "complete":
                raise ValueError("declared learning budget unavailable; no partial task is sealed")
            write_json(completed, {"plan_sha256": binding, "task": task,
                                    "inventory_sha256": inventory_digest(target)})
        reports[task] = report
        metrics.extend(metric_rows(task, report))
        print(json.dumps({"completed_tasks": position + 1, "total_tasks": len(tasks), "task": task,
                          "curve_wall_ns": report["wall_ns"]}), flush=True)
    with (root / "metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)
    summary = {"plan": plan, "task_count": len(tasks), "task_family_count": plan["task_family_count"],
        "aggregate": compact_summary(metrics), "aggregate_interpretation": "descriptive task/seed means; correlated tasks are not independent trials",
        "curve_wall_ns_sum": sum(report["wall_ns"] for report in reports.values()),
        "feature_load": feature_report["load"], "feature_encoding": feature_report["encoding"],
        "source_recovery": source_recovery,
        "metrics_csv_sha256": sha_file(root / "metrics.csv"), "full_curves_directory": "curves",
        "finalization": None}
    if phase != "curves":
        preserved = [dataset, feature_directory / "features.npz", feature_directory / "report.json", *source_paths]
        if source_report is not None:
            preserved.append(Path(source_report))
        summary["finalization"] = _finish(root, data, features, feature_report, reports, plan, preserved, source_recovery)
    summary["current_invocation_wall_ns"] = time.perf_counter_ns() - started
    summary["current_invocation_parent_cpu_ns"] = time.process_time_ns() - cpu_started
    if (sha_file(dataset) != plan["dataset_sha256"]
            or sha_file(feature_directory / "features.npz") != plan["feature_archive_sha256"]
            or sha_file(feature_directory / "report.json") != plan["feature_receipt_sha256"]
            or (source_report is not None and sha_file(source_report) != source_recovery["report_sha256"])
            or code_hashes(CURVE_CODE) != plan["source_code_sha256"]):
        raise ValueError("study inputs or implementation changed while running")
    write_json(root / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--phase", choices=("all", "curves", "finalize"), default="all")
    parser.add_argument("--source-path", action="append", default=[])
    parser.add_argument("--source-report")
    args = parser.parse_args()
    result = run_study(args.dataset, args.features, args.output, resume=args.resume,
                       phase=args.phase, source_paths=args.source_path, source_report=args.source_report)
    print(json.dumps({"task_count": result["task_count"], "task_family_count": result["task_family_count"],
                      "summary": str(Path(args.output) / "summary.json")}))


if __name__ == "__main__":
    main()
