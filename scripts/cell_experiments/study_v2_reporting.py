"""Descriptive paired business outcomes; no independent learning qualification."""

from . import data
from .study_v2_evidence import source_macro


def summarize(evaluation):
    rows = evaluation["rows"]
    failures = [row for row in rows if not row["first_attempt_success"]]
    return {
        "tasks": len(rows),
        "first_attempt_successes": sum(row["first_attempt_success"] for row in rows),
        "within_two_successes": sum(row["success"] for row in rows),
        "source_macro_first": source_macro(rows),
        "source_macro_within_two": source_macro(rows, "success"),
        "initial_failures": len(failures),
        "successful_recoveries": sum(row["success"] for row in failures),
        "recovery_rate_given_initial_failure": sum(row["success"] for row in failures)
        / len(failures)
        if failures
        else None,
        "executed_attempts": sum(
            step["executed"] for row in rows for step in row["steps"]
        ),
        "cost": evaluation["cost"],
        "evaluation_digest": data.digest(evaluation),
    }


def report_experiments(b, c, c_records, selection):
    e1_names = ("parent", "retrieval", "final_answer", "trajectory")
    e2_names = {
        "demonstration": "trajectory",
        "shadow": "e2_shadow",
        "controlled": "e2_controlled",
    }
    best = selection["E3_best_single"]
    indexed = {
        name: {row["task_id"]: row for row in value["rows"]}
        for name, value in c.items()
    }
    methods = {
        "best_single": indexed[best],
        "direct_mixture_sft": indexed["final_answer"],
        "domain_route": {
            r["task_id"]: indexed["specialist_" + r["task_domain"]][r["task_id"]]
            for r in c_records
        },
        "same_base_delta_integration": indexed["integrated"],
    }
    domains = sorted({r["task_domain"] for r in c_records})
    comparison = {}
    for name, chosen in methods.items():
        rows = [chosen[r["task_id"]] for r in c_records]
        domain_results = {}
        for domain in domains:
            tasks = [r["task_id"] for r in c_records if r["task_domain"] == domain]
            successes = sum(chosen[task]["success"] for task in tasks)
            baseline = sum(indexed[best][task]["success"] for task in tasks)
            domain_results[domain] = {
                "tasks": len(tasks),
                "successes": successes,
                "best_B_single_successes": baseline,
                "success_delta": successes - baseline,
            }
        comparison[name] = {
            "tasks": len(rows),
            "within_two_successes": sum(r["success"] for r in rows),
            "first_attempt_successes": sum(r["first_attempt_success"] for r in rows),
            "source_macro_within_two": source_macro(rows, "success"),
            "domains": domain_results,
            "newly_successful_vs_B_best_single": [
                r["task_id"]
                for r in rows
                if r["success"] and not indexed[best][r["task_id"]]["success"]
            ],
            "regressed_vs_B_best_single": [
                r["task_id"]
                for r in rows
                if not r["success"] and indexed[best][r["task_id"]]["success"]
            ],
            "selected_original_result_digests": {
                r["task_id"]: data.digest(r) for r in rows
            },
        }
    return {
        "E1": {
            "primary": "task success within two observed-feedback attempts",
            "secondary": "first attempt",
            "B": {name: summarize(b[name]) for name in e1_names},
            "C": {name: summarize(c[name]) for name in e1_names},
            "trajectory_single_action_records_remain_degenerate": True,
            "unseen_real_source_or_future_task_qualified": False,
        },
        "E2": {
            "B": {arm: summarize(b[name]) for arm, name in e2_names.items()},
            "C": {arm: summarize(c[name]) for arm, name in e2_names.items()},
            "demonstration_is_existing_trajectory_model_alias": True,
            "correction_source": "authored verified A references; no external teacher",
            "original_student_failures_and_retries_are_not_new_tasks": True,
        },
        "E3": {
            "best_single_frozen_from_B": best,
            "C": comparison,
            "direct_mixture_definition": "one final-answer SFT adapter over both authored A task domains",
            "integration_definition": "exact equal-weight sum of two same-base rank4 LoRA deltas, materialized at rank8",
            "domain_routing_definition": "pre-action task_domain metadata chooses numeric or structured expert",
            "domain_router_learned": False,
            "online_routed_execution_performed": False,
            "B_domain_balance": "selection panel is entirely structured; domain coverage is incomplete",
            "external_teacher_models": 0,
            "independent_complementarity_qualification": "BLOCKED",
            "rank8_integrated_cost_matches_rank4": False,
            "cached_model_costs": {
                name: c[name]["cost"]
                for name in (
                    "specialist_numeric",
                    "specialist_structured",
                    "final_answer",
                    "integrated",
                )
            },
        },
        "comparison_scope": "12 curated repository function-contract tasks; no full repository build, authenticated users or future-source generalization",
    }
