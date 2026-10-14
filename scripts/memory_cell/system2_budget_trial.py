"""Fit one shared budget head on actual frozen-policy returns, then freeze it.

The gate never learns from evaluation traces. Fixed continuation arms supply
post-seal calibration targets for unchosen actions; they do NOT feed the runtime
gate. This is a synthetic, two-stage compute controller, not general NDU efficacy.
"""

import argparse
from fractions import Fraction
import hashlib
import itertools
import json
import os
from pathlib import Path
import re

from safetensors.torch import load_file, save_file

from system2_ablation import model_digest
from system2_budget_audit import menu_report
from system2_budget_control import (
    ARMS,
    COUNTERS,
    LIMITS,
    UNIT_COST,
    collect_training,
    episode,
    fit,
    make_head,
    training_census,
)
from system2_native_receipt import index_rows
from system2_search_budget import read_parent, task_groups, write
from system2_verified_search import ExactLabels, digest, verify


def journal(path, row):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def cohort(parent):
    previous = task_groups(parent)
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    old = previous["reused"] + previous["next_hash_slice"]
    new = catalogue[60:108]
    train = catalogue[:12]
    if (
        set(train) & (set(old) | set(new))
        or set(old) & set(new)
        or len(old) != 48
        or len(new) != 48
    ):
        raise ValueError("training/prior/new task census drift")
    return train, dict(previous_tasks=old, next_48_tasks=new)


def aggregate(rows):
    if not rows:
        raise ValueError("empty aggregation")
    failed = sum(r["status"] != "completed" for r in rows)
    known = [r["utility"] for r in rows if r["status"] == "completed"]
    lower = sum(known) - sum(
        UNIT_COST * r["budget"] for r in rows if r["status"] != "completed"
    )
    return dict(
        planned=len(rows),
        failed=failed,
        valid_proofs=sum(r["verified_solution"] for r in rows),
        solvable_tasks=sum(r["solvable"] for r in rows),
        utility_bounds=[lower / len(rows), (sum(known) + failed) / len(rows)],
        seconds_including_failures=sum(r["seconds"] for r in rows),
        costs={k: sum(r["costs"][k] for r in rows) for k in COUNTERS},
        controller_calls=sum(r["controller_calls"] for r in rows),
        voluntary_stops=sum(
            r.get("decision", {}).get("action") == "stop" for r in rows
        ),
        failed_costs_may_be_incomplete=failed > 0,
    )


def calibration(rows):
    """Unchosen actions are scored only from completed fixed-control experiments."""
    lookup = {(r["query_id"], r["budget"], r["arm"]): r for r in rows}
    summary = {}
    for arm in ("learned", "shuffled", "cost_blind"):
        errors, cost_errors, unavailable = [], [], 0
        for row in rows:
            detail = row.get("decision", {})
            if row["arm"] != arm or "probability" not in detail:
                continue
            for i, control in enumerate(("probe_heuristic", "probe_value")):
                reference = lookup[row["query_id"], row["budget"], control]
                if (
                    reference["status"] != "completed"
                    or len(reference["executions"]) != 2
                ):
                    unavailable += 1
                    continue
                if (
                    row["executions"][0]["result"]["costs"]
                    != reference["executions"][0]["result"]["costs"]
                ):
                    raise ValueError("probe context changed across paired policies")
                tail = reference["executions"][1]["result"]
                errors.append((detail["probability"][i] - float(tail["found"])) ** 2)
                cost_errors.append(
                    abs(
                        detail["expected_successors"][i]
                        - tail["costs"]["generated_successors"]
                    )
                    / detail["remaining"]
                )
        summary[arm] = dict(
            observed_action_targets=len(errors),
            missing=unavailable,
            brier_score=sum(errors) / len(errors) if errors else None,
            normalized_cost_mae=sum(cost_errors) / len(cost_errors)
            if cost_errors
            else None,
            calibration_established=False,
            conditional_on_failed_probe=True,
        )
    return summary


