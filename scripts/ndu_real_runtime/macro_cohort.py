"""Frozen prospective macro rosters; finite-cohort arithmetic, not attestation.

Missing records remain UNKNOWN. Only independently admitted terminal outcomes
belong in COMPLETED records. All prices use the frozen utility/tariff units;
unknown physical costs and one-off fit/calibration/tuning costs stay unknown.
Policy labels and dependency hashes are declarations, not authenticated identities.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations

from .metacontrol_value_gate import digest, number

STATUSES = ("NOT_STARTED", "RUNNING", "UNKNOWN", "FAILED", "CANCELLED", "COMPLETED")
SHARED = {
    "action_sha256",
    "legal_actions_sha256",
    "settlement_sha256",
    "evaluator_sha256",
    "utility_sha256",
    "tariff_sha256",
}
ARM_FIELDS = {
    "arm_id",
    "content_mode",
    "control_mode",
    "policy",
    "content_sha256",
    "critic_context_sha256",
}
ROW_FIELDS = {
    "source_id",
    "case_id",
    "seed",
    "arm_id",
    "status",
    "execution_id",
    "shared_sha256",
    "content_sha256",
    "critic_context_sha256",
    "quality",
    "task_cost",
    "full_cost_observed",
    "evidence_sha256",
    "evidence_kind",
}
FACTORIAL = {
    "off_off": ("off", "off"),
    "off_on": ("off", "on"),
    "on_off": ("on", "off"),
    "on_on": ("on", "on"),
}


def _identifier(value):
    return type(value) is str and 0 < len(value) <= 512


def _sha(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _context(row):
    return row["source_id"], row["case_id"], row["seed"]


def validate_plan(plan, *, expected_plan_sha256):
    """Validate the externally pinned Cartesian roster before executing any arm."""
    if digest(plan) != expected_plan_sha256:
        raise ValueError("Plan differs from independently frozen pin")
    if (
        set(plan)
        != {
            "schema",
            "contexts",
            "arms",
            "partitions",
            "shared",
            "one_off_costs",
            "factorial",
        }
        or plan["schema"] != "ndu.real.macro-cohort.v1"
    ):
        raise ValueError("Unexpected cohort plan schema")
    contexts, arms = plan["contexts"], plan["arms"]
    if (
        type(contexts) is not list
        or not 1 <= len(contexts) <= 4096
        or type(arms) is not list
        or not 1 <= len(arms) <= 12
        or set(plan["shared"]) != SHARED
        or not all(_sha(v) for v in plan["shared"].values())
    ):
        raise ValueError("Invalid roster or shared action/settlement identities")
    seen = set()
    for row in contexts:
        if (
            set(row) != {"source_id", "case_id", "seed"}
            or not _identifier(row["source_id"])
            or not _identifier(row["case_id"])
            or type(row["seed"]) is not int
            or row["seed"] < 0
            or _context(row) in seen
        ):
            raise ValueError("Invalid or duplicate registered context")
        seen.add(_context(row))
    partitions = plan["partitions"]
    if set(partitions) != {"fit", "calibration", "evaluation"}:
        raise ValueError("All source partitions must be declared")
    source_sets = []
    for sources in partitions.values():
        if (
            type(sources) is not list
            or not all(_identifier(s) for s in sources)
            or len(set(sources)) != len(sources)
        ):
            raise ValueError("Invalid source partition")
        source_sets.append(set(sources))
    if any(a & b for a, b in combinations(source_sets, 2)) or set(
        partitions["evaluation"]
    ) != {c[0] for c in seen}:
        raise ValueError("Source leakage or missing evaluation-source roster")
    arm_map, content_pins = {}, {}
    for arm in arms:
        if (
            set(arm) != ARM_FIELDS
            or not _identifier(arm["arm_id"])
            or arm["arm_id"] in arm_map
            or arm["content_mode"] not in ("off", "on")
            or arm["control_mode"] not in ("off", "on")
            or arm["policy"]
            not in (
                "STOP",
                "light",
                "tuned-fixed",
                "point",
                "unconditional",
                "conditional",
            )
            or not _sha(arm["content_sha256"])
            or not _sha(arm["critic_context_sha256"])
        ):
            raise ValueError("Invalid or duplicate policy arm")
        pins = arm["content_sha256"], arm["critic_context_sha256"]
        mode = arm["content_mode"]
        if mode in content_pins and content_pins[mode] != pins:
            raise ValueError("Policies changed content or critic dependencies")
        content_pins[mode] = pins
        arm_map[arm["arm_id"]] = dict(arm)
    costs = plan["one_off_costs"]
    if set(costs) != set(arm_map):
        raise ValueError("Every arm must declare its one-off costs")
    for cost in costs.values():
        if set(cost) != {"fit", "calibration", "tuning"} or any(
            v is not None and (not number(v) or v < 0) for v in cost.values()
        ):
            raise ValueError("Invalid one-off cost scope")
    factorial = plan["factorial"]
    if factorial is not None:
        if (
            type(factorial) is not dict
            or set(factorial) != set(FACTORIAL)
            or len(set(factorial.values())) != 4
            or any(arm not in arm_map for arm in factorial.values())
            or any(
                (
                    arm_map[factorial[k]]["content_mode"],
                    arm_map[factorial[k]]["control_mode"],
                )
                != modes
                for k, modes in FACTORIAL.items()
            )
        ):
            raise ValueError("Factorial must identify four distinct learning arms")
        if any(
            arm_map[factorial[f"off_{mode}"]]["policy"]
            != arm_map[factorial[f"on_{mode}"]]["policy"]
            for mode in ("off", "on")
        ):
            raise ValueError(
                "Factorial policies must remain fixed across content modes"
            )
    return seen, arm_map


def evaluate(plan, observations, *, expected_plan_sha256, allow_fixtures=False):
    """Account for every planned item; never infer a result from a prediction."""
    plan, observations = deepcopy(plan), deepcopy(observations)
    contexts, arms = validate_plan(plan, expected_plan_sha256=expected_plan_sha256)
    if type(observations) is not list or len(observations) > len(contexts) * len(arms):
        raise ValueError("Observations exceed the registered inventory")
    records, executions = {}, set()
    shared_pin = digest(plan["shared"])
    for row in observations:
        if type(row) is not dict or set(row) != ROW_FIELDS:
            raise ValueError("Unexpected execution record schema")
        if (
            not _identifier(row["source_id"])
            or not _identifier(row["case_id"])
            or not _identifier(row["arm_id"])
            or type(row["seed"]) is not int
            or row["seed"] < 0
        ):
            raise ValueError("Invalid execution context identity")
        key = _context(row), row["arm_id"]
        if (
            key[0] not in contexts
            or key[1] not in arms
            or key in records
            or row["status"] not in STATUSES
            or row["shared_sha256"] != shared_pin
            or any(
                row[k] != arms[key[1]][k]
                for k in ("content_sha256", "critic_context_sha256")
            )
        ):
            raise ValueError("Unknown/duplicate context or execution identity drift")
        execution = row["execution_id"]
        if execution is not None:
            if not _identifier(execution) or execution in executions:
                raise ValueError("An execution cannot stand for multiple planned items")
            executions.add(execution)
        if (
            row["status"] == "NOT_STARTED"
            and execution is not None
            or row["status"] in ("RUNNING", "FAILED", "COMPLETED")
            and execution is None
            or type(row["full_cost_observed"]) is not bool
            or row["task_cost"] is not None
            and (not number(row["task_cost"]) or row["task_cost"] < 0)
            or row["full_cost_observed"]
            and row["task_cost"] is None
            or row["evidence_sha256"] is not None
            and not _sha(row["evidence_sha256"])
            or row["evidence_kind"] not in (None, "native_macro", "fixture")
            or row["evidence_kind"] == "fixture"
            and not allow_fixtures
        ):
            raise ValueError("Invalid execution, evidence or cost record")
        if row["status"] == "COMPLETED":
            if (
                not number(row["quality"])
                or not 0 <= row["quality"] <= 1
                or row["evidence_kind"] is None
                or row["evidence_sha256"] is None
            ):
                raise ValueError("COMPLETED requires an admitted terminal measurement")
        elif row["quality"] is not None:
            raise ValueError("An unresolved outcome cannot be imputed as a score")
        records[key] = row

    def source_mean(values):
        grouped = defaultdict(list)
        for context, value in values.items():
            grouped[context[0]].append(value)
        means = [sum(v) / len(v) for v in grouped.values()]
        return sum(means) / len(means) if means else None

    summaries, net_values = {}, {}
    for arm_id in arms:
        rows = {c: records.get((c, arm_id)) for c in contexts}
        counts = Counter(r["status"] if r else "UNKNOWN" for r in rows.values())
        complete = {c: r for c, r in rows.items() if r and r["status"] == "COMPLETED"}
        quality = {c: r["quality"] for c, r in complete.items()}
        cost_parts = plan["one_off_costs"][arm_id]
        one_off = (
            sum(cost_parts.values())
            if all(v is not None for v in cost_parts.values())
            else None
        )
        values = {
            c: r["quality"] - r["task_cost"] - one_off / len(contexts)
            for c, r in complete.items()
            if r["full_cost_observed"] and one_off is not None
        }
        net_values[arm_id] = values
        known_costs = [
            r["task_cost"] for r in rows.values() if r and r["task_cost"] is not None
        ]
        summaries[arm_id] = {
            "planned": len(contexts),
            "planned_sources": len(plan["partitions"]["evaluation"]),
            "statuses": {s: counts[s] for s in STATUSES},
            "missing_records": sum(r is None for r in rows.values()),
            "admitted_completed": len(complete),
            "fully_costed": len(values),
            "primary_quality": source_mean(quality)
            if len(quality) == len(contexts)
            else None,
            "primary_full_cost_net": source_mean(values)
            if len(values) == len(contexts)
            else None,
            "observed_subset": {
                "contexts": len(quality),
                "sources": len({c[0] for c in quality}),
                "quality": source_mean(quality),
                "full_cost_net": source_mean(values),
            },
            "observed_task_cost_total": sum(known_costs) if known_costs else None,
            "unknown_task_cost_items": len(contexts) - len(known_costs),
            "one_off_cost_total": one_off,
        }
    contrasts = []
    for candidate, baseline in combinations(arms, 2):
        paired = {
            c: net_values[candidate][c] - net_values[baseline][c]
            for c in net_values[candidate].keys() & net_values[baseline].keys()
        }
        contrasts.append(
            {
                "candidate": candidate,
                "baseline": baseline,
                "planned_contexts": len(contexts),
                "paired_contexts": len(paired),
                "planned_sources": len(plan["partitions"]["evaluation"]),
                "paired_sources": len({c[0] for c in paired}),
                "source_equal_full_cost_difference": (
                    source_mean(paired) if len(paired) == len(contexts) else None
                ),
            }
        )
    factorial = None
    if plan["factorial"] is not None:
        cells = {key: net_values[arm] for key, arm in plan["factorial"].items()}
        paired = set.intersection(*(set(values) for values in cells.values()))
        interaction = {
            c: cells["on_on"][c]
            - cells["on_off"][c]
            - cells["off_on"][c]
            + cells["off_off"][c]
            for c in paired
        }
        factorial = {
            "planned_contexts": len(contexts),
            "paired_contexts": len(paired),
            "planned_sources": len(plan["partitions"]["evaluation"]),
            "paired_sources": len({c[0] for c in paired}),
            "source_equal_interaction": (
                source_mean(interaction) if len(paired) == len(contexts) else None
            ),
        }
    return {
        "schema": "ndu.real.macro-cohort-report.v1",
        "plan_sha256": expected_plan_sha256,
        "planned_executions": len(contexts) * len(arms),
        "arms": summaries,
        "paired_contrasts": contrasts,
        "factorial": factorial,
        "registered_full_cost_comparison_complete": all(
            len(v) == len(contexts) for v in net_values.values()
        ),
        "fixture_records": sum(
            r["evidence_kind"] == "fixture" for r in records.values()
        ),
        "observer_authenticated": False,
        "adoption_authorized": False,
        "new_source_confidence_bound_proved": False,
        "decision": "NoUpdate",
    }
