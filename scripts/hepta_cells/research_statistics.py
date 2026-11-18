"""Fixed-design paired source-group statistics, separate from research admission.

Persist this plan before B/C/D access and pass its externally retained digest.
The digest detects changed commitments; this module cannot authenticate their
time, source independence, receipt provenance, actual budget use, or sealed C/D
access. It never selects candidates or authorizes an experiment. Full P04 nulls
still block admission; this statistical sub-plan cannot fill those commitments.

Conditionally on fixed candidates and independent source groups, each group's
mean paired gain X_g is in [-1,1]. Hoeffding gives
P(mean(X)-mean(E[X]) >= e) <= exp(-N*e**2/2). For a prespecified family of m
comparisons, e=sqrt(2*log(m/alpha)/N); the union bound limits the chance of any
overstated lower bound to alpha. Seeds/repeats are paired and averaged within
each group; they do not increase N. All planned comparisons, including failed
or unrun attempts, consume the family allocation. Adaptive tests, unseen
attempts, optional stopping and C-based tuning require an external access and
budget ledger; inventing a new plan after seeing results is not preregistration.
"""

import hashlib
from itertools import product
import json
import math
import re


def _finite(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("finite number required; bool is not a score")
    return value


def _schedule(values, value_type):
    if type(values) not in (list, tuple) or not values:
        raise ValueError("explicit nonempty schedule required")
    if any(type(v) is not value_type or (value_type is str and not v) for v in values):
        raise ValueError("invalid schedule value")
    if len(set(values)) != len(values):
        raise ValueError("duplicate schedule value")
    return list(values)


def statistical_plan_digest(plan):
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_statistical_plan(
    *,
    alpha,
    margin,
    comparison_count,
    comparisons,
    groups,
    seeds,
    repeats,
    phase,
    metric,
    precision_justification,
    stopping_rule,
):
    """Validate explicit commitments; construction does not prove preregistration."""
    if not 0 < _finite(alpha) < 1 or not 0 <= _finite(margin) <= 1:
        raise ValueError("alpha or meaningful gain margin outside its range")
    if type(comparison_count) is not int or comparison_count < 1:
        raise ValueError("positive integer comparison count required")
    if type(comparisons) is not dict or len(comparisons) != comparison_count:
        raise ValueError("all comparison/attempt slots must be declared and charged")
    for name, pair in comparisons.items():
        if (
            type(name) is not str
            or not name
            or type(pair) is not dict
            or set(pair) != {"candidate", "control"}
        ):
            raise ValueError("named candidate/control comparisons required")
        if any(
            type(v) is not str or not re.fullmatch("[0-9a-f]{64}", v)
            for v in pair.values()
        ):
            raise ValueError("frozen candidate and control manifest digests required")
    if phase not in ("B", "C", "D_cold", "retention"):
        raise ValueError("evaluation phase required")
    if any(type(v) is not str or not v for v in (metric, precision_justification)):
        raise ValueError("metric and precision justification must be explicit")
    if stopping_rule != "fixed_complete_schedule_no_interim_tests":
        raise ValueError("this bound only supports the fixed complete schedule")
    return dict(
        alpha=alpha,
        margin=margin,
        comparison_count=comparison_count,
        comparisons=json.loads(json.dumps(comparisons)),
        groups=_schedule(groups, str),
        seeds=_schedule(seeds, int),
        repeats=_schedule(repeats, str),
        phase=phase,
        metric=metric,
        precision_justification=precision_justification,
        stopping_rule=stopping_rule,
    )


def analyze_grouped_pairs(plan, rows, *, frozen_plan_sha256):
    """Analyze complete fixed schedules; missing pairs never yield a gain claim.

    A row names comparison, source_group, seed, repeat, candidate and control.
    Scores must lie in [0,1]. None denotes an unavailable outcome, never zero.
    Paired repeats are averaged per seed, then seeds per source group. Each
    independent group has equal weight regardless of observations within it.
    """
    try:
        validated = build_statistical_plan(**plan)
    except TypeError as error:
        raise ValueError("all explicit statistical commitments required") from error
    if validated != plan or statistical_plan_digest(plan) != frozen_plan_sha256:
        raise ValueError("statistical plan differs from external frozen digest")
    if type(rows) is not list:
        raise ValueError("explicit observation list required")
    schedule = set(product(plan["groups"], plan["seeds"], plan["repeats"]))
    observed = {name: {} for name in plan["comparisons"]}
    fields = {"comparison", "source_group", "seed", "repeat", "candidate", "control"}
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("observation fields differ from paired score schema")
        if any(
            type(row[key]) is not str
            for key in ("comparison", "source_group", "repeat")
        ):
            raise ValueError("string observation identities required")
        if type(row["seed"]) is not int:
            raise ValueError("seed must be an integer, not bool")
        key = (row["source_group"], row["seed"], row["repeat"])
        if row["comparison"] not in observed or key not in schedule:
            raise ValueError("unscheduled comparison/group/seed/repeat")
        comparison = observed[row["comparison"]]
        if key in comparison:
            raise ValueError("duplicate pair cannot increase statistical N")
        for score in (row["candidate"], row["control"]):
            if score is not None and not 0 <= _finite(score) <= 1:
                raise ValueError("paired scores must lie in [0,1]")
        comparison[key] = (
            None
            if row["candidate"] is None or row["control"] is None
            else row["candidate"] - row["control"]
        )
    results = {}
    for name, comparison in observed.items():
        group_means = {}
        for group in plan["groups"]:
            values = [
                comparison.get((group, seed, repeat))
                for seed in plan["seeds"]
                for repeat in plan["repeats"]
            ]
            group_means[group] = (
                None if None in values else math.fsum(values) / len(values)
            )
        complete = all(value is not None for value in group_means.values())
        n = len(plan["groups"])
        mean = math.fsum(group_means.values()) / n if complete else None
        radius = math.sqrt(
            2 * (math.log(plan["comparison_count"]) - math.log(plan["alpha"])) / n
        )
        lower = max(-1.0, mean - radius) if complete else None
        results[name] = dict(
            status="COMPLETE_FIXED_SCHEDULE" if complete else "INCOMPLETE",
            planned_pairs=len(schedule),
            observed_pairs=len(comparison),
            missing_pairs=sum(comparison.get(key) is None for key in schedule),
            group_means=group_means,
            statistical_n=n if complete else 0,
            mean_paired_gain=mean,
            hoeffding_radius=radius,
            lower_confidence_bound=lower,
            statistical_gain_exceeds_margin=complete and lower > plan["margin"],
        )
    return dict(
        schema="hepta.grouped-paired-statistics.v1",
        plan_sha256=frozen_plan_sha256,
        family_comparisons_charged=plan["comparison_count"],
        family_wise_alpha=plan["alpha"],
        results=results,
        research_accepted=None,
        preregistration_timing_verified=False,
        source_group_independence_verified=False,
    )
