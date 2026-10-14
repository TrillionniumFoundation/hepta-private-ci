"""One-shot fixed-policy confirmation of a CPU-calibrated successor allocation.

The ratio 512 -> 1024 was frozen before opening catalogue positions 348:396.
This is a new synthetic slice, not an independent natural-language domain.
"""

from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import statistics

from system2_cpu_exchange import append, one, write
from system2_verified_search import digest

BASE_CAP = 512
PREFILTER_CAP = 1024
REPEATS = 5


def fresh_cohort():
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    new = catalogue[348:396]
    if len(new) != 48 or len(set(new)) != 48:
        raise ValueError("confirmation task drift")
    return new


def run(output, *, source_commit):
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(c not in "0123456789abcdef" for c in source_commit)
    ):
        raise ValueError("exact generating commit required")
    tasks = fresh_cohort()
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema="hepta.system2.cpu-confirmation.v1",
            source_commit=source_commit,
            questions=[list(n) for n in tasks],
            reference_cap=BASE_CAP,
            prefilter_cap=PREFILTER_CAP,
            repeats=REPEATS,
            fixed_before_question_outcomes=True,
            matching="aggregate measured process CPU",
            data="new synthetic multisets, overlapping arithmetic family",
            no_retraining_or_oracle=True,
            production_accepted=False,
        ),
    )
    records = []
    expected = len(tasks) * REPEATS * 2
    try:
        for rep in range(REPEATS):
            for n in tasks:
                qid = digest(n)
                profiles = [("reference", BASE_CAP), ("prefilter", PREFILTER_CAP)]
                if (rep + int(qid[:8], 16)) % 2:
                    profiles.reverse()
                for profile, cap in profiles:
                    row = dict(
                        repeat=rep,
                        question_id=qid,
                        numbers=list(n),
                        profile=profile,
                        successor_cap=cap,
                        status="started",
                    )
                    append(output / "starts.jsonl", row)
                    try:
                        receipt = one(n, cap, profile)
                        row.update(status="completed", **receipt)
                    except BaseException as exc:
                        row.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:512],
                            unknown_cost=True,
                        )
                        append(output / "predictions.jsonl", row)
                        raise
                    append(output / "predictions.jsonl", row)
                    records.append(row)
        if len(records) != expected:
            raise ValueError("incomplete predeclared confirmation")
        raw = (output / "predictions.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "prediction-seal.json",
            dict(sha256=seal, rows=len(records), posthoc_review_started=False),
        )
        rounds = []
        for rep in range(REPEATS):
            left = {
                r["question_id"]: r
                for r in records
                if r["repeat"] == rep and r["profile"] == "reference"
            }
            right = {
                r["question_id"]: r
                for r in records
                if r["repeat"] == rep and r["profile"] == "prefilter"
            }
            if len(left) != 48 or set(left) != set(right):
                raise ValueError("question identity drift")
            gains = [k for k in left if not left[k]["found"] and right[k]["found"]]
            losses = [k for k in left if left[k]["found"] and not right[k]["found"]]
            for k in left:
                if left[k]["found"] and (
                    not right[k]["found"]
                    or left[k]["proof"] != right[k]["proof"]
                    or left[k]["work"]["generated_successors"]
                    != right[k]["work"]["generated_successors"]
                ):
                    raise ValueError("proof lost under same-policy expanded budget")
            old_cpu = sum(r["cpu_ns"] for r in left.values())
            new_cpu = sum(r["cpu_ns"] for r in right.values())
            rounds.append(
                dict(
                    repeat=rep,
                    baseline_proofs=sum(x["found"] for x in left.values()),
                    optimized_proofs=sum(x["found"] for x in right.values()),
                    gains=gains,
                    losses=losses,
                    baseline_cpu_ns=old_cpu,
                    optimized_cpu_ns=new_cpu,
                    cpu_ratio=new_cpu / old_cpu,
                )
            )
        accepted = all(
            not r["losses"] and r["cpu_ratio"] <= 1.05 for r in rounds
        ) and any(r["gains"] for r in rounds)
        result = dict(
            planned=expected,
            recorded=len(records),
            failed=0,
            rounds=rounds,
            median_cpu_ratio=statistics.median(r["cpu_ratio"] for r in rounds),
            median_proof_gain=statistics.median(len(r["gains"]) for r in rounds),
            candidate_disposition=(
                "independent_natural_domain_required"
                if accepted
                else "stop_no_stable_cpu_confirmation"
            ),
            production_accepted=False,
            independent_natural_data=False,
            generation_commit=source_commit,
            prediction_sha256=seal,
        )
        write(output / "summary.json", result)
        if (
            hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("prediction seal changed")
        return result
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                complete=False,
                missing_work_not_imputed=True,
                completed_attempts=len(records),
                planned=expected,
            ),
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
                k: r[k]
                for k in ("planned", "recorded", "failed", "candidate_disposition")
            }
        )
    )
