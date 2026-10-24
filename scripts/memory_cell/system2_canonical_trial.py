"""Pre-registered exact arithmetic generation-pruning development experiment.

Previously exposed 204 multisets are diagnostics, not confirmation. The next 48
hash-ordered multisets are an untouched-for-THIS-test slice, not an independent
natural-language domain. Every solution is checked by the runtime proof verifier.
"""

import argparse
import hashlib
from itertools import combinations_with_replacement, product
import json
import os
from pathlib import Path
import re
import time

from system2_resumable_search import SearchSession
from system2_verified_search import digest, search, verify

PROFILES = ("reference", "canonical_pair")
BUDGETS = (256, 1024)


def tasks():
    catalogue = sorted(
        combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    prior, fresh = catalogue[:204], catalogue[204:252]
    if len(prior) != 204 or len(fresh) != 48 or set(prior) & set(fresh):
        raise ValueError("fixed disjoint task selection drift")
    return dict(previous_204=prior, next_48_tasks=fresh)


def journal(path, record):
    with path.open("a", encoding="utf8") as stream:
        stream.write(json.dumps(record, allow_nan=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def solve_one(numbers, budget, profile):
    first = SearchSession(numbers, 24, "heuristic_search", generation_profile=profile)
    before = first.advance(budget // 4)
    after = first.advance(budget)
    second = SearchSession(numbers, 24, "heuristic_search", generation_profile=profile)
    direct = second.advance(budget)
    if any(
        after[k] != direct[k] for k in ("found", "proof", "costs", "generation_filter")
    ):
        raise ValueError("pausing mutated proof or generated-work counters")
    if before["costs"]["generated_successors"] > after["costs"]["generated_successors"]:
        raise ValueError("nonmonotone cumulative work")
    if direct["costs"]["generated_successors"] > budget:
        raise ValueError("budget overshoot")
    if direct["found"] and not verify(numbers, 24, direct["proof"]):
        raise ValueError("invalid canonical proof")
    if profile == "reference":
        old = search(
            numbers,
            24,
            "heuristic_search",
            8192,
            None,
            terminal_policy="eager",
            successor_limit=budget,
        )
        if (old["found"], old["proof"], old["costs"]["generated_successors"]) != (
            direct["found"],
            direct["proof"],
            direct["costs"]["generated_successors"],
        ):
            raise ValueError("reference semantics changed")
    return dict(
        found=direct["found"],
        proof=direct["proof"],
        costs=direct["costs"],
        generation_filter=direct["generation_filter"],
        uninterrupted_seconds=direct["seconds"],
        resumed_seconds=after["seconds"],
        split_probe_success=before["found"],
    )


def evaluate(records, groups):
    required = {
        (digest(n), b, a)
        for tasks_ in groups.values()
        for n in tasks_
        for b, a in product(BUDGETS, PROFILES)
    }
    observed = [(r["query_id"], r["budget"], r["profile"]) for r in records]
    if (
        len(observed) != len(required)
        or set(observed) != required
        or len(set(observed)) != len(observed)
    ):
        raise ValueError("incomplete, duplicated or changed experimental census")
    lookup = {key: r for key, r in zip(observed, records, strict=True)}
    results = []
    contrasts = []
    failures = sum(r["status"] != "completed" for r in records)
    for group, ns in groups.items():
        for budget in BUDGETS:
            for profile in PROFILES:
                subset = [lookup[digest(n), budget, profile] for n in ns]
                completed = [r for r in subset if r["status"] == "completed"]
                results.append(
                    dict(
                        group=group,
                        budget=budget,
                        profile=profile,
                        planned=len(subset),
                        failed=len(subset) - len(completed),
                        valid_proofs=sum(bool(r.get("found")) for r in completed),
                        generated_successors=sum(
                            r.get("costs", {}).get("generated_successors", 0)
                            for r in subset
                        ),
                        timed_uninterrupted_seconds=sum(
                            r.get("uninterrupted_seconds", 0) for r in subset
                        ),
                        suppressed_pair_branches=sum(
                            r.get("generation_filter", {}).get("pair_skips", 0)
                            for r in subset
                        ),
                        suppressed_symmetric_variants=sum(
                            r.get("generation_filter", {}).get("symmetry_skips", 0)
                            for r in subset
                        ),
                        actual_compute_matched=False,
                    )
                )
            gained, lost, equal = [], [], []
            for n in ns:
                qid = digest(n)
                old, new = (
                    lookup[qid, budget, "reference"],
                    lookup[qid, budget, "canonical_pair"],
                )
                if old["status"] != "completed" or new["status"] != "completed":
                    continue
                if new["found"] and not old["found"]:
                    gained.append(list(n))
                elif old["found"] and not new["found"]:
                    lost.append(list(n))
                else:
                    equal.append(list(n))
            contrasts.append(
                dict(
                    group=group,
                    budget=budget,
                    paired=len(gained) + len(lost) + len(equal),
                    gains=gained,
                    losses=lost,
                    changed_outcomes=len(gained) + len(lost),
                    no_regression_observed=len(lost) == 0 and not failures,
                    independent_confirmation=False,
                )
            )
    return dict(
        planned=len(required),
        recorded=len(records),
        failed=failures,
        results=results,
        paired_contrasts=contrasts,
        proof_superiority_established=False,
        production_accepted=False,
        cost_equivalence_claimed=False,
        ndu_generalization_proven=False,
    )


def run(output, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact tested head required")
    output.mkdir(parents=True, exist_ok=False)
    groups = tasks()
    plan = dict(
        schema="hepta.system2.canonical-generation.v1",
        source_commit=source_commit,
        groups=groups,
        profiles=PROFILES,
        budgets=BUDGETS,
        generator="same original rational actions with equal-pair and symmetric-variant pruning",
        per_method_execution="quarter cumulative, full cumulative, independent uninterrupted parity",
        online_oracle_calls=0,
        training_updates=0,
        new_encoder_reader_calls=0,
        fresh_tasks_not_independent_domain=True,
        all_generated_actions_charged=True,
        pair_comparisons_not_free=True,
        production_accepted=False,
    )
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    records = []
    options = list(product(BUDGETS, PROFILES))
    for group, ns in groups.items():
        for numbers in ns:
            shifted = int(digest(numbers)[:8], 16) % len(options)
            for budget, profile in options[shifted:] + options[:shifted]:
                item = dict(
                    query_id=digest(numbers),
                    numbers=list(numbers),
                    group=group,
                    budget=budget,
                    profile=profile,
                )
                journal(output / "starts.jsonl", item)
                started = time.perf_counter()
                try:
                    item.update(solve_one(numbers, budget, profile), status="completed")
                except Exception as exc:
                    item.update(
                        status="failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:512],
                        costs_may_be_incomplete=True,
                    )
                item["elapsed_seconds"] = time.perf_counter() - started
                records.append(item)
                journal(output / "predictions.jsonl", item)
    data = (output / "predictions.jsonl").read_bytes()
    seal = hashlib.sha256(data).hexdigest()
    (output / "prediction-seal.json").write_text(
        json.dumps(dict(sha256=seal, rows=len(records), posthoc_analysis_started=False))
        + "\n"
    )
    summary = plan | evaluate(records, groups) | dict(prediction_sha256=seal)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    if hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest() != seal:
        raise ValueError("posthoc analysis mutated predictions")
    if summary["failed"]:
        raise RuntimeError("failed prediction rows retained in complete census")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(args.output, os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""))
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "planned",
                    "recorded",
                    "failed",
                    "results",
                    "paired_contrasts",
                )
            },
            allow_nan=False,
        )
    )
