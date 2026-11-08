#!/usr/bin/env python3
"""Analyze real B evidence through the source-pinned descriptive contrast code.

Inputs are an existing ndu.real.pilot-plan.v1, selected-sources.json, selection-
lock.json, paired-rows.jsonl and fit-results.json. Supply their independently
read-back SHA256/byte bindings; this helper never dispatches or repairs a run.

The bindings JSON has schema hepta.causal-b.analysis-inputs.v1 and an artifacts
object with plan, selected, selection_lock, paired_rows and fit_results keys.
Each value is {path: absolute_path, sha256: lowercase_digest, bytes: integer}.
The caller must provide the bindings file's expected digest as well.
The separately frozen analysis policy binds this helper, the evaluation plan,
and the prospective BudgetStop adapter; it is never inferred from outcomes.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time


ARTIFACTS = ("plan", "selected", "selection_lock", "paired_rows", "fit_results")
METRICS = ("gross_score", "failure_adjusted_score", "deployment_utility")
TERMINAL = {"Completed", "Failed"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return (
        isinstance(value, str)
        and re.fullmatch("[0-9a-f]{64}", value) is not None
        and value != "0" * 64
    )


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read_bound(binding, limit=256 * 1024 * 1024):
    require(
        isinstance(binding, dict) and set(binding) == {"path", "sha256", "bytes"},
        "Closed artifact binding required",
    )
    require(
        isinstance(binding["path"], str) and Path(binding["path"]).is_absolute(),
        "Absolute artifact path required",
    )
    require(
        digest(binding["sha256"])
        and type(binding["bytes"]) is int
        and 0 <= binding["bytes"] <= limit,
        "Invalid digest or bounded artifact size",
    )
    path = Path(binding["path"])
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_size == binding["bytes"],
            "Artifact size or type changed",
        )
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    fingerprint = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    require(
        fingerprint(before) == fingerprint(after) == fingerprint(path.lstat()),
        "Artifact changed during read",
    )
    require(
        len(raw) == binding["bytes"]
        and hashlib.sha256(raw).hexdigest() == binding["sha256"],
        "Artifact SHA256 mismatch",
    )
    return raw


def load_frozen_analysis(plan, source_root):
    """Check the registered execution source before importing its analysis code."""
    original_root = Path(plan["execution"]["repository_root"])
    require(
        original_root.is_absolute() and source_root.is_absolute(),
        "Absolute source roots required",
    )
    verified = {}
    for pin in plan["source_pins"]:
        named = Path(pin["path"])
        relative = named.relative_to(original_root) if named.is_absolute() else named
        require(
            relative.parts and not any(part in {".", ".."} for part in relative.parts),
            "Escaping source pin",
        )
        key = relative.as_posix()
        require(key not in verified, "Duplicate registered source pin")
        binding = {
            "path": str(source_root / relative),
            "sha256": pin["sha256"],
            "bytes": pin["bytes"],
        }
        read_bound(binding, 64 * 1024 * 1024)
        verified[key] = binding
    required = {
        "scripts/ndu_real_runtime/" + name + ".py"
        for name in (
            "__init__",
            "causal_analysis",
            "causal_protocol",
            "metering",
            "span_meter",
            "matrix",
        )
    }
    require(
        required <= set(verified),
        "Analysis, contrasts and failure policy were not pinned in the evaluation plan",
    )
    sys.path.insert(0, str(source_root / "scripts"))
    analysis = importlib.import_module("ndu_real_runtime.causal_analysis")
    protocol = importlib.import_module("ndu_real_runtime.causal_protocol")
    for module in (analysis, protocol):
        relative = "scripts/" + module.__name__.replace(".", "/") + ".py"
        require(
            Path(module.__file__).resolve() == (source_root / relative).resolve(),
            "Imported analysis came from another checkout",
        )
    return (
        analysis.paired_contrast,
        protocol.b_contrasts(),
        protocol.canonical_sha,
        verified,
    )


def condition_map(design):
    require(
        design.get("estimand") == "matched_training",
        "This adapter only analyzes the matched_training estimand",
    )
    require(
        design.get("memory_modes") == ["reset", "persistent"]
        and set(design["regimes"]) == {"frozen", "joint"},
        "Both regimes and both prospectively paired state modes are required",
    )
    require(
        design.get("training", {}).get("observation_policy") == "matched_episodes",
        "Unmatched observation policy",
    )
    expected = {
        (core, control, mode)
        for core in ("ordinary", "hepta")
        for control in ("light", "ndu", "tuned_fixed", "voi", "mpc")
        for mode in ("reset", "persistent")
    }
    result = {}
    require(isinstance(design.get("arms"), dict), "Frozen named arms required")
    for arm, spec in design["arms"].items():
        require(
            isinstance(arm, str)
            and arm
            and isinstance(spec, list)
            and len(spec) == 3
            and all(isinstance(item, str) for item in spec)
            and tuple(spec) in expected,
            "Invalid frozen arm",
        )
        result[arm] = "/".join(spec)
    require(
        len(result) == len(expected) and len(set(result.values())) == len(expected),
        "Incomplete or aliased B condition inventory",
    )
    return result


def selected_cases(selected):
    require(
        selected.get("schema") == "ndu.real.selected-sources.v1",
        "Unknown selected-source schema",
    )
    groups = [group for values in selected["groups"].values() for group in values]
    require(
        len(groups) == len(set(groups)),
        "Source group crosses training/tuning/pilot roles",
    )
    cases, by_split = {}, {"development": [], "retention_validation": []}
    for category, split in (
        ("pilot_new", "development"),
        ("pilot_retention", "retention_validation"),
    ):
        for case in selected["cases"][category]:
            require(
                case["id"] not in cases
                and case["role"] == split
                and case["source_id"] in selected["groups"][category],
                "Selected case aliases identity, split or group",
            )
            mapped = {
                "case_id": case["id"],
                "source_group_id": case["source_id"],
                "split": split,
                "task_family": case["task_family"],
            }
            cases[case["id"]] = mapped
            by_split[split].append(mapped)
    return cases, by_split


def training_and_selection_gates(plan, lock, fitted, mapping):
    require(
        fitted.get("schema") == "ndu.real.causal-b.training-result.v1",
        "Unknown matched-training result schema",
    )
    fits = {item["fit_id"]: item for item in plan["independent_fit_roster"]}
    require(
        fits and len(fits) == len(plan["independent_fit_roster"]),
        "Duplicate or missing independent fit identity",
    )
    seeds = [item["training_seed"] for item in fits.values()]
    require(
        len(seeds) == len(set(seeds))
        and all(type(seed) is int and 0 <= seed < 2**32 for seed in seeds),
        "Invalid independent seed roster",
    )
    require(
        seeds == plan["design"]["training_seeds"],
        "Evaluation and training fit rosters differ",
    )
    results = fitted["results"]
    require(
        isinstance(results, dict)
        and type(fitted["planned_jobs"]) is int
        and 0 < fitted["planned_jobs"] >= len(results),
        "Invalid complete training denominator",
    )
    require(
        all(item.get("original_operation_id") == key for key, item in results.items()),
        "Training operation identity mismatch",
    )
    counts = dict(Counter(item["status"] for item in results.values()))
    require(
        counts == fitted["status_counts"],
        "Training status tally disagrees with original inventory",
    )
    completed_models = {
        (item["weights_sha256"], item["receipt_sha256"])
        for item in results.values()
        if item["status"] == "completed"
    }
    require(
        all(digest(weight) and digest(receipt) for weight, receipt in completed_models),
        "Completed fit lacks exact model/receipt digests",
    )
    paired = fitted.get("paired_training_audit", [])
    audited_jobs = [identity for pair in paired for identity in pair["job_ids"]]
    require(
        len(audited_jobs) == len(set(audited_jobs)),
        "Training pair audit duplicated an original job",
    )
    require(
        set(results) <= set(audited_jobs)
        and len(audited_jobs) == fitted["planned_jobs"],
        "Pair audit lost planned training jobs",
    )
    training_complete = (
        len(results) == fitted["planned_jobs"]
        and counts.get("completed", 0) == fitted["planned_jobs"]
        and fitted.get("independent_seed_groups_planned") == len(seeds)
        and fitted.get("independent_seed_groups_complete") == len(seeds)
        and bool(paired)
        and all(
            len(pair["job_ids"]) == 2
            and pair["complete"] is True
            and pair["same_initialization_data_batches_and_opportunities"] is True
            for pair in paired
        )
    )
    init = fitted.get("initialization_audit", [])
    initial_complete = (
        len(init) == len(seeds)
        and {row["training_seed"] for row in init} == set(seeds)
        and all(
            row.get("all_observed_initializations_equal") is True
            and row.get("cores_observed") == ["hepta", "ordinary"]
            for row in init
        )
    )
    profiles, profile_keys = {}, set()
    for choice in lock["selected"]:
        profile = choice["profile"]
        identity = profile["profile_id"]
        key = (profile["fit_id"], profile["regime"], profile["arm"])
        require(
            identity not in profiles and key not in profile_keys,
            "Selected profile duplicated",
        )
        require(
            key[0] in fits
            and key[1] in plan["design"]["regimes"]
            and key[2] in mapping,
            "Selected profile outside frozen roster",
        )
        require(
            profile["training_seed"] == fits[key[0]]["training_seed"]
            and [profile[k] for k in ("core", "controller", "memory_mode")]
            == plan["design"]["arms"][key[2]]
            and profile.get("training_memory_mode") == profile["memory_mode"]
            and profile.get("observation_policy") == "matched_episodes"
            and profile.get("estimand") == "matched_training",
            "Selected profile changed its trained condition",
        )
        require(
            (profile["model_sha256"], profile["training_receipt_sha256"])
            in completed_models,
            "Selected model does not bind a completed original fit",
        )
        profiles[identity] = profile
        profile_keys.add(key)
    expected_profiles = {
        (fit, regime, arm)
        for fit in fits
        for regime in plan["design"]["regimes"]
        for arm in mapping
    }
    profile_complete = (
        profile_keys == expected_profiles
        and lock.get("complete_profile_selection") is True
    )
    expected_trials = len(expected_profiles) * len(
        plan["design"]["training"]["head_learning_rates"]
    )
    summaries = lock.get("candidate_summaries", [])
    search_complete = (
        lock.get("all_search_trials_complete") is True
        and lock.get("all_planned_candidates_accounted") is True
        and not lock.get("unavailable_training_candidates")
        and len(summaries) == expected_trials
        and all(row.get("complete") is True for row in summaries)
    )
    return (
        fits,
        profiles,
        {
            "training_complete": bool(training_complete),
            "constructor_initialization_complete": bool(initial_complete),
            "selected_profile_roster_complete": bool(profile_complete),
            "all_search_trials_complete": bool(search_complete),
            "planned_training_jobs": fitted["planned_jobs"],
            "observed_training_jobs": len(results),
            "training_status_counts": counts,
            "planned_profiles": len(expected_profiles),
            "selected_profiles": len(profiles),
            "planned_search_trials": expected_trials,
            "recorded_search_trials": len(summaries),
            "unavailable_training_candidates": len(
                lock.get("unavailable_training_candidates", [])
            ),
            "same_prefit_checkpoint_required": False,
            "initialization_scope": "seeded constructor before mode-specific content pretraining",
            "full_improvement_budget_complete": False,
        },
    )


def map_rows(rows, plan, cases, fits, profiles, mapping, lock_digest, canonical_sha):
    """Bind original rows and apply the prospectively frozen analysis adapter."""
    mapped, identities, coordinates = [], set(), set()
    latency = plan["design"]["controller"]["latency_weight"]
    require(finite(latency) and latency >= 0, "Invalid registered latency penalty")
    fallback_count, missing_score = 0, 0
    budget_stops = []
    for row in rows:
        require(
            row.get("fit_id") in fits
            and row.get("arm") in mapping
            and row.get("case_id") in cases,
            "Observed row outside the frozen fit/arm/case roster",
        )
        require(
            row.get("regime") in plan["design"]["regimes"]
            and row.get("estimand") == "matched_training",
            "Row crosses regime or estimand",
        )
        case, spec = cases[row["case_id"]], plan["design"]["arms"][row["arm"]]
        require(
            all(row.get(key) == value for key, value in case.items()),
            "Row crossed its frozen case, source group, split or family",
        )
        require(
            [row.get(key) for key in ("core", "controller", "memory_mode")] == spec
            and row.get("training_seed") == fits[row["fit_id"]]["training_seed"],
            "Row relabeled a trained condition",
        )
        require(
            "condition_id" not in row or row["condition_id"] == mapping[row["arm"]],
            "Row supplied a conflicting condition label",
        )
        key = (row["fit_id"], row["regime"], row["arm"], row["case_id"])
        require(
            key not in coordinates,
            "Duplicate fit/regime/arm/case; retries cannot replace originals",
        )
        coordinates.add(key)
        status, operation = row.get("terminal_status"), row.get("original_operation_id")
        require(
            isinstance(status, str) and status,
            "Missing original terminal or unresolved status",
        )
        require(
            row.get("original_terminal_status", status) == status,
            "Input row already rewrote its original terminal status",
        )
        original_status = status
        if operation is not None:
            require(
                isinstance(operation, str)
                and operation
                and operation not in identities,
                "Duplicate original operation",
            )
            identities.add(operation)
        profile = profiles.get(row.get("profile_id"))
        if status in TERMINAL | {"BudgetStop"} or row.get("profile_id") is not None:
            require(
                profile is not None,
                "Observed original does not name a selected profile",
            )
            require(
                row.get("selection_lock_sha256") == lock_digest
                and all(
                    row.get(key) == profile[key]
                    for key in (
                        "fit_id",
                        "regime",
                        "arm",
                        "model_sha256",
                        "policy_sha256",
                        "training_memory_mode",
                        "observation_policy",
                    )
                ),
                "Row does not consume the frozen selected profile binding",
            )
            expected = (
                "pilot-"
                + canonical_sha(
                    [plan["execution_run_id"], profile["profile_id"], row["case_id"]]
                )[:32]
            )
            require(
                operation == expected,
                "Original operation came from a different plan/profile/case",
            )
        if status in TERMINAL | {"BudgetStop"}:
            require(
                digest(row.get("result_sha256")),
                "Known terminal row lacks original result byte binding",
            )
        score_verified = (
            row.get("evaluator_sha256") == plan["execution"]["evaluator_sha256"]
            and row.get("rubric_sha256") == plan["rubric_sha256"]
        )
        gross = (
            row.get("gross_score")
            if score_verified and finite(row.get("gross_score"))
            else None
        )
        if status == "Completed":
            require(gross is not None, "Completed result lacks a bound evaluator score")
        if gross is None:
            missing_score += 1
        seconds = row.get("deployment_wall_seconds")
        observed_deployment_wall = finite(seconds) and seconds >= 0
        if original_status == "BudgetStop":
            status = (
                "Completed"
                if gross is not None and observed_deployment_wall
                else "Unresolved"
            )
        adjusted = (
            gross if status == "Completed" else -1.0 if status == "Failed" else None
        )
        if seconds is None and status == "Failed":
            seconds = row.get("research_wall_seconds")
            fallback_count += 1
        utility = row.get("analysis_utility")
        utility_derived = False
        if (
            original_status == "BudgetStop"
            and status == "Completed"
            and utility is None
        ):
            utility = adjusted - latency * seconds
            utility_derived = True
        if status in TERMINAL and finite(utility):
            require(
                finite(seconds) and seconds >= 0,
                "Reported utility lacks its measured latency or failure envelope",
            )
            expected_utility = adjusted - latency * seconds
            require(
                finite(expected_utility)
                and math.isclose(
                    utility, expected_utility, rel_tol=1e-10, abs_tol=1e-10
                ),
                "Reported utility differs from the frozen score/failure/latency rule",
            )
        else:
            utility = None
        if original_status == "BudgetStop":
            budget_stops.append(
                {
                    "original_operation_id": operation,
                    "fit_id": row["fit_id"],
                    "regime": row["regime"],
                    "condition_id": mapping[row["arm"]],
                    "case_id": row["case_id"],
                    "original_terminal_status": original_status,
                    "analysis_terminal_status": status,
                    "bound_finite_evaluator_score": gross is not None,
                    "observed_nonnegative_deployment_wall": observed_deployment_wall,
                    "deployment_utility_derived_from_observed_inputs": utility_derived,
                }
            )
        mapped.append(
            {
                **row,
                "original_terminal_status": original_status,
                "terminal_status": status,
                "condition_id": mapping[row["arm"]],
                "metric_values": {
                    "gross_score": gross,
                    "failure_adjusted_score": adjusted,
                    "deployment_utility": utility,
                },
            }
        )
    return mapped, {
        "terminal_status_counts": dict(
            Counter(row["original_terminal_status"] for row in mapped)
        ),
        "original_terminal_status_counts": dict(
            Counter(row["original_terminal_status"] for row in mapped)
        ),
        "analysis_terminal_status_counts": dict(
            Counter(row["terminal_status"] for row in mapped)
        ),
        "budget_stop_count": len(budget_stops),
        "budget_stop_resolved_count": sum(
            item["analysis_terminal_status"] == "Completed" for item in budget_stops
        ),
        "budget_stop_unresolved_count": sum(
            item["analysis_terminal_status"] == "Unresolved" for item in budget_stops
        ),
        "budget_stop_adaptations": budget_stops,
        "failed_utility_outer_wall_fallback_rows": fallback_count,
        "rows_without_bound_raw_evaluator_score": missing_score,
    }
