"""Sealed, research-only CPU experiment for exact-target leaf filtering.

A terminal with an internally computed exact Fraction unequal to the goal
cannot be a valid proof. Potential successes STILL require independent postfix
verification. The default search behavior remains unchanged.
"""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import statistics
import time

from system2_canonical_cpu import BUDGETS, PROFILES, cohorts, sealed_index
from system2_resumable_search import SearchSession
from system2_verified_search import digest, verify

REPEATS = 7
TERMINALS = ("all_leaves", "goal_prefilter")


def append(path, record):
    with path.open("a", encoding="utf8") as stream:
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def timed(numbers, budget, generation, terminal):
    if terminal not in TERMINALS or generation not in PROFILES or budget not in BUDGETS:
        raise ValueError("unregistered terminal experiment")
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    result = SearchSession(
        numbers,
        24,
        "heuristic_search",
        generation_profile=generation,
        terminal_prefilter=terminal == "goal_prefilter",
    ).advance(budget)
    cpu, wall = time.process_time_ns() - start_cpu, time.perf_counter_ns() - start_wall
    if result["found"] and not verify(numbers, 24, result["proof"]):
        raise ValueError("independent verifier rejected result")
    if result["costs"]["generated_successors"] > budget:
        raise ValueError("bounded successor budget exceeded")
    return result, cpu, wall


def assert_pair(legacy, filtered, sealed):
    for row in (legacy, filtered):
        if (
            row["found"] != sealed["found"]
            or list(row["proof"] or []) != list(sealed["proof"] or [])
            or row["generation_filter"] != sealed["generation_filter"]
        ):
            raise ValueError("source proof/profile drift")
        for key in ("generated_successors", "popped_states", "critic_examples"):
            if row["costs"][key] != sealed["costs"][key]:
                raise ValueError("source generated work drift")
    if legacy["costs"] != sealed["costs"]:
        raise ValueError("old verifier count drift")
    if (
        filtered["costs"]["verifier_calls"] + filtered["verification_skips"]
        != legacy["costs"]["verifier_calls"]
        or legacy["verification_skips"] != 0
        or legacy["terminal_prefilter"]
        or not filtered["terminal_prefilter"]
    ):
        raise ValueError("unaccounted exact-terminal verification")


def summarize(records, groups, repeats):
    results = []
    for group, tasks in groups.items():
        for budget, generation in itertools.product(BUDGETS, PROFILES):
            rounds = []
            for repeat in range(repeats):
                group_rows = [
                    r
                    for r in records
                    if (r["group"], r["budget"], r["generation"], r["repeat"])
                    == (group, budget, generation, repeat)
                ]
                if len(group_rows) != len(tasks) * 2:
                    raise ValueError("missing per-round records")
                snapshot = {}
                for terminal in TERMINALS:
                    rows = [r for r in group_rows if r["terminal"] == terminal]
                    if len(rows) != len(tasks):
                        raise ValueError("incomplete paired positions")
                    snapshot[terminal] = dict(
                        cpu_ns=sum(x["cpu_ns"] for x in rows),
                        wall_ns=sum(x["wall_ns"] for x in rows),
                        verification_calls=sum(x["verifier_calls"] for x in rows),
                        verification_skips=sum(x["verification_skips"] for x in rows),
                    )
                rounds.append(snapshot)
            ref = [x["all_leaves"]["cpu_ns"] for x in rounds]
            new = [x["goal_prefilter"]["cpu_ns"] for x in rounds]
            results.append(
                dict(
                    group=group,
                    budget=budget,
                    generation=generation,
                    tasks=len(tasks),
                    repeats=repeats,
                    median_cpu_all_seconds=statistics.median(ref) / 1e9,
                    median_cpu_filtered_seconds=statistics.median(new) / 1e9,
                    cpu_fraction_saved=1
                    - statistics.median(new) / statistics.median(ref),
                    favorable_cpu_rounds=sum(a > b for a, b in zip(ref, new)),
                    original_verifier_calls_per_repeat=sum(
                        r["all_leaves"]["verification_calls"] for r in rounds
                    )
                    / repeats,
                    filtered_verifier_calls_per_repeat=sum(
                        r["goal_prefilter"]["verification_calls"] for r in rounds
                    )
                    / repeats,
                    skipped_verifications_per_repeat=sum(
                        r["goal_prefilter"]["verification_skips"] for r in rounds
                    )
                    / repeats,
                    repeated_measurements_correlated=True,
                    rounds=rounds,
                )
            )
    return results


