"""Predeclared, complete-denominator analysis of the separate mechanism pilot.

Four independent training seeds are the sampling units. The two evaluation
episode seeds are averaged within a selected fitted model. Missing fits do
not shrink the registered family, and no result here authorizes expansion.
"""

import argparse
from datetime import datetime
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from .mechanism_contract import (
    ARMS, TASKS, digest, file_sha, load_contract, read_json, select_group,
    utc_now, verify_sources, write_json,
)
from .mechanism_training import read_attempt, summarize, validate_selection_lock


MUD = .01
ALPHA = .05
CONTRASTS = (
    "smooth_minus_full", "strongest_registered_minus_full", "margin_only_minus_full",
    "call_only_minus_full", "risk_only_minus_full", "endpoint_minus_full",
    "no_reset_minus_full", "no_refractory_minus_full", "uniform_tick_minus_full",
    "fixed_minus_conditional",
)
STATISTICAL_CONTRACT = dict(
    independent_unit="training_seed", registered_independent_seeds=4,
    evaluation_episode_seeds_are_independent_training_repeats=False,
    evaluation_aggregation="Sum squared errors / total episode count within each selected fit",
    primary_metric="mean_squared_error", useful_absolute_mse_reduction=MUD,
    interval="Pointwise two-sided 95% paired Student-t interval; df=n-1",
    test="One-sided paired Student-t H0: mean MSE reduction <= .01",
    multiplicity="Holm over the fixed 20 task-by-contrast family; missing p-values counted as 1",
    family_size=20, alpha=ALPHA, incomplete_four_seed_contrasts_eligible=False,
    status="exploratory_synthetic_pilot_not_confirmatory",
    zero_sample_variance_policy="No Student-t inference; preserve mean and mark ineligible",
    uncertainty_scope="Training randomness conditional on the fixed task data and validation-selection procedure; not task/dataset sampling uncertainty",
    retention=None, full_cost_boundary=None, deployment_expansion_eligible=False,
)