def run(archive, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact generating commit required")
    output.mkdir(exist_ok=False, parents=True)
    parent, children, _, audit = read_parent(archive)
    training, groups = cohort(parent)
    plan = dict(
        schema="hepta.system2.budget-returns.v1",
        source_commit=source_commit,
        training=training,
        groups=groups,
        budgets=LIMITS,
        arms=ARMS,
        parameters=324,
        probe="fixed heuristic, floor(total/4) successors, exact eager verifier",
        tail="restart frozen chosen search with remaining budget; repeated work paid again",
        objective=dict(
            success_reward=1.0, cost_per_generated_successor=UNIT_COST, discount=1.0
        ),
        targets="observed fixed-child proof success and normalized consumed successors",
        optimizer_steps=200,
        training_tasks=12,
        hyperparameter_search=False,
        primary="next_48_tasks/1024: learned versus direct_heuristic, probe_heuristic, probe_value, shuffled, cost_blind",
        frozen_child_model=model_digest(children["value"]),
        new_encoder_reader_calls=0,
        exact_compute_matched=False,
        independent_natural_task_evidence=False,
        intermediate_states_may_overlap=True,
        probability_calibrated=False,
        general_ndu_qualified=False,
        production_accepted=False,
    )
    write(output / "plan.json", plan)
    write(output / "parent-audit.json", audit)
    rollouts = []
    try:
        x, y, _ = collect_training(
            training,
            children["value"],
            ledger=rollouts,
            event_sink=lambda event: journal(output / "training-events.jsonl", event),
        )
    finally:
        # Also runs on ordinary exceptions/interrupts; durable child events cover
        # earlier progress if the process terminates before this final snapshot.
        write(output / "training-rollouts.json", rollouts)
        write(output / "training-census.json", training_census(rollouts, training))
    write(
        output / "training-examples.json",
        dict(
            features=x.tolist(),
            targets=y.tolist(),
            counterfactual_rollout_calls=sum(len(r["executions"]) for r in rollouts),
            generated_successors=sum(
                e["result"]["costs"]["generated_successors"]
                for r in rollouts
                for e in r["executions"]
            ),
        ),
    )
    models, receipts = {}, {}
    for name, shuffle in (("learned", False), ("shuffled", True)):
        model, receipts[name] = fit(x, y, shuffled=shuffle)
        file = output / (name + ".safetensors")
        save_file(model.state_dict(), str(file))
        restored = make_head()
        restored.load_state_dict(load_file(str(file)), strict=True)
        restored.eval().requires_grad_(False)
        if model_digest(restored) != model_digest(model):
            raise ValueError("frozen controller reload changed parameters")
        models[name] = restored
    write(output / "training.json", receipts)
    frozen = {
        k: model_digest(m) for k, m in {**models, "child": children["value"]}.items()
    }
    write(output / "freeze.json", dict(models=frozen, evaluation_started=False))
    records = []
    configurations = list(itertools.product(LIMITS, ARMS))
    for group, tasks in groups.items():
        for numbers in tasks:
            qid = digest(numbers)
            offset = int(qid[:8], 16) % len(configurations)
            for budget, arm in configurations[offset:] + configurations[:offset]:
                identity = dict(group=group, query_id=qid, arm=arm, budget=budget)
                journal(output / "starts.jsonl", identity)
                head = models["shuffled" if arm == "shuffled" else "learned"]
                row = episode(
                    numbers,
                    budget,
                    arm,
                    children["value"],
                    head,
                    decision_sink=lambda d: journal(
                        output / "decisions.jsonl", identity | dict(decision=d)
                    ),
                )
                row.update(identity)
                records.append(row)
                journal(output / "predictions.jsonl", row)
    expected = {
        (digest(n), b, a)
        for tasks in groups.values()
        for n in tasks
        for b, a in configurations
    }
    index_rows(records, ("query_id", "budget", "arm"), expected)
    if frozen != {
        k: model_digest(m) for k, m in {**models, "child": children["value"]}.items()
    }:
        raise ValueError("evaluation changed a frozen policy")
    seal = hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
    write(
        output / "prediction-seal.json",
        dict(sha256=seal, rows=len(records), scoring_started=False),
    )
    labeler = ExactLabels()
    possible = {
        digest(n): labeler.solve(tuple(map(Fraction, n)), 24)
        for tasks in groups.values()
        for n in tasks
    }
    scored = []
    for row in records:
        valid = bool(row.get("found")) and verify(row["numbers"], 24, row["proof"])
        if row.get("found") and not valid:
            raise ValueError("invalid exported proof")
        scored.append(
            row | dict(verified_solution=valid, solvable=possible[row["query_id"]])
        )
    results = []
    for group in groups:
        for budget, arm in configurations:
            rows = [
                r
                for r in scored
                if (r["group"], r["budget"], r["arm"]) == (group, budget, arm)
            ]
            results.append(dict(group=group, budget=budget, arm=arm) | aggregate(rows))
    primary = {
        r["arm"]: r
        for r in results
        if r["group"] == "next_48_tasks" and r["budget"] == 1024
    }
    controls = (
        "direct_heuristic",
        "probe_heuristic",
        "probe_value",
        "shuffled",
        "cost_blind",
    )
    candidate = primary["learned"]
    gain = all(
        candidate["valid_proofs"] >= primary[c]["valid_proofs"]
        and candidate["utility_bounds"][0] > primary[c]["utility_bounds"][1]
        for c in controls
    )
    summary = plan | dict(
        planned=len(expected),
        recorded=len(scored),
        failed=sum(r["status"] != "completed" for r in scored),
        results=results,
        calibration={
            g: calibration([r for r in scored if r["group"] == g]) for g in groups
        },
        prediction_sha256=seal,
        frozen_models=frozen,
        evaluation_oracle_states=labeler.calls,
        candidate_disposition="independent_confirmation_required"
        if gain
        else "stop_no_controlled_budget_value_gain",
        reasoning_emergence_established=False,
    )
    write(output / "action-menu-audit.json", menu_report(records, groups))
    write(output / "scored.json", scored)
    write(output / "summary.json", summary)
    if hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest() != seal:
        raise ValueError("scoring changed original decisions or proofs")
    if summary["failed"]:
        raise RuntimeError("failed episodes retained in the complete census")
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
                    for k in (
                        "planned",
                        "recorded",
                        "failed",
                        "candidate_disposition",
                        "results",
                    )
                },
                allow_nan=False,
            )
        )
    except Exception as exc:
        if args.output.is_dir():
            write(
                args.output / "run-failure.json",
                dict(
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    complete=False,
                    missing_work_not_imputed=True,
                ),
            )
        raise
