"""Compare sealed fixed-update and fixed-formula-budget public studies.

This module performs no training and selects no winner. It verifies that both
studies used the same frozen model material, selected inputs, features, seed and
Head geometry, then reports paired outcome changes and observed work/exposure.
Equal updates and equal formula work are different estimands; neither alone is a
full system-cost or scientific-superiority certificate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from shared_learning_probe import score_sealed

SCHEMA = "hepta.public-schedule-comparison.v1"
_ALLOWED_STUDY_DIFFERENCES = {
    "schema", "study_id", "schedule", "training_flops_budget", "max_budget_steps"
}


def _read_experiment(root: Path, expected_seal_id: str):
    if (not isinstance(expected_seal_id, str) or len(expected_seal_id) != 64
            or any(c not in "0123456789abcdef" for c in expected_seal_id)):
        raise ValueError("externally retained study seal required")
    if (root / "FAILED.json").exists():
        raise ValueError("failed public study cannot enter schedule comparison")
    marker = strict_json(root / "COMMITTED.json")
    required = {"seal_id", "files"}
    if not isinstance(marker, dict) or set(marker) != required or marker["seal_id"] != expected_seal_id:
        raise ValueError("public study marker differs from retained seal")
    if not isinstance(marker["files"], dict) or set(marker["files"]) != {
            "scores.json", "selection.json", "STUDY.json", "source_files.json"}:
        raise ValueError("complete public study file inventory required")
    for name, digest in marker["files"].items():
        if file_sha256(root / name) != digest:
            raise ValueError("public study file changed after sealing: " + name)
    study = strict_json(root / "STUDY.json")
    selection = strict_json(root / "selection.json")
    scores = strict_json(root / "scores.json")
    run = strict_json(root / "controls" / "predictions.json")
    return dict(root=root, marker=marker, study=study, selection=selection,
                stored_scores=scores, run=run)


def _validate_top_marker(exp, expected_seal_id):
    # The top-level marker carries the controls seal as its seal_id. Its content
    # is not self-hashed, so the externally retained identity remains required.
    if exp["marker"]["seal_id"] != expected_seal_id:
        raise ValueError("top-level and retained controls seals differ")
    controls = strict_json(exp["root"] / "controls" / "COMMITTED.json")
    if controls.get("seal_id") != expected_seal_id:
        raise ValueError("top-level and controls seals differ")


def _correct(rows, labels):
    if (not isinstance(rows, list) or len(rows) != len(labels)
            or any(not isinstance(row, list) or len(row) != 4
                   or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                   for row in rows)):
        raise ValueError("complete finite four-class predictions required")
    return [int(max(range(4), key=row.__getitem__) == target)
            for row, target in zip(rows, labels, strict=True)]


def _paired_changes(left, right, labels):
    def summarize(indices):
        recovered = sum(left[i] == 0 and right[i] == 1 for i in indices)
        lost = sum(left[i] == 1 and right[i] == 0 for i in indices)
        return dict(rows=len(indices), recovered=recovered, lost=lost,
                    both_correct=sum(left[i] == right[i] == 1 for i in indices),
                    both_wrong=sum(left[i] == right[i] == 0 for i in indices),
                    accuracy_delta=(recovered - lost) / len(indices) if indices else None)
    per_class = {str(c): summarize([i for i, target in enumerate(labels) if target == c])
                 for c in range(4)}
    deltas = [v["accuracy_delta"] for v in per_class.values() if v["rows"]]
    return dict(overall=summarize(list(range(len(labels)))), per_class=per_class,
                worst_observed_class_delta=min(deltas),
                observed_class_regressions=[c for c, v in per_class.items()
                                            if v["rows"] and v["accuracy_delta"] < 0])


def _arm_map(score, run):
    scores = {arm["topology"]: arm for arm in score["arms"]}
    predictions = {row["topology"]: row for row in run["predictions"]}
    records = {row["topology"]: row for row in run["arms"]}
    if not (set(scores) == set(predictions) == set(records)):
        raise ValueError("score, prediction and execution arm inventories differ")
    return scores, predictions, records


def _training_summary(record):
    training = record.get("training")
    if not isinstance(training, dict):
        return dict(steps=None, examples_seen=None, observed_formula_work=None,
                    stop_reason="failed_or_missing_training")
    steps, examples = training.get("steps"), training.get("examples_seen")
    if type(steps) is not int or steps < 0 or type(examples) is not int or examples < 0:
        raise ValueError("invalid recorded update or exposure count")
    observed = record.get("work", {}).get("phase_flops", {}).get("train")
    if observed is not None and (type(observed) is not int or observed < 0):
        raise ValueError("invalid observed train work")
    budget = training.get("budget")
    stop = "fixed_update_limit"
    if budget is not None:
        if (not isinstance(budget, dict) or budget.get("observed") != observed
                or budget.get("updates") is None or len(budget["updates"]) != steps):
            raise ValueError("budget training record contradicts execution work")
        stop = budget.get("stop_reason")
    return dict(steps=steps, examples_seen=examples, observed_formula_work=observed,
                stop_reason=stop)


def compare_schedules(fixed_root, budget_root, labels, *,
                      expected_fixed_seal_id, expected_budget_seal_id):
    """Return a content-bound descriptive comparison; never train or select."""
    fixed = _read_experiment(Path(fixed_root), expected_fixed_seal_id)
    budget = _read_experiment(Path(budget_root), expected_budget_seal_id)
    _validate_top_marker(fixed, expected_fixed_seal_id)
    _validate_top_marker(budget, expected_budget_seal_id)
    if (not isinstance(labels, list) or not 4 <= len(labels) <= 128
            or any(type(v) is not int or not 0 <= v < 4 for v in labels)):
        raise ValueError("complete shared four-class labels required")
    if fixed["selection"] != budget["selection"]:
        raise ValueError("fixed-update and fixed-budget sample selections differ")
    if fixed["run"]["heldout_inputs"] != budget["run"]["heldout_inputs"] or \
            fixed["run"]["training_inputs"] != budget["run"]["training_inputs"]:
        raise ValueError("schedule studies used different input identities")
    if fixed["run"]["feature_sha256"] != budget["run"]["feature_sha256"]:
        raise ValueError("schedule studies used different frozen features")
    if fixed["run"]["training_labels_sha256"] != budget["run"]["training_labels_sha256"]:
        raise ValueError("schedule studies used different training labels")
    if fixed["stored_scores"].get("model_snapshot_sha256") != budget["stored_scores"].get("model_snapshot_sha256"):
        raise ValueError("schedule studies used different model snapshots")
    if fixed["stored_scores"].get("selected_material_id") != budget["stored_scores"].get("selected_material_id"):
        raise ValueError("schedule studies used different selected material")
    if fixed["study"].get("schema") != "hepta.public-shared-learning-config.v1" or \
            budget["study"].get("schema") != "hepta.public-shared-learning-config.v2":
        raise ValueError("fixed-update V1 and fixed-budget V2 are required")
    left_common = {k: v for k, v in fixed["study"].items() if k not in _ALLOWED_STUDY_DIFFERENCES}
    right_common = {k: v for k, v in budget["study"].items() if k not in _ALLOWED_STUDY_DIFFERENCES}
    if left_common != right_common:
        raise ValueError("schedule comparison changed a non-schedule control")

    fixed_score = score_sealed(fixed["root"] / "controls", labels,
                               expected_seal_id=expected_fixed_seal_id)
    budget_score = score_sealed(budget["root"] / "controls", labels,
                                expected_seal_id=expected_budget_seal_id)
    if fixed_score["labels_sha256"] != budget_score["labels_sha256"]:
        raise ValueError("schedule comparisons did not use one label vector")
    fs, fp, fr = _arm_map(fixed_score, fixed["run"])
    bs, bp, br = _arm_map(budget_score, budget["run"])
    if set(fs) != set(bs):
        raise ValueError("fixed-update and fixed-budget topology inventories differ")

    arms = []
    for name in fs:
        fixed_status, budget_status = fs[name]["status"], bs[name]["status"]
        entry = dict(topology=name, fixed_status=fixed_status, budget_status=budget_status,
                     fixed_training=_training_summary(fr[name]),
                     budget_training=_training_summary(br[name]))
        if fixed_status == budget_status == "completed":
            fixed_after = _correct(fp[name]["after"], labels)
            budget_after = _correct(bp[name]["after"], labels)
            entry.update(fixed_accuracy=fs[name]["after"]["accuracy"],
                         budget_accuracy=bs[name]["after"]["accuracy"],
                         accuracy_delta=bs[name]["after"]["accuracy"] - fs[name]["after"]["accuracy"],
                         fixed_brier=fs[name]["after"]["brier"],
                         budget_brier=bs[name]["after"]["brier"],
                         brier_delta=bs[name]["after"]["brier"] - fs[name]["after"]["brier"],
                         paired_quality=_paired_changes(fixed_after, budget_after, labels))
        else:
            entry.update(fixed_accuracy=None, budget_accuracy=None, accuracy_delta=None,
                         fixed_brier=None, budget_brier=None, brier_delta=None,
                         paired_quality=dict(status="unavailable_failed_arm", rows=len(labels)))
        arms.append(entry)

    report = dict(schema=SCHEMA,
        fixed_study_id=fixed["study"]["study_id"], budget_study_id=budget["study"]["study_id"],
        fixed_seal_id=expected_fixed_seal_id, budget_seal_id=expected_budget_seal_id,
        selected_material_id=fixed["stored_scores"]["selected_material_id"],
        model_snapshot_sha256=fixed["stored_scores"]["model_snapshot_sha256"],
        labels_sha256=fixed_score["labels_sha256"], heldout_rows=len(labels),
        fixed_schedule="equal_updates_and_nominal_exposure_not_equal_compute",
        budget_schedule="approximately_equal_observed_train_formula_work_not_equal_exposure",
        fixed_training_work_matched=fixed_score["observed_training_work_matched_within_one_percent"],
        budget_training_work_matched=budget_score["observed_training_work_matched_within_one_percent"],
        arms=arms,
        causal_topology_effect_identified=False, equal_data_exposure_and_compute_simultaneously=False,
        independent_replication=False, statistical_superiority_established=False,
        full_system_efficiency_established=False, production_authorized=False)
    report["comparison_id"] = _digest(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixed-dir", "budget-dir", "news-dir", "fixed-seal-id",
                 "budget-seal-id", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    from public_news_materials import prepare_news
    _, _, _, labels, material = prepare_news(args.news_dir)
    fixed_selection = strict_json(Path(args.fixed_dir) / "selection.json")
    budget_selection = strict_json(Path(args.budget_dir) / "selection.json")
    if material != fixed_selection or material != budget_selection:
        raise ValueError("live pinned material differs from both sealed selections")
    output = Path(args.output)
    output.mkdir(exist_ok=False)
    try:
        report = compare_schedules(args.fixed_dir, args.budget_dir, labels,
                                   expected_fixed_seal_id=args.fixed_seal_id,
                                   expected_budget_seal_id=args.budget_seal_id)
        write_json_exclusive(output / "comparison.json", report)
        write_json_exclusive(output / "COMMITTED.json", dict(
            comparison_id=report["comparison_id"],
            comparison_sha256=file_sha256(output / "comparison.json")))
        print(json.dumps({"comparison_id": report["comparison_id"],
                          "statistical_superiority_established": False}, sort_keys=True))
    except Exception as exc:
        write_json_exclusive(output / "FAILED.json", dict(
            error_type=type(exc).__name__, production_authorized=False))
        raise


if __name__ == "__main__":
    main()
