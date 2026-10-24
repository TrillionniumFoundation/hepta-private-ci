"""Additive label-access and measured head-resource ledger from frozen studies."""

import argparse
import hashlib
import json
from pathlib import Path

from cell_calibrated_curve import inventory, sha_file, verify_prepared, write_json
from cell_learning_models import canonical


def label_counts(entries, rows_by_id):
    pairs = set(entries)
    sources = {source for _, source in pairs}
    if not sources.issubset(rows_by_id):
        raise ValueError("label ledger source is absent from bound dataset")
    return {"unique_source_rows": len(sources),
            "unique_source_groups": len({rows_by_id[source]["group_id"] for source in sources}),
            "source_target_label_entries": len(pairs)}


def summarize_resources(dataset, study, output):
    root = Path(study)
    data = json.loads(Path(dataset).read_bytes())
    plan = json.loads((root/"study-plan.json").read_bytes())
    summary = json.loads((root/"summary.json").read_bytes())
    if sha_file(dataset) != plan["dataset_sha256"]:
        raise ValueError("label source dataset differs from completed study")
    rows = {r["source_id"]: r for r in data["rows"]}
    stages = {name: set() for name in ("available_training_pool_for_stratification",
        "selected_gradient_training", "tuning", "calibration", "heldout_scoring_only")}
    runs, path_reports, preparations, evaluations, selection_binding = [], [], [], [], []
    saved_parameter_bytes = calibration_cpu = calibration_wall = calibration_iterations = 0
    baseline_max = 0
    for task in plan["tasks"]:
        prepared = root/task/"prepared"
        if not prepared.exists():
            continue
        frozen = verify_prepared(prepared)
        preparations.append(frozen)
        p = frozen["plan"]
        pools = {"available_training_pool_for_stratification": p["contexts"][0]["source_ids"],
                 "tuning": p["tuning_source_ids"], "calibration": p["calibration_source_ids"]}
        evaluation_path = root/task/"evaluation/report.json"
        if evaluation_path.exists():
            if json.loads((evaluation_path.parent/"seal.json").read_bytes()) != {
                    "schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(evaluation_path.parent)}:
                raise ValueError("completed evaluation inventory changed")
            evaluation = json.loads(evaluation_path.read_bytes())
            evaluations.append(evaluation)
            pools["heldout_scoring_only"] = evaluation["source_ids"]
        for stage, ids in pools.items():
            stages[stage].update((task, source) for source in ids)
        for run in frozen["runs"]:
            selected = run["training_source_ids"]
            stages["selected_gradient_training"].update((task, source) for source in selected)
            selection_binding.append([task, run["seed"], run["budget"], selected])
            fitted = [(task, source) for source in selected+p["tuning_source_ids"]+p["calibration_source_ids"]]
            runs.append({"task": task, "family": p["family_id"], "seed": run["seed"], "budget": run["budget"],
                "available_training_pool": label_counts([(task, s) for s in pools["available_training_pool_for_stratification"]], rows),
                "gradient_selected": label_counts([(task, s) for s in selected], rows),
                "tuning": label_counts([(task, s) for s in p["tuning_source_ids"]], rows),
                "calibration": label_counts([(task, s) for s in p["calibration_source_ids"]], rows),
                "heldout_scoring_only": label_counts([(task, s) for s in pools.get("heldout_scoring_only", [])], rows),
                "selected_gradient_plus_tuning_calibration": label_counts(fitted, rows),
                "selected_arm": run["selected_arm"], "optimizer_updates_all_paths": run["all_search_optimizer_steps"],
                "trainable_parameters_by_learned_arm": {m: run["arms"][m]["trainable_parameters"] for m in ("linear", "gated", "residual")}})
            path_reports.extend(run["search_paths"])
            baseline_max = max(baseline_max, run["baseline_retained_state"]["reachable_state_bytes"])
            for arm in run["arms"].values():
                saved_parameter_bytes += arm.get("training", {}).get("parameter_bytes", 0)
                fit = arm.get("calibration", {})
                calibration_cpu += fit.get("cpu_ns", 0)
                calibration_wall += fit.get("wall_ns", 0)
                calibration_iterations += fit.get("iterations", 0)
    total = lambda key: sum(p.get(key, 0) for p in path_reports)
    maximum = lambda key: max((p.get(key, 0) for p in path_reports), default=0)
    result = {"schema": "hepta.calibrated-label-resource-ledger.v1", "dataset_sha256": sha_file(dataset),
        "study_plan_sha256": sha_file(root/"study-plan.json"), "summary_sha256": sha_file(root/"summary.json"),
        "source_sha256": sha_file(__file__), "condition": plan["condition"],
        "label_stages": {name: label_counts(entries, rows) for name, entries in stages.items()},
        "per_task_seed_budget": runs,
        "label_budget_interpretation": "8/32/128 counts selected gradient examples, not total annotation or label access",
        "labels_shared_across_runs": "same fixed tuning/calibration cohorts reused across seeds, budgets and arms; unions are deduplicated",
        "target_labels_are_independent_annotations": False,
        "underlying_human_annotation_cost_measured": False,
        "label_reuse_across_feature_conditions": "same dataset/source/target identities must be deduplicated, not summed",
        "gradient_source_selection_sha256": hashlib.sha256(canonical(selection_binding)).hexdigest(),
        "head_cost": {"actual_optimizer_updates_all_paths": total("optimizer_steps"),
            "actual_example_updates_all_paths": total("example_updates"),
            "discarded_updates_after_selected_checkpoints": total("discarded_updates_after_selected"),
            "executed_dense_matmul_flops_all_paths": total("executed_dense_matmul_flops"),
            "estimated_elementwise_flops_all_paths": total("estimated_elementwise_flops"),
            "all_path_training_cpu_ns": total("cpu_ns"), "all_path_training_wall_ns": total("wall_ns"),
            "full_preparation_cpu_ns": sum(p["cpu_ns"] for p in preparations),
            "full_preparation_wall_ns": sum(p["wall_ns"] for p in preparations),
            "calibration_cpu_ns": calibration_cpu, "calibration_wall_ns": calibration_wall,
            "calibration_optimizer_iterations": calibration_iterations,
            "evaluation_parent_cpu_ns": sum(e["cpu_ns"] for e in evaluations),
            "evaluation_wall_ns": sum(e["wall_ns"] for e in evaluations),
            "fresh_process_child_cpu_ns": sum(e["fresh_process_child_cpu_ns"] for e in evaluations),
            "maximum_head_parameters": maximum("trainable_parameters"),
            "maximum_per_path_optimizer_state_bytes": maximum("optimizer_state_bytes"),
            "maximum_per_path_gradient_bytes": maximum("gradient_bytes"),
            "maximum_per_path_checkpoint_buffer_bytes": maximum("checkpoint_buffer_bytes"),
            "maximum_per_path_accounted_persistent_tensor_bytes": maximum("persistent_tensor_bytes_accounted"),
            "maximum_baseline_reachable_state_bytes": baseline_max,
            "all_saved_experimental_heads_parameter_bytes": saved_parameter_bytes,
            "global_process_or_concurrent_peak_rss_measured": False,
            "encoder_forward_calls_in_head_study": 0,
            "equal_parameter_cap_or_steps_imply_equal_cost": False},
        "feature_extraction_receipt_cost": plan["feature_extraction_cost"],
        "cost_scope": "matrix products counted, elementwise estimates, transcendentals excluded; cached feature extraction shown separately",
        "quality_qualification": False}
    write_json(Path(output), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "study", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    summarize_resources(args.dataset, args.study, args.output)


if __name__ == "__main__":
    main()
