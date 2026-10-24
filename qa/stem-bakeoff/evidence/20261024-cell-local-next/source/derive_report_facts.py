"""Read-only endpoint facts from already sealed learning evidence; no scoring."""

import argparse
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np

from cell_calibrated_curve import sha_file, write_json


METRICS = ("balanced_accuracy", "positive_recall", "nll", "brier_multiclass_sum",
    "ece10_equal_width", "coverage", "overall_success", "forced_accuracy",
    "balanced_success", "selective_risk", "auroc", "balanced_accuracy_at_prior_threshold")
ARMS = ("exact", "bm25", "dense_nearest", "prototype", "linear", "gated", "residual", "prior_only")


class Reader:
    def __init__(self):
        self.pins = {}

    def read(self, path):
        path = Path(path).resolve()
        blob = path.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if str(path) in self.pins and self.pins[str(path)] != digest:
            raise ValueError("input changed during facts derivation")
        self.pins[str(path)] = digest
        return json.loads(blob)

    def sealed(self, path):
        path = Path(path)
        report = self.read(path)
        seal = self.read(path.parent/"seal.json")
        if seal["files"][path.name]["sha256"] != self.pins[str(path.resolve())]:
            raise ValueError("report or frozen preparation differs from its seal")
        return report


def counts(ids, rows, task):
    unique = set(ids)
    support = Counter(rows[s]["labels"][task] for s in unique)
    return {"source_rows": len(unique), "source_groups": len({rows[s]["group_id"] for s in unique}),
            "class_support_rows": [support[0], support[1]]}


def score_of(run, name):
    if name == "frozen_tuning_selector":
        return run["arms"].get(run["selected_arm"])
    arm, _, control = name.partition(".")
    result = run["arms"].get(arm)
    return result.get("controls", {}).get(control) if result and control else result


def endpoint(reports, declared, seeds, family, budget):
    selected, missing = {}, []
    for task in declared:
        rows = {r["seed"]: r for r in reports[task]["runs"] if r["budget"] == budget}
        if set(rows) != set(seeds):
            missing.append({"task": task, "reason": "not all fixed seeds available at this registered budget",
                            "unavailable_records": [r for r in reports[task].get("unavailable", []) if r["budget"] == budget]})
        else:
            selected[task] = [rows[s] for s in seeds]
    names = [*ARMS, "frozen_tuning_selector", *[f"{m}.{c}" for m in ("linear", "gated", "residual")
                                               for c in ("parameters_off", "shuffled_parameters")]]
    table = []
    for name in names:
        cases = {t: [score_of(r, name) for r in runs] for t, runs in selected.items()}
        if not cases or any(any(v is None for v in values) for values in cases.values()):
            continue
        metrics = {}
        for metric in METRICS:
            means, unavailable = [], []
            for task, values in cases.items():
                values = [v["semantic"].get(metric, v.get("secondary_discrimination", {}).get(metric)) for v in values]
                if any(v is None for v in values):
                    unavailable.append(task)
                else:
                    means.append(statistics.mean(values))
            metrics[metric] = {"mean": statistics.mean(means) if means and not unavailable else None,
                               "tasks_observed": len(means), "tasks_with_unavailable_metric": unavailable}
        table.append({"arm": name, "metrics": metrics,
            "task_seed_prediction_cases": sum(len(v) for v in cases.values()),
            "accepted_prediction_decisions": sum(v["semantic"]["accepted"] for values in cases.values() for v in values),
            "all_prediction_decisions": sum(v["semantic"]["rows"] for values in cases.values() for v in values),
            "decision_counts_are_not_independent_source_counts": True})
    source_ids = {s for t in selected for s in reports[t]["source_ids"]}
    groups = {g for t in selected for g in reports[t]["group_ids"]}
    return {"family": family, "budget": budget,
        "status": "unavailable" if not selected else "partial_family" if missing else "complete",
        "declared_tasks": declared, "included_tasks": list(selected), "unavailable_tasks": missing,
        "fixed_seed_count": len(seeds), "distinct_heldout_source_rows": len(source_ids),
        "distinct_heldout_source_groups": len(groups), "arm_results": table,
        "tuning_selector_counts": dict(Counter(r["selected_arm"] for runs in selected.values() for r in runs)),
        "aggregation": "mean fixed seeds within each task, then equal task means within this family"}


