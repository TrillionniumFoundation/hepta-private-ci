"""Count correct accepted answers and false accepts without relabeling refusals."""

from collections import Counter
import math

from .config import DEFAULT_CONFIG
from .contracts import INTENTS, REJECT
from .router import decisions_from_scores


def wilson_interval(successes, total, z=1.959963984540054):
    if total <= 0:
        return None
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(rows, decisions):
    if not rows or len(rows) != len(decisions):
        raise ValueError("empty or mismatched evaluation rows")
    known = [i for i, row in enumerate(rows) if row["intent"] != REJECT]
    ood = [i for i, row in enumerate(rows) if row["intent"] == REJECT]
    if not known or not ood:
        raise ValueError("both known and near-OOD observations are required")
    correct = sum(decisions[i]["accepted_intent"] == rows[i]["intent"] for i in known)
    accepted = sum(decisions[i]["accepted"] for i in known)
    false = sum(decisions[i]["accepted"] for i in ood)
    raw_correct = sum(decisions[i]["raw_label"] == rows[i]["intent"] for i in known)
    raw_false = sum(decisions[i]["raw_label"] != REJECT for i in ood)
    by_intent = {}
    for intent in INTENTS:
        subset = [i for i in known if rows[i]["intent"] == intent]
        by_intent[intent] = {
            "rows": len(subset),
            "correct_accepted": sum(
                decisions[i]["accepted_intent"] == intent for i in subset
            ),
            "accepted": sum(decisions[i]["accepted"] for i in subset),
            "raw_correct": sum(decisions[i]["raw_label"] == intent for i in subset),
            "raw_confusion": dict(Counter(decisions[i]["raw_label"] for i in subset)),
        }
    by_family = {}
    for family in sorted({rows[i]["family"] for i in ood}):
        subset = [i for i in ood if rows[i]["family"] == family]
        by_family[family] = {
            "rows": len(subset),
            "false_accepted": sum(decisions[i]["accepted"] for i in subset),
            "raw_false_accepted": sum(
                decisions[i]["raw_label"] != REJECT for i in subset
            ),
        }
    coverage, risk = correct / len(known), false / len(ood)
    return {
        "known_rows": len(known),
        "ood_rows": len(ood),
        "known_correct_accepted": correct,
        "known_accepted": accepted,
        "known_wrong_accepted": accepted - correct,
        "ood_false_accepted": false,
        "correct_known_coverage": coverage,
        "ood_false_accept_rate": risk,
        "correct_known_wilson_interval": wilson_interval(correct, len(known)),
        "ood_false_accept_wilson_interval": wilson_interval(false, len(ood)),
        "raw_argmax_known_correct": raw_correct,
        "raw_argmax_known_accuracy": raw_correct / len(known),
        "raw_argmax_ood_false_accepted": raw_false,
        "raw_argmax_ood_false_accept_rate": raw_false / len(ood),
        "known_coverage_gate": coverage
        >= DEFAULT_CONFIG["minimum_correct_known_coverage"],
        "ood_risk_gate": risk <= DEFAULT_CONFIG["maximum_ood_false_accept"],
        "qualified": coverage >= DEFAULT_CONFIG["minimum_correct_known_coverage"]
        and risk <= DEFAULT_CONFIG["maximum_ood_false_accept"],
        "by_intent": by_intent,
        "by_ood_family": by_family,
        "interval_scope": "descriptive fixed-query counts, not a selection-adjusted or population safety guarantee",
    }


def calibrate(rows, scores):
    candidates = []
    for confidence in DEFAULT_CONFIG["confidence_grid"]:
        for margin in DEFAULT_CONFIG["margin_grid"]:
            calibration = {
                "minimum_confidence": confidence,
                "minimum_margin": margin,
                "reject_all": False,
            }
            report = summarize(rows, decisions_from_scores(scores, calibration))
            candidates.append({"calibration": calibration, "metrics": report})
    fallback = {"minimum_confidence": 1.0, "minimum_margin": 1.0, "reject_all": True}
    candidates.append(
        {
            "calibration": fallback,
            "metrics": summarize(rows, decisions_from_scores(scores, fallback)),
        }
    )
    feasible = [
        candidate for candidate in candidates if candidate["metrics"]["ood_risk_gate"]
    ]
    selected = min(
        feasible,
        key=lambda item: (
            -item["metrics"]["known_correct_accepted"],
            item["metrics"]["known_wrong_accepted"],
            item["metrics"]["ood_false_accepted"],
            item["calibration"]["minimum_confidence"],
            item["calibration"]["minimum_margin"],
            item["calibration"]["reject_all"],
        ),
    )
    compact = [
        {
            "calibration": item["calibration"],
            "known_correct_accepted": item["metrics"]["known_correct_accepted"],
            "known_wrong_accepted": item["metrics"]["known_wrong_accepted"],
            "ood_false_accepted": item["metrics"]["ood_false_accepted"],
            "qualified": item["metrics"]["qualified"],
            "risk_feasible": item["metrics"]["ood_risk_gate"],
        }
        for item in candidates
    ]
    return selected["calibration"], selected["metrics"], compact


def primary_key(candidate):
    metrics = candidate["selection"]
    if not metrics["ood_risk_gate"]:
        raise ValueError(
            "candidate calibration must be risk-feasible or explicit reject-all"
        )
    return (
        -metrics["known_correct_accepted"],
        metrics["known_wrong_accepted"],
        metrics["ood_false_accepted"],
        candidate["artifact"]["bytes"],
        candidate["name"],
        candidate["calibration"]["minimum_confidence"],
        candidate["calibration"]["minimum_margin"],
    )
