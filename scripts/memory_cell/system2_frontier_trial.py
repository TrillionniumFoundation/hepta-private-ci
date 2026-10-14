"""Fixed resumed-frontier stop study; all unchosen outcomes stay post-seal.

The continuation is the unchanged heuristic SearchSession, not a restarted or
switched solver. This control can save futile work, not find extra direct proofs.
"""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re

from safetensors.torch import load_file, save_file

from system2_ablation import model_digest
from system2_budget_control import COUNTERS, LIMITS, UNIT_COST
from system2_budget_trial import cohort, journal
from system2_frontier_value import (
    ARMS,
    TRAINING_MODES,
    collect_training,
    episode,
    fit,
    make_head,
)
from system2_native_receipt import index_rows
from system2_search_budget import read_parent, write
from system2_verified_search import digest, verify


def task_plan(parent):
    training, previous = cohort(parent)
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    exposed = [n for group in previous.values() for n in group]
    new = catalogue[108:156]
    if (
        len(exposed) != 96
        or len(new) != 48
        or set(new) & (set(training) | set(exposed))
    ):
        raise ValueError("fixed task identity or disjointness changed")
    return training, dict(exposed_96=exposed, next_48_tasks=new)


def analyze(records, groups):
    """Realized stop/resume ceiling is diagnostic only, never an input to choose."""
    expected = {
        (digest(n), b, a)
        for tasks in groups.values()
        for n in tasks
        for b in LIMITS
        for a in ARMS
    }
    indexed = index_rows(records, ("query_id", "budget", "arm"), expected)
    identities = {digest(n): (g, list(n)) for g, tasks in groups.items() for n in tasks}
    for row in records:
        if (row["group"], row["numbers"]) != identities[row["query_id"]]:
            raise ValueError("task identity drift")
        if row["status"] not in ("completed", "failed"):
            raise ValueError("unknown episode status")
        spent = row["costs"]["generated_successors"]
        if type(spent) is not int or not 0 <= spent <= row["budget"]:
            raise ValueError("known budget violation invalidates bounded utility")
        if row["status"] != "completed":
            continue
        if (
            type(row["found"]) is not bool
            or (row["found"] and not verify(row["numbers"], 24, row["proof"]))
            or (not row["found"] and row["proof"] is not None)
            or abs(row["utility"] - (float(row["found"]) - UNIT_COST * spent)) > 1e-12
        ):
            raise ValueError("invalid proof or task utility")
        direct = indexed[row["query_id"], row["budget"], "direct"]
        reference = indexed[row["query_id"], row["budget"], "resume"]
        if direct["status"] == "completed" and row["found"] and not direct["found"]:
            raise ValueError(
                "stopping cannot create a proof absent from unchanged direct policy"
            )
        if row["arm"] == "resume" and direct["status"] == "completed":
            if any(row[k] != direct[k] for k in ("found", "proof", "costs")):
                raise ValueError("fixed continuation no longer equals direct search")
        if row["arm"] != "direct" and reference["status"] == "completed":
            if any(
                row["probe"][k] != reference["probe"][k]
                for k in ("found", "proof", "costs")
            ):
                raise ValueError("paired probe drift")
            if row.get("context") != reference.get("context"):
                raise ValueError("paired observable context drift")
            if row["decision"]["action"] == "resume" and any(
                row[k] != reference[k] for k in ("found", "proof", "costs")
            ):
                raise ValueError("chosen continuation changed fixed policy outcome")
    results = []
    ceilings = []
    for group, tasks in groups.items():
        for budget in LIMITS:
            upper, unknown = 0.0, 0
            for numbers in tasks:
                qid = digest(numbers)
                options = [indexed[qid, budget, a] for a in ("resume", "probe_stop")]
                if any(r["status"] != "completed" for r in options):
                    unknown += 1
                else:
                    upper += max(r["utility"] for r in options)
            ceilings.append(
                dict(
                    group=group,
                    budget=budget,
                    questions=len(tasks),
                    unknown=unknown,
                    mean_utility_bounds=[
                        (upper - unknown * UNIT_COST * budget) / len(tasks),
                        (upper + unknown) / len(tasks),
                    ],
                    online_policy=False,
                    independent_confirmation=False,
                )
            )
            for arm in ARMS:
                rows = [indexed[digest(n), budget, arm] for n in tasks]
                failed = sum(r["status"] != "completed" for r in rows)
                known = sum(r["utility"] for r in rows if r["status"] == "completed")
                lost, brier, cost_error, missing = 0, [], [], 0
                for row in rows:
                    reference = indexed[row["query_id"], budget, "resume"]
                    if row["status"] == reference["status"] == "completed":
                        lost += reference["found"] and not row["found"]
                        decision = row["decision"]
                        if "probability" in decision:
                            extra = (
                                reference["costs"]["generated_successors"]
                                - reference["probe"]["costs"]["generated_successors"]
                            )
                            brier.append(
                                (decision["probability"] - float(reference["found"]))
                                ** 2
                            )
                            cost_error.append(
                                abs(decision["expected_additional_successors"] - extra)
                                / decision["remaining"]
                            )
                    else:
                        missing += 1
                results.append(
                    dict(
                        group=group,
                        budget=budget,
                        arm=arm,
                        planned=len(rows),
                        failed=failed,
                        valid_proofs=sum(
                            r["status"] == "completed" and r["found"] for r in rows
                        ),
                        direct_proofs_lost=lost,
                        unknown_pairs=missing,
                        utility_bounds=[
                            (known - failed * UNIT_COST * budget) / len(rows),
                            (known + failed) / len(rows),
                        ],
                        costs={k: sum(r["costs"][k] for r in rows) for k in COUNTERS},
                        seconds_including_failures=sum(r["seconds"] for r in rows),
                        stops=sum(r["decision"]["action"] == "stop" for r in rows),
                        brier=sum(brier) / len(brier) if brier else None,
                        normalized_cost_mae=sum(cost_error) / len(cost_error)
                        if cost_error
                        else None,
                        calibration_targets=len(brier),
                        probability_calibrated=False,
                    )
                )
    primary = {
        r["arm"]: r
        for r in results
        if r["group"] == "next_48_tasks" and r["budget"] == 1024
    }
    candidate = primary["frontier"]
    failed = sum(r["status"] != "completed" for r in records)
    controls = ("direct", "resume", "root_only", "shuffled", "cost_blind")
    gain = (
        not failed
        and candidate["direct_proofs_lost"] == 0
        and all(
            candidate["valid_proofs"] >= primary[c]["valid_proofs"]
            and candidate["utility_bounds"][0] > primary[c]["utility_bounds"][1]
            for c in controls
        )
    )
    return dict(
        planned=len(expected),
        recorded=len(records),
        failed=failed,
        results=results,
        realized_menu_ceilings=ceilings,
        primary="next_48_tasks/1024",
        disposition="independent_confirmation_required"
        if gain
        else "stop_no_controlled_resume_value_gain",
        production_accepted=False,
        probability_calibrated=False,
        proof_count_increase_possible=False,
    )