def condition_facts(reader, entry, *, parent=None, lexical=False):
    root = Path(entry.get("study", entry.get("root")))
    if not (root/"summary.json").exists():
        return {"condition": entry.get("condition", entry.get("name")), "status": "pending",
                "study": str(root), "reason": "verified encoder bundle and frozen head scoring pending"}
    plan, summary = reader.read(root/"study-plan.json"), reader.read(root/"summary.json")
    if summary["plan"] != plan:
        raise ValueError("study plan and completed summary differ")
    dataset = Path(parent["dataset"] if parent else entry.get("source_dataset", entry.get("dataset")))
    data = reader.read(dataset)
    expected = plan.get("source_dataset_sha256", plan["dataset_sha256"]) if lexical else plan["dataset_sha256"]
    if reader.pins[str(dataset.resolve())] != expected:
        raise ValueError("fact table dataset is not the study's bound source")
    rows = {r["source_id"]: r for r in data["rows"]}
    prepared_root = Path(parent["study"]) if parent else root
    reports, preparations, task_labels, parameter_profiles = {}, {}, {}, {}
    fresh = Counter()
    for task in plan["tasks"]:
        reports[task] = reader.sealed(root/task/"evaluation/report.json")
        preparations[task] = reader.sealed(prepared_root/task/"prepared/frozen.json")
        frozen = preparations[task]
        p = frozen["plan"]
        task_labels[task] = {
            "available_training_pool_for_stratification": counts([s for s, r in rows.items()
                if r["split"] == "train" and r.get("labels", {}).get(task) is not None], rows, task),
            "fixed_tuning": counts(p["tuning_source_ids"], rows, task),
            "fixed_calibration": counts(p["calibration_source_ids"], rows, task),
            "heldout_scoring_only": counts(reports[task]["source_ids"], rows, task),
            "selected_support_by_budget": {}}
        for budget in plan["protocol"]["budgets"]:
            available = [r for r in frozen["runs"] if r["budget"] == budget]
            observations = [{"seed": r["seed"], "selected": counts(r["training_source_ids"], rows, task),
                "selected_plus_fixed_tuning_and_calibration": counts(r["training_source_ids"]+
                    p["tuning_source_ids"]+p["calibration_source_ids"], rows, task)} for r in available]
            task_labels[task]["selected_support_by_budget"][str(budget)] = observations or {
                "status": "unavailable", "records": [u for u in frozen["unavailable"] if u["budget"] == budget]}
        if not lexical:
            for run in frozen["runs"]:
                for mode in ("linear", "gated", "residual"):
                    if mode in parameter_profiles:
                        continue
                    spec = run["arms"][mode]
                    model = prepared_root/task/"prepared"/spec["artifact"]
                    manifest = reader.read(model/"manifest.json")
                    weight_path = model/"weights.npz"
                    weight_sha = sha_file(weight_path)
                    if weight_sha != manifest["weights_sha256"]:
                        raise ValueError("serialized head weights differ from manifest")
                    reader.pins[str(weight_path.resolve())] = weight_sha
                    with np.load(weight_path, allow_pickle=False) as arrays:
                        shapes = {k: list(arrays[k].shape) for k in arrays.files}
                        dtypes = sorted({str(arrays[k].dtype) for k in arrays.files})
                        scalars = sum(arrays[k].size for k in arrays.files)
                        size = sum(arrays[k].nbytes for k in arrays.files)
                    if scalars != spec["trainable_parameters"]:
                        raise ValueError("head parameter count differs from stored weights")
                    parameter_profiles[mode] = {"feature_width": manifest["width"], "classes": manifest["classes"],
                        "rank": manifest["rank"], "trainable_scalars": scalars, "stored_parameter_bytes": size,
                        "stored_parameter_dtypes": dtypes, "tensor_shapes": shapes,
                        "additional_private_calibration_scalars": 4,
                        "common_private_scalar_ceiling": plan["protocol"]["max_parameters"],
                        "normalization": manifest["normalization"], "observed_source_manifest": str(model/"manifest.json")}
        for run in reports[task]["runs"]:
            for arm in run["arms"].values():
                if "fresh_process" in arm:
                    fresh["fresh_process_checks"] += 1
                    fresh["fresh_process_bitwise_logits_and_probabilities"] += int(arm["fresh_process"]["bitwise_equal_logits_and_probabilities"])
                for control in arm.get("controls", {}):
                    fresh[control+"_scored_cases"] += 1
                fresh["parameter_unchanged_off_checks"] += int(arm.get("parameters_unchanged") is True)
                fresh["calibration_not_refitted_off_cases"] += int(arm.get("calibration_refitted") is False)
    endpoint_budget = max(plan["protocol"]["budgets"])
    shown_budgets = [endpoint_budget]
    if plan["holdout_use"] == "new_operational_holdout" and 32 in plan["protocol"]["budgets"] and 32 != endpoint_budget:
        shown_budgets.append(32)
    families = sorted(set(plan["families"].values()))
    tables = [endpoint(reports, [t for t in plan["tasks"] if plan["families"][t] == family],
                       plan["protocol"]["seeds"], family, budget) for family in families for budget in shown_budgets]
    resource = reader.read(entry["resource_ledger"]) if entry.get("resource_ledger") else None
    return {"condition": entry.get("condition", entry.get("name")), "status": "complete", "study": str(root),
        "kind": "full_text_lexical" if lexical else "modality_off" if parent else "main",
        "dataset_sha256": plan["dataset_sha256"], "source_dataset_sha256": expected,
        "feature_identity": plan["feature_identity"], "input_modality": plan["input_modality"],
        "holdout_use": plan["holdout_use"], "registered_gradient_budgets": plan["protocol"]["budgets"],
        "endpoint_budget": endpoint_budget, "fixed_seeds": plan["protocol"]["seeds"],
        "endpoint_policy": "largest registered budget; operational32 additionally predeclared; no best-score selection",
        "operating_threshold": plan["protocol"]["threshold"], "fixed_risk_thresholds": [0, .5, .6, .7, .8, .9, .95, 1],
        "families": tables, "task_label_counts": task_labels,
        "parameter_profiles": parameter_profiles, "feature_tensor_dtype": "float32" if not lexical else None,
        "fitted_prototype_scalar_count": 2*next(iter(parameter_profiles.values()))["feature_width"] if parameter_profiles else None,
        "zero_gradient_parameters_do_not_imply_zero_retrieval_or_prototype_storage": True,
        "control_verification_counts": dict(fresh),
        "modality_off_has_no_new_fitting": bool(parent),
        "head_cost": resource["head_cost"] if resource else None,
        "modality_off_scoring_cost": {k: summary[k] for k in ("wall_ns", "cpu_ns")} if parent else None,
        "source_authenticity_claim": "bound completed study; separate encoder/source replay receipts supply authenticity",
        "quality_promotion": False}


