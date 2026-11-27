"""Complete paired denominators and crossed descriptive uncertainty for pilots."""

from collections import defaultdict
import math
import random
import statistics

from .causal_protocol import COST_STAGES, COST_UNITS


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def cost_inventory(events, methods, required_stages=COST_STAGES):
    """Sum only top-level envelopes; retain missing stages and unknown measures.

    Sum of job wall durations is cumulative work, not parallel campaign elapsed
    time. Per-method shared charges are standalone costs, never summed to infer
    physical campaign work. This checks supplied evidence, not its provenance.
    """
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("Unique planned methods required")
    by_id = {}
    for event in events:
        identity = event["event_id"]
        if not isinstance(identity, str) or not identity or identity in by_id:
            raise ValueError("Duplicate or empty original cost event")
        if (
            event["stage"] not in required_stages
            or not event["methods"]
            or (set(event["methods"]) - set(methods))
            or len(set(event["methods"])) != len(event["methods"])
        ):
            raise ValueError("Unknown or duplicated cost ownership")
        if set(event["measurements"]) != set(COST_UNITS) or any(
            v is not None and (not number(v) or v < 0)
            for v in event["measurements"].values()
        ):
            raise ValueError("Measured zero and unknown must remain distinct")
        if event.get("provider_charges_unit") is None and (
            event["measurements"]["provider_charges"] is not None
        ):
            raise ValueError("Provider charge unit is required")
        by_id[identity] = event
    for event in events:
        path, current = set(), event
        while current.get("parent_event_id") is not None:
            parent = current["parent_event_id"]
            if parent not in by_id or parent in path or parent == event["event_id"]:
                raise ValueError("Missing or cyclic enclosing cost event")
            path.add(parent)
            following = by_id[parent]
            if not set(current["methods"]) <= set(following["methods"]):
                raise ValueError("Nested event ownership escapes its envelope")
            current = following
    roots = [event for event in events if event.get("parent_event_id") is None]

    def summarize(owned):
        units = {
            e.get("provider_charges_unit")
            for e in owned
            if e["measurements"]["provider_charges"] is not None
        }
        if len(units) > 1:
            raise ValueError("Different monetary or provider units cannot be added")
        return {
            unit: {
                "observed_sum": sum(e["measurements"][unit] or 0 for e in owned),
                "unknown_events": [
                    e["event_id"] for e in owned if e["measurements"][unit] is None
                ],
            }
            for unit in COST_UNITS
        }

    report = {}
    for method in methods:
        owned = [e for e in roots if method in e["methods"]]
        covered = {e["stage"] for e in events if method in e["methods"]}
        sums = summarize(owned)
        missing = sorted(set(required_stages) - covered)
        report[method] = {
            "top_level_events": [e["event_id"] for e in owned],
            "missing_stages": missing,
            "measurements": sums,
            "stage_measurement_unknowns": {
                unit: [
                    e["event_id"]
                    for e in events
                    if method in e["methods"] and e["measurements"][unit] is None
                ]
                for unit in COST_UNITS
            },
            "complete": not missing
            and all(not v["unknown_events"] for v in sums.values()),
        }
    return {
        "methods": report,
        "physical_campaign": summarize(roots),
        "wall_semantics": "sum_task_wall_seconds; not elapsed parallel time",
        "whole_budget_complete": all(r["complete"] for r in report.values()),
        "provider_authenticity_verified": False,
    }


