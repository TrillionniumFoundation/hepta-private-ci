"""An explicit global empirical error budget across six operating points."""

import math

from addressing.contracts import OPERATIONS, digest


THRESHOLDS = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.01)
MARGINS = (0.0, 0.05, 0.15, 0.3)
MAX_OOD_RATE = 0.05
MIN_KNOWN_COVERAGE = 0.8


def accepted(hypothesis, policy):
    return (hypothesis["raw_operation"] in OPERATIONS
            and hypothesis["score"] >= policy["threshold"]
            and hypothesis["margin"] >= policy["margin"])


def metrics(rows, hypotheses, policies):
    if len(rows) != len(hypotheses):
        raise ValueError("row and prediction counts differ")
    counts = {"known": 0, "known_correct": 0, "known_wrong_accepted": 0, "known_abstained": 0,
              "ood": 0, "ood_accepted": 0}
    by_operation = {name: {"rows": 0, "correct": 0} for name in OPERATIONS}
    for row, prediction in zip(rows, hypotheses):
        raw = prediction["raw_operation"]
        decision = raw if raw in policies and accepted(prediction, policies[raw]) else None
        if row["operation"] == "reject":
            counts["ood"] += 1
            counts["ood_accepted"] += int(decision is not None)
        else:
            counts["known"] += 1
            by_operation[row["operation"]]["rows"] += 1
            if decision == row["operation"]:
                counts["known_correct"] += 1
                by_operation[row["operation"]]["correct"] += 1
            elif decision is None:
                counts["known_abstained"] += 1
            else:
                counts["known_wrong_accepted"] += 1
    counts["known_correct_coverage"] = counts["known_correct"] / counts["known"] if counts["known"] else None
    counts["ood_acceptance_rate"] = counts["ood_accepted"] / counts["ood"] if counts["ood"] else None
    counts["by_operation"] = by_operation
    return counts


def contract_comparison(rows, learned, guarded, policies):
    """Keep learned scores separate from explicit-contract gains and losses."""
    if len(rows) != len(learned) or len(rows) != len(guarded):
        raise ValueError("contract comparison requires identical paired requests")
    return {
        "raw_learned_with_same_frozen_policy": metrics(rows, learned, policies),
        "after_contract_with_same_frozen_policy": metrics(rows, guarded, policies),
        "raw_learned_argmax_known_correct": sum(row["operation"] != "reject" and raw["raw_operation"] == row["operation"]
                                                 for row, raw in zip(rows, learned)),
        "raw_learned_argmax_ood_routes": sum(row["operation"] == "reject" and raw["raw_operation"] != "reject"
                                             for row, raw in zip(rows, learned)),
        "explicit_contract_rejections": {
            label: sum((row["operation"] == "reject") == (label == "ood") and bool(value["capability_reason"])
                       for row, value in zip(rows, guarded)) for label in ("known", "ood")},
        "weights_and_thresholds_identical": True,
        "interpretation": "Diagnostic contract ablation on the same rows; not an independently admitted raw-model policy.",
    }


def fit_policies(rows, hypotheses, previous=None):
    """Maximize empirical coverage under one unchanged total OOD constraint.

    Selection may choose margins. Independent calibration only raises each
    selected threshold; it cannot change the candidate, margins or weights.
    Dynamic programming does not assume that operation groups are independent.
    """
    if len(rows) != len(hypotheses) or not rows or len(rows) > 16_384:
        raise ValueError("bounded nonempty paired calibration input required")
    if set(row["operation"] for row in rows) != {*OPERATIONS, "reject"}:
        raise ValueError("all supported operations and OOD are required")
    allowance = math.floor(MAX_OOD_RATE * sum(row["operation"] == "reject" for row in rows))
    curves, frontiers = {}, {}
    for operation in OPERATIONS:
        relevant = [(row, prediction) for row, prediction in zip(rows, hypotheses)
                    if prediction["raw_operation"] == operation]
        if previous is None:
            thresholds, margins = THRESHOLDS, MARGINS
        else:
            old = previous[operation]
            scores = [prediction["score"] for _, prediction in relevant]
            thresholds = sorted({old["threshold"], 1.01, *[
                value for score in scores for value in (score, math.nextafter(score, math.inf))
                if old["threshold"] <= value <= 1.01]})
            margins = (old["margin"],)
        curve, frontier = [], {}
        for threshold in thresholds:
            for margin in margins:
                policy = {"threshold": float(threshold), "margin": float(margin)}
                correct = wrong = bad = 0
                for row, prediction in relevant:
                    if accepted(prediction, policy):
                        correct += int(row["operation"] == operation)
                        bad += int(row["operation"] == "reject")
                        wrong += int(row["operation"] not in (operation, "reject"))
                point = {**policy, "correct": correct, "wrong_known": wrong, "ood_accepted": bad,
                         "feasible": wrong == 0 and bad <= allowance}
                curve.append(point)
                if point["feasible"] and (bad not in frontier or
                        (correct, threshold, margin) > tuple(frontier[bad][key] for key in ("correct", "threshold", "margin"))):
                    frontier[bad] = point
        curves[operation], frontiers[operation] = curve, frontier
    states = {0: (0, 0.0, 0.0, {})}
    for operation in OPERATIONS:
        updated = {}
        for spent, state in states.items():
            for extra, point in frontiers[operation].items():
                total = spent + extra
                if total > allowance:
                    continue
                candidate = (state[0] + point["correct"], state[1] + point["threshold"],
                             state[2] + point["margin"], {**state[3], operation: point})
                if total not in updated or candidate[:3] > updated[total][:3]:
                    updated[total] = candidate
        states = updated
    spent, choice = max(states.items(), key=lambda item: (item[1][0], -item[0], item[1][1], item[1][2]))
    policies = {operation: {key: point[key] for key in ("threshold", "margin")} for operation, point in choice[3].items()}
    result = metrics(rows, hypotheses, policies)
    assert result["ood_accepted"] == spent and spent <= allowance and result["known_wrong_accepted"] == 0
    gate = result["known_correct_coverage"] >= MIN_KNOWN_COVERAGE and result["ood_acceptance_rate"] <= MAX_OOD_RATE
    return {"schema": "hepta.memory.v9.empirical-admission.v1", "policies": policies, "metrics": result,
            "curves": curves, "input_rows_sha256": digest(rows), "prediction_sha256": digest(hypotheses),
            "previous_policy_sha256": digest(previous) if previous is not None else None,
            "global_ood_allowance": allowance, "global_ood_used": spent,
            "operation_ood_allocation": {name: point["ood_accepted"] for name, point in choice[3].items()},
            "minimum_known_coverage": MIN_KNOWN_COVERAGE, "maximum_ood_rate": MAX_OOD_RATE,
            "empirical_gate_passed": gate, "population_risk_established": False,
            "interpretation": "One finite authored-sample error budget; no calibrated-posterior or population-risk claim.",
            "selection_key": [result["known_correct"], -result["known_wrong_accepted"], -result["ood_accepted"]]}
