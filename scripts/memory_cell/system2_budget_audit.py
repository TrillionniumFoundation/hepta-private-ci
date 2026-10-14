"""Post-seal action-menu bounds; no policy input, model call, or new evaluation.

The perfect-information envelope concerns ONLY stop and the two observed root
restarts. It is not achievable online in general and does not bound other search
algorithms. Missing/failed arms retain the planned denominator and bounded unknown
utility. A failed invocation is never reinterpreted as a negative task label.
"""

import argparse
from collections import defaultdict
import hashlib
import math
import json
from pathlib import Path

from system2_budget_control import ARMS, COUNTERS, LIMITS, UNIT_COST
from system2_native_receipt import strict_json, verified_archive
from system2_verified_search import digest, validate_task, verify

MENU = ("probe_stop", "probe_heuristic", "probe_value")


def _bounds(row, budget):
    if row is None or row["status"] != "completed":
        return -UNIT_COST * budget, 1.0
    spent = row["costs"]["generated_successors"]
    utility = float(row["found"]) - UNIT_COST * spent
    return utility, utility


def _probe_key(row):
    first = row["executions"][0]
    result = first["result"]
    return (
        first["solver"],
        first["successor_limit"],
        result["found"],
        result["proof"],
        result["costs"],
    )


def menu_report(rows, groups):
    """Compare the realized menu envelope with the direct and learned policies.

    This function is called only after the complete prediction journal is sealed.
    The seal/order is enforced by the runner or archive entry point, not claimed
    as a property of an arbitrary Python function invocation.
    """
    questions = {}
    for group, tasks in groups.items():
        for numbers in tasks:
            validate_task(numbers, 24)
            qid = digest(numbers)
            if qid in questions:
                raise ValueError("duplicate question across planned groups")
            questions[qid] = (group, list(numbers))
    if not questions:
        raise ValueError("empty planned census")
    expected = {(qid, b, a) for qid in questions for b in LIMITS for a in ARMS}
    indexed = {}
    for row in rows:
        key = row["query_id"], row["budget"], row["arm"]
        if key not in expected or key in indexed:
            raise ValueError("duplicate or unplanned prediction")
        if (row["group"], row["numbers"]) != questions[row["query_id"]]:
            raise ValueError("question provenance drift")
        if row["status"] not in ("completed", "failed"):
            raise ValueError("unregistered prediction status")
        indexed[key] = row
        if row["status"] != "completed":
            spent = row.get("costs", {}).get("generated_successors")
            if isinstance(spent, (int, float)) and spent > row["budget"]:
                raise ValueError("failed run exceeded the assumed successor cap")
            continue
        costs = row["costs"]
        if (
            type(row["found"]) is not bool
            or any(type(costs[k]) is not int or costs[k] < 0 for k in COUNTERS)
            or costs["generated_successors"] > row["budget"]
            or not isinstance(row["utility"], (int, float))
            or not math.isfinite(row["utility"])
            or abs(row["utility"] - _bounds(row, row["budget"])[0]) > 1e-12
            or (row["found"] and not verify(row["numbers"], 24, row["proof"]))
            or (not row["found"] and row["proof"] is not None)
            or not 1 <= len(row["executions"]) <= 2
        ):
            raise ValueError("invalid completed proof, utility, or accounting")
        if any(e["status"] != "completed" for e in row["executions"]):
            raise ValueError("completed episode has incomplete child")
        for execution in row["executions"]:
            result = execution["result"]
            if (
                type(result["found"]) is not bool
                or any(
                    type(result["costs"][k]) is not int or result["costs"][k] < 0
                    for k in COUNTERS
                )
                or result["costs"]["generated_successors"]
                > execution["successor_limit"]
                or (result["found"] and not verify(row["numbers"], 24, result["proof"]))
                or (not result["found"] and result["proof"] is not None)
            ):
                raise ValueError("invalid child proof or work")
        if any(
            row[k] != row["executions"][-1]["result"][k] for k in ("found", "proof")
        ):
            raise ValueError("episode proof differs from final child result")
        if any(
            sum(e["result"]["costs"][k] for e in row["executions"]) != costs[k]
            for k in COUNTERS
        ):
            raise ValueError("child work does not sum to episode receipt")

    details, grouped = [], defaultdict(list)
    for qid, (group, numbers) in questions.items():
        for budget in LIMITS:
            cell = {a: indexed.get((qid, budget, a)) for a in ARMS}
            complete_menu = [
                cell[a]
                for a in MENU
                if cell[a] is not None and cell[a]["status"] == "completed"
            ]
            if complete_menu and any(
                _probe_key(r) != _probe_key(complete_menu[0]) for r in complete_menu
            ):
                raise ValueError("counterfactual controls do not share the same probe")
            candidate = cell["learned"]
            if candidate is not None and candidate["status"] == "completed":
                action = candidate.get("decision", {}).get("action", "stop")
                selected = {
                    "stop": "probe_stop",
                    "heuristic_search": "probe_heuristic",
                    "value_search": "probe_value",
                }.get(action)
                if selected is None:
                    raise ValueError("unknown learned action")
                reference = cell[selected]
                if reference is not None and reference["status"] == "completed":
                    if _probe_key(candidate) != _probe_key(reference) or any(
                        candidate[k] != reference[k]
                        for k in ("found", "proof", "costs")
                    ):
                        raise ValueError(
                            "selected frozen action disagrees with paired control"
                        )
            menu_bounds = [_bounds(cell[a], budget) for a in MENU]
            envelope = [max(v[0] for v in menu_bounds), max(v[1] for v in menu_bounds)]
            direct, learned = (
                _bounds(cell["direct_heuristic"], budget),
                _bounds(candidate, budget),
            )
            direct_known = (
                cell["direct_heuristic"] is not None
                and cell["direct_heuristic"]["status"] == "completed"
            )
            known_flags = [r["found"] for r in complete_menu]
            menu_complete = len(complete_menu) == len(MENU)
            proof_bounds = [
                int(any(known_flags)),
                int(any(known_flags) or not menu_complete),
            ]
            lost = bool(
                direct_known
                and cell["direct_heuristic"]["found"]
                and proof_bounds[1] == 0
            )
            unknown = sum(
                cell[a] is None or cell[a]["status"] != "completed"
                for a in (*MENU, "direct_heuristic", "learned")
            )
            detail = dict(
                group=group,
                query_id=qid,
                numbers=numbers,
                budget=budget,
                unknown_required_arms=unknown,
                menu_utility_bounds=envelope,
                menu_proof_bounds=proof_bounds,
                structurally_lost_direct_proof=lost,
                menu_minus_direct_bounds=[
                    envelope[0] - direct[1],
                    envelope[1] - direct[0],
                ],
                selector_regret_bounds=[
                    max(0.0, envelope[0] - learned[1]),
                    max(0.0, envelope[1] - learned[0]),
                ],
            )
            details.append(detail)
            grouped[group, budget].append(detail)
    summaries = []
    for (group, budget), items in sorted(grouped.items()):
        n = len(items)
        summary = dict(
            group=group,
            budget=budget,
            planned_questions=n,
            questions_with_unknown_arms=sum(
                r["unknown_required_arms"] > 0 for r in items
            ),
            menu_proofs_bounds=[
                sum(r["menu_proof_bounds"][j] for r in items) for j in (0, 1)
            ],
            structurally_lost=[
                r["numbers"] for r in items if r["structurally_lost_direct_proof"]
            ],
        )
        for name in (
            "menu_utility_bounds",
            "menu_minus_direct_bounds",
            "selector_regret_bounds",
        ):
            summary["mean_" + name] = [
                sum(r[name][j] for r in items) / n for j in (0, 1)
            ]
        summary["menu_cannot_beat_observed_direct_mean"] = (
            summary["mean_menu_minus_direct_bounds"][1] <= 0
        )
        summaries.append(summary)
    return dict(
        schema="hepta.system2.menu-evidence.v1",
        planned_predictions=len(expected),
        recorded_predictions=len(rows),
        missing_predictions=len(expected) - len(rows),
        failed_predictions=sum(r["status"] == "failed" for r in rows),
        groups=summaries,
        details=details,
        compared_menu=list(MENU),
        unit_cost=UNIT_COST,
        perfect_information_not_online_policy=True,
        confidence_interval=False,
        unknown_imputation=False,
        bounds_assume_registered_successor_cap=True,
        new_model_calls=0,
        production_accepted=False,
    )


def audit_archive(path, pin, source, output):
    files = verified_archive(path, pin)
    if files["tested-commit.txt"].decode().strip() != source:
        raise ValueError("archive generating source mismatch")
    plan = strict_json(files["trial/plan.json"])
    raw = files["trial/predictions.jsonl"]
    seal = strict_json(files["trial/prediction-seal.json"])
    if (
        plan["source_commit"] != source
        or plan["objective"]
        != dict(
            success_reward=1.0, cost_per_generated_successor=UNIT_COST, discount=1.0
        )
        or plan["arms"] != list(ARMS)
        or plan["budgets"] != list(LIMITS)
        or seal["scoring_started"] is not False
        or hashlib.sha256(raw).hexdigest() != seal["sha256"]
    ):
        raise ValueError("source, protocol or prediction seal mismatch")
    rows = [strict_json(line) for line in raw.splitlines()]
    if seal["rows"] != len(rows):
        raise ValueError("sealed prediction census mismatch")
    report = menu_report(rows, plan["groups"])
    report.update(
        generating_source=source,
        archive_sha256=pin,
        verified_manifest_entries=len(files) - 1,
        prediction_sha256=seal["sha256"],
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    audit_archive(args.archive, args.sha256, args.source, args.output)
