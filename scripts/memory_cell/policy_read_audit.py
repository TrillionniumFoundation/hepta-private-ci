"""Matched read-policy intervention, without a knowledge-writer dependency.

Reuse the original candidate census, deterministic controls and learned policy.
No answer labels enter control construction. Post-generation comparisons concern
actual task outcomes, not a renamed support-document recall score.
"""

import copy
import math
import time

from event_memory_trial import ARMS
from event_projection import EventProjection
from experience_policy import INITIAL, choose, lookup_from_question, validate_policy
from native import Question

POLICY_ARMS = ("policy_initial", "policy")
ALL_ARMS = ARMS + POLICY_ARMS


def extend_controls(plan, originals, policy, *, reader_identity, revoked):
    weights = validate_policy(
        policy,
        tuple(originals.values()),
        reader_identity=reader_identity,
        test_scopes={case["query"]["scope"] for case in plan["cases"]},
        revoked=revoked,
    )
    extended = copy.deepcopy(plan)
    for case in extended["cases"]:
        if set(case["controls"]) != set(ARMS):
            raise ValueError("original frozen controls changed")
        query = Question(**case["query"])
        pool = case["candidate_ids"]
        if any(k not in originals or originals[k].scope != query.scope for k in pool):
            raise ValueError("foreign or missing candidate source")
        projection = EventProjection(
            tuple(d for d in originals.values() if d.scope == query.scope)
        )
        lookup = lookup_from_question(query)
        for arm, parameters in (("policy_initial", INITIAL), ("policy", weights)):
            started = time.perf_counter()
            selected, receipt = choose(
                projection, lookup, pool, parameters, revoked=revoked
            )
            if not set(selected).issubset(pool):
                raise ValueError("policy inserted an out-of-pool source")
            case["controls"][arm] = dict(
                selected=list(selected),
                selection=receipt | dict(seconds=time.perf_counter() - started),
            )
    return extended


def measured(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("nonnegative finite measured cost required")
    return value


def audit_policy(rows, expected, policy):
    if (
        not expected
        or len(set(expected)) != len(expected)
        or len(rows) != len(expected) * len(ALL_ARMS)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(q, a) for q in expected for a in ALL_ARMS}
    ):
        raise ValueError("complete eight-arm census required")
    grouped, profiles = {}, set()
    for row in rows:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown attempt status")
        grouped.setdefault(row["question_id"], {})[row["arm"]] = row
        if row["status"] == "failed":
            if row.get("strict_task_success") is not None:
                raise ValueError("failed generation cannot have a task score")
            continue
        if not isinstance(row["answer"], str) or not row["answer"].strip():
            raise ValueError("missing actual generated answer")
        if any(
            type(row[k]) is not bool
            for k in ("strict_task_success", "required_sources_covered")
        ):
            raise ValueError("missing task/support disposition")
        receipt = row["receipt"]
        profiles.add(
            (
                receipt["reader_identity"],
                receipt["reader_profile"],
                receipt["token_limit"],
            )
        )
        measured(receipt["seconds"])
        for key in ("input_tokens", "generated_tokens"):
            if type(receipt[key]) is not int or receipt[key] < 0:
                raise ValueError("invalid actual token work")
        if row["arm"] in POLICY_ARMS:
            measured(row["selection_receipt"]["seconds"])
        if row["kind"] == "procedure":
            worker = row["procedure_verification"]
            if type(worker["exit_code"]) is not int or row["strict_task_success"] != (
                worker["exit_code"] == 0
            ):
                raise ValueError("task success detached from actual procedure")
            measured(worker["seconds"])
    if len(profiles) != 1:
        raise ValueError("different or absent frozen reader")
    for by_arm in grouped.values():
        if any(
            len({r[key] for r in by_arm.values()}) != 1
            for key in ("kind", "candidate_digest")
        ):
            raise ValueError("changed task kind or candidate pool")
    stats = {}
    for arm in ALL_ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        good = [r for r in subset if r["status"] == "succeeded"]
        strata = {}
        for kind in sorted({r["kind"] for r in subset}):
            cases = [r for r in subset if r["kind"] == kind]
            strata[kind] = dict(
                planned=len(cases),
                success=sum(r.get("strict_task_success") is True for r in cases),
                failed=sum(r["status"] == "failed" for r in cases),
            )
        stats[arm] = dict(
            planned=len(subset),
            generated=len(good),
            failed=len(subset) - len(good),
            strict_success=sum(r["strict_task_success"] for r in good),
            support_covered=sum(r["required_sources_covered"] for r in good),
            by_kind=strata,
            reader_seconds=sum(r["receipt"]["seconds"] for r in good),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in good),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in good),
            selection_seconds=(
                sum(r["selection_receipt"]["seconds"] for r in good)
                if arm in POLICY_ARMS
                else None
            ),
            procedure_seconds=sum(
                r["procedure_verification"]["seconds"]
                for r in good
                if r["kind"] == "procedure"
            ),
            semantic_citation_precision=None,
        )
    contrasts = {}
    for baseline in ("policy_initial", "hybrid", "organized"):
        values = dict(
            wins=0,
            losses=0,
            ties=0,
            failed_pairs=0,
            selection_changed=0,
            answer_changed=0,
            support_gain_without_task_gain=0,
        )
        for group in grouped.values():
            left, right = group[baseline], group["policy"]
            if left["status"] != "succeeded" or right["status"] != "succeeded":
                values["failed_pairs"] += 1
                continue
            delta = int(right["strict_task_success"]) - int(left["strict_task_success"])
            values["wins" if delta > 0 else "losses" if delta < 0 else "ties"] += 1
            values["selection_changed"] += left["selected"] != right["selected"]
            values["answer_changed"] += left["answer"] != right["answer"]
            values["support_gain_without_task_gain"] += (
                right["required_sources_covered"]
                and not left["required_sources_covered"]
                and delta <= 0
            )
        values["all_planned_success_delta"] = (
            stats["policy"]["strict_success"] - stats[baseline]["strict_success"]
        ) / len(expected)
        values["positive_complete_point_difference"] = (
            values["failed_pairs"] == 0 and values["wins"] > values["losses"]
        )
        contrasts[baseline] = values
    write_seconds = measured(policy["write_seconds"])
    return dict(
        arms=stats,
        contrasts=contrasts,
        all_attempts=len(rows),
        policy_training=policy,
        amortized_policy_write_seconds={
            str(n): write_seconds / n for n in (1, 10, 100, 1000)
        },
        latency_sample_is_not_a_benchmark=True,
        total_lifecycle_cost=None,
        missing_costs=[
            "production maintenance",
            "longitudinal retention",
            "cross-host recovery",
        ],
        general_semantic_accuracy=None,
        independently_reviewed=False,
        source_families_are_authored_controls=True,
        significance_established=False,
        reader_optimizer_executed=False,
        knowledge_optimizer_executed=False,
        production_accepted=False,
    )
