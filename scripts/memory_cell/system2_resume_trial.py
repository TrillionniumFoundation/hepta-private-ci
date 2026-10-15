"""Compare paused/resumed search with uninterrupted search and paid root restart.

Consume sealed observed-return outputs for diagnosis, never to choose an online
policy. Exact terminal proof checks remain separate from the scoring model.
No new controller training; a restart-trained gate is NOT reused for resumption.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import os
import re

from system2_ablation import model_digest
from system2_budget_control import ARMS, LIMITS, UNIT_COST
from system2_budget_trial import cohort, journal
from system2_native_receipt import index_rows, strict_json
from system2_search_budget import read_parent, write
from system2_resumable_search import SearchSession
from system2_verified_search import digest, verify


def restart_ceiling(rows):
    """Post-hoc menu ceiling; NOT an online policy or a global optimality bound."""
    groups = defaultdict(dict)
    for row in rows:
        key = row["group"], row["budget"], row["query_id"]
        if row["arm"] in groups[key]:
            raise ValueError("duplicate diagnostic cell")
        groups[key][row["arm"]] = row
    totals = defaultdict(
        lambda: dict(
            questions=0,
            direct_proofs=0,
            learned_proofs=0,
            restart_menu_proofs=0,
            structurally_lost=[],
            unknown=0,
            utility_upper_sum=0.0,
        )
    )
    for (group, budget, qid), cell in groups.items():
        target = totals[group, budget]
        target["questions"] += 1
        names = (
            "direct_heuristic",
            "learned",
            "probe_stop",
            "probe_heuristic",
            "probe_value",
        )
        if any(
            name not in cell or cell[name]["status"] != "completed" for name in names
        ):
            target["unknown"] += 1
            continue
        menu = [cell[name] for name in names[2:]]
        possible = any(r["found"] for r in menu)
        target["direct_proofs"] += cell["direct_heuristic"]["found"]
        target["learned_proofs"] += cell["learned"]["found"]
        target["restart_menu_proofs"] += possible
        target["utility_upper_sum"] += max(r["utility"] for r in menu)
        if cell["direct_heuristic"]["found"] and not possible:
            target["structurally_lost"].append(
                dict(query_id=qid, numbers=cell["direct_heuristic"]["numbers"])
            )
    return [
        dict(
            group=g,
            budget=b,
            **v,
            independent_upper_bound=False,
            evaluation_outcomes_used_only_posthoc=True,
        )
        for (g, b), v in sorted(totals.items())
    ]


def run(
    archive,
    budget_run,
    output,
    *,
    source_commit,
    execution_context="full-repository-source",
):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact source identity required")
    output.mkdir(parents=True, exist_ok=False)
    parent, models, _, parent_audit = read_parent(archive)
    _, groups = cohort(parent)
    source_binding = (
        {"source_commit": source_commit}
        if execution_context == "full-repository-source"
        else {"overlay_parent": source_commit}
    )
    plan = dict(
        schema="hepta.system2.resume.v1",
        **source_binding,
        execution_context=execution_context,
        executing_files={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                Path(__file__).with_name("system2_resumable_search.py"),
            )
        },
        groups=groups,
        budgets=LIMITS,
        solvers=["heuristic_search", "value_search"],
        split="quarter cumulative budget then full cumulative budget, same policy",
        criterion="same proof, generated successors and full session cost counters",
        original_mode="unchanged eager root search; post-limit queue draining is not replayed",
        new_training_updates=0,
        new_encoder_reader_calls=0,
        in_memory_only=True,
        same_exposed_tasks=True,
        production_accepted=False,
        controller_improvement_claim=False,
    )
    write(output / "plan.json", plan)
    raw = (budget_run / "predictions.jsonl").read_bytes()
    seal = strict_json((budget_run / "prediction-seal.json").read_bytes())
    if (
        hashlib.sha256(raw).hexdigest() != seal["sha256"]
        or seal["scoring_started"] is not False
    ):
        raise ValueError("observed-return prediction seal mismatch")
    previous = [strict_json(line) for line in raw.splitlines()]
    expected = {
        (digest(n), b, a)
        for tasks in groups.values()
        for n in tasks
        for b in LIMITS
        for a in ARMS
    }
    old = index_rows(previous, ("query_id", "budget", "arm"), expected)
    if seal.get("rows") != len(previous):
        raise ValueError("observed-return prediction count mismatch")
    bindings = {digest(n): (g, list(n)) for g, tasks in groups.items() for n in tasks}
    previous_plan = strict_json((budget_run / "plan.json").read_bytes())
    if (
        previous_plan["groups"] != json.loads(json.dumps(groups))
        or previous_plan["frozen_child_model"] != model_digest(models["value"])
        or previous_plan["objective"]["cost_per_generated_successor"] != UNIT_COST
    ):
        raise ValueError("prior task/model/utility identity drift")
    for row in previous:
        if (row["group"], row["numbers"]) != bindings[row["query_id"]]:
            raise ValueError("prior question/group identity drift")
        if row["status"] != "completed":
            continue
        spent = row["costs"]["generated_successors"]
        if (
            type(row["found"]) is not bool
            or type(spent) is not int
            or not 0 <= spent <= row["budget"]
            or abs(row["utility"] - (float(row["found"]) - UNIT_COST * spent)) > 1e-12
            or (row["found"] and not verify(row["numbers"], 24, row["proof"]))
            or (not row["found"] and row["proof"] is not None)
        ):
            raise ValueError("invalid prior proof or cost")
    write(output / "restart-menu-ceiling.json", restart_ceiling(previous))
    write(
        output / "source-receipt.json",
        dict(
            parent_archive=parent_audit,
            budget_prediction_sha256=seal["sha256"],
            budget_source=previous_plan["source_commit"],
        ),
    )
    rows = []
    for group, tasks in groups.items():
        for numbers in tasks:
            for budget in LIMITS:
                for solver in plan["solvers"]:
                    row = dict(
                        group=group,
                        query_id=digest(numbers),
                        numbers=list(numbers),
                        budget=budget,
                        solver=solver,
                    )
                    try:
                        model = models["value"] if solver == "value_search" else None
                        one = SearchSession(numbers, 24, solver, model).advance(budget)
                        session = SearchSession(numbers, 24, solver, model)
                        probe = session.advance(budget // 4)
                        split = session.advance(budget)
                        row.update(uninterrupted=one, probe=probe, resumed=split)
                        if any(one[k] != split[k] for k in ("found", "proof", "costs")):
                            raise ValueError(
                                "pause changed policy outcome or useful-work counters"
                            )
                        direct = old[
                            digest(numbers),
                            budget,
                            "direct_value"
                            if solver == "value_search"
                            else "direct_heuristic",
                        ]
                        if direct["status"] != "completed":
                            raise ValueError("historical direct reference unavailable")
                        if (
                            one["found"] != direct["found"]
                            or (list(one["proof"]) if one["proof"] else None)
                            != direct["proof"]
                            or one["costs"]["generated_successors"]
                            != direct["costs"]["generated_successors"]
                        ):
                            raise ValueError(
                                "resumable engine changed legacy proof or successor order"
                            )
                        if one["found"] and not verify(numbers, 24, one["proof"]):
                            raise ValueError("invalid resumed proof")
                        row["status"] = "matched"
                    except Exception as exc:
                        row.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:512],
                        )
                    rows.append(row)
                    journal(output / "comparisons.jsonl", row)
    wanted = {
        (digest(n), b, s)
        for tasks in groups.values()
        for n in tasks
        for b in LIMITS
        for s in plan["solvers"]
    }
    index_rows(rows, ("query_id", "budget", "solver"), wanted)
    failed = sum(r["status"] != "matched" for r in rows)
    contrasts = []
    for group in groups:
        for budget in LIMITS:
            subset = [
                r
                for r in rows
                if (r["group"], r["budget"], r["solver"])
                == (group, budget, "heuristic_search")
            ]
            controls = [old[r["query_id"], budget, "probe_heuristic"] for r in subset]
            available = all(r["status"] == "matched" for r in subset) and all(
                r["status"] == "completed" for r in controls
            )
            contrasts.append(
                dict(
                    group=group,
                    budget=budget,
                    planned=len(subset),
                    available=available,
                    resume_proofs=sum(r["resumed"]["found"] for r in subset)
                    if available
                    else None,
                    restart_proofs=sum(r["found"] for r in controls)
                    if available
                    else None,
                    resume_successors=sum(
                        r["resumed"]["costs"]["generated_successors"] for r in subset
                    )
                    if available
                    else None,
                    restart_successors=sum(
                        r["costs"]["generated_successors"] for r in controls
                    )
                    if available
                    else None,
                )
            )
    summary = plan | dict(
        planned=len(wanted),
        recorded=len(rows),
        failed=failed,
        exact_resume_matches=len(rows) - failed,
        contrasts=contrasts,
        disposition="resume_mechanics_validated_not_learned_control_gain"
        if not failed
        else "reject_resume_drift",
    )
    write(output / "summary.json", summary)
    if failed:
        raise RuntimeError("resume comparisons failed; all attempted rows retained")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("budget_run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.archive,
                args.budget_run,
                args.output,
                source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
            ),
            allow_nan=False,
        )
    )