def derive(registry, root, output):
    reader, root = Reader(), Path(root)
    registry_data = reader.read(registry)
    main_entries = {e["condition"]: e for e in registry_data["main_studies"]}
    conditions = [condition_facts(reader, e) for e in main_entries.values()]
    conditions += [condition_facts(reader, e, parent=main_entries[e["parent_condition"]])
                   for e in registry_data["modality_off_controls"]]
    lexical = [condition_facts(reader, e, lexical=True) for e in registry_data["full_text_lexical"]]
    pairs = []
    for plan_name, directory, prefix in (("paired-analysis-plan.json", "paired-analysis", "calibrated"),
                                       ("full-text-lexical-analysis-plan.json", "full-text-lexical-analysis", "")):
        plan = reader.read(root/plan_name)
        for declared in plan["contrasts"]:
            path = root/directory/declared["name"]/"report.json"
            if not path.exists():
                pairs.append({**declared, "analysis_plan": plan_name, "status": "pending"})
                continue
            report = reader.sealed(path)
            pairs.append({**declared, "analysis_plan": plan_name, "status": report["status"],
                "report_sha256": reader.pins[str(path.resolve())], "families": report["families"],
                "joint_source_group_count": report["joint_source_group_count"],
                "bootstrap_draws": report["bootstrap_draws"], "bootstrap_seed": report["bootstrap_seed"],
                "source_pairing_verified": report["training_tuning_calibration_source_pairing_verified"],
                "unavailable_tasks": report["unavailable_tasks"], "holdout_use": report["holdout_use"],
                "confidence_scope": report["confidence_scope"]})
    if any(sha_file(path) != digest for path, digest in reader.pins.items()):
        raise ValueError("input evidence changed while deriving report facts")
    result = {"schema": "hepta.cell-final-report-facts.v1", "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "derivation_source_sha256": sha_file(__file__), "input_artifact_sha256": reader.pins,
        "main_and_modality_off_conditions": conditions, "full_text_lexical_conditions": lexical,
        "fixed_paired_contrasts": pairs,
        "completed_main_or_off_conditions": sum(c["status"] == "complete" for c in conditions),
        "pending_main_conditions": [c["condition"] for c in conditions if c["status"] == "pending"],
        "label_budget_interpretation": "8/32/128 and separate122 are selected gradient/support examples, not total labelled-data budgets; the full training pool is labelled for stratification and fixed disjoint tuning/calibration labels are additional. Task labels and reused seeds/conditions are correlated.",
        "confidence_scope": "source/bug-group resampling conditional on fixed datasets, repositories, trained heads and calibration cohorts; fixed seeds averaged within tasks and families kept separate; no multiplicity correction or uncertainty over new repositories/calibration cohorts",
        "source_disjointness_does_not_certify_foundation_pretraining_nonoverlap": True,
        "no_new_fitting_prediction_scoring_or_threshold_selection": True,
        "cross_family_grand_mean": None, "quality_promotion": False, "authority": "SHADOW_ONLY / DENY_ALL"}
    write_json(Path(output), result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("registry", "root", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    facts = derive(args.registry, args.root, args.output)
    print(json.dumps({"completed_conditions": facts["completed_main_or_off_conditions"],
                      "pending": facts["pending_main_conditions"], "output": args.output}))
