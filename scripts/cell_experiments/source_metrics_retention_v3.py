"""Paired semantic retention outcomes; held-out C gain is not forgetting."""

from .circuit_readiness_v3 import verified_business_row
from .circuit_receipts_v3 import semantic_identity
from .composition_core import require, sha
from .data import digest


def retention_metrics(
    before,
    after,
    *,
    expected_before_digest,
    expected_after_digest,
    expected_panel_digest,
):
    """Measure forgetting on paired retained business outcomes, never new C gain."""
    require(
        sha(expected_before_digest)
        and digest(before) == expected_before_digest
        and sha(expected_after_digest)
        and digest(after) == expected_after_digest,
        "retention receipt identity differs",
    )
    require(
        sha(expected_panel_digest)
        and before.get("panel_digest")
        == after.get("panel_digest")
        == expected_panel_digest,
        "retention panel differs",
    )
    require(
        before.get("panel_role") == after.get("panel_role") == "retention",
        "predeclared retention panel required",
    )
    require(
        sha(before.get("model_digest")) and sha(after.get("model_digest")),
        "before/after model identities required",
    )
    left = {row["task_id"]: row for row in before["rows"]}
    right = {row["task_id"]: row for row in after["rows"]}
    require(
        bool(left)
        and set(left) == set(right)
        and len(left) == len(before["rows"]) == len(after["rows"]),
        "paired unique retention tasks required",
    )
    for task in left:
        require(
            all(
                left[task].get(field) == right[task].get(field)
                for field in ("source_id", "lineage_id", "task_digest")
            ),
            "retention provenance changed",
        )
        require(
            semantic_identity(left[task]["semantic_receipt"])
            == semantic_identity(right[task]["semantic_receipt"]),
            "retention semantic task identity changed",
        )
        require(
            left[task]["model_digest"] == before["model_digest"]
            and right[task]["model_digest"] == after["model_digest"],
            "retention model binding changed",
        )
    a = {task: verified_business_row(row) for task, row in left.items()}
    b = {task: verified_business_row(row) for task, row in right.items()}
    known = all(value is not None for value in [*a.values(), *b.values()])
    original_successes = sum(value is True for value in a.values())
    lost = [task for task in a if a[task] is True and b[task] is False]
    gained = [task for task in a if a[task] is False and b[task] is True]
    sources = {}
    for source in sorted({row["source_id"] for row in left.values()}):
        tasks = [task for task in left if left[task]["source_id"] == source]
        measured = all(a[task] is not None and b[task] is not None for task in tasks)
        sources[source] = {
            "unique_tasks": len(tasks),
            "before_successes": sum(a[task] is True for task in tasks)
            if measured
            else None,
            "after_successes": sum(b[task] is True for task in tasks)
            if measured
            else None,
        }
    return {
        "schema": "hepta.retention-metrics.v3",
        "before_digest": expected_before_digest,
        "after_digest": expected_after_digest,
        "panel_digest": expected_panel_digest,
        "unique_task_count": len(left),
        "statistical_effective_sample_size": None,
        "business_outcomes_complete": known,
        "previously_successful_tasks": original_successes if known else None,
        "lost_tasks": lost,
        "gained_tasks": gained,
        "regression_rate_among_previously_successful": len(lost) / original_successes
        if known and original_successes
        else None,
        "task_success_rate_change": (len(gained) - len(lost)) / len(left)
        if known
        else None,
        "sources": sources,
        "independent_sample_increment": 0,
        "independent_scientific_qualification": "BLOCKED",
        "scope": "paired declared retention panel; zero prior successes cannot establish absence of forgetting",
    }
