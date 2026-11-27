"""Read-only consistency gate for a new real-data study; never starts training.

Receipts and hashes must be checked against their actual sources independently.
Passing these checks is neither execution authority nor evidence of superiority.
"""

import argparse
import json
import math
from pathlib import Path
import re

ARMS = ("gru", "gru_d", "cfc", "snn", "mamba", "attention", "hcsn",
        "frozen_physics", "call_only", "risk_only", "dual", "plain_dual_gate",
        "no_reset", "mean_state", "independent_generators", "content_only", "rollover_on")
READOUTS = {"call", "risk", "margin", "expected_events", "active"}
ERROR_AXES = ("phase", "space", "tail", "time")
COST_PARTS = ("training", "tuning", "failed_retries", "encoder_tables", "evaluation", "transfer")
METRICS = ("state_bytes", "peak_ram_bytes", "peak_vram_bytes", "throughput_per_second",
           "p99_seconds", "training_wall_seconds", "energy_joules")
ENERGY_SCOPE = "whole_system_all_cost_parts"


def _number(value, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_plan(plan):
    """Return blocking contract errors; an intentionally unfinished draft fails."""
    errors = []
    require = lambda condition, message: errors.append(message) if not condition else None
    require(plan.get("schema") == "hcsn-real-benchmark-v1", "unknown plan schema")
    require(plan.get("study_id") and plan.get("budget_origin") == "new_study_only"
            and plan.get("old_study_credit") == 0, "new study identity/budget required")
    for name in ("data_sha256", "split_sha256", "protocol_sha256", "measurement_context_sha256"):
        require(_hash(plan.get(name)), f"missing {name}")
    require(plan.get("timestamp_unit_verified") is True, "timestamp unit unverified")
    gap, limit = plan.get("max_gap_seconds"), plan.get("qualified_max_dt_seconds")
    require(_number(gap) and _number(limit, True) and gap <= limit
            and plan.get("long_gap_policy") == "reject", "gap exceeds qualified single step")
    partitions = plan.get("partitions", {})
    for field in ("subjects", "sequence_ids", "sequence_sha256"):
        seen = set()
        for part in ("train", "dev", "test"):
            values = partitions.get(part, {}).get(field, [])
            require(isinstance(values, list) and bool(values), f"empty {part}.{field}")
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                errors.append(f"invalid {part}.{field}")
                continue
            require(not seen.intersection(values), f"leakage across {field}")
            require(len(values) == len(set(values)), f"duplicate {part}.{field}")
            seen.update(values)
            if field == "sequence_sha256":
                require(all(_hash(v) for v in values), f"invalid {part} sequence digest")
    frontend = plan.get("frontend", {})
    require(_hash(frontend.get("sha256")) and frontend.get("frozen") is True
            and frontend.get("fit_partition") == "train" and frontend.get("causal") is True,
            "shared frozen causal training-only frontend required")
    require(plan.get("test_used_for_selection") is False, "test data used for selection")
    seeds = plan.get("training_seeds", [])
    require(isinstance(seeds, list) and len(seeds) >= 5
            and all(type(s) is int for s in seeds) and len(set(seeds)) == len(seeds),
            "at least five distinct training seeds required")
    budget = plan.get("budget", {})
    require(_number(budget.get("per_arm_wall_seconds"), True)
            and type(budget.get("tuning_trials")) is int and budget["tuning_trials"] > 0
            and _number(budget.get("max_trainable_parameters"), True)
            and bool(budget.get("authorization_reference")), "new explicit budget missing")
    numerical = plan.get("numerical_qualification", {})
    require(numerical.get("passed") is True and _hash(numerical.get("source_sha256"))
            and _hash(numerical.get("evidence_sha256")), "numerical qualification missing")
    for axis in ERROR_AXES:
        row = numerical.get(axis, {})
        require(_number(row.get("budget"), True) and _number(row.get("observed"))
                and row["observed"] <= row["budget"], f"unclosed numerical error: {axis}")
    arms = plan.get("arms", {})
    for arm in ARMS:
        spec = arms.get(arm, {})
        require(_hash(spec.get("implementation_sha256")), f"missing implementation: {arm}")
        require(spec.get("frontend_sha256") == frontend.get("sha256")
                and _hash(spec.get("frontend_sha256")), f"frontend mismatch: {arm}")
        require(_number(spec.get("parameters"), True) and _number(spec.get("content_width"), True)
                and _hash(spec.get("search_space_sha256")), f"capacity/tuning absent: {arm}")
        require(_number(budget.get("max_trainable_parameters"), True)
                and _number(spec.get("parameters"), True)
                and spec["parameters"] <= budget["max_trainable_parameters"],
                f"parameter budget exceeded/unknown: {arm}")
    for arm, expected in (("call_only", {"call"}), ("risk_only", {"risk"}),
                          ("dual", {"call", "risk"}), ("content_only", set()),
                          ("plain_dual_gate", set())):
        require(arms.get(arm, {}).get("physical_readouts") is not None
                and set(arms[arm]["physical_readouts"]) == expected,
                f"physical bypass mismatch: {arm}")
    dual, gate = arms.get("dual", {}), arms.get("plain_dual_gate", {})
    require(_number(dual.get("parameters"), True) and _number(gate.get("parameters"), True)
            and abs(gate["parameters"] / dual["parameters"] - 1) <= .05
            and gate.get("content_width") == dual.get("content_width"),
            "ordinary dual gate must match parameters within 5% and content width")
    require(arms.get("hcsn", {}).get("implementation_sha256") == numerical.get("source_sha256")
            and _hash(numerical.get("source_sha256")), "qualification/source mismatch")
    return errors


def validate_results(plan, results):
    """Validate selected independent fits; missing meters only block efficiency claims."""
    errors, missing_metrics = validate_plan(plan), []
    seen, ids, checkpoints, initializations = set(), set(), set(), set()
    arm_seconds, arm_trials = {}, {}
    for run in results:
        arm, seed = run.get("arm"), run.get("training_seed")
        label = f"{arm}/{seed}"
        key = (arm, seed)
        if arm not in ARMS or seed not in plan.get("training_seeds", []) or key in seen:
            errors.append(f"unexpected/duplicate training unit: {label}")
        seen.add(key)
        if run.get("independent_unit") != "training_run" or run.get("status") != "completed":
            errors.append(f"not a completed independent fit: {label}")
        for field, previous in (("run_id", ids), ("checkpoint_sha256", checkpoints),
                                ("initialization_sha256", initializations)):
            value = run.get(field)
            if not isinstance(value, str) or not value or value in previous:
                errors.append(f"missing/reused {field}: {label}")
            if isinstance(value, str):
                previous.add(value)
            if field != "run_id" and not _hash(value):
                errors.append(f"invalid {field}: {label}")
        expected = {"split_sha256": plan.get("split_sha256"),
                    "frontend_sha256": plan.get("frontend", {}).get("sha256"),
                    "measurement_context_sha256": plan.get("measurement_context_sha256"),
                    "implementation_sha256": plan.get("arms", {}).get(arm, {}).get("implementation_sha256")}
        if any(run.get(k) != v or not _hash(v) for k, v in expected.items()):
            errors.append(f"result provenance mismatch: {label}")
        if not _hash(run.get("execution_receipt_sha256")):
            errors.append(f"execution receipt missing: {label}")
        quality = run.get("quality", {})
        if any(not _number(quality.get(k)) or quality[k] > 1 for k in ("macro_f1", "brier", "ece")):
            errors.append(f"quality/calibration missing: {label}")
        cost = run.get("cost_seconds", {})
        if (cost.get("ledger_complete") is not True
                or any(not _number(cost.get(k)) for k in COST_PARTS)
                or not _number(cost.get("training"), True)
                or not _number(cost.get("evaluation"), True)
                or not _number(cost.get("total"), True)):
            errors.append(f"unknown/incomplete compute accounting: {label}")
        elif not math.isclose(sum(cost[k] for k in COST_PARTS), cost["total"], rel_tol=1e-8):
            errors.append(f"compute total/budget mismatch: {label}")
        else:
            arm_seconds[arm] = arm_seconds.get(arm, 0) + cost["total"]
        trials = run.get("tuning_trials_charged")
        if type(trials) is not int or trials < 0:
            errors.append(f"tuning trial accounting missing: {label}")
        else:
            arm_trials[arm] = arm_trials.get(arm, 0) + trials
        for metric in METRICS:
            row = run.get("metrics", {}).get(metric, {})
            value = row.get("value")
            if value is None and row.get("status") == "unknown" and row.get("reason"):
                missing_metrics.append(f"{label}:{metric}")
            elif (row.get("status") != "measured" or not _number(value)
                  or (value == 0 and not (metric == "peak_vram_bytes" and run.get("device") == "cpu"))
                  or not row.get("scope")):
                errors.append(f"invalid/zero-filled measurement: {label}:{metric}")
            if metric == "energy_joules" and value is not None and row.get("scope") != ENERGY_SCOPE:
                missing_metrics.append(f"{label}:energy does not cover whole experiment")
    trials_cap = plan.get("budget", {}).get("tuning_trials")
    if type(trials_cap) is not int or any(t > trials_cap for t in arm_trials.values()):
        errors.append("aggregate tuning trial budget exceeded or unknown")
    cap = plan.get("budget", {}).get("per_arm_wall_seconds")
    if not _number(cap, True) or any(total > cap for total in arm_seconds.values()):
        errors.append("aggregate compute budget exceeded or unknown")
    expected = {(arm, seed) for arm in ARMS for seed in plan.get("training_seeds", [])}
    if seen != expected:
        errors.append("missing required arms or independent training seeds")
    return {"contract_valid": not errors, "quality_eligible": not errors,
            "efficiency_eligible": not errors and not missing_metrics,
            "distinct_arm_seed_pairs": len(seen), "errors": errors,
            "unmeasured_or_partial": missing_metrics,
            "claim_boundary": "Record consistency only; authenticate receipts and analyze uncertainty."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = (validate_results(plan, json.loads(args.results.read_text(encoding="utf-8")))
              if args.results else {"errors": validate_plan(plan)})
    print(json.dumps(report, indent=2, allow_nan=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
