"""Calibrate larger search budgets on CPU cost alone, then freeze and evaluate.

Explicit development-only research. A CPU budget matched on a different task
cohort is not a per-question deadline, a FLOP match, or an independent domain.
There is no training, oracle, semantic Reader or random data replacement.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import statistics
import time

from system2_resumable_search import SearchSession
from system2_verified_search import digest, verify

BASE_BUDGETS = (256, 512, 1024)
CANDIDATES = {
    256: (256, 320, 384, 448, 512),
    512: (512, 640, 768, 896, 1024),
    1024: (1024, 1280, 1536, 1792, 2048),
}
CALIBRATION_REPEATS = 3
EVAL_REPEATS = 5
SCHEMA = "hepta.system2.cpu-exchange.v1"


def cohorts():
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    train = catalogue[:204]
    test = catalogue[300:348]
    if len(train) != 204 or len(test) != 48 or set(train) & set(test):
        raise ValueError("fixed cohort drift")
    return train, test


def write(path, item):
    path.write_text(json.dumps(item, sort_keys=True, indent=2, allow_nan=False) + "\n")


def append(path, item):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def one(numbers, limit, profile):
    registered = set(BASE_BUDGETS).union(*(set(v) for v in CANDIDATES.values()))
    if (
        type(limit) is not int
        or limit not in registered
        or profile not in ("reference", "prefilter")
    ):
        raise ValueError("bounded named frozen policy required")
    cpu0, wall0 = time.process_time_ns(), time.perf_counter_ns()
    result = SearchSession(
        numbers, 24, "heuristic_search", terminal_prefilter=profile == "prefilter"
    ).advance(limit)
    cpu, wall = time.process_time_ns() - cpu0, time.perf_counter_ns() - wall0
    if (result["found"] and not verify(numbers, 24, result["proof"])) or (
        not result["found"] and result["proof"] is not None
    ):
        raise ValueError("invalid proof or spurious proof")
    if result["costs"]["generated_successors"] > limit:
        raise ValueError("budget overshoot")
    return {
        "cpu_ns": cpu,
        "wall_ns": wall,
        "found": result["found"],
        "proof": result["proof"],
        "work": result["costs"],
        "verification_skips": result["verification_skips"],
    }


def calibrate(tasks, output):
    """Accept candidate based only on median aggregate CPU, never proof count."""
    rows = []
    for rep in range(CALIBRATION_REPEATS):
        for numbers in tasks:
            qid = digest(numbers)
            for baseline in BASE_BUDGETS:
                choices = [("reference", baseline)] + [
                    ("prefilter", cap) for cap in CANDIDATES[baseline]
                ]
                shift = (rep + int(qid[:8], 16)) % len(choices)
                for profile, cap in choices[shift:] + choices[:shift]:
                    row = {
                        "repeat": rep,
                        "question_id": qid,
                        "baseline": baseline,
                        "profile": profile,
                        "limit": cap,
                        "status": "started",
                    }
                    append(output / "calibration-starts.jsonl", row)
                    try:
                        receipt = one(numbers, cap, profile)
                        row.update(
                            status="completed",
                            cpu_ns=receipt["cpu_ns"],
                            found=receipt["found"],
                            generated=receipt["work"]["generated_successors"],
                        )
                    except BaseException as exc:
                        row.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:512],
                            unknown_cost=True,
                        )
                        append(output / "calibration.jsonl", row)
                        raise
                    rows.append(row)
                    append(output / "calibration.jsonl", row)
    selections = {}
    for baseline in BASE_BUDGETS:
        rounds = {}
        for profile, cap in [("reference", baseline)] + [
            ("prefilter", c) for c in CANDIDATES[baseline]
        ]:
            totals = [
                sum(
                    row["cpu_ns"]
                    for row in rows
                    if row["repeat"] == rep
                    and row["baseline"] == baseline
                    and row["profile"] == profile
                    and row["limit"] == cap
                )
                for rep in range(CALIBRATION_REPEATS)
            ]
            if not totals or min(totals) <= 0:
                raise ValueError("incomplete calibration")
            rounds[profile + ":" + str(cap)] = {
                "cpu_per_round_ns": totals,
                "median_total_ns": statistics.median(totals),
            }
        budget_cpu = rounds["reference:" + str(baseline)]["median_total_ns"]
        feasible = [
            c
            for c in CANDIDATES[baseline]
            if rounds["prefilter:" + str(c)]["median_total_ns"] <= budget_cpu
        ]
        # The smallest candidate equals the baseline cap; it should never need
        # to be larger to satisfy this rule. Failure remains a failed trial.
        if not feasible:
            raise ValueError("no cost-feasible prefilter candidate")
        frozen = max(feasible)
        selections[str(baseline)] = {
            "successor_limit": frozen,
            "source_budget": baseline,
            "reference_cpu_ns": budget_cpu,
            "calibrated_cpu_ns": rounds["prefilter:" + str(frozen)]["median_total_ns"],
            "candidate_costs": rounds,
            "selection_used_proof_labels": False,
        }
    write(output / "calibration-choice.json", selections)
    return selections


def evaluate(tasks, selections, output):
    rows = []
    for rep in range(EVAL_REPEATS):
        for numbers in tasks:
            qid = digest(numbers)
            for baseline in BASE_BUDGETS:
                profiles = [
                    ("reference", baseline),
                    ("prefilter", selections[str(baseline)]["successor_limit"]),
                ]
                if (rep + int(qid[:8], 16)) % 2:
                    profiles.reverse()
                for profile, limit in profiles:
                    context = {
                        "repeat": rep,
                        "question_id": qid,
                        "numbers": list(numbers),
                        "baseline": baseline,
                        "profile": profile,
                        "limit": limit,
                        "status": "started",
                    }
                    append(output / "evaluation-starts.jsonl", context)
                    try:
                        data = one(numbers, limit, profile)
                        context.update(data, status="completed")
                    except BaseException as exc:
                        context.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:512],
                            unknown_cost=True,
                        )
                        append(output / "evaluation.jsonl", context)
                        raise
                    rows.append(context)
                    append(output / "evaluation.jsonl", context)
    n_expected = EVAL_REPEATS * len(tasks) * len(BASE_BUDGETS) * 2
    if len(rows) != n_expected:
        raise ValueError("missing task-policy pairs")
    seal = hashlib.sha256((output / "evaluation.jsonl").read_bytes()).hexdigest()
    write(
        output / "evaluation-seal.json",
        {"sha256": seal, "rows": len(rows), "posthoc_scoring_started": False},
    )
    # No label oracle: proof validity and resource receipts are the only outcomes.
    contrasts = []
    for baseline in BASE_BUDGETS:
        rounds = []
        for rep in range(EVAL_REPEATS):
            old = [
                r
                for r in rows
                if r["repeat"] == rep
                and r["baseline"] == baseline
                and r["profile"] == "reference"
            ]
            new = [
                r
                for r in rows
                if r["repeat"] == rep
                and r["baseline"] == baseline
                and r["profile"] == "prefilter"
            ]
            if len(old) != len(tasks) or len(new) != len(tasks):
                raise ValueError("incomplete paired evaluation")
            old_by_id = {r["question_id"]: r for r in old}
            new_by_id = {r["question_id"]: r for r in new}
            for key in old_by_id:
                left, right = old_by_id[key], new_by_id[key]
                if left["found"] and (
                    not right["found"]
                    or left["proof"] != right["proof"]
                    or left["work"]["generated_successors"]
                    != right["work"]["generated_successors"]
                ):
                    raise ValueError(
                        "same-policy proof was lost or changed at larger budget"
                    )
            gains = [
                k
                for k in old_by_id
                if not old_by_id[k]["found"] and new_by_id[k]["found"]
            ]
            losses = [
                k
                for k in old_by_id
                if old_by_id[k]["found"] and not new_by_id[k]["found"]
            ]
            rounds.append(
                {
                    "repeat": rep,
                    "baseline_proofs": sum(x["found"] for x in old),
                    "prefilter_proofs": sum(x["found"] for x in new),
                    "baseline_cpu_ns": sum(x["cpu_ns"] for x in old),
                    "prefilter_cpu_ns": sum(x["cpu_ns"] for x in new),
                    "gains": gains,
                    "losses": losses,
                    "baseline_generated": sum(
                        x["work"]["generated_successors"] for x in old
                    ),
                    "prefilter_generated": sum(
                        x["work"]["generated_successors"] for x in new
                    ),
                }
            )
        med_old = statistics.median(x["baseline_cpu_ns"] for x in rounds)
        med_new = statistics.median(x["prefilter_cpu_ns"] for x in rounds)
        contrasts.append(
            {
                "baseline_limit": baseline,
                "allocated_prefilter_limit": selections[str(baseline)][
                    "successor_limit"
                ],
                "median_proof_gain": statistics.median(
                    x["prefilter_proofs"] - x["baseline_proofs"] for x in rounds
                ),
                "median_cpu_ratio": med_new / med_old,
                "cpu_ratios_per_repeat": [
                    x["prefilter_cpu_ns"] / x["baseline_cpu_ns"] for x in rounds
                ],
                "every_repeat_cpu_within_five_pct": all(
                    x["prefilter_cpu_ns"] <= 1.05 * x["baseline_cpu_ns"] for x in rounds
                ),
                "no_loss_in_all_repetitions": all(not x["losses"] for x in rounds),
                "at_least_one_gain": any(x["gains"] for x in rounds),
                "rounds": rounds,
            }
        )
    if hashlib.sha256((output / "evaluation.jsonl").read_bytes()).hexdigest() != seal:
        raise ValueError("evaluation seal drift")
    return rows, contrasts, seal


def run(output, *, source_commit, calibration=None, evaluation=None):
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(c not in "0123456789abcdef" for c in source_commit)
    ):
        raise ValueError("exact generating commit required")
    base, fresh = cohorts()
    base = base if calibration is None else calibration
    fresh = fresh if evaluation is None else evaluation
    if (
        not base
        or not fresh
        or len(set(base)) != len(base)
        or len(set(fresh)) != len(fresh)
        or set(base) & set(fresh)
    ):
        raise ValueError("training/evaluation identity overlap")
    output.mkdir(exist_ok=False, parents=True)
    plan = {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "calibration_tasks": [list(n) for n in base],
        "evaluation_tasks": [list(n) for n in fresh],
        "baseline_budgets": BASE_BUDGETS,
        "candidate_successor_caps": CANDIDATES,
        "calibration_repeats": CALIBRATION_REPEATS,
        "evaluation_repeats": EVAL_REPEATS,
        "selection_signal": "only aggregate process CPU cost in 204 old numeric tasks",
        "cpu_matched_on_evaluation_not_guaranteed": True,
        "independent_natural_data": False,
        "production_accepted": False,
    }
    write(output / "plan.json", plan)
    try:
        decisions = calibrate(base, output)
        rows, contrasts, seal = evaluate(fresh, decisions, output)
        good = all(
            x["no_loss_in_all_repetitions"] and x["every_repeat_cpu_within_five_pct"]
            for x in contrasts
        )
        better = any(x["median_proof_gain"] > 0 for x in contrasts)
        report = {
            "schema": SCHEMA,
            "recorded": len(rows),
            "failed": 0,
            "calibration_planned": len(base)
            * len(BASE_BUDGETS)
            * 6
            * CALIBRATION_REPEATS,
            "evaluation_planned": len(fresh) * len(BASE_BUDGETS) * 2 * EVAL_REPEATS,
            "selection": decisions,
            "contrasts": contrasts,
            "evaluation_sha256": seal,
            "candidate_disposition": (
                "independent_compute_confirmation_required"
                if good and better
                else "stop_no_stable_aggregate_cpu_gain"
            ),
            "production_accepted": False,
            "general_ndu_fbsde_gain": False,
        }
        write(output / "summary.json", report)
        return report
    except BaseException as exc:
        write(
            output / "run-failure.json",
            {
                "type": type(exc).__name__,
                "error": str(exc)[:512],
                "complete": False,
                "missing_work_not_free": True,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    r = run(args.output, source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""))
    print(
        json.dumps(
            {
                "evaluation_planned": r["evaluation_planned"],
                "recorded": r["recorded"],
                "candidate_disposition": r["candidate_disposition"],
            }
        )
    )
