"""Extract fixed prospective results; never fit, predict or resample."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean


PINS = {
    "analysis-final/report.json": "97bff59582b512ec61d9e82a1909175da4c1df28cdb4079a3ca74f20929683f7",
    "analysis-final/seal.json": "4073c89d0de7b1223f105b9a6b88c75653a636ccf042717a81e8dffb97dd9353",
    "analysis-interpretation-check.json": "b30967f33636359242c2e11a47cfa50cf2ba075469ef1298cd75bfd68f3e8836",
    "private-cost-supplement.json": "8f73afc510e45eb1872d912261922ad1cef3a8bf9a8e5c69a893678f6a572528",
    "dataset-final/audit.json": "c225135963bdd2efe48b5d8649ceb3440db392fb2a856409ed4463cdf779fbd0",
    "learning-preparation/report.json": "77fac73c27874c1f4a81a574edd4c34054d437510d246fb8a3f5628c00f97e00",
    "learning-inference/report.json": "4b1e5c5d3ac8d96aa569e92a52c21f4bc5a92ba937cbd9c285348324ad64395a",
}
SEMANTIC = (
    "balanced_accuracy", "positive_recall", "nll", "brier_multiclass_sum",
    "ece10_equal_width", "coverage", "selective_risk", "overall_success",
    "forced_accuracy", "auroc", "balanced_success",
    "balanced_accuracy_at_prior_threshold", "positive_recall_at_prior_threshold",
)
RANKING = (
    "known_positive_hit_rate", "known_positive_hit_groups", "unknown_selections",
    "groups_selecting_unknown", "abstained_groups", "groups_with_recommendation",
    "selected_actions", "known_negative_selections",
)


def read_bound(root, name):
    payload = (root / name).read_bytes()
    if hashlib.sha256(payload).hexdigest() != PINS[name]:
        raise ValueError("changed source: " + name)
    return json.loads(payload)


def complete_mean(values):
    return None if any(value is None for value in values) else mean(values)


def derive(root):
    sources = {name: read_bound(root, name) for name in PINS}
    report = sources["analysis-final/report.json"]
    audit = sources["analysis-interpretation-check.json"]
    private = sources["private-cost-supplement.json"]
    if report["quality_qualified"] or report["holdout_model_selection_performed"]:
        raise ValueError("unexpected quality or selection status")
    if len(report["fixed_contrasts"]) != 63:
        raise ValueError("missing fixed contrasts")
    rows, selection = [], {}
    for condition, value in sorted(report["conditions"].items()):
        if value["status"] != "complete" or len(value["runs"]) != 9:
            raise ValueError("incomplete condition")
        selection[condition] = dict(Counter(run["selected_arm"] for run in value["runs"]))
        for budget in (8, 32, 64):
            runs = sorted((run for run in value["runs"] if run["budget"] == budget),
                          key=lambda run: run["seed"])
            if [run["seed"] for run in runs] != [7, 17, 29]:
                raise ValueError("changed fixed seeds")
            for arm in sorted(runs[0]["variants"]):
                variants = [run["variants"][arm] for run in runs]
                semantic = {
                    key: complete_mean([variant["semantic"][key] for variant in variants])
                    for key in SEMANTIC
                }
                ranks = {
                    str(k): {key: mean(variant["ranking"]["top_k"][str(k)][key]
                                       for variant in variants) for key in RANKING}
                    for k in (1, 2, 3)
                }
                positive = {
                    key: mean(variant["ranking"]["positive_threshold_recommendation"][key]
                              for variant in variants) for key in RANKING
                }
                rows.append({
                    "condition": condition, "budget": budget, "arm": arm,
                    "fixed_seeds": [7, 17, 29], "semantic": semantic,
                    "top_k": ranks, "positive_action_threshold_07": positive,
                    "valid_rows_each_seed": [variant["semantic"]["rows"] for variant in variants],
                    "valid_groups_each_seed": [variant["semantic"]["groups"] for variant in variants],
                    "arm_eligible_valid_rows_each_seed": [
                        variant["coverage"]["arm_eligible_valid_outcome_rows"] for variant in variants],
                    "positive_recommendation_groups_each_seed": [
                        variant["ranking"]["positive_threshold_recommendation"]["groups_with_recommendation"]
                        for variant in variants],
                    "selected_arm_each_seed": [run["selected_arm"] for run in runs],
                })
    by_key = {(row["condition"], row["budget"], row["arm"]): row for row in rows}
    for checked in audit["fixed_seed_means"]:
        actual = by_key[(checked["condition"], checked["budget"], checked["arm"])]
        for metric, value in checked["semantic"].items():
            if metric in actual["semantic"] and abs(actual["semantic"][metric] - value) > 1e-12:
                raise ValueError("independent mean differs")
    contrasts = []
    for comparison in report["fixed_contrasts"]:
        if comparison["status"] != "complete" or comparison["missing"]:
            raise ValueError("incomplete fixed contrast")
        result = comparison["result"]
        metrics = {}
        for metric, value in result["contrasts"].items():
            metrics[metric] = value if value.get("difference") is None else {
                "left": value["left"], "right": value["right"], "difference": value["difference"],
                "whole_bug_ci95": value["whole_bug_bootstrap"]["ci95"],
                "project_cluster_ci95": value["project_cluster_bootstrap"]["ci95"],
                "whole_bug_valid_replicates": value["whole_bug_bootstrap"]["valid_replicates"],
                "project_valid_replicates": value["project_cluster_bootstrap"]["valid_replicates"],
            }
        contrasts.append({"definition": comparison["definition"], "status": comparison["status"],
                          "metrics": metrics, "bootstrap": result["bootstrap"]})
    return {
        "schema": "hepta.prospective-report-facts.v1", "source_sha256": PINS,
        "derivation": "Arithmetic extraction of sealed metrics; no fitting, prediction, resampling or new qualification.",
        "authority": report["authority"], "quality_qualified": False,
        "units": {"logical_tasks": 1, "condition_budget_seed_runs": 27,
                  "saved_neural_heads": 81, "search_paths": 162, "fixed_contrasts": 63},
        "fit_counts": audit["fit_counts"], "heldout_outcomes": audit["heldout_outcomes"],
        "heldout_project_denominators": audit["heldout_project_denominators"],
        "role_denominators": audit["role_denominators"],
        "fixed_seed_means": rows, "fixed_contrasts": contrasts,
        "ranking_controls": audit["ranking_controls"], "selected_arm_counts": selection,
        "selected_arm_counts_all_conditions": audit["selected_arm_counts_all_conditions"],
        "cross_feature_training_draw_overlap": audit["cross_feature_training_draw_overlap"],
        "calibration": audit["calibration"],
        "private_cost": {key: private[key] for key in (
            "head_table", "trainable_parameters_all_saved_heads",
            "fp64_trainable_tensor_bytes_all_saved_heads", "normalization", "calibration",
            "serialized_preparation", "training_compute", "label_budget")},
        "interpretation_limits": audit["interpretation_limits_and_claim_checks"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = derive(Path(args.phase_root))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    print(json.dumps({"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "bytes": target.stat().st_size, "mean_rows": len(result["fixed_seed_means"]),
                      "fixed_contrasts": len(result["fixed_contrasts"])}))
