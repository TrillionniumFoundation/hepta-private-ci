"""Read-only, counterbalanced CPU-cost replay of a sealed canonical experiment.

No labels, oracle, training, Reader, changed policy, or fresh-dataset claim.
Process CPU time and elapsed time are measured separately. Repeated timing
measurements are correlated; they are not independent test questions.
"""

from __future__ import annotations

import argparse
from itertools import combinations_with_replacement
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

from system2_resumable_search import SearchSession
from system2_verified_search import digest, verify

BUDGETS = (256, 1024)
PROFILES = ("reference", "canonical_pair")
REPEATS = 7


def cohorts():
    catalogue = sorted(
        combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    return dict(previous_204=catalogue[:204], next_48_tasks=catalogue[204:252])


def canonical_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def sealed_index(original, groups, expected_commit):
    raw = (original / "predictions.jsonl").read_bytes()
    seal = canonical_json(original / "prediction-seal.json")
    plan = canonical_json(original / "plan.json")
    if (
        seal.get("sha256") != hashlib.sha256(raw).hexdigest()
        or seal.get("rows") != len(raw.splitlines())
        or seal.get("posthoc_analysis_started") is not False
        or plan.get("source_commit") != expected_commit
    ):
        raise ValueError("source prediction/commit seal mismatch")
    expected = {
        (digest(n), b, p)
        for group in groups.values()
        for n in group
        for b in BUDGETS
        for p in PROFILES
    }
    seen = {}
    for line in raw.splitlines():
        row = json.loads(line)
        key = (row["query_id"], row["budget"], row["profile"])
        if (
            key in seen
            or key not in expected
            or row.get("status") != "completed"
            or digest(row.get("numbers")) != row["query_id"]
        ):
            raise ValueError("missing, duplicate, extra or failed source condition")
        if row.get("found") is not True and row.get("found") is not False:
            raise ValueError("invalid found status")
        if row["found"] and not verify(row["numbers"], 24, row["proof"]):
            raise ValueError("invalid source proof")
        if row["costs"]["generated_successors"] > row["budget"]:
            raise ValueError("source budget overshoot")
        seen[key] = row
    if set(seen) != expected:
        raise ValueError("incomplete source census")
    return seen, seal["sha256"]


def single(numbers, budget, profile):
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    result = SearchSession(
        numbers, 24, "heuristic_search", generation_profile=profile
    ).advance(budget)
    cpu, wall = (
        time.process_time_ns() - started_cpu,
        time.perf_counter_ns() - started_wall,
    )
    if result["found"] and not verify(numbers, 24, result["proof"]):
        raise ValueError("invalid fresh proof")
    if result["costs"]["generated_successors"] > budget:
        raise ValueError("fresh budget overshoot")
    return result, cpu, wall


def summarize(records, groups):
    rows = []
    for group, ns in groups.items():
        for budget in BUDGETS:
            subset = [
                r for r in records if r["group"] == group and r["budget"] == budget
            ]
            rounds = []
            for repeat in range(REPEATS):
                pair = {
                    profile: [
                        r
                        for r in subset
                        if r["repeat"] == repeat and r["profile"] == profile
                    ]
                    for profile in PROFILES
                }
                if any(len(pair[p]) != len(ns) for p in PROFILES):
                    raise ValueError("missing timed repeat")
                totals = {
                    p: dict(
                        cpu_ns=sum(r["cpu_ns"] for r in pair[p]),
                        wall_ns=sum(r["wall_ns"] for r in pair[p]),
                    )
                    for p in PROFILES
                }
                rounds.append(totals)
            ref = [r["reference"]["cpu_ns"] for r in rounds]
            can = [r["canonical_pair"]["cpu_ns"] for r in rounds]
            gain_fraction = (
                statistics.median(ref) - statistics.median(can)
            ) / statistics.median(ref)
            win_rounds = sum(a > b for a, b in zip(ref, can))
            rows.append(
                dict(
                    group=group,
                    budget=budget,
                    repeats=REPEATS,
                    question_count=len(ns),
                    cpu_median_reference_seconds=statistics.median(ref) / 1e9,
                    cpu_median_canonical_seconds=statistics.median(can) / 1e9,
                    median_cpu_fraction_saved=gain_fraction,
                    rounds_with_cpu_saving=win_rounds,
                    wall_median_reference_seconds=statistics.median(
                        r["reference"]["wall_ns"] for r in rounds
                    )
                    / 1e9,
                    wall_median_canonical_seconds=statistics.median(
                        r["canonical_pair"]["wall_ns"] for r in rounds
                    )
                    / 1e9,
                    correlated_repeats_not_independent=True,
                    per_round=rounds,
                )
            )
    return rows


def run(original, output, *, source_commit):
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(c not in "0123456789abcdef" for c in source_commit)
    ):
        raise ValueError("exact commit required")
    output.mkdir(parents=True, exist_ok=False)
    groups = cohorts()
    frozen, seal = sealed_index(original, groups, source_commit)
    plan = dict(
        schema="hepta.system2.canonical-cpu.v1",
        source_commit=source_commit,
        source_prediction_sha256=seal,
        repeats=REPEATS,
        groups={k: [list(n) for n in v] for k, v in groups.items()},
        budgets=BUDGETS,
        profiles=PROFILES,
        measurement="process_time_ns plus perf_counter_ns including session construction and internal verification; excludes posthoc proof recheck",
        counterbalance="question-hash parity plus repeat parity",
        eligibility=">=5% CPU median saving and at least 5/7 positive rounds, no proof losses",
        no_new_training=True,
        no_independent_domain=True,
        production_accepted=False,
    )
    (output / "plan.json").write_text(
        json.dumps(plan, indent=2, allow_nan=False) + "\n"
    )
    records = []
    for repeat in range(REPEATS):
        for group, numbers_list in groups.items():
            for numbers in numbers_list:
                qid = digest(numbers)
                for budget in BUDGETS:
                    profiles = (
                        PROFILES if (repeat + int(qid[:8], 16)) % 2 else PROFILES[::-1]
                    )
                    for profile in profiles:
                        fresh, cpu, wall = single(numbers, budget, profile)
                        prior = frozen[qid, budget, profile]
                        if (
                            fresh["found"] != prior["found"]
                            or list(fresh["proof"] or []) != (prior["proof"] or [])
                            or fresh["costs"] != prior["costs"]
                            or (
                                profile == "canonical_pair"
                                and fresh["generation_filter"]
                                != prior["generation_filter"]
                            )
                        ):
                            raise ValueError("source-vs-cost-run proof or work drift")
                        records.append(
                            dict(
                                repeat=repeat,
                                group=group,
                                query_id=qid,
                                budget=budget,
                                profile=profile,
                                cpu_ns=cpu,
                                wall_ns=wall,
                                found=fresh["found"],
                                generated_successors=fresh["costs"][
                                    "generated_successors"
                                ],
                                pair_checks=fresh["generation_filter"]["pair_checks"],
                            )
                        )
        # Persist each full repeat; a partially written later repeat is never accepted.
        with (output / "timings.jsonl").open("a", encoding="utf8") as stream:
            for row in records[-(252 * 2 * 2) :]:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    expected = (
        REPEATS * sum(len(ns) for ns in groups.values()) * len(BUDGETS) * len(PROFILES)
    )
    if len(records) != expected:
        raise ValueError("incomplete timed repeat census")
    summary = summarize(records, groups)
    # The paired proof results were verified against immutable source outputs.
    next_rows = [r for r in summary if r["group"] == "next_48_tasks"]
    eligible = all(
        r["median_cpu_fraction_saved"] >= 0.05 and r["rounds_with_cpu_saving"] >= 5
        for r in next_rows
    )
    pair_changes = []
    for group, ns in groups.items():
        for budget in BUDGETS:
            gains = [
                list(n)
                for n in ns
                if frozen[digest(n), budget, "canonical_pair"]["found"]
                and not frozen[digest(n), budget, "reference"]["found"]
            ]
            losses = [
                list(n)
                for n in ns
                if frozen[digest(n), budget, "reference"]["found"]
                and not frozen[digest(n), budget, "canonical_pair"]["found"]
            ]
            pair_changes.append(
                dict(group=group, budget=budget, gains=gains, losses=losses)
            )
    eligible = eligible and all(not row["losses"] for row in pair_changes)
    result = plan | dict(
        planned=expected,
        recorded=len(records),
        failures=0,
        summary=summary,
        paired_proof_changes=pair_changes,
        candidate_disposition=(
            "independent_cost_confirmation_required"
            if eligible
            else "stop_no_consistent_cpu_gain"
        ),
        real_flops_measured=False,
        wall_time_equivalence_claimed=False,
    )
    (output / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    ret = run(
        args.original,
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            {
                k: ret[k]
                for k in ("planned", "recorded", "failures", "candidate_disposition")
            }
        )
    )
