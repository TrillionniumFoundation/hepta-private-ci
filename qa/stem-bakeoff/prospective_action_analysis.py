"""Score sealed all-proposal inference under an immutable pre-label analysis plan."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from cell_group_metrics import group_weighted_metrics
from cell_learning_models import canonical
from prospective_action_compare import compare_action_conditions
from prospective_action_learning_run import verify_inference
from prospective_action_ranking import rank_actions
from prospective_analysis_artifacts import CapturedArtifacts, load_condition, validate_dataset, verify_alias_lineage
from prospective_analysis_plan import (ARMS, BUDGETS, CONDITIONS, CONTROLS, SEEDS,
    code_hashes, fixed_contrasts, sha)


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def denominators(registry, available, task_id, rows):
    """Report proposal and source/feature/outcome support without erasing unknowns."""
    records = {}
    for group in registry:
        record = records.setdefault(group["repo"], {"split": group["split"], "proposed_groups": 0,
            "proposed_actions": 0, "source_available_actions": 0, "feature_available_actions": 0,
            "valid_outcome_actions": 0, "feature_and_valid_outcome_actions": 0,
            "positive_outcome_actions": 0, "negative_outcome_actions": 0, "unknown_outcome_actions": 0,
            "source_available_groups": 0, "feature_available_groups": 0, "valid_outcome_groups": 0,
            "feature_and_valid_outcome_groups": 0})
        if record["split"] != group["split"]:
            raise ValueError("project crosses frozen roles")
        record["proposed_groups"] += 1
        supported = [False]*4
        for action in group["actions"]:
            source, label = action["source_id"], action["label"]
            source_ok, feature_ok, valid = source in rows, source in available, label is not None
            if source_ok and rows[source]["labels"][task_id] != label:
                raise ValueError("proposal/source outcome differs")
            record["proposed_actions"] += 1
            for index, (key, flag) in enumerate(zip(("source_available", "feature_available", "valid_outcome",
                    "feature_and_valid_outcome"), (source_ok, feature_ok, valid, feature_ok and valid))):
                record[key+"_actions"] += flag
                supported[index] |= flag
            record[("unknown" if label is None else "positive" if label else "negative")+"_outcome_actions"] += 1
        for key, flag in zip(("source_available", "feature_available", "valid_outcome", "feature_and_valid_outcome"), supported):
            record[key+"_groups"] += flag
    return records


def _ranking_summary(report):
    return {key: value for key, value in report.items() if key != "group_records"}


def _score_variant(item, source_ids, public, rows, task, registry, expected):
    values = item["values"]
    known = np.asarray([rows[source]["labels"][task] is not None for source in source_ids], dtype=bool)
    indices = np.flatnonzero(known)
    labels = np.asarray([rows[source_ids[i]]["labels"][task] for i in indices], dtype=np.int64)
    semantic = (group_weighted_metrics(values["probabilities"][known], labels, [public[i] for i in indices],
        eligible=values["eligible"][known], threshold=.7, calibration_prior=item["prior"]) if len(indices)
        else {"status": "unavailable_no_valid_outcome_feature_rows", "rows": 0, "groups": 0})
    scores = {source: {"score": float(values["probabilities"][i, 1]), "eligible": bool(values["eligible"][i])}
              for i, source in enumerate(source_ids)}
    ranking = rank_actions(registry, scores, method_kind="calibrated_probability", expected_group_ids=expected)
    coverage = {"feature_available_holdout_rows": len(source_ids), "valid_outcome_feature_rows": int(known.sum()),
        "unknown_outcome_feature_rows": int((~known).sum()), "arm_eligible_holdout_rows": int(values["eligible"].sum()),
        "arm_eligible_valid_outcome_rows": int((values["eligible"] & known).sum()),
        "arm_eligible_unknown_outcome_rows": int((values["eligible"] & ~known).sum()),
        "source_order_sha256": sha(canonical(source_ids)), "unknown_outcomes_relabelled_negative": False}
    return {"semantic": semantic, "ranking": ranking, "coverage": coverage,
            "prediction_receipt": item["receipt"]}, (indices, labels)


def score_verified(plan, dataset, conditions, output):
    """Numeric analysis only; caller authenticates every supplied artifact first."""
    rows, registry = validate_dataset(dataset, plan)
    expected, task = plan["expected_holdout_group_ids"], plan["task_id"]
    raw_scores = {source: {"score": score, "eligible": True} for source, score in plan["raw_jaccard"].items()}
    ranking_controls = {
        "raw_jaccard": rank_actions(registry, raw_scores, method_kind="identifier_jaccard", expected_group_ids=expected),
        "command_hash": rank_actions(registry, {}, method_kind="command_hash", expected_group_ids=expected)}
    comparisons, summaries, cached = [], {}, {}
    for name in CONDITIONS:
        loaded = conditions[name]
        summary = {"feature_identity": plan["conditions"][name]["feature_identity"],
            "denominators_by_project": denominators(dataset["proposal_registry"],
                set(plan["conditions"][name]["feature_available_source_ids"]), task, rows), "runs": []}
        if loaded is None:
            summary.update(status="unavailable_preparation_or_inference", unavailable=conditions["unavailable"][name])
            summaries[name] = summary
            continue
        summary.update(status="complete", unavailable=loaded["report"]["unavailable"],
            cost_receipts={"preparation": loaded["preparation_reference"], "inference": loaded["inference_reference"],
                "scope": "Pinned complete child reports retain every search path, discarded update, baseline, calibrator and replay; nested costs are not summed here."})
        for (seed, budget), result in sorted(loaded["runs"].items()):
            run, detail, small = result["run"], {}, {}
            for variant, item in result["variants"].items():
                scored, (indices, labels) = _score_variant(item, loaded["source_ids"], loaded["public_rows"],
                    rows, task, registry, expected)
                detail[variant] = scored
                small[variant] = {**scored, "ranking": _ranking_summary(scored["ranking"])}
                key = (name, budget, variant)
                bank = cached.setdefault(key, {"name": "/".join(map(str, key)),
                    "source_ids": [loaded["source_ids"][i] for i in indices],
                    "group_ids": [loaded["public_rows"][i]["group_id"] for i in indices], "labels": labels,
                    "probabilities_by_seed": {}, "rankings_by_seed": {}})
                bank["probabilities_by_seed"][seed] = item["values"]["probabilities"][indices]
                bank["rankings_by_seed"][seed] = scored["ranking"]
            path = Path(output)/f"{name}-seed-{seed}-n-{budget}.json"
            write_json(path, {"condition": name, "seed": seed, "budget": budget,
                "selected_arm": run["selected_arm"], "selection_source": run["selection_source"], "variants": detail})
            summaries_entry = {"seed": seed, "budget": budget, "selected_arm": run["selected_arm"],
                "selection_source": run["selection_source"], "variants": small,
                "detail_file": path.name, "detail_sha256": sha(path.read_bytes()),
                "selected_is_alias_of_predeclared_arm": True, "selection_or_prior_fallback_is_learning_evidence": False}
            summary["runs"].append(summaries_entry)
        summaries[name] = summary
    for contrast in plan["contrasts"]:
        pair, missing = [], []
        for feature, arm in (contrast["left"], contrast["right"]):
            if feature is None:
                pair.append({"name": arm, "source_ids": [], "group_ids": [], "labels": [],
                    "probabilities_by_seed": None, "rankings_by_seed": {seed: ranking_controls[arm] for seed in SEEDS}})
            else:
                value = cached.get((feature, contrast["budget"], arm))
                absent = sorted(set(SEEDS)-set(value["rankings_by_seed"] if value else []))
                if absent:
                    missing.append({"condition": feature, "arm": arm, "seeds": absent})
                pair.append(value)
        comparisons.append({"definition": contrast, "status": "unavailable_missing_fixed_runs" if missing else "complete",
            "missing": missing, "result": None if missing else compare_action_conditions(*pair,
                proposal_registry=registry, expected_group_ids=expected)})
    return {"conditions": summaries, "ranking_only_controls": ranking_controls, "fixed_contrasts": comparisons,
        "proposed_holdout_groups": len(registry), "proposed_holdout_actions": sum(len(g["actions"]) for g in registry),
        "fixed_seeds": list(SEEDS), "outcome_join_scope": "Binary outcomes only for action metrics; all proposed groups for ranking.",
        "holdout_model_selection_performed": False, "quality_qualified": False, "authority": "DENY_ALL"}


def analyze(dataset_path, inference_root, analysis_plan, output, *, dataset_sha256,
            inference_report_sha256, inference_seal_sha256, analysis_plan_sha256):
    started, cpu, captured = time.perf_counter_ns(), time.process_time_ns(), CapturedArtifacts()
    plan = captured.document(analysis_plan, analysis_plan_sha256)
    if (plan["code_sha256"] != code_hashes() or plan["contrasts"] != fixed_contrasts()
            or plan["budgets"] != list(BUDGETS) or plan["seeds"] != list(SEEDS)
            or plan["arms"] != list(ARMS) or plan["controls"] != list(CONTROLS)
            or plan["outcomes_or_predictions_used"] or len(plan["expected_holdout_group_ids"]) != 48):
        raise ValueError("analysis plan/code must be frozen before labels and predictions")
    data = captured.document(dataset_path, dataset_sha256)
    rows, _ = validate_dataset(data, plan)
    root = Path(inference_root)
    captured.tree(root, inference_seal_sha256)
    global_report = captured.document(root/"report.json", inference_report_sha256)
    if (global_report != verify_inference(root) or global_report["plan"]["dataset_sha256"] != dataset_sha256
            or global_report["plan"]["input_dataset_sha256"] != plan["input_dataset_sha256"]):
        raise ValueError("global preparation/inference barrier differs from the frozen analysis condition")
    preparation_root = Path(global_report["preparation_root"])
    captured.tree(preparation_root, global_report["preparation_seal_sha256"])
    preparation = captured.document(preparation_root/"report.json", global_report["preparation_report_sha256"])
    for path, expected in preparation["plan"]["input_file_pins"].items():
        captured.read(path, expected)
    records = {r["name"]: r for r in global_report["conditions"]}
    if len(records) != len(global_report["conditions"]) or set(records) != set(CONDITIONS):
        raise ValueError("complete global condition registry required")
    loaded = {"unavailable": {}}
    for name in CONDITIONS:
        record = records[name]
        verify_alias_lineage(captured, record, plan["conditions"][name], plan, dataset_sha256)
        if not record.get("inference_dir"):
            if not str(record.get("status", "")).startswith("unavailable"):
                raise ValueError("absent inference requires an explicit unavailable condition")
            loaded[name], loaded["unavailable"][name] = None, record
            continue
        item = load_condition(captured, record, plan["conditions"][name], rows, dataset_sha256)
        item["preparation_reference"] = {"path": str(Path(record["prepared_dir"])/"frozen.json"),
            "sha256": record["preparation_report_sha256"], "wall_ns": item["frozen"]["wall_ns"],
            "cpu_ns": item["frozen"]["cpu_ns"]}
        item["inference_reference"] = {"path": str(Path(record["inference_dir"])/"report.json"),
            "sha256": record["inference_report_sha256"], "wall_ns": item["report"]["wall_ns"],
            "parent_cpu_ns": item["report"]["cpu_ns"],
            "fresh_process_child_cpu_ns": item["report"]["fresh_process_child_cpu_ns"]}
        loaded[name] = item
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = score_verified(plan, data, loaded, output)
    captured.verify()
    if code_hashes() != plan["code_sha256"]:
        raise ValueError("analysis implementation changed before publication")
    result.update(schema="hepta.prospective-action-analysis.v1", dataset_sha256=dataset_sha256,
        analysis_plan_sha256=analysis_plan_sha256, inference_report_sha256=inference_report_sha256,
        inference_seal_sha256=inference_seal_sha256, verified_input_files=captured.pins,
        cost={"wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
            "scope": "Inclusive verification, outcome joins, metrics, rankings, paired resampling and detail writes; excludes final report/seal writes.",
            "nested_preparation_inference_or_encoding_cost_added": False, "new_encoder_calls": 0,
            "new_private_updates": 0, "new_prediction_calls": 0},
        inherited_global_inference_receipt={"path": str(root/"report.json"), "sha256": inference_report_sha256})
    result["inherited_global_preparation_receipt"] = {"path": str(preparation_root/"report.json"),
        "sha256": global_report["preparation_report_sha256"],
        "scope": "Global inclusive receipt supersedes child preparation timings for cost aggregation."}
    write_json(output/"report.json", result)
    write_json(output/"seal.json", {"schema": "hepta.prospective-analysis-seal.v1", "files": {
        p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "dataset-sha256", "inference-root", "inference-report-sha256",
                 "inference-seal-sha256", "analysis-plan", "analysis-plan-sha256", "output"):
        parser.add_argument("--"+name, required=True)
    args = vars(parser.parse_args())
    analyze(args.pop("dataset"), args.pop("inference_root"), args.pop("analysis_plan"), args.pop("output"), **args)


if __name__ == "__main__":
    main()
