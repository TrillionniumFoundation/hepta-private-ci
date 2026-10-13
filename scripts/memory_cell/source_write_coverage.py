"""Audit source-only curriculum exposure without changing model training.

Report exact direct/two-hop visits, original source usage and token counts.
No evaluation questions or answers are opened, and this never rewrites the
writer's examples, schedule, optimizer, or computation ceiling.
"""

from collections import Counter

from native import digest

KINDS = ("direct", "two_hop")
TWO_HOP = "hepta.source-only.two-hop-curriculum.v1"


def audit_coverage(examples, prepared, plan, *, curriculum):
    """Bind the complete source census to the registered immutable schedule."""
    if curriculum not in ("single_hop", "source_two_hop"):
        raise ValueError("unregistered source-only curriculum")
    if not 1 <= len(examples) == len(prepared) <= 2048:
        raise ValueError("complete bounded source-only examples required")
    if plan.get("schema") != "hepta.source-write.schedule.v1":
        raise ValueError("unregistered source write schedule")
    ids = set()
    groups = {}
    kinds = []
    for ex in examples:
        if not isinstance(ex, dict) or not isinstance(ex.get("query"), dict):
            raise ValueError("source-only example missing exact question")
        q = ex["query"]
        identity, scope = q.get("identity"), q.get("scope")
        src = ex.get("sources")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in ids
            or not isinstance(scope, str)
            or not scope
            or not isinstance(src, (list, tuple))
            or not src
            or len(src) > 8
            or any(not isinstance(s, str) or not s for s in src)
            or len(set(src)) != len(src)
            or not isinstance(ex.get("source_digest"), str)
            or not ex["source_digest"]
            or not isinstance(ex.get("target"), str)
            or not ex["target"]
        ):
            raise ValueError("missing or duplicate original source-only example")
        ids.add(identity)
        groups.setdefault(scope, []).append(len(kinds))
        kind = (
            "direct"
            if "curriculum" not in ex
            else "two_hop"
            if ex["curriculum"] == TWO_HOP
            else "invalid"
        )
        if kind == "invalid" or (curriculum == "single_hop" and kind != "direct"):
            raise ValueError("example curriculum differs from admitted writer")
        kinds.append(kind)
    strategy = plan.get("strategy", "original")
    if strategy == "direct_interleave":
        from source_write_schedule import interleave_source_kinds

        if (
            curriculum != "source_two_hop"
            or plan.get("source_only_order_intervention") is not True
            or plan.get("original_groups_digest") != digest(groups)
        ):
            raise ValueError("unbound source-only interleave plan")
        groups = interleave_source_kinds(examples, groups)
    elif (
        strategy != "original"
        or "original_groups_digest" in plan
        or "source_only_order_intervention" in plan
    ):
        raise ValueError("unregistered source write schedule strategy")
    if plan.get("prepared_digest") != digest(prepared) or plan.get(
        "groups_digest"
    ) != digest(groups):
        raise ValueError("source schedule differs from prepared source examples")
    entries = plan.get("entries")
    if (
        not isinstance(entries, list)
        or len(entries) != plan.get("planned_steps")
        or len(entries) > plan.get("maximum_steps", 0)
        or type(plan.get("token_ceiling")) is not int
        or type(plan.get("maximum_steps")) is not int
        or plan.get("actual_optimizer_steps") != 0
    ):
        raise ValueError("invalid planned optimizer census")
    counts = Counter()
    for index in entries:
        if type(index) is not int or not 0 <= index < len(prepared):
            raise ValueError("unregistered source example scheduled")
        counts[index] += 1
    visits = [counts[i] for i in range(len(prepared))]
    if (
        plan.get("visits_per_example") != visits
        or plan.get("unvisited_examples") != [i for i, n in enumerate(visits) if not n]
        or sum(len(prepared[i][0]) for i in entries) != plan.get("planned_input_tokens")
        or sum(sum(label != -100 for label in prepared[i][1]) for i in entries)
        != plan.get("planned_supervised_tokens")
        or plan["planned_input_tokens"] > plan["token_ceiling"]
    ):
        raise ValueError("planner visits or token exposure drifted")
    outcomes = {}
    for kind in KINDS:
        indices = [i for i, k in enumerate(kinds) if k == kind]
        viewed = [i for i in indices if visits[i]]
        outcomes[kind] = dict(
            available_source_examples=len(indices),
            source_examples_seen_at_least_once=len(viewed),
            source_examples_unvisited=len(indices) - len(viewed),
            planned_updates=sum(visits[i] for i in indices),
            planned_input_tokens=sum(len(prepared[i][0]) * visits[i] for i in indices),
            planned_supervised_tokens=sum(
                sum(label != -100 for label in prepared[i][1]) * visits[i]
                for i in indices
            ),
            source_scopes_with_exposure=len(
                {examples[i]["query"]["scope"] for i in viewed}
            ),
            unique_training_source_ids=len(
                {source for i in viewed for source in examples[i]["sources"]}
            ),
        )
    return dict(
        schema="hepta.source-write.curriculum-coverage.v1",
        curriculum=curriculum,
        source_examples_digest=digest(examples),
        schedule_digest=digest(plan),
        total_source_examples=len(examples),
        planned_optimizer_updates=len(entries),
        by_kind=outcomes,
        direct_or_composition_exposure_is_not_task_accuracy=True,
        independent_semantic_support_review=False,
        heldout_task_plan_loaded=False,
        production_accepted=False,
    )
