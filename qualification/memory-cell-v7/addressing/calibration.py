"""Candidate selection and an independent, one-way OOD threshold calibration."""

import math

import numpy as np
from scipy.stats import binom

from .contracts import OPERATIONS, digest


def measure(rows, decisions):
    known = [index for index, row in enumerate(rows) if row["operation"] in OPERATIONS]
    ood = [index for index, row in enumerate(rows) if row["operation"] == "reject"]
    correct = sum(
        decisions[index]["operation"] == rows[index]["operation"] for index in known
    )
    wrong = sum(
        decisions[index]["operation"] not in (None, rows[index]["operation"])
        for index in known
    )
    language = {}
    for name in sorted({row["language"] for row in rows}):
        selected = [index for index in known if rows[index]["language"] == name]
        if selected:
            language[name] = sum(
                decisions[index]["operation"] == rows[index]["operation"]
                for index in selected
            ) / len(selected)
    return {
        "known_rows": len(known),
        "known_correct": correct,
        "known_wrong_accepted": wrong,
        "known_correct_rate": correct / max(len(known), 1),
        "known_wrong_rate": wrong / max(len(known), 1),
        "ood_rows": len(ood),
        "ood_accepted": sum(decisions[index]["operation"] is not None for index in ood),
        "ood_acceptance_rate": sum(
            decisions[index]["operation"] is not None for index in ood
        )
        / max(len(ood), 1),
        "language_known_correct_rates": language,
    }


def select_policy(model, rows, hypotheses):
    trials = []
    for threshold in (0.0, 0.35, 0.5, 0.65, 0.8):
        for margin in (0.0, 0.05, 0.1, 0.2, 0.3):
            model.threshold, model.margin = threshold, margin
            metrics = measure(rows, [model.decide(row) for row in hypotheses])
            key = (
                metrics["ood_acceptance_rate"] <= 0.05
                and metrics["known_wrong_rate"] <= 0.02,
                min(metrics["language_known_correct_rates"].values()),
                metrics["known_correct_rate"],
                -metrics["ood_acceptance_rate"],
                -metrics["known_wrong_rate"],
                -threshold,
                -margin,
            )
            trials.append(
                {
                    "threshold": threshold,
                    "margin": margin,
                    "metrics": metrics,
                    "selection_key": list(key),
                }
            )
    selected = max(trials, key=lambda item: item["selection_key"])
    model.threshold, model.margin = selected["threshold"], selected["margin"]
    return {"selected": selected, "trials": trials, "selection_sha256": digest(rows)}


def calibrate(model, rows, hypotheses, *, risk_target=0.05, delta=0.05):
    """Only tighten a selected policy; no model/margin selection uses this data.

    For an independent iid/exchangeable calibration sample, the k-th ascending
    score gives a one-sided tolerance threshold: P(F(S_(k)) >= 1-risk_target)
    >= 1-delta. Strict exceedance handles tied scores conservatively. Synthetic
    author-written families do not establish that population assumption.
    """
    if not 0 < risk_target < 1 or not 0 < delta < 1 or len(rows) != len(hypotheses):
        raise ValueError("invalid calibration inputs")
    previous_threshold, previous_margin = model.threshold, model.margin
    scores = []
    for row, hypothesis in zip(rows, hypotheses):
        if row["operation"] == "reject":
            eligible = (
                hypothesis["raw_operation"] in OPERATIONS
                and hypothesis["margin"] >= previous_margin
            )
            scores.append(hypothesis["score"] if eligible else -1.0)
    count = len(scores)
    order_index = next(
        (
            index
            for index in range(1, count + 1)
            if binom.cdf(index - 1, count, 1 - risk_target) >= 1 - delta
        ),
        None,
    )
    if order_index is None:
        calibrated_threshold, selected_score = 1.01, None
    else:
        selected_score = sorted(scores)[order_index - 1]
        calibrated_threshold = max(
            previous_threshold, float(np.nextafter(selected_score, math.inf)), 0.0
        )
    model.threshold = calibrated_threshold
    decisions = [model.decide(row) for row in hypotheses]
    result = {
        "schema": "hepta.memory.v7.independent-calibration.v1",
        "calibration_sha256": digest(rows),
        "rows": len(rows),
        "ood_rows": count,
        "known_rows": sum(row["operation"] != "reject" for row in rows),
        "prior_threshold": previous_threshold,
        "threshold": calibrated_threshold,
        "margin_unchanged": previous_margin,
        "risk_target": risk_target,
        "delta": delta,
        "ascending_order_index_1_based": order_index,
        "selected_ood_score": selected_score,
        "head_parameters_updated": False,
        "candidate_selection_performed": False,
        "policy_only_tightened": calibrated_threshold >= previous_threshold,
        "metrics": measure(rows, decisions),
        "bound_requires_independent_exchangeable_calibration": True,
        "population_risk_established": False,
        "limitation": "Author-written synthetic families are not a representative iid human request population; the tolerance calculation is conditional on that additional assumption.",
    }
    model.calibration = result
    return result, decisions
