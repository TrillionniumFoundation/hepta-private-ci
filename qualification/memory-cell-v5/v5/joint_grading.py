"""Exact numeric and ordered-source grading, separate from serving callbacks."""

from collections import Counter
import math

from .contracts import INTENTS, REJECT
from .joint_cases import GATES


def exact_result(actual, target):
    if target is None or actual is None or not isinstance(actual, dict):
        return False
    return (
        set(actual) == {"kind", "value", "support"}
        and actual["kind"] == "number"
        and type(actual["value"]) in (int, float)
        and math.isfinite(actual["value"])
        and actual["value"] == target["value"]
        and list(actual["support"]) == target["support"]
    )


def route_metrics(graders, decisions):
    if len(graders) != len(decisions):
        raise ValueError("route denominator differs from grader")
    known = [i for i, row in enumerate(graders) if row["gold_intent"] is not None]
    ood = [i for i, row in enumerate(graders) if row["gold_intent"] is None]
    correct = sum(
        decisions[i]["accepted_intent"] == graders[i]["gold_intent"] for i in known
    )
    false_accept = sum(decisions[i]["accepted_intent"] is not None for i in ood)
    confusion, raw = Counter(), Counter()
    for row, decision in zip(graders, decisions, strict=True):
        gold = row["gold_intent"] or REJECT
        confusion[gold, decision["accepted_intent"] or REJECT] += 1
        raw[gold, decision["raw_label"]] += 1
    per_intent = {}
    for intent in INTENTS:
        indices = [i for i, row in enumerate(graders) if row["gold_intent"] == intent]
        per_intent[intent] = {
            "queries": len(indices),
            "correct_accepted": sum(
                decisions[i]["accepted_intent"] == intent for i in indices
            ),
            "raw_correct": sum(decisions[i]["raw_label"] == intent for i in indices),
        }
    return {
        "known_queries": len(known),
        "ood_queries": len(ood),
        "known_correct_accepted": correct,
        "known_correct_accepted_fraction": correct / len(known),
        "ood_false_accepted": false_accept,
        "ood_false_accept_fraction": false_accept / len(ood),
        "raw_known_correct": sum(
            decisions[i]["raw_label"] == graders[i]["gold_intent"] for i in known
        ),
        "raw_ood_false_accepted": sum(
            decisions[i]["raw_label"] in INTENTS for i in ood
        ),
        "per_intent": per_intent,
        "accepted_confusion": [
            {"gold": key[0], "prediction": key[1], "count": value}
            for key, value in sorted(confusion.items())
        ],
        "raw_confusion": [
            {"gold": key[0], "prediction": key[1], "count": value}
            for key, value in sorted(raw.items())
        ],
    }


def grade_domain(graders, actual_rows, strong_rows, oracle_rows):
    count = len(graders)
    if any(len(rows) != count for rows in (actual_rows, strong_rows, oracle_rows)):
        raise ValueError("joint arm row counts differ")
    decisions = [row["decision"] for row in actual_rows]
    if decisions != [row["decision"] for row in strong_rows]:
        raise ValueError(
            "actual and strong fresh processes have different route decisions"
        )
    metrics = route_metrics(graders, decisions)
    arm_values = {
        **{
            name: [row["arms"][name] for row in actual_rows]
            for name in (
                "parameter_connected",
                "parameter_removed",
                "parameter_permuted",
            )
        },
        "strong_planner": [row["arms"]["strong_planner"] for row in strong_rows],
        "parameter_oracle": [row["parameter_oracle"] for row in oracle_rows],
        "strong_oracle": [row["strong_oracle"] for row in oracle_rows],
    }
    known = [i for i, row in enumerate(graders) if row["gold_intent"] is not None]
    composed = [i for i in known if graders[i]["gold_intent"] != "at"]
    arms, row_scores = {}, []
    exacts = {
        name: [
            exact_result(value["actual"], grader["target"])
            for value, grader in zip(values, graders, strict=True)
        ]
        for name, values in arm_values.items()
    }
    for name, values in arm_values.items():
        arms[name] = {
            "known_queries": len(known),
            "known_exact": sum(exacts[name][i] for i in known),
            "known_exact_fraction": sum(exacts[name][i] for i in known) / len(known),
            "composed_queries": len(composed),
            "composed_exact": sum(exacts[name][i] for i in composed),
            "composed_exact_fraction": sum(exacts[name][i] for i in composed)
            / len(composed),
            "hop_calls": sum(value["execution"]["calls"] for value in values),
            "numeric_read_calls": sum(value["numeric_read_calls"] for value in values),
            "numeric_coordinates_read": sum(
                value["numeric_coordinates_read"] for value in values
            ),
        }
    for i, grader in enumerate(graders):
        row_scores.append(
            {
                "index": i,
                "template_id": grader["template_id"],
                "gold_intent": grader["gold_intent"],
                "accepted_intent": decisions[i]["accepted_intent"],
                "exact_by_arm": {name: flags[i] for name, flags in exacts.items()},
            }
        )
    connected = arms["parameter_connected"]["composed_exact"]
    gain_removed = (connected - arms["parameter_removed"]["composed_exact"]) / len(
        composed
    )
    gain_permuted = (connected - arms["parameter_permuted"]["composed_exact"]) / len(
        composed
    )
    checks = {
        "semantic": metrics["known_correct_accepted_fraction"]
        >= GATES["known_correct_accepted_min"]
        and metrics["ood_false_accept_fraction"] <= GATES["ood_false_accept_max"],
        "parameter_oracle_exact": arms["parameter_oracle"]["known_exact_fraction"]
        == GATES["parameter_oracle_exact"],
        "composed_actual_ablation_gain": min(gain_removed, gain_permuted)
        >= GATES["composed_ablation_gain_min"],
    }
    return {
        "routing": metrics,
        "arms": arms,
        "checks": checks,
        "all_preregistered_gates_pass": all(checks.values()),
        "composed_gain_vs_removed": gain_removed,
        "composed_gain_vs_permuted": gain_permuted,
        "oracle_exact_gap": arms["parameter_oracle"]["known_exact_fraction"]
        - arms["parameter_connected"]["known_exact_fraction"],
        "actual_parameter_minus_strong_planner": arms["parameter_connected"][
            "known_exact_fraction"
        ]
        - arms["strong_planner"]["known_exact_fraction"],
        "fresh_route_decisions_exactly_equal": True,
        "rows": row_scores,
    }
