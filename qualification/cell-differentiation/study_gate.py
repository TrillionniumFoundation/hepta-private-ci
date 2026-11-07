"""Preregistered, independent research decision; never production authorization."""

from dataclasses import asdict

import numpy as np

from study_data import ARMS, canonical_bytes, digest
from study_evidence import audit_run, audit_source


def adjudicate(run, plan, source_digest):
    try:
        audit_run(run, plan, source_digest)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"decision": "HOLD", "reasons": [f"invalid_evidence: {exc}"], "production_authority": False}
    reasons = []
    evidence = run["demand_evidence"]
    if not evidence.get("persistent_demand"):
        reasons.append("no_persistent_demand")
    if not evidence.get("negative_transfer_observed"):
        reasons.append("negative_transfer_not_observed")
    for name, arm in run["arms"].items():
        if arm["failure"]:
            reasons.append(f"model_stage_failure:{name}")
        if any(arm[split]["summary"]["mse"] is None for split in ("validation", "test")):
            reasons.append(f"incomplete_observations:{name}")
        if not arm["cost"]["complete"]:
            reasons.append(f"incomplete_cost_evidence:{name}")
        if not arm["migration"]["exact_validation_behavior"]:
            reasons.append(f"migration_behavior_mismatch:{name}")
    if any(r.startswith(("model_stage_", "incomplete_", "migration_")) for r in reasons):
        return {"decision": "HOLD", "reasons": reasons, "production_authority": False}
    candidate = run["arms"]["demand_specialization"]
    incumbent = run["arms"]["frozen_incumbent"]
    old_regression = candidate["test"]["old_task"]["mse"] - incumbent["test"]["old_task"]["mse"]
    if old_regression > plan.policy.maximum_old_task_mse_increase:
        reasons.append("old_task_regression")
    gains = {}
    for name in ARMS[:-1]:
        gain = run["arms"][name]["test"]["summary"]["mse"] - candidate["test"]["summary"]["mse"]
        gains[name] = gain
        if gain < plan.policy.minimum_mse_gain:
            reasons.append(f"insufficient_gain_over:{name}")
    reference_ops = run["arms"]["continued_parent"]["cost"]["estimated_float_ops"]
    if candidate["cost"]["estimated_float_ops"] > reference_ops * plan.policy.maximum_float_ops_ratio_to_continued:
        reasons.append("total_algorithmic_compute_budget_exceeded")
    if candidate["cost"]["retained_parameter_bytes"] > plan.policy.maximum_parameter_bytes:
        reasons.append("parameter_storage_budget_exceeded")
    return {"decision": "RESEARCH_ELIGIBLE" if not reasons else "HOLD", "reasons": reasons,
            "paired_test_mse_gains": gains, "old_task_mse_increase": old_regression,
            "production_authority": False}


def summarize_study(runs, plan):
    summaries = {}
    for scenario in plan.scenarios:
        selected = [r for r in runs if r["scenario"] == scenario]
        complete_seeds = [r["seed"] for r in selected] == list(plan.seeds)
        metrics = {}
        for name in ARMS:
            losses = [r["arms"][name]["test"]["summary"]["mse"] for r in selected]
            old = [r["arms"][name]["test"]["old_task"]["mse"] for r in selected]
            ops = [r["arms"][name]["cost"]["estimated_float_ops"] for r in selected]
            metrics[name] = {
                "test_mse_mean": float(np.mean(losses)) if all(v is not None for v in losses) else None,
                "test_mse_across_seed_std": float(np.std(losses, ddof=1)) if len(losses) > 1 and
                    all(v is not None for v in losses) else None,
                "old_task_mse_mean": float(np.mean(old)) if all(v is not None for v in old) else None,
                "requested_test_predictions": sum(r["arms"][name]["test"]["summary"]["requested"] for r in selected),
                "completed_test_predictions": sum(r["arms"][name]["test"]["summary"]["completed"] for r in selected),
                "mean_estimated_float_ops_including_shared": float(np.mean(ops))
                    if all(v is not None for v in ops) else None,
            }
        eligible = complete_seeds and all(r["decision"]["decision"] == "RESEARCH_ELIGIBLE" for r in selected)
        summaries[scenario] = {
            "decision": "RESEARCH_ELIGIBLE" if eligible else "HOLD", "planned_seeds": list(plan.seeds),
            "observed_seeds": [r["seed"] for r in selected], "all_planned_seeds_required": True,
            "reasons_by_seed": {str(r["seed"]): r["decision"]["reasons"] for r in selected}, "arms": metrics,
            "uncertainty": "Across-seed standard deviation is descriptive, not a significance or generalization claim.",
            "production_authority": False,
        }
    return summaries


def audit_study(report, plan):
    if canonical_bytes(report["plan"]) != canonical_bytes(asdict(plan)) or report["plan_digest"] != digest(asdict(plan)):
        raise ValueError("study plan differs from its commitment")
    expected = [(scenario, seed) for scenario in plan.scenarios for seed in plan.seeds]
    if [(r["scenario"], r["seed"]) for r in report["runs"]] != expected:
        raise ValueError("planned trial denominator changed")
    audit_source(report)
    for run in report["runs"]:
        audit_run(run, plan, report["source_digest"])
        if run["decision"] != adjudicate(run, plan, report["source_digest"]):
            raise ValueError("decision differs from the preregistered gate")
    if report["summary"] != summarize_study(report["runs"], plan):
        raise ValueError("aggregate summary discarded trials or altered results")
    if report["production_authority"] is not False or report["rsi_proven"] is not False:
        raise ValueError("the study cannot authorize production adoption or claim RSI")
