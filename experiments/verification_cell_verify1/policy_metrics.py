"""Frozen loss/pricing specifications and descriptive fixed-bin calibration.

A specification must be bound by an original opportunity plan before events.
Metrics concern supplied known labels, not independently authenticated truth.
"""

import math

from .contracts import _number, _require, _text
from .cost_ledger import METRICS, summarize_costs
from .policy_costs import snapshot_costs
from .shadow_risk import DISPOSITIONS


def freeze_evaluation_spec(
    cost_rosters, *, losses, rates, utility_unit, bins=(0, 0.25, 0.5, 0.75, 1)
):
    """Build the specification to hash into the opportunity plan before events.

    The caller must retain that plan. This function alone does not freeze time,
    prove physical coverage, or authenticate any supplied cost roster.
    """
    cost_rosters, _ = snapshot_costs(cost_rosters)
    _text(utility_unit, "utility unit")
    _require(len(utility_unit) <= 256, "utility unit too long")
    for policy, roster in cost_rosters.items():
        _text(policy, "policy")
        _require(
            len(policy) <= 256 and type(roster) in (list, tuple),
            "invalid policy or cost roster",
        )
    _require(
        sum(len(roster) for roster in cost_rosters.values()) <= 10000,
        "combined cost roster exceeds limit",
    )
    summarize_costs(
        [item for rows in cost_rosters.values() for item in rows], (), rates
    )
    _require(type(rates) is dict and set(rates) == set(METRICS), "all rates required")
    _require(
        type(losses) is dict and set(losses) == set(DISPOSITIONS),
        "complete disposition loss table required",
    )
    for row in losses.values():
        _require(type(row) is dict and set(row) == {"correct", "error"}, "loss fields")
        for loss in row.values():
            _number(loss, "terminal loss", maximum=1e12)
    _require(
        type(bins) in (tuple, list) and 2 <= len(bins) <= 21,
        "bounded calibration bins required",
    )
    for edge in bins:
        _number(edge, "bin edge", maximum=1)
    _require(
        bins[0] == 0
        and bins[-1] == 1
        and all(left < right for left, right in zip(bins, bins[1:])),
        "bins must strictly partition zero to one",
    )
    return dict(
        schema="hepta.verify.policy-evaluation-spec.v1",
        utility_unit=utility_unit,
        losses={key: dict(value) for key, value in losses.items()},
        rates=dict(rates),
        bins=list(bins),
        cost_roster_sha256={
            policy: summarize_costs(roster, ())["roster_sha256"]
            for policy, roster in sorted(cost_rosters.items())
        },
    )


def calibration_metrics(rows, bins):
    predicted = [row for row in rows if row["probability"] is not None]
    scored = [row for row in predicted if row["truth"] is not None]
    reliability = []
    for lower, upper in zip(bins, bins[1:]):
        cell = [
            row
            for row in predicted
            if lower <= row["probability"] <= upper
            and (row["probability"] < upper or upper == 1)
        ]
        known = [row for row in cell if row["truth"] is not None]
        reliability.append(
            dict(
                interval=[lower, upper],
                predictions=len(cell),
                known_labels=len(known),
                unknown_labels=len(cell) - len(known),
                mean_risk_known=math.fsum(row["probability"] for row in known)
                / len(known)
                if known
                else None,
                error_rate_known=sum(row["truth"] for row in known) / len(known)
                if known
                else None,
            )
        )
    infinite = sum(row["probability"] == 1 - row["truth"] for row in scored)
    return dict(
        planned=len(rows),
        predictions=len(predicted),
        scored=len(scored),
        missing_or_unsupported_predictions=len(rows) - len(predicted),
        unknown_labels_among_predictions=len(predicted) - len(scored),
        brier_known=math.fsum(
            (row["probability"] - row["truth"]) ** 2 for row in scored
        )
        / len(scored)
        if scored
        else None,
        log_loss_known=math.fsum(
            -math.log(row["probability"])
            if row["truth"]
            else -math.log1p(-row["probability"])
            for row in scored
        )
        / len(scored)
        if scored and not infinite
        else None,
        infinite_log_loss_count=infinite,
        ece_known=math.fsum(
            cell["known_labels"]
            * abs(cell["mean_risk_known"] - cell["error_rate_known"])
            for cell in reliability
            if cell["known_labels"]
        )
        / len(scored)
        if scored
        else None,
        reliability=reliability,
        interpretation="fixed-bin known-label description; not calibrated-risk qualification",
    )
