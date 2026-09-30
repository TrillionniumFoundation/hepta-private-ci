"""Finite-sample diagnostics, not independently issued calibration authority.

Counts must come from a frozen independent evaluation population. Repeated
examples, correlated episodes and synthetic task labels do not establish that
assumption. This module deliberately cannot select a model or approve deployment.
"""
from __future__ import annotations

import math

MAX_TRIALS = 1_000_000


def error_upper_bound(errors: int, trials: int, alpha: float = 0.05) -> float | None:
    """One-sided Clopper-Pearson upper limit for a binomial error probability.

    Invert Pr[X <= errors] = alpha. The search starts at the observed rate, so
    backward probability ratios never increase. Returning the upper search
    endpoint plus a numerical guard is conservative to floating-point precision.
    An empty population has no observed bound. Units must be independent trials.
    """
    if type(trials) is not int or not 0 <= trials <= MAX_TRIALS:
        raise ValueError("invalid bounded trial count")
    if type(errors) is not int or not 0 <= errors <= trials:
        raise ValueError("invalid error count")
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("invalid tail probability")
    if not trials:
        return None
    if errors == trials:
        return 1.0
    if errors == 0:
        return -math.expm1(math.log(alpha) / trials)
    lo, hi = errors / trials, 1.0
    coefficient = math.lgamma(trials + 1) - math.lgamma(errors + 1) - math.lgamma(trials - errors + 1)
    for _ in range(64):
        probability = (lo + hi) / 2
        if probability == lo or probability == hi:
            break
        mass = coefficient + errors * math.log(probability) + (trials - errors) * math.log1p(-probability)
        term = total = 1.0
        ratio = (1 - probability) / probability
        for index in range(errors, 0, -1):
            term *= index / (trials - index + 1) * ratio
            total += term
            if term <= total * 1e-16:
                break
        if mass + math.log(total) > math.log(alpha):
            lo = probability
        else:
            hi = probability
    return min(1.0, hi + 1e-10)


def support_report(*, ood_errors: int, ood_trials: int,
                   decision_errors: int, decision_trials: int,
                   maximum_error_ppm: int = 5000) -> dict:
    """Report simultaneous 95% count limits for OOD and accepted decisions.

    Two one-sided limits each use alpha=.025 (Bonferroni). This is a new
    diagnostic, not an in-place reinterpretation of selection-evaluation.v2.
    No independence, data provenance, calibration trust or deployment is asserted.
    """
    if type(maximum_error_ppm) is not int or not 0 < maximum_error_ppm < 1_000_000:
        raise ValueError("invalid rate budget")
    maximum = maximum_error_ppm / 1_000_000
    alpha = 0.025
    ood = error_upper_bound(ood_errors, ood_trials, alpha)
    decision = error_upper_bound(decision_errors, decision_trials, alpha)
    minimum = math.ceil(math.log(alpha) / math.log1p(-maximum))
    return {
        "schema": "hepta.decision-cell-count-support.v1",
        "method": "one-sided-clopper-pearson-bonferroni-two",
        "familywise_alpha": 0.05,
        "maximum_error_ppm": maximum_error_ppm,
        "zero_error_minimum_independent_trials_per_population": minimum,
        "ood": {"errors": ood_errors, "trials": ood_trials, "upper": ood},
        "accepted_decision": {"errors": decision_errors, "trials": decision_trials, "upper": decision},
        "count_bounds_met": ood is not None and decision is not None and max(ood, decision) <= maximum,
        "independence_established": False,
        "calibration_trust_granted": False,
        "runtime_selection_eligible": False,
        "prospective_future_window_evidence": False,
        "production_activation": False,
    }


def family_support_report(*, candidate_receipts: dict[str, str],
                          observations: dict[str, dict],
                          maximum_error_ppm: int = 5000) -> dict:
    """Bound both risks for every member of an explicitly frozen candidate family.

    Bonferroni needs no independence between models or between the two risks.
    The binomial model still needs independent sampling units within each risk.
    Missing candidates cannot silently reduce the multiplicity penalty. Receipt
    identities are bindings supplied by the caller, not provenance verification.
    """
    import re

    if (type(candidate_receipts) is not dict or not 1 <= len(candidate_receipts) <= 32 or
            any(type(name) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name) is None or
                type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for name, digest in candidate_receipts.items()) or
            len(set(candidate_receipts.values())) != len(candidate_receipts)):
        raise ValueError("invalid bounded candidate receipt family")
    if type(observations) is not dict or set(observations) != set(candidate_receipts):
        raise ValueError("observations must cover exactly the frozen candidate family")
    if type(maximum_error_ppm) is not int or not 0 < maximum_error_ppm < 1_000_000:
        raise ValueError("invalid rate budget")
    fields = {"ood_errors", "ood_trials", "decision_errors", "decision_trials"}
    maximum = maximum_error_ppm / 1_000_000
    bound_count = 2 * len(candidate_receipts)
    alpha = 0.05 / bound_count
    rows = []
    for name in sorted(candidate_receipts):
        counts = observations[name]
        if type(counts) is not dict or set(counts) != fields:
            raise ValueError("invalid candidate count record")
        ood = error_upper_bound(counts["ood_errors"], counts["ood_trials"], alpha)
        decision = error_upper_bound(counts["decision_errors"], counts["decision_trials"], alpha)
        rows.append({
            "model_name": name, "receipt_sha256": candidate_receipts[name],
            "ood": {"errors": counts["ood_errors"], "trials": counts["ood_trials"], "upper": ood},
            "accepted_decision": {"errors": counts["decision_errors"],
                                  "trials": counts["decision_trials"], "upper": decision},
            "count_bounds_met": ood is not None and decision is not None and max(ood, decision) <= maximum,
        })
    return {
        "schema": "hepta.decision-cell-family-count-support.v1",
        "method": "one-sided-clopper-pearson-bonferroni-frozen-family",
        "candidate_count": len(candidate_receipts), "bound_count": bound_count,
        "familywise_alpha": 0.05, "per_bound_alpha": alpha,
        "maximum_error_ppm": maximum_error_ppm,
        "zero_error_minimum_independent_trials_per_population": math.ceil(math.log(alpha) / math.log1p(-maximum)),
        "candidates": rows, "all_count_bounds_met": all(row["count_bounds_met"] for row in rows),
        "independence_established": False, "calibration_trust_granted": False,
        "runtime_selection_eligible": False, "prospective_future_window_evidence": False,
        "production_activation": False,
    }
