"""Sufficient finite-policy improvement gate using baseline-Q intervals.

The intervals must simultaneously cover Q^baseline for the SAME recursive
model, including every relevant continuation error. The gate cannot establish
their coverage. Uncovered or locally adverse rows retain the original baseline.
Monotonicity then gives global policy nondecrease on the coverage event.
"""

from copy import deepcopy
from fractions import Fraction
import math


def _lower_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Certificate outside supported numeric range")
    return math.nextafter(result, -math.inf) if Fraction(result) > value else result


def initial_value_gate(candidate_interval, baseline_interval, verification_cost):
    """Alternative route with independent simultaneous INITIAL-value coverage.

These intervals must cover complete recursive policy values, not plug-in
trajectory CE, one-step Q, or values under a different initial distribution.
This route can admit delayed benefits rejected by the local sufficient gate.
"""
    for bounds in (candidate_interval, baseline_interval):
        if (not isinstance(bounds, tuple) or len(bounds) != 2
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in bounds)
                or bounds[0] > bounds[1]):
            raise ValueError("Finite ordered initial-value intervals required")
    if (type(verification_cost) not in (int, float)
            or not math.isfinite(verification_cost) or verification_cost < 0):
        raise ValueError("A finite nonnegative full validation fee is required")
    lower = _lower_float(Fraction(candidate_interval[0]) - Fraction(baseline_interval[1])
                         - Fraction(verification_cost))
    return {"decision": "adopt" if lower > 0 else "no-update",
            "net_gain_lower": lower, "spent": verification_cost,
            "returned_policy_net_gain_lower": lower if lower > 0 else -verification_cost,
            "scope": "independent_complete_recursive_initial_value_coverage_required"}


def guarded_update(baseline, proposed, intervals, root, verification_cost=0.0):
    """Return a paid accepted policy or baseline, with local rejection reasons.

A strictly positive root advantage is a conservative whole-policy gain lower
bound if all other effective rows have nonnegative baseline advantage. Subtract
the full audit fee once. Rejection avoids a policy regression but retains its
sunk fee; it does NOT promise zero economic loss versus never auditing.
"""
    finite = lambda x: type(x) in (int, float) and math.isfinite(x)
    if (not isinstance(baseline, dict) or not baseline or root not in baseline
            or not isinstance(proposed, dict) or set(proposed) != set(baseline)
            or not isinstance(intervals, dict) or set(intervals) - set(baseline)
            or not finite(verification_cost) or verification_cost < 0):
        raise ValueError("A common finite policy space, root and full fee are required")
    effective, lower, reasons = deepcopy(baseline), {}, {}
    for state, row in baseline.items():
        other = proposed[state]
        if (not isinstance(row, dict) or not row or not isinstance(other, dict)
                or set(other) != set(row)):
            raise ValueError("Policies must share their complete legal action sets")
        for law in (row, other):
            if (any(not finite(v) or v < 0 for v in law.values())
                    or not math.isclose(math.fsum(law.values()), 1.0, abs_tol=1e-12, rel_tol=0)):
                raise ValueError("Policy probability mass is invalid")
        lower[state] = 0.0
        if row == other:
            reasons[state] = "unchanged"
            continue
        if state not in intervals:
            reasons[state] = "uncovered_baseline_fallback"
            continue
        bounds = intervals[state]
        if not isinstance(bounds, dict) or set(bounds) != set(row):
            raise ValueError("Covered states need every baseline action-value interval")
        # Normalize rounding-only probability mass, then compute the signed
        # interval bound exactly on the supplied binary-float endpoints. A
        # large constant Q must not turn a mass tolerance into invented gain.
        old_total = sum(map(Fraction, row.values()))
        new_total = sum(map(Fraction, other.values()))
        terms = []
        for action, mass in row.items():
            bound = bounds[action]
            if (not isinstance(bound, tuple) or len(bound) != 2
                    or not all(finite(x) for x in bound) or bound[0] > bound[1]):
                raise ValueError("Finite ordered action-value intervals required")
            difference = Fraction(other[action]) / new_total - Fraction(mass) / old_total
            terms.append(difference * Fraction(bound[0 if difference >= 0 else 1]))
        advantage = _lower_float(sum(terms, Fraction(0)))
        if advantage >= 0:
            effective[state], lower[state] = deepcopy(other), advantage
            reasons[state] = "covered_nonnegative_advantage"
        else:
            reasons[state] = "negative_bound_baseline_fallback"
    net_lower = _lower_float(Fraction(lower[root]) - Fraction(verification_cost))
    adopted = net_lower > 0
    return {"decision": "adopt" if adopted else "no-update",
            "policy": effective if adopted else deepcopy(baseline),
            "state_reasons": reasons, "baseline_advantage_lower": lower,
            "proposed_gated_policy_gain_lower": lower[root],
            "proposed_net_gain_lower": net_lower,
            "spent": verification_cost,
            "returned_policy_net_gain_lower": net_lower if adopted else -verification_cost,
            "scope": "finite_model_simultaneous_baseline_Q_coverage_required"}
