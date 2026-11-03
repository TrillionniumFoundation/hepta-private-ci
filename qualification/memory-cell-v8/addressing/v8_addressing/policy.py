"""Per-operation empirical operating points; no population-risk guarantee."""

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


def fit_policies(rows, hypotheses, previous=None):
    """Selection fixes margins; independent calibration only tightens thresholds.

    Each operation receives one sixth of the total OOD error allowance. Wrong
    accepted supported operations are never permitted on the fitting split.
    These are finite authored-sample constraints, not statistical certificates.
    """
    if len(rows) != len(hypotheses) or not rows:
        raise ValueError("nonempty paired calibration input required")
    if set(row["operation"] for row in rows) != {*OPERATIONS, "reject"}:
        raise ValueError("all supported operations and OOD are required")
    ood = sum(row["operation"] == "reject" for row in rows)
    allowance = math.floor(MAX_OOD_RATE * ood / len(OPERATIONS))
    policies, curves = {}, {}
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
        curve = []
        for threshold in thresholds:
            for margin in margins:
                policy = {"threshold": float(threshold), "margin": float(margin)}
                correct = wrong = bad = 0
                for row, prediction in relevant:
                    if not accepted(prediction, policy):
                        continue
                    correct += int(row["operation"] == operation)
                    bad += int(row["operation"] == "reject")
                    wrong += int(row["operation"] not in (operation, "reject"))
                curve.append({**policy, "correct": correct, "wrong_known": wrong,
                              "ood_accepted": bad, "feasible": wrong == 0 and bad <= allowance})
        feasible = [row for row in curve if row["feasible"]]
        chosen = max(feasible, key=lambda row: (row["correct"], -row["ood_accepted"], row["threshold"], row["margin"]))
        policies[operation] = {name: chosen[name] for name in ("threshold", "margin")}
        curves[operation] = curve
    result = metrics(rows, hypotheses, policies)
    gate = (result["known_correct_coverage"] >= MIN_KNOWN_COVERAGE
            and result["known_wrong_accepted"] == 0
            and result["ood_acceptance_rate"] <= MAX_OOD_RATE)
    return {"schema": "hepta.memory.v8.empirical-admission.v1", "policies": policies,
            "metrics": result, "curves": curves, "input_rows_sha256": digest(rows),
            "prediction_sha256": digest(hypotheses), "previous_policy_sha256": digest(previous) if previous is not None else None,
            "operation_ood_allowance": allowance, "minimum_known_coverage": MIN_KNOWN_COVERAGE,
            "maximum_ood_rate": MAX_OOD_RATE, "empirical_gate_passed": gate,
            "population_risk_established": False,
            "interpretation": "Per-operation authored-sample operating points. No iid population, exchangeability, or calibrated-posterior claim.",
            "selection_key": [result["known_correct"], -result["known_wrong_accepted"], -result["ood_accepted"]]}