def paired_summary(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("Paired effects must be finite scalars")
    count = len(values)
    result = dict(independent_training_seeds=count, mean_effect=None, standard_error=None,
                  pointwise_95_ci=None, one_sided_p_above_mud=None,
                  all_four_registered_seeds_present=count == 4, inferential_eligible=False)
    if count:
        result["mean_effect"] = float(values[0] if np.all(values == values[0]) else values.mean())
    if count < 2:
        return result
    mean = result["mean_effect"]
    se = 0. if np.all(values == values[0]) else float(values.std(ddof=1) / math.sqrt(count))
    result["standard_error"] = se
    result["zero_sample_variance"] = se == 0
    if se == 0:
        result["inference_unavailable_reason"] = "A degenerate sample does not estimate a Student-t standard error"
        return result
    half = float(student_t.ppf(.975, count - 1)) * se
    result["pointwise_95_ci"] = [mean - half, mean + half]
    result["one_sided_p_above_mud"] = float(student_t.sf((mean - MUD) / se, count - 1))
    result["inferential_eligible"] = count == 4
    return result


def holm_fixed_family(rows):
    if len(rows) != STATISTICAL_CONTRACT["family_size"]:
        raise ValueError("The registered family must retain all 20 contrasts")
    eligible_p = [row["one_sided_p_above_mud"]
                  if row["all_four_registered_seeds_present"] and row["inferential_eligible"] and row["one_sided_p_above_mud"] is not None
                  else 1. for row in rows]
    running = 0.
    for rank, index in enumerate(sorted(range(len(rows)), key=lambda i: (eligible_p[i], i))):
        running = max(running, min(1., (len(rows) - rank) * eligible_p[index]))
        rows[index]["holm_adjusted_p_above_mud"] = running
        rows[index]["exploratory_effect_gate_pass"] = bool(
            rows[index]["all_four_registered_seeds_present"] and rows[index]["inferential_eligible"] and running <= ALPHA
            and rows[index]["pointwise_95_ci"][0] > MUD)
    return rows


def selected_evaluation(study, fit, lock, identity, plan):
    """Validate the selected checkpoint and aggregate only its episode seeds."""
    path = Path(study) / "evaluations" / fit["fit_id"]
    terminal_path, process_path = path / "terminal.json", path / "process-completion.json"
    if not terminal_path.is_file() or not process_path.is_file():
        return None, "Missing evaluation or supervisor terminal"
    result, process = read_json(terminal_path), read_json(process_path)
    if result.get("status") != "COMPLETED" or process.get("returncode") != 0 or process.get("timed_out"):
        return None, "Evaluation failed, timed out, or is not authoritatively complete"
    if result.get("identity") != identity or result.get("fit") != fit or result.get("phase") != "selected_test":
        raise ValueError("Evaluation identity differs from its exact frozen roster row")
    lock_path = Path(study) / "blocks" / fit["group_id"] / "selection-lock.json"
    if result.get("selection_lock_sha256") != file_sha(lock_path):
        raise ValueError("Evaluation is not bound to the selection lock")
    chosen = lock["selected"][fit["arm"]]
    if chosen["fit_id"] != fit["fit_id"] or result.get("checkpoint_sha256") != chosen["checkpoint_sha256"]:
        raise ValueError("Evaluation used a different checkpoint")
    if not result.get("source_and_input_pins_unchanged_at_completion"):
        raise ValueError("Evaluation lacks final source/input verification")
    if datetime.fromisoformat(result["started_at"]) < datetime.fromisoformat(lock["created_at"]):
        raise ValueError("Test started before the group selection lock")
    episodes = result.get("test", [])
    if len(episodes) != len(plan["test_episode_seeds"]):
        raise ValueError("Missing or duplicate selected-fit episode seeds")
    if [row.get("episode_seed") for row in episodes] != plan["test_episode_seeds"]:
        raise ValueError("Evaluation episode roster differs from the frozen plan")
    for row in episodes:
        if row.get("count") != plan["test_count"] or not math.isfinite(row.get("squared_error_sum", math.nan)):
            raise ValueError("Incomplete/nonfinite evaluation episode batch")
        if row["squared_error_sum"] < 0 or abs(row["mse"] - row["squared_error_sum"] / row["count"]) > 1e-10:
            raise ValueError("Reported episode MSE is inconsistent with its count and error sum")
    mse = sum(row["squared_error_sum"] for row in episodes) / sum(row["count"] for row in episodes)
    if abs(mse - result["same_fit_aggregated_test_mse"]) > 1e-10:
        raise ValueError("Within-fit aggregate differs from raw episode totals")
    if result.get("independent_training_replicates_represented") != 1 or result.get("evaluation_episode_seeds_are_training_replicates") is not False:
        raise ValueError("Episode seeds must not become training repetitions")
    return dict(fit=fit, mse=mse, validation_mse=chosen["validation_mse"],
                checkpoint_sha256=chosen["checkpoint_sha256"], terminal_sha256=file_sha(terminal_path),
                evaluation_episodes=episodes, performance=result.get("performance"),
                memory=result.get("memory"), peak_gpu_allocated_bytes=result.get("gpu_peak_allocated_bytes"),
                peak_gpu_reserved_bytes=result.get("gpu_peak_reserved_bytes"), environment=result.get("environment")), None


def analyze(study, bundle, plan_path, output):
    study, output = Path(study), Path(output)
    plan, metadata, arrays, roster, identity = load_contract(bundle, plan_path)
    if plan.get("statistical_contract") != STATISTICAL_CONTRACT:
        raise ValueError("Analysis differs from the predeclared statistical contract")
    if read_json(study / "study.json")["identity"] != identity:
        raise ValueError("Study identity drift")
    by_id = {fit["fit_id"]: fit for fit in roster}
    terminals = {fit["fit_id"]: read_attempt(study, fit, identity) for fit in roster}
    groups = {}
    for fit in roster:
        groups.setdefault(fit["group_id"], []).append(fit)
    selected, locks, missing = {}, {}, []
    paired_checks = []
    for group_id, fits in groups.items():
        path = study / "blocks" / group_id / "selection-lock.json"
        if not path.is_file():
            missing.append(dict(group_id=group_id, reason="Selection lock missing"))
            continue
        lock, _ = validate_selection_lock(study, plan, fits, identity)
        expected = select_group(plan, fits, terminals, identity)
        for key, value in expected.items():
            if lock.get(key) != value:
                raise ValueError("Selection lock no longer matches training-only evidence: " + key)
        if any(terminals[fit["fit_id"]]["status"] == "UNSTARTED" for fit in fits):
            raise ValueError("Selection occurred before all registered training attempts")
        for fit in fits:
            terminal_path = study / "attempts" / fit["fit_id"] / "terminal.json"
            if terminal_path.exists() and lock["fit_terminal_file_sha256"].get(fit["fit_id"]) != file_sha(terminal_path):
                raise ValueError("Training terminal changed after selection")
        locks[group_id] = lock
        for arm, pair in lock["incomplete_tuning_pairs"].items():
            missing.append(dict(group_id=group_id, arm=arm, reason="Incomplete registered learning-rate pair",
                                registered_attempt_status=pair))
        completed = [terminals[fit["fit_id"]] for fit in fits if terminals[fit["fit_id"]]["status"] == "COMPLETED"]
        checks = dict(group_id=group_id, completed=len(completed),
                      all_expected_updates=all(row["optimizer_updates_completed"] == plan["train_updates"] for row in completed),
                      same_initial_parameters=len({row["initial_parameter_sha256"] for row in completed}) <= 1,
                      same_train_data=len({row["data"]["train"]["data_identity_sha256"] for row in completed}) <= 1,
                      same_validation_data=len({row["data"]["validation"]["data_identity_sha256"] for row in completed}) <= 1,
                      same_batch_order=len({row["batch_order_sha256"] for row in completed}) <= 1,
                      matched_trainable_parameters=all(row["memory"]["total"]["trainable_parameters"] == plan["expected_parameter_count"] for row in completed))
        if not all(checks[k] for k in checks if k not in ("group_id", "completed")):
            raise ValueError("Matched-budget/data/parameter invariant failed: " + group_id)
        paired_checks.append(checks)
        for arm, choice in lock["selected"].items():
            result, error = selected_evaluation(study, by_id[choice["fit_id"]], lock, identity, plan)
            if result is None:
                missing.append(dict(group_id=group_id, arm=arm, reason=error))
            else:
                selected[(lock["task"], lock["training_seed"], arm)] = result
    arm_rows = []
    for task in TASKS:
        for arm in ARMS:
            observations = [selected[(task, seed, arm)] for seed in plan["training_seeds"] if (task, seed, arm) in selected]
            values = [row["mse"] for row in observations]
            arm_rows.append(dict(task=task, arm=arm, independent_training_seeds=len(values),
                                 registered_seeds=plan["training_seeds"],
                                 mean_mse=float(np.mean(values)) if values else None,
                                 per_training_seed=observations))
    contrasts = []
    for task in TASKS:
        for contrast in CONTRASTS:
            effects = []
            for seed in plan["training_seeds"]:
                full = selected.get((task, seed, "regenerative_dual"))
                if full is None:
                    continue
                if contrast == "strongest_registered_minus_full":
                    lock = locks.get(f"{task}-seed-{seed}", {})
                    other_arm = lock.get("strongest_registered_comparator")
                elif contrast == "smooth_minus_full":
                    other_arm = "smooth_dual"
                elif contrast == "fixed_minus_conditional":
                    other_arm = "conditional_boundary"
                else:
                    other_arm = contrast.removesuffix("_minus_full")
                other = selected.get((task, seed, other_arm))
                if other is None:
                    continue
                effect = full["mse"] - other["mse"] if contrast == "fixed_minus_conditional" else other["mse"] - full["mse"]
                effects.append(dict(training_seed=seed, comparator=other_arm, effect=effect,
                                    full_fit_id=full["fit"]["fit_id"], comparator_fit_id=other["fit"]["fit_id"]))
            contrasts.append(dict(task=task, contrast=contrast, paired_effects=effects,
                                  **paired_summary([row["effect"] for row in effects])))
    holm_fixed_family(contrasts)
    progress = summarize(study, roster, identity)
    verify_sources(plan["source_pins"])
    result = dict(schema="hcsn-mechanism-pilot-analysis-v1", at=utc_now(), identity=identity,
                  statistical_contract=STATISTICAL_CONTRACT,
                  execution_progress=progress, selected_fit_count=len(selected),
                  independent_seeds_per_arm_task=4, registered_full_fit_count=160,
                  paired_data_budget_checks=paired_checks, arm_results=arm_rows, contrasts=contrasts,
                  missing=missing,
                  registered_fit_terminal_status=[dict(fit=fit, status=terminals[fit["fit_id"]]["status"],
                                                       error=terminals[fit["fit_id"]].get("error"),
                                                       reason=terminals[fit["fit_id"]].get("reason")) for fit in roster],
                  all_registered_selected_evaluations_available=len(selected) == 80,
                  complete_cost=False, physical_energy_joules=None, old_capability_retention=None,
                  external_task_gain_established=False, expansion_decision="HOLD",
                  expansion_reasons=["This is a synthetic exploratory mechanism pilot, not independent external task confirmation",
                                     "Old-capability retention and full total-cost boundary are unmeasured",
                                     "Four independent seeds and pointwise t intervals do not establish a confirmatory power plan"],
                  strongest_comparator_scope="The per-training-seed validation-selection procedure over this registered arm set; selected arms can differ by seed; not a post-test best model or the world's strongest deployable model",
                  original_campaign_completion_credit=0, hepta_ndu_completion_credit=0)
    result["scientific_status"] = ("EXPLORATORY_MATRIX_COMPLETE" if progress["entire_training_and_evaluation_matrix_completed"]
                                   and len(selected) == 80 else "INCOMPLETE_OR_FAILED_MATRIX_RETAINED")
    write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.study, args.bundle, args.plan, args.output)
    print(result["scientific_status"])


if __name__ == "__main__":
    main()
