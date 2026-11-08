"""Matched tuning and full ordinary/Hepta pilot matrix on frozen source groups."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from ndu_real_materials.common import strict_json
from .metering import atomic_json, canonical_sha, file_sha
from .study import now, run_requests, verify_plan


def profile_candidates(root, index):
    plan, _ = verify_plan(root)
    design = plan["design"]
    profiles, unavailable = [], []
    controls = Path(root) / "control-plans"
    controls.mkdir(exist_ok=False)
    for fit in plan["independent_fit_roster"]:
        seed = fit["training_seed"]
        for regime in design["regimes"]:
            for arm, (core, controller) in design["arms"].items():
                for trial in range(1 if controller == "initial" else 3):
                    rows = (
                        index["content"] if controller == "initial" else index["fits"]
                    )
                    model = [
                        row
                        for row in rows
                        if row["seed"] == seed
                        and row["core"] == core
                        and (
                            controller == "initial"
                            or (
                                row["regime"] == regime
                                and row["trial_index"] == trial
                                and row["controller"]
                                == ("shared" if regime == "frozen" else controller)
                            )
                        )
                    ]
                    identity = f"{fit['fit_id']}-{regime}-{arm}-trial-{trial}"
                    if len(model) != 1 or model[0]["status"] != "completed":
                        unavailable.append(
                            {
                                "profile_id": identity,
                                "fit_id": fit["fit_id"],
                                "regime": regime,
                                "arm": arm,
                                "trial_index": trial,
                                "matching_models": model,
                                "status": "training_unavailable",
                            }
                        )
                        continue
                    model = model[0]
                    directory = Path(model["directory"])
                    weights, receipt = (
                        directory / "weights.pt",
                        directory / "receipt.json",
                    )
                    if (
                        file_sha(weights) != model["weights_sha256"]
                        or file_sha(receipt) != model["receipt_sha256"]
                    ):
                        raise ValueError("Training artifacts changed before tuning")
                    control = {
                        "control": design["controller"],
                        "episode_wall_seconds": design["budgets"][
                            "episode_wall_seconds"
                        ],
                        "fixed_schedule": design["fixed_schedule_candidates"][trial],
                        "seed": seed,
                    }
                    path = controls / (identity + ".json")
                    control_pin = atomic_json(path, control)
                    policy_pin = canonical_sha(
                        {
                            "controller": controller,
                            "control_plan_sha256": control_pin,
                            "execution_source_pins": plan["source_pins"],
                        }
                    )
                    profiles.append(
                        {
                            "study_id": design["study_id"],
                            **fit,
                            "profile_id": identity,
                            "regime": regime,
                            "arm": arm,
                            "core": core,
                            "controller": controller,
                            "trial_index": trial,
                            "weights": str(weights),
                            "model_sha256": model["weights_sha256"],
                            "training_receipt_sha256": model["receipt_sha256"],
                            "control_plan": str(path),
                            "control_plan_sha256": control_pin,
                            "policy_sha256": policy_pin,
                            "episode_seed": 0,
                            "retry_of": None,
                        }
                    )
    result = {
        "profiles": profiles,
        "unavailable": unavailable,
        "created_at": now(),
        "model_index_sha256": canonical_sha(index),
    }
    atomic_json(Path(root) / "candidate-profiles.json", result)
    return result


def make_requests(root, phase, plan, profiles, cases, lock_sha=None):
    requests = []
    for profile in profiles:
        for case in cases:
            operation = (
                phase
                + "-"
                + canonical_sha(
                    [plan["execution_run_id"], profile["profile_id"], case["id"]]
                )[:32]
            )
            requests.append(
                {
                    "config": plan["execution"],
                    "case": case,
                    "profile": {
                        **profile,
                        "original_operation_id": operation,
                        "selection_lock_sha256": lock_sha,
                    },
                    "output": str(Path(root) / "episodes" / operation),
                }
            )
    return requests


def retained_rows(phase_result, latency_weight):
    rows = []
    for attempt in phase_result["attempts"]:
        if "output" not in attempt:
            request = strict_json(Path(attempt["request"]).read_bytes())
            rows.append(
                {
                    **request["profile"],
                    "case_id": request["case"]["id"],
                    "source_group_id": request["case"]["source_id"],
                    "split": request["case"]["role"],
                    "task_family": request["case"]["task_family"],
                    "analysis_utility": None,
                    "terminal_status": "Unresolved",
                    "request": attempt.get("request"),
                    "error": attempt.get("error"),
                }
            )
            continue
        directory = Path(attempt["output"])
        row = strict_json((directory / "result.json").read_bytes())
        if attempt["attempt"]["terminal_status"] != row["terminal_status"]:
            row["retained_episode_status_before_outer_failure"] = row["terminal_status"]
            row["terminal_status"] = "Failed"
            row["outer_status_mismatch"] = True
        deployment = row.get("deployment_meter")
        wall = None if deployment is None else deployment["wall_seconds"]
        if row["terminal_status"] == "Failed":
            row["analysis_utility"] = -1.0 - latency_weight * (
                attempt["attempt"]["wall_seconds"] if wall is None else wall
            )
            row["analysis_failure_penalty_applied"] = True
        else:
            row["analysis_utility"] = row["gross_score"] - latency_weight * wall
            row["analysis_failure_penalty_applied"] = False
        row.update(
            result_path=str(directory / "result.json"),
            result_sha256=file_sha(directory / "result.json"),
            original_attempt=attempt["attempt"],
            deployment_wall_seconds=wall,
        )
        rows.append(row)
    return rows


def tune(root, model_index):
    root = Path(root)
    plan, selected = verify_plan(root)
    design = plan["design"]
    candidates = profile_candidates(root, strict_json(Path(model_index).read_bytes()))
    requests = make_requests(
        root, "search", plan, candidates["profiles"], selected["cases"]["tuning"]
    )
    result = run_requests(
        root,
        "search",
        requests,
        design["budgets"]["max_workers"],
        design["budgets"]["phase_wall_seconds"],
    )
    rows = retained_rows(result, design["controller"]["latency_weight"])
    by_profile = defaultdict(list)
    for row in rows:
        if "profile_id" in row:
            by_profile[row["profile_id"]].append(row)
    summaries, choices = [], []
    expected_ids = {row["id"] for row in selected["cases"]["tuning"]}
    for profile in candidates["profiles"]:
        observed = by_profile[profile["profile_id"]]
        complete = (
            len(observed) == len(expected_ids)
            and {row["case_id"] for row in observed} == expected_ids
            and all(
                row.get("analysis_utility") is not None
                and row.get("deployment_wall_seconds") is not None
                for row in observed
            )
        )
        groups = defaultdict(list)
        for row in observed:
            if row.get("analysis_utility") is not None:
                groups[row["source_group_id"]].append(row["analysis_utility"])
        value = (
            float(np.mean([np.mean(values) for values in groups.values()]))
            if complete
            else None
        )
        summaries.append(
            {
                "profile": profile,
                "mean_tuning_utility": value,
                "complete": complete,
                "failed_episodes": sum(
                    row["terminal_status"] == "Failed" for row in observed
                ),
                "observed_episodes": len(observed),
                "expected_episodes": len(expected_ids),
            }
        )
    for fit in plan["independent_fit_roster"]:
        for regime in design["regimes"]:
            for arm in design["arms"]:
                trials = [
                    row
                    for row in summaries
                    if row["profile"]["fit_id"] == fit["fit_id"]
                    and row["profile"]["regime"] == regime
                    and row["profile"]["arm"] == arm
                    and row["complete"]
                ]
                if trials:
                    winner = max(
                        trials,
                        key=lambda row: (
                            row["mean_tuning_utility"],
                            -row["profile"]["trial_index"],
                        ),
                    )
                    choices.append(winner)
    strongest = []
    for fit in plan["independent_fit_roster"]:
        for regime in design["regimes"]:
            pool = [
                row
                for row in choices
                if row["profile"]["fit_id"] == fit["fit_id"]
                and row["profile"]["regime"] == regime
                and row["profile"]["arm"] not in {"A", "B", "C", "D"}
            ]
            if pool:
                winner = max(
                    pool,
                    key=lambda row: (row["mean_tuning_utility"], row["profile"]["arm"]),
                )
                strongest.append(
                    {
                        "fit_id": fit["fit_id"],
                        "regime": regime,
                        "arm": winner["profile"]["arm"],
                        "profile_id": winner["profile"]["profile_id"],
                        "mean_tuning_utility": winner["mean_tuning_utility"],
                        "all_eight_comparators_available": len(pool) == 8,
                    }
                )
    incumbents = []
    for choice in choices:
        profile = choice["profile"]
        if profile["regime"] != "frozen" or profile["controller"] != "initial":
            continue
        identity = profile["fit_id"] + "-retention-incumbent-" + profile["core"]
        control = {
            "control": design["controller"],
            "episode_wall_seconds": design["budgets"]["episode_wall_seconds"],
            "fixed_schedule": ["WRITE_TEXT"],
            "seed": profile["training_seed"],
        }
        path = root / "control-plans" / (identity + ".json")
        pin = atomic_json(path, control)
        incumbents.append(
            {
                **profile,
                "profile_id": identity,
                "arm": "incumbent_" + profile["core"],
                "controller": "tuned_fixed",
                "control_plan": str(path),
                "control_plan_sha256": pin,
                "policy_sha256": canonical_sha(
                    {
                        "controller": "tuned_fixed",
                        "control_plan_sha256": pin,
                        "execution_source_pins": plan["source_pins"],
                    }
                ),
            }
        )
    lock = {
        "schema": "ndu.real.comparator-lock.v1",
        "locked_at": now(),
        "pilot_plan_sha256": file_sha(root / "PILOT_PLAN.json"),
        "search_phase_sha256": file_sha(root / "search/phase-result.json"),
        "candidate_summaries": summaries,
        "unavailable_training_candidates": candidates["unavailable"],
        "selected": choices,
        "strongest": strongest,
        "retention_incumbents": incumbents,
        "complete_profile_selection": len(choices)
        == len(design["arms"])
        * len(design["regimes"])
        * len(plan["independent_fit_roster"]),
        "all_planned_candidates_accounted": len(candidates["profiles"])
        + len(candidates["unavailable"])
        == len(plan["independent_fit_roster"])
        * len(design["regimes"])
        * sum(1 if c == "initial" else 3 for _, c in design["arms"].values()),
        "all_search_trials_complete": not candidates["unavailable"]
        and all(row["complete"] for row in summaries),
        "native_authentication": "SEPARATE_REQUIRED",
    }
    pin = atomic_json(root / "selection-lock.json", lock)
    print(
        json.dumps(
            {
                "event": "comparators_locked",
                "lock_sha256": pin,
                "selected": len(choices),
                "complete": lock["complete_profile_selection"],
            }
        ),
        flush=True,
    )
    return lock


def compact_row(row):
    keys = (
        "study_id",
        "fit_id",
        "training_seed",
        "fit_run_id",
        "profile_id",
        "source_group_id",
        "case_id",
        "episode_group",
        "split",
        "task_family",
        "regime",
        "arm",
        "core",
        "controller",
        "episode_seed",
        "original_operation_id",
        "model_sha256",
        "policy_sha256",
        "source_sha256",
        "output_text_sha256",
        "output_image_sha256",
        "gross_score",
        "analysis_utility",
        "analysis_failure_penalty_applied",
        "terminal_status",
        "retry_of",
        "selection_lock_sha256",
        "deployment_wall_seconds",
        "result_path",
        "result_sha256",
        "error",
    )
    compact = {key: row.get(key) for key in keys}
    meter, score = row.get("deployment_meter", {}), row.get("score_components", {})
    compact.update(
        costs_by_category=meter.get("costs"),
        cpu_seconds=meter.get("cpu_seconds"),
        cost_schema=meter.get("schema"),
        cost_cpu_scope=meter.get("cpu_scope"),
        cost_subcategory_status=meter.get("subcategory_status"),
        cost_unclassified_seconds=meter.get("observed_unclassified_overhead_seconds"),
        cost_raw_spans_sha256=meter.get("raw_spans_sha256"),
        cost_observer_tail_sha256=meter.get("observer_tail_sha256"),
        cost_deployment_latency_scope=meter.get("deployment_latency_scope"),
        cost_actor_record_sha256s=meter.get("actor_record_sha256s"),
        cost_interval_reconciliation=meter.get("interval_reconciliation"),
        cost_unclosed_actor_subcategories=meter.get("unclosed_actor_subcategories"),
        evaluator_sha256=score.get("evaluator_source_sha256"),
        rubric_sha256=score.get("rubric_sha256"),
        score_components={
            key: score.get(key)
            for key in ("text_quality", "image_quality", "committed_output_preserved")
        },
        started_at=row.get("original_attempt", {}).get("started_at"),
        finished_at=row.get("original_attempt", {}).get("finished_at"),
        research_wall_seconds=row.get("original_attempt", {}).get("wall_seconds"),
        research_cpu_seconds=row.get("original_attempt", {}).get("cpu_seconds"),
    )
    return compact


def pilot(root):
    root = Path(root)
    plan, selected = verify_plan(root)
    design = plan["design"]
    lock = strict_json((root / "selection-lock.json").read_bytes())
    if lock["pilot_plan_sha256"] != file_sha(root / "PILOT_PLAN.json"):
        raise ValueError("Comparator lock was made for a different prospective plan")
    profiles = [row["profile"] for row in lock["selected"]]
    cases = selected["cases"]["pilot_new"] + selected["cases"]["pilot_retention"]
    requests = make_requests(
        root, "pilot", plan, profiles, cases, file_sha(root / "selection-lock.json")
    )
    result = run_requests(
        root,
        "pilot",
        requests,
        design["budgets"]["max_workers"],
        design["budgets"]["phase_wall_seconds"],
    )
    rows = retained_rows(result, design["controller"]["latency_weight"])
    covered = {
        (row.get("fit_id"), row.get("regime"), row.get("arm"), row.get("case_id"))
        for row in rows
    }
    for fit in plan["independent_fit_roster"]:
        for regime in design["regimes"]:
            for arm, (core, controller) in design["arms"].items():
                for case in cases:
                    if (fit["fit_id"], regime, arm, case["id"]) not in covered:
                        rows.append(
                            {
                                **fit,
                                "study_id": design["study_id"],
                                "regime": regime,
                                "arm": arm,
                                "core": core,
                                "controller": controller,
                                "case_id": case["id"],
                                "source_group_id": case["source_id"],
                                "split": case["role"],
                                "task_family": case["task_family"],
                                "terminal_status": "NotStarted",
                                "error": {
                                    "type": "MissingOriginalExecution",
                                    "message": "Full planned roster retained; no fabricated result",
                                },
                            }
                        )
    with (root / "paired-rows.jsonl").open("x") as output:
        for row in rows:
            output.write(
                json.dumps(compact_row(row), separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    print(
        json.dumps(
            {
                "event": "pilot_rows_retained",
                "observed": len(rows),
                "planned": len(requests),
                "paired_rows_sha256": file_sha(root / "paired-rows.jsonl"),
                "scientific_admission": "HOLD",
            }
        ),
        flush=True,
    )
    incumbent_requests = make_requests(
        root,
        "incumbent-retention",
        plan,
        lock["retention_incumbents"],
        selected["cases"]["pilot_retention"],
        file_sha(root / "selection-lock.json"),
    )
    incumbent_phase = run_requests(
        root,
        "incumbent-retention",
        incumbent_requests,
        design["budgets"]["max_workers"],
        design["budgets"]["phase_wall_seconds"],
    )
    incumbent_rows = retained_rows(
        incumbent_phase, design["controller"]["latency_weight"]
    )
    covered = {
        (row.get("fit_id"), row.get("core"), row.get("case_id"))
        for row in incumbent_rows
    }
    for fit in plan["independent_fit_roster"]:
        for core in ("ordinary", "hepta"):
            for case in selected["cases"]["pilot_retention"]:
                if (fit["fit_id"], core, case["id"]) not in covered:
                    incumbent_rows.append(
                        {
                            **fit,
                            "study_id": design["study_id"],
                            "regime": "frozen",
                            "arm": "incumbent_" + core,
                            "core": core,
                            "controller": "tuned_fixed",
                            "case_id": case["id"],
                            "source_group_id": case["source_id"],
                            "split": case["role"],
                            "task_family": case["task_family"],
                            "terminal_status": "NotStarted",
                        }
                    )
    with (root / "retention-incumbent-rows.jsonl").open("x") as output:
        for row in incumbent_rows:
            output.write(
                json.dumps(compact_row(row), separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("tune", "pilot"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model-index", type=Path)
    args = parser.parse_args()
    tune(args.root, args.model_index) if args.command == "tune" else pilot(args.root)
    return 0
