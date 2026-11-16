#!/usr/bin/env python3
"""Independent arithmetic/pinning verifier for archived REAL CPU forwards.

This program does *not* execute a model. GitHub CI must not claim native
inference just because this read-only archival reanalysis passes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from native_lora_ood_probe import (
    ARMS, FAMILIES, PLAN_HEAD, SCHEMA, SEEDS, check_plan, family_summary, sha256
)


def verify(report, plan, source_script_path):
    tasks = check_plan(plan)
    expected = {r["id"]: r for r in tasks}
    if report.get("schema") != SCHEMA or report.get("authority") != "DENY_ALL_HOLD_NO_GO":
        raise ValueError("incorrect report schema/authority")
    if report.get("evaluation") != "PUBLIC_OPERATOR_OOD_EXPLORATORY_NOT_INDEPENDENT":
        raise ValueError("missing non-independent declaration")
    if report.get("selection") != "NO_UPDATE_RECOMMENDED_RESEARCH_ONLY_NOT_OWNER_DECISION":
        raise ValueError("unsupported adoption or selection")
    if report.get("precommitted_plan_head") != PLAN_HEAD or report.get("source_plan_pr") != 5960:
        raise ValueError("wrong protocol source identity")
    if report.get("original_training_pr") != 5905 or report.get("task_count_per_condition") != 24:
        raise ValueError("wrong original training evidence or task count")
    if report.get("script_sha256") != sha256(source_script_path):
        raise ValueError("unverified original inference program")
    if report.get("threads") != 4 or report.get("cpu_only") is not True:
        raise ValueError("unfrozen hardware opportunity")
    if report.get("original_training_result_sha256") != (
        "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"):
        raise ValueError("wrong real training archive")
    conditions = ["base"] + [f"seed{seed} {arm}" for seed in SEEDS for arm in ARMS]
    if report.get("conditions") != conditions or len(report.get("runs", [])) != 9:
        raise ValueError("missing or reordered original model condition")
    if [r.get("condition") for r in report["runs"]] != conditions:
        raise ValueError("condition labels differ from declared order")
    recomputed = {}
    for run in report["runs"]:
        name = run["condition"]
        rows = run["predictions"]
        if len(rows) != 24 or set(r["id"] for r in rows) != set(expected):
            raise ValueError("missing/duplicate prompt identity")
        if len(set(r["id"] for r in rows)) != 24:
            raise ValueError("duplicate model score row")
        for r in rows:
            task = expected[r["id"]]
            if r["truth"] != task["truth"] or r["family"] != task["family"]:
                raise ValueError("model scores do not bind to the published task")
            prompt = task["question"].strip() + "\nAnswer:"
            if hashlib.sha256(prompt.encode()).hexdigest() != r["prompt_sha256"]:
                raise ValueError("prompt identity mismatch")
            p = r["p_yes"]
            if type(p) is not float or not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError("invalid model probability")
            pred = "yes" if p >= 0.5 else "no"
            if pred != r["prediction"] or (pred == task["truth"]) != r["correct"]:
                raise ValueError("prediction arithmetic or truth mismatch")
            logloss = -math.log(max(p if task["truth"] == "yes" else 1-p, 1e-12))
            brier = (p - (task["truth"] == "yes")) ** 2
            if abs(logloss - r["log_loss"]) > 2e-8 or abs(brier - r["brier"]) > 2e-8:
                raise ValueError("per-question proper score arithmetic mismatch")
        recalculated = family_summary(rows)
        for family in ("overall", *FAMILIES):
            expected_score = (run["scores"]["overall"] if family == "overall"
                              else run["scores"]["by_family"][family])
            actual_score = (recalculated["overall"] if family == "overall"
                            else recalculated["by_family"][family])
            for k in ("n", "yes_predictions", "accuracy", "mean_binary_log_loss", "mean_brier"):
                if abs(expected_score[k] - actual_score[k]) > 1e-8:
                    raise ValueError("per-family scored result mismatch")
        if (run["cost"]["load_plus_inference_wall_seconds"] < 0
                or run["cost"]["process_cpu_seconds"] < 0
                or run["cost"]["ru_maxrss_kib_lifetime_peak"] <= 0):
            raise ValueError("invalid measured resource fields")
        recomputed[name] = run["scores"]["overall"]
    if len(report.get("paired", [])) != len(SEEDS):
        raise ValueError("missing paired seed contrasts")
    for item, seed in zip(report["paired"], SEEDS):
        if item["seed"] != seed:
            raise ValueError("paired seeds not predeclared")
        a, b = recomputed[f"seed{seed} interleaved"], recomputed[f"seed{seed} bursty"]
        for metric, expected_delta in (
            ("bursty_minus_interleaved_accuracy", b["accuracy"]-a["accuracy"]),
            ("bursty_minus_interleaved_logloss",
             b["mean_binary_log_loss"]-a["mean_binary_log_loss"])):
            if abs(item[metric] - expected_delta) > 1e-8:
                raise ValueError("paired effect arithmetic mismatch")
    return {
        "verified_model_score_rows": sum(len(r["predictions"]) for r in report["runs"]),
        "conditions": len(conditions),
        "base_accuracy": recomputed["base"]["accuracy"],
        "per_condition_accuracy": {k: v["accuracy"] for k,v in recomputed.items()},
        "mean_bursty_minus_interleaved_logloss": statistics.fmean(
            x["bursty_minus_interleaved_logloss"] for x in report["paired"]),
        "independent_evaluator": False, "owner_authority": "DENY_ALL"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--plan", type=Path, default=Path(__file__).with_name("HPCA_V2_OOD_PLAN.json"))
    p.add_argument("--source", type=Path, default=Path(__file__).with_name("native_lora_ood_probe.py"))
    a = p.parse_args()
    result = json.loads(a.result.read_text())
    plan = json.loads(a.plan.read_text())
    if result.get("plan_sha256") != sha256(a.plan):
        raise ValueError("incorrect plan SHA-256")
    print(json.dumps(verify(result, plan, a.source), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