def run(archive, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact source identity required")
    output.mkdir(parents=True, exist_ok=False)
    parent, _, _, parent_audit = read_parent(archive)
    training, groups = task_plan(parent)
    plan = dict(
        schema="hepta.system2.frontier-return.v1",
        source_commit=source_commit,
        training=training,
        groups=groups,
        budgets=LIMITS,
        arms=ARMS,
        parameters_per_head=562,
        inputs="15 question/budget + 5 frontier counters + 12 top-queued-state features",
        policy="unchanged heuristic session; one quarter probe then stop or resume to full allowance",
        unit_cost=UNIT_COST,
        optimizer_steps=200,
        primary="next_48_tasks/1024",
        fixed_before_training=True,
        fresh_multisets_within_exposed_generator=48,
        intermediate_states_may_overlap=True,
        sufficient_state_not_claimed=True,
        new_encoder_reader_calls=0,
        old_restart_head_reused=False,
        exact_compute_matched=False,
        production_accepted=False,
        natural_language_evidence=False,
    )
    write(output / "plan.json", plan)
    write(output / "parent-audit.json", parent_audit)
    ledger = []
    try:
        x, y = collect_training(
            training, ledger, lambda e: journal(output / "training-events.jsonl", e)
        )
    finally:
        write(output / "training-rollouts.json", ledger)
        write(
            output / "training-census.json",
            dict(
                planned=len(training) * len(LIMITS),
                started=len(ledger),
                completed=sum(r["status"] == "completed" for r in ledger),
                failed=sum(r["status"] == "failed" for r in ledger),
                unstarted=len(training) * len(LIMITS) - len(ledger),
            ),
        )
    write(
        output / "training-examples.json", dict(features=x.tolist(), targets=y.tolist())
    )
    models, receipts = {}, {}
    for mode in TRAINING_MODES:
        model, receipts[mode] = fit(x, y, mode)
        path = output / (mode + ".safetensors")
        save_file(model.state_dict(), str(path))
        clone = make_head()
        clone.load_state_dict(load_file(str(path)), strict=True)
        clone.eval().requires_grad_(False)
        if model_digest(clone) != model_digest(model):
            raise ValueError("saved frontier head changed on reload")
        models[mode] = clone
    write(output / "training.json", receipts)
    frozen = {k: model_digest(v) for k, v in models.items()}
    write(output / "freeze.json", dict(models=frozen, evaluation_started=False))
    records = []
    configs = list(itertools.product(LIMITS, ARMS))
    for group, tasks in groups.items():
        for numbers in tasks:
            offset = int(digest(numbers)[:8], 16) % len(configs)
            for budget, arm in configs[offset:] + configs[:offset]:
                identity = dict(
                    group=group,
                    query_id=digest(numbers),
                    numbers=list(numbers),
                    budget=budget,
                    arm=arm,
                )
                journal(output / "starts.jsonl", identity)
                model = models.get(arm, models["frontier"])
                row = episode(
                    numbers,
                    budget,
                    arm,
                    model,
                    event_sink=lambda event, identity=identity: journal(
                        output / "events.jsonl", identity | event
                    ),
                )
                row.update(identity)
                records.append(row)
                journal(output / "predictions.jsonl", row)
    if frozen != {k: model_digest(v) for k, v in models.items()}:
        raise ValueError("evaluation mutated frontier heads")
    seal = hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
    write(
        output / "prediction-seal.json",
        dict(sha256=seal, rows=len(records), scoring_started=False),
    )
    summary = (
        plan
        | analyze(records, groups)
        | dict(prediction_sha256=seal, frozen_models=frozen)
    )
    write(output / "summary.json", summary)
    if hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest() != seal:
        raise ValueError("post-seal analysis changed predictions")
    if summary["failed"]:
        raise RuntimeError("failed episodes remain in the complete census")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = run(
            args.archive,
            args.output,
            source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ("planned", "recorded", "failed", "disposition", "results")
                },
                allow_nan=False,
            )
        )
    except BaseException as exc:
        if args.output.is_dir():
            write(
                args.output / "run-failure.json",
                dict(
                    error_type=type(exc).__name__, error=str(exc)[:512], complete=False
                ),
            )
        raise