def run(original, output, *, source_commit, repeats=REPEATS):
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(c not in "0123456789abcdef" for c in source_commit)
        or type(repeats) is not int
        or not 1 <= repeats <= REPEATS
    ):
        raise ValueError("exact generating SHA and bounded repeats required")
    groups = cohorts()
    sealed, source_digest = sealed_index(original, groups, source_commit)
    output.mkdir(parents=True, exist_ok=False)
    expected = (
        repeats
        * sum(map(len, groups.values()))
        * len(BUDGETS)
        * len(PROFILES)
        * len(TERMINALS)
    )
    plan = dict(
        schema="hepta.system2.terminal-prefilter.v1",
        source_commit=source_commit,
        source_prediction_sha256=source_digest,
        groups={k: [list(n) for n in v] for k, v in groups.items()},
        budgets=BUDGETS,
        generations=PROFILES,
        terminals=TERMINALS,
        repeats=repeats,
        goal_comparison="exact Fraction, trusted in-process successors",
        independent_verifier_for_possible_success=True,
        counterbalance="question identity xor repetition parity",
        promotion="at least 10% median CPU saved and >=5/7 favorable rounds in both budgets and generators, no proof/work drift",
        no_new_model_training_encoder_reader_or_oracle=True,
        exposed_synthetic_tasks_not_independent=True,
        production_accepted=False,
    )
    (output / "plan.json").write_text(
        json.dumps(plan, indent=2, allow_nan=False) + "\n"
    )
    records = []
    pairs = 0
    try:
        for repeat in range(repeats):
            for group, tasks in groups.items():
                for numbers in tasks:
                    question_id = digest(numbers)
                    for budget, generation in itertools.product(BUDGETS, PROFILES):
                        order = (
                            TERMINALS
                            if (repeat + int(question_id[:8], 16)) % 2
                            else TERMINALS[::-1]
                        )
                        matched = {}
                        for terminal in order:
                            row = dict(
                                group=group,
                                question_id=question_id,
                                numbers=list(numbers),
                                budget=budget,
                                generation=generation,
                                repeat=repeat,
                                terminal=terminal,
                                status="started",
                            )
                            append(output / "starts.jsonl", row)
                            try:
                                result, cpu, wall = timed(
                                    numbers, budget, generation, terminal
                                )
                                row.update(
                                    status="completed",
                                    cpu_ns=cpu,
                                    wall_ns=wall,
                                    found=result["found"],
                                    proof=result["proof"],
                                    costs=result["costs"],
                                    generation_filter=result["generation_filter"],
                                    verifier_calls=result["costs"]["verifier_calls"],
                                    verification_skips=result["verification_skips"],
                                )
                                matched[terminal] = result
                            except BaseException as exc:
                                row.update(
                                    status="failed",
                                    error_type=type(exc).__name__,
                                    error=str(exc)[:512],
                                    unknown_work=True,
                                )
                                append(output / "predictions.jsonl", row)
                                raise
                            records.append(row)
                            append(output / "predictions.jsonl", row)
                        assert_pair(
                            matched["all_leaves"],
                            matched["goal_prefilter"],
                            sealed[question_id, budget, generation],
                        )
                        pairs += 1
        if len(records) != expected or pairs * 2 != expected:
            raise ValueError("incomplete paired experiment census")
        summary = summarize(records, groups, repeats)
        next_rows = [r for r in summary if r["group"] == "next_48_tasks"]
        eligible = repeats == REPEATS and all(
            r["cpu_fraction_saved"] >= 0.10 and r["favorable_cpu_rounds"] >= 5
            for r in next_rows
        )
        receipt = dict(
            planned=expected,
            recorded=len(records),
            failed=0,
            summary=summary,
            candidate_disposition="independent_cpu_confirmation_required"
            if eligible
            else "stop_no_consistent_cpu_gain",
            reasoning_emergence_established=False,
            production_accepted=False,
        )
        raw = (output / "predictions.jsonl").read_bytes()
        (output / "prediction-seal.json").write_text(
            json.dumps(
                dict(
                    sha256=hashlib.sha256(raw).hexdigest(),
                    rows=len(records),
                    posthoc_analysis_started=False,
                )
            )
            + "\n"
        )
        (output / "summary.json").write_text(
            json.dumps(receipt, indent=2, allow_nan=False) + "\n"
        )
        return receipt
    except BaseException as exc:
        (output / "run-failure.json").write_text(
            json.dumps(
                dict(
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    complete=False,
                    planned=expected,
                    completed=len(records),
                    missing_work_not_imputed=True,
                )
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    r = run(
        args.original,
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            {
                k: r[k]
                for k in ("planned", "recorded", "failed", "candidate_disposition")
            }
        )
    )
