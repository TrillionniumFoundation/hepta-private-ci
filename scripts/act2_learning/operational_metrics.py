"""Report observed ACT costs and clustered quality without filling evidence gaps."""

from collections import defaultdict


KNOWLEDGE = {"CONFIRMED_COMPLETE", "CONFIRMED_INCOMPLETE", "UNKNOWN"}
MEASUREMENTS = (
    "end_to_end_ns",
    "duration_ns",
    "selection_ns",
    "primitive_calls",
    "owner_requests",
    "independent_oracle_queries",
    "duplicate_effects",
)


def summarize(rows, baseline="fixed"):
    """Keep oracle truth separate from knowledge available to the executing policy.

    ``complete`` is an offline oracle result. ``effect_knowledge`` is an explicit
    current observation supplied by the caller; its absence stays UNKNOWN.
    Seed repetitions are paired within task IDs and never counted as new tasks.
    """
    indexed, groups = {}, defaultdict(list)
    for row in rows:
        task, arm, seed = row["task_id"], row["arm"], row["seed"]
        if (
            not isinstance(task, str)
            or not task
            or not isinstance(arm, str)
            or not arm
            or type(seed) is not int
        ):
            raise ValueError("invalid task, arm or seed identity")
        key = task, arm, seed
        if key in indexed:
            raise ValueError("duplicate task/arm/seed row")
        for field in ("complete", "claimed_success"):
            if row.get(field) is not None and type(row[field]) is not bool:
                raise ValueError(f"invalid outcome: {field}")
        knowledge = row.get("effect_knowledge")
        if knowledge is None:
            knowledge = "UNKNOWN"
        if not isinstance(knowledge, str) or knowledge not in KNOWLEDGE:
            raise ValueError("invalid effect knowledge")
        for field in MEASUREMENTS:
            value = row.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"invalid measurement: {field}")
        indexed[key] = row
        groups[arm].append(row)

    arms = {}
    for arm, panel in sorted(groups.items()):
        measurements = {}
        for field in MEASUREMENTS:
            observed = [r[field] for r in panel if r.get(field) is not None]
            measurements[field] = {
                "sum": sum(observed) if observed else None,
                "measured_rows": len(observed),
                "missing_rows": len(panel) - len(observed),
            }
        evaluated = [
            r
            for r in panel
            if r.get("complete") is not None and r.get("claimed_success") is not None
        ]
        arms[arm] = {
            "episodes": len(panel),
            "task_clusters": len({r["task_id"] for r in panel}),
            "offline_complete": sum(r.get("complete") is True for r in panel),
            "offline_oracle_unknown": sum(r.get("complete") is None for r in panel),
            "claimed_success": sum(r.get("claimed_success") is True for r in panel),
            "claim_unknown": sum(r.get("claimed_success") is None for r in panel),
            "false_success": sum(
                r["claimed_success"] and not r["complete"] for r in evaluated
            ),
            "false_success_unassessed": len(panel) - len(evaluated),
            "policy_confirmed_complete": sum(
                r.get("effect_knowledge") == "CONFIRMED_COMPLETE" for r in panel
            ),
            "unknown_effect_outcomes": sum(
                r.get("effect_knowledge") in (None, "UNKNOWN") for r in panel
            ),
            "measurements": measurements,
        }

    paired = []
    if groups and baseline not in groups:
        raise ValueError("missing fixed baseline")
    baseline_keys = {(r["task_id"], r["seed"]) for r in groups.get(baseline, [])}
    for arm, panel in sorted(groups.items()):
        if arm == baseline:
            continue
        if {(r["task_id"], r["seed"]) for r in panel} != baseline_keys:
            raise ValueError("unpaired task/seed grid")
        for task in sorted({r["task_id"] for r in panel}):
            seeds = sorted(r["seed"] for r in panel if r["task_id"] == task)
            deltas = []
            for seed in seeds:
                actual = indexed[task, arm, seed].get("complete")
                control = indexed[task, baseline, seed].get("complete")
                if actual is not None and control is not None:
                    deltas.append(int(actual) - int(control))
            paired.append(
                {
                    "task_id": task,
                    "arm": arm,
                    "seed_pairs": len(seeds),
                    "measured_seed_pairs": len(deltas),
                    "unknown_seed_pairs": len(seeds) - len(deltas),
                    "mean_completion_delta": (
                        sum(deltas) / len(deltas) if len(deltas) == len(seeds) else None
                    ),
                }
            )
    return {
        "scope": {
            "quality_unit": "task_id cluster; seeds are repeated paired probes",
            "offline_completion_is_policy_knowledge": False,
            "duration_ns_is_end_to_end": False,
            "overlapping_measurements_are_additive": False,
            "full_lifetime_cost_measured": False,
            "efficiency_gain_qualified": False,
            "missing_measurements_are_zero": False,
        },
        "arms": arms,
        "paired_task_results": paired,
        "promotion": False,
    }
