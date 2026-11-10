"""Finite-cohort interval arithmetic, not observer authentication or adoption.

Every registered context stays in the denominator. Bounds and the cost scope
require external justification. No confidence claim for new sources is made.
"""

import hashlib
import json
import math


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def evaluate(plan, observations, *, expected_plan_sha256):
    if digest(plan) != expected_plan_sha256:
        raise ValueError("Value plan differs from the independently frozen pin")
    if set(plan) != {
        "cases",
        "candidate",
        "baselines",
        "bounds",
        "one_off_costs",
        "margin",
    }:
        raise ValueError("Unexpected plan fields")
    cases = plan["cases"]
    if type(cases) is not dict or not 1 <= len(cases) <= 4096:
        raise ValueError("Invalid planned context inventory")
    if any(
        type(k) is not str or not k or type(v) is not str or not v
        for k, v in cases.items()
    ):
        raise ValueError("Context and source IDs must be nonempty strings")
    if type(plan["baselines"]) is not list or not plan["baselines"]:
        raise ValueError("Strong baselines must be predeclared")
    methods = [plan["candidate"], *plan["baselines"]]
    if (
        any(type(m) is not str or not m for m in methods)
        or len(set(methods)) != len(methods)
        or set(plan["bounds"]) != set(methods)
        or set(plan["one_off_costs"]) != set(methods)
        or not number(plan["margin"])
        or plan["margin"] < 0
    ):
        raise ValueError("Invalid method or cost contract")
    for method in methods:
        bound, cost = plan["bounds"][method], plan["one_off_costs"][method]
        if (
            type(bound) is not list
            or len(bound) != 2
            or not all(number(v) for v in bound)
            or bound[0] > bound[1]
            or (cost is not None and (not number(cost) or cost < 0))
        ):
            raise ValueError("Invalid bound or one-off cost in common utility units")
    if type(observations) is not list or len(observations) > len(cases) * len(methods):
        raise ValueError("Observations exceed the planned inventory")
    values = {}
    for row in observations:
        if set(row) != {
            "case_id",
            "method",
            "net_value",
            "costs_complete",
            "evidence_kind",
        }:
            raise ValueError("Unexpected observation fields")
        key = row["case_id"], row["method"]
        if (
            key[0] not in cases
            or key[1] not in methods
            or key in values
            or type(row["costs_complete"]) is not bool
            or row["evidence_kind"] != "measured_terminal"
        ):
            raise ValueError("Unknown/duplicate context, method or observation kind")
        value = row["net_value"]
        if value is not None and (
            not number(value)
            or not plan["bounds"][key[1]][0] <= value <= plan["bounds"][key[1]][1]
        ):
            raise ValueError("Observed value violates the registered bound")
        values[key] = value if row["costs_complete"] else None
    counts = {
        source: list(cases.values()).count(source) for source in set(cases.values())
    }
    weights = {
        case: 1 / (len(counts) * counts[source]) for case, source in cases.items()
    }
    intervals, denominators = {}, {}
    for method in methods:
        lower = upper = observed = 0
        for case, weight in weights.items():
            value = values.get((case, method))
            lo, hi = plan["bounds"][method] if value is None else (value, value)
            lower += weight * lo
            upper += weight * hi
            observed += value is not None
        cost = plan["one_off_costs"][method]
        intervals[method] = (
            None
            if cost is None
            else [lower - cost / len(cases), upper - cost / len(cases)]
        )
        denominators[method] = {
            "planned": len(cases),
            "observed_priced": observed,
            "unknown": len(cases) - observed,
        }
    differences = {}
    for baseline in plan["baselines"]:
        a, b = intervals[plan["candidate"]], intervals[baseline]
        differences[baseline] = (
            None if a is None or b is None else [a[0] - b[1], a[1] - b[0]]
        )
    complete = all(d["unknown"] == 0 for d in denominators.values()) and all(
        v is not None for v in intervals.values()
    )
    passed = complete and all(v[0] > plan["margin"] for v in differences.values())
    return {
        "plan_sha256": expected_plan_sha256,
        "planned_sources": len(counts),
        "denominators": denominators,
        "net_intervals": intervals,
        "candidate_minus_baseline": differences,
        "finite_cohort_gate_passed": passed,
        "decision": "RESEARCH_PASS" if passed else "NoUpdate",
        "adoption_authorized": False,
        "observer_authenticated": False,
        "new_source_confidence_bound_proved": False,
    }
