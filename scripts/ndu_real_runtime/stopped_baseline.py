"""Independent ordinary entropic one-step DP on the same terminal lotteries.

This is an arithmetic negative control, not a second deployed policy trial.
It reuses the already-paid forecasts and decision-cut budget to establish when
the stopped NDU profile reduces exactly to ordinary risk-sensitive control.
"""

import math
import time

from .controllers import ACTIONS


def ordinary_risk_choice(
    outcomes, plan, *, over_budget_actions=(), practical_margin=0.0
):
    if plan.horizon != 1 or not isinstance(outcomes, dict) or "STOP" not in outcomes:
        raise ValueError("Ordinary terminal DP requires horizon one and paid STOP")
    if set(outcomes) - set(ACTIONS) or set(over_budget_actions) - set(outcomes):
        raise ValueError("Unrecognized action or budget exclusion")
    if (
        type(practical_margin) not in (int, float)
        or not math.isfinite(practical_margin)
        or not 0 <= practical_margin <= 1
    ):
        raise ValueError("Invalid ordinary-control practical margin")
    scores = {}
    for action, rows in outcomes.items():
        if not isinstance(rows, (tuple, list)) or not 1 <= len(rows) <= 64:
            raise ValueError("A bounded finite terminal lottery is required")
        for row in rows:
            if (
                not isinstance(row, (tuple, list))
                or len(row) != 3
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in row)
                or not 0 <= row[0] <= 1
                or not 0 < row[1] <= 3600
                or row[2] < 0
            ):
                raise ValueError("Invalid terminal quality, duration, or probability")
        mass = math.fsum(row[2] for row in rows)
        if not math.isclose(mass, 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError("Terminal probability mass must sum to one")
        # Independent arithmetic: do not import the NDU edge/CE implementation.
        values = [
            (
                plan.discount_per_second**seconds * quality
                - plan.latency_weight * seconds,
                probability / mass,
            )
            for quality, seconds, probability in rows
            if probability > 0
        ]
        mean = math.fsum(value * probability for value, probability in values)
        if plan.risk == 0:
            score = mean
        elif max(abs(plan.risk * (value - mean)) for value, _ in values) <= 1e-3:
            delta = math.fsum(
                probability * math.expm1(-plan.risk * (value - mean))
                for value, probability in values
            )
            score = mean - math.log1p(delta) / plan.risk
        else:
            minimum = min(value for value, _ in values)
            expected = math.fsum(
                probability * math.exp(-plan.risk * (value - minimum))
                for value, probability in values
            )
            score = minimum - math.log(expected) / plan.risk
        if not math.isfinite(score):
            raise ValueError("Ordinary risk score exceeds the finite domain")
        scores[action] = score
    # Keep paid STOP as the emergency fallback even when it exceeds remaining
    # time. This is shared action eligibility, never a deadline guarantee.
    eligible = [
        "STOP",
        *(
            action
            for action in outcomes
            if action != "STOP" and action not in over_budget_actions
        ),
    ]
    best = max(eligible, key=lambda action: scores[action])
    if scores[best] <= scores["STOP"] + practical_margin:
        best = "STOP"
    return best, scores


def compare_ordinary_risk(receipt, plan):
    started = time.perf_counter()
    if receipt.get("horizon") != 1 or receipt.get("risk") != plan.risk:
        raise ValueError("Reference and candidate objective settings differ")
    if receipt.get("planner_budget_exhausted"):
        return {
            "status": "unavailable",
            "reason": "candidate_forecasts_incomplete",
            "independent_ndu_benefit_established": False,
        }
    action, scores = ordinary_risk_choice(
        receipt["terminal_scenarios"],
        plan,
        over_budget_actions=receipt["over_budget_actions"],
        practical_margin=receipt["practical_margin"],
    )
    differences = {
        name: abs(value - receipt["predicted_values"][name])
        for name, value in scores.items()
    }
    return {
        "status": "compared",
        "reference": "ordinary_entropic_terminal_DP",
        "ordinary_action": action,
        "ordinary_values": scores,
        "selected_action_equal": action == receipt["selected_action"],
        "values_equal_within_1e12": all(
            value <= 1e-12 for value in differences.values()
        ),
        "maximum_absolute_value_difference": max(differences.values()),
        "same_terminal_lotteries": True,
        "same_decision_cut_budget": True,
        "additional_forecast_calls": 0,
        "comparison_seconds": time.perf_counter() - started,
        "cost_scope": "shared_forecasts; extra_diagnostic_arithmetic_measured",
        "standalone_runtime_budget_matched": False,
        "policy_return_comparison": False,
        "independent_ndu_benefit_established": False,
    }
