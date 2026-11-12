"""Offline chosen-action diagnostics without rewriting frozen decisions.

These are descriptive complete-case scores, not survival estimates or policy
effects. Missing, interval and right-censored times are never exact CRPS labels.
Source declarations do not authenticate provenance or identify counterfactuals.
"""

from collections import Counter, defaultdict
import math

from .observed_evaluation import (
    COST_FIELDS,
    QUANTILES,
    ObservedDecision,
    score_forecast,
    validate_forecast,
)

MAX_OBSERVATIONS = 4096
METRICS = ("quality_brier", "duration_crps", "cost_crps")


def _statistics(values, count):
    observed = [value for value in values if value is not None]
    return {
        "count": count,
        "eligible": len(observed),
        "missing": count - len(observed),
        "mean": math.fsum(value / len(observed) for value in observed)
        if observed else None,
    }


def _summary(rows):
    count = len(rows)
    decisions = [row["decision"] for row in rows]
    metrics = {
        name: _statistics(
            [None if row["scores"] is None else row["scores"][name] for row in rows],
            count,
        )
        for name in METRICS
    }
    bins = []
    for index in range(10):
        eligible = [
            row for row in rows
            if row["scores"] is not None and row["scores"]["quality_brier"] is not None
            and min(int(row["prediction"]["success_probability"] * 10), 9) == index
        ]
        bins.append({
            "lower": index / 10, "upper": (index + 1) / 10,
            "count": len(eligible),
            "mean_prediction": _statistics(
                [row["prediction"]["success_probability"] for row in eligible], len(eligible)
            )["mean"],
            "outcome_rate": _statistics(
                [row["decision"].evidence.outcome for row in eligible], len(eligible)
            )["mean"],
        })
    coverage = {}
    for name in ("duration", "cost"):
        coverage[name] = []
        for index, level in enumerate(QUANTILES):
            stats = _statistics([
                None if row["scores"] is None
                else row["scores"][name + "_quantiles"][index]["covered"]
                for row in rows
            ], count)
            coverage[name].append({"level": level, **stats, "coverage": stats["mean"]})
    complete_cost = sum(all(d.costs[key] is not None for key in COST_FIELDS) for d in decisions)
    full_wall = sum(d.full_wall_seconds is not None for d in decisions)
    return {
        "count": count,
        "task_group_count": len({d.task_group for d in decisions}),
        "source_counts": dict(Counter(d.source for d in decisions)),
        "evidence_source_counts": dict(Counter(d.evidence.source.value for d in decisions)),
        "observation_status_counts": dict(Counter(d.evidence.observation_status.value for d in decisions)),
        "time_kind_counts": dict(Counter(d.evidence.time_kind.value for d in decisions)),
        "unsupported_predictions": sum(row["prediction"] is None for row in rows),
        "unobserved_chosen_actions": sum(not row["executed"] for row in rows),
        "unknown_outcome_count": sum(d.evidence.outcome is None for d in decisions),
        "final_cost_missing_count": sum(d.evidence.final_cost is None for d in decisions),
        "cost_ledger_complete_count": complete_cost,
        "cost_ledger_incomplete_count": count - complete_cost,
        "full_wall_observed_count": full_wall,
        "full_wall_missing_count": count - full_wall,
        "missing_cost_item_counts": {
            key: sum(d.costs[key] is None for d in decisions) for key in COST_FIELDS
        },
        "metrics": metrics,
        "success_reliability_bins": bins,
        "quantile_coverage": coverage,
    }


def summarize_offline_forecasts(
    observations: list[ObservedDecision], predictions: list[dict | None]
) -> dict:
    """Summarize matching offline predictions; None retains unsupported rows.

    Metric ``count`` is the full denominator; ``eligible`` counts scored labels,
    and ``missing`` is their difference. Quantile coverage is truth <= quantile,
    not an interval coverage claim. Overall scores may mix declared sources and
    are descriptive only; each source/split/chosen-action group stays separate.
    A common budget contract is required. The caller must additionally bind
    common target definitions and units in its frozen input manifest; those
    definitions cannot be inferred from ObservedDecision alone.
    """
    if not isinstance(observations, list) or not isinstance(predictions, list):
        raise ValueError("observations and predictions must be bounded lists")
    if not 1 <= len(observations) <= MAX_OBSERVATIONS or len(predictions) != len(observations):
        raise ValueError("need 1..4096 observations with matching predictions")
    if not all(isinstance(d, ObservedDecision) for d in observations):
        raise ValueError("observed decisions required")
    if len({d.sample_id for d in observations}) != len(observations):
        raise ValueError("duplicate sample identity")
    if len({d.budget_contract_digest for d in observations}) != 1:
        raise ValueError("mixed budget contracts require separate calibration reports")
    rows, grouped = [], defaultdict(list)
    for decision, prediction in zip(observations, predictions):
        if prediction is not None:
            if not isinstance(prediction, dict):
                raise ValueError("prediction must be a dictionary or None")
            prediction = validate_forecast(prediction)
        executed = (
            decision.executed_action == decision.chosen_action
            and decision.execution_ref is not None
        )
        row = {
            "decision": decision, "prediction": prediction, "executed": executed,
            "scores": score_forecast(prediction, decision.evidence)
            if executed and prediction is not None else None,
        }
        rows.append(row)
        grouped[decision.source, decision.split, decision.chosen_action].append(row)
    return {
        "schema": "pred1-offline-calibration-v1",
        "overall": _summary(rows),
        "groups": [
            {"source": source, "split": split, "chosen_action": action, **_summary(group)}
            for (source, split, action), group in sorted(grouped.items())
        ],
        "scope": "offline complete-case chosen-action diagnostics; informative missingness can bias all-task calibration; original decisions are unchanged",
        "cost_scope": "cost CRPS targets final action cost, not the full physical ledger",
        "decision": "NoUpdate", "candidate_eligible": False,
        "prediction_deployed": False, "production_activation": False,
        "native_provenance_authenticated": False,
        "causal_policy_value_identified": False, "counterfactual_policy_value": None,
    }