def paired_contrast(rows, coefficients, fits, cases, *, draws=2000, seed=32452843):
    """Require every planned fit/condition/case before estimating a contrast.

    Caller supplies already frozen failure penalties. Unknown or unmeasured
    outcomes block estimation; rows are never dropped to improve completeness.
    Each source group is equally weighted and each fit remains one replicate.
    """
    if (
        not fits
        or len(set(fits)) != len(fits)
        or len(coefficients) < 2
        or any(not number(v) or v == 0 for v in coefficients.values())
        or abs(sum(coefficients.values())) > 1e-12
    ):
        raise ValueError("A paired zero-sum contrast and unique fits are required")
    if type(draws) is not int or not 100 <= draws <= 100000:
        raise ValueError("Bounded bootstrap draws required")
    case_map = {c["case_id"]: c for c in cases}
    if len(case_map) != len(cases) or not cases:
        raise ValueError("Unique prospectively selected cases required")
    splits = {c["split"] for c in cases}
    if len(splits) != 1 or not splits <= {"development", "retention_validation"}:
        raise ValueError(
            "Analyze development and retention separately; no sealed test access"
        )
    selected, all_ids = {}, set()
    for row in rows:
        identity = row.get("original_operation_id")
        if identity is not None:
            if identity in all_ids:
                raise ValueError("Original attempt duplicated")
            all_ids.add(identity)
        if row["condition_id"] not in coefficients:
            continue
        if row["fit_id"] not in fits or row["case_id"] not in case_map:
            raise ValueError("Observed result outside frozen contrast roster")
        case = case_map[row["case_id"]]
        if any(
            row.get(k) != case[k] for k in ("source_group_id", "split", "task_family")
        ):
            raise ValueError(
                "Observed case crossed its frozen source group, split or family"
            )
        key = (row["fit_id"], row["condition_id"], row["case_id"])
        if key in selected:
            raise ValueError(
                "Duplicate fit/condition/case; retries cannot replace originals"
            )
        selected[key] = row
    expected = [
        (fit, condition, case)
        for fit in fits
        for condition in coefficients
        for case in case_map
    ]
    missing = [key for key in expected if key not in selected]
    unknown = [
        key
        for key in expected
        if key in selected
        and (
            not number(selected[key].get("analysis_utility"))
            or selected[key].get("terminal_status") not in {"Completed", "Failed"}
        )
    ]
    report = {
        "planned_rows": len(expected),
        "observed_rows": len(selected),
        "independent_fit_count": len(fits),
        "source_group_count": len({c["source_group_id"] for c in cases}),
        "missing_rows": missing,
        "unknown_rows": unknown,
        "failed_rows": sum(
            r.get("terminal_status") == "Failed" for r in selected.values()
        ),
        "confirmatory_use": False,
        "scientific_acceptance": "HOLD",
    }
    if missing or unknown:
        return {**report, "status": "INCOMPLETE", "mean": None, "interval": None}
    paired_values = {}
    try:
        for fit in fits:
            for case in case_map:
                value = math.fsum(
                    coefficients[condition]
                    * selected[(fit, condition, case)]["analysis_utility"]
                    for condition in coefficients
                )
                if not number(value):
                    raise ValueError("Contrast arithmetic exceeds finite range")
                paired_values[(fit, case)] = value
    except (OverflowError, ValueError) as error:
        raise ValueError("Contrast arithmetic exceeds finite range") from error
    groups = defaultdict(lambda: defaultdict(list))
    for case in cases:
        groups[case["source_group_id"]][case["task_family"]].append(case["case_id"])
    values = [
        [
            statistics.mean(
                statistics.mean(paired_values[(fit, case)] for case in family_cases)
                for family_cases in group_families.values()
            )
            for group_families in groups.values()
        ]
        for fit in fits
    ]
    per_fit = [statistics.mean(v) for v in values]
    mean = statistics.mean(per_fit)
    interval = None
    if len(fits) >= 2 and len(groups) >= 2:
        rng, samples = random.Random(seed), []
        for _ in range(draws):
            fi = [rng.randrange(len(fits)) for _ in fits]
            gi = [rng.randrange(len(groups)) for _ in groups]
            samples.append(statistics.mean(values[i][j] for i in fi for j in gi))
        samples.sort()
        interval = [
            samples[int(0.025 * (draws - 1))],
            samples[int(0.975 * (draws - 1))],
        ]
    try:
        fit_variance = statistics.variance(per_fit) if len(per_fit) > 1 else None
    except OverflowError as error:
        raise ValueError("Contrast variance exceeds finite range") from error
    if fit_variance is not None and not number(fit_variance):
        raise ValueError("Contrast variance exceeds finite range")
    return {
        **report,
        "status": "DESCRIPTIVE_PILOT",
        "mean": mean,
        "per_fit": dict(zip(fits, per_fit)),
        "interval": interval,
        "interval_scope": "unadjusted descriptive crossed paired bootstrap",
        "fit_sample_variance": fit_variance,
        "full_cost_adjusted": False,
        "limit": "deployment utility is not total improvement efficiency; full cost gate remains separate",
    }
