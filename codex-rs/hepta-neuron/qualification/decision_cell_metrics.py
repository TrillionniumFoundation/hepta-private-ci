"""Versioned diagnostic selection metrics; no model or deployment authority.

The gates are frozen pilot conditions, not a production statistical certificate.
Unknown or all-rejected outcomes cannot manufacture zero-risk supported behavior.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

EVALUATION_PROFILE = "hepta.decision-cell-selection-evaluation.v2"
HEADS = ("action", "target", "disposition", "postcondition")


def selection_statistics(
    predictions: Mapping[str, Sequence[int]],
    labels: Mapping[str, Sequence[int]],
    confidence_accepted: Sequence[bool],
    ood_rejected: Sequence[bool],
    in_domain: Sequence[bool],
) -> dict[str, Any]:
    """Evaluate the complete decision and the exact combined acceptance rule."""
    count = len(in_domain)
    if not count or set(predictions) != set(HEADS) or set(labels) != set(HEADS):
        raise ValueError("incomplete decision evaluation")
    columns = [*predictions.values(), *labels.values(), confidence_accepted, ood_rejected]
    if any(len(values) != count for values in columns):
        raise ValueError("decision evaluation length mismatch")
    if any(type(value) is not bool for values in (confidence_accepted, ood_rejected, in_domain) for value in values):
        raise ValueError("acceptance observations must be booleans")
    for name in HEADS:
        upper = 4 if name == "target" else 6
        for role, values in (("prediction", predictions[name]), ("label", labels[name])):
            lower = -1 if role == "label" and name == "target" else 0
            if any(type(value) is not int or not lower <= value < upper for value in values):
                raise ValueError("invalid decision class")
    joint = [
        all(predictions[name][i] == labels[name][i] for name in HEADS if name != "target")
        and (labels["target"][i] < 0 or predictions["target"][i] == labels["target"][i])
        for i in range(count)
    ]
    accepted = [confidence_accepted[i] and not ood_rejected[i] for i in range(count)]
    supported = sum(accepted)
    supported_in_domain = sum(accepted[i] and in_domain[i] for i in range(count))
    domain_rows = sum(in_domain)
    errors = sum(accepted[i] and (not joint[i] or not in_domain[i]) for i in range(count))
    # An empty accepted population has no observed error rate, not zero risk.
    rate = errors / supported if supported else None
    upper = None
    if supported:
        z = 1.959963984540054
        denominator = 1 + z * z / supported
        centre = rate + z * z / (2 * supported)
        radius = z * math.sqrt(rate * (1 - rate) / supported + z * z / (4 * supported * supported))
        upper = min(1.0, (centre + radius) / denominator)
    return {
        "joint_exact_accuracy": sum(joint) / count,
        "supported_rows": supported,
        "supported_in_domain_rows": supported_in_domain,
        "supported_in_domain_coverage": supported_in_domain / domain_rows if domain_rows else None,
        "supported_joint_error": rate,
        "supported_joint_error_wilson95_upper": upper,
    }


def quality_gates(receipt: Mapping[str, Any]) -> dict[str, bool]:
    """Keep pre-existing quality floors and add non-vacuous joint support.

    The 25%/20-row coverage floor is a pre-run diagnostic rule. Wilson bounds
    are reported separately; passing these empirical gates is not activation.
    Missing legacy metrics remain ineligible rather than being inferred.
    """
    test = receipt.get("test_metrics", {})
    ood = receipt.get("ood_test_metrics", {})
    if not isinstance(test, Mapping) or not isinstance(ood, Mapping):
        raise ValueError("invalid metric record")

    def rate(record: Mapping[str, Any], name: str, floor: float = 0.0, ceiling: float = 1.0) -> bool:
        value = record.get(name)
        return type(value) in (int, float) and math.isfinite(value) and floor <= value <= ceiling

    supported = test.get("supported_in_domain_rows")
    return {
        "current_evaluation_profile": receipt.get("evaluation_profile") == EVALUATION_PROFILE,
        "action_accuracy_at_least_0_80": rate(test, "action_accuracy", 0.80),
        "target_accuracy_at_least_0_70": rate(test, "target_accuracy", 0.70),
        "disposition_accuracy_at_least_0_80": rate(test, "disposition_accuracy", 0.80),
        "postcondition_accuracy_at_least_0_80": rate(test, "postcondition_accuracy", 0.80),
        "joint_exact_accuracy_at_least_0_65": rate(test, "joint_exact_accuracy", 0.65),
        "ood_false_acceptance_at_most_0_05": rate(ood, "ood_false_acceptance", ceiling=0.05),
        "confidence_error_at_most_0_05": rate(test, "confidence_error", ceiling=0.05),
        "supported_in_domain_rows_at_least_20": type(supported) is int and supported >= 20,
        "supported_in_domain_coverage_at_least_0_25": rate(test, "supported_in_domain_coverage", 0.25),
        "supported_joint_error_at_most_0_05": rate(test, "supported_joint_error", ceiling=0.05),
    }


def recommendations(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive recommendation views from verified model rows, never self-claims."""
    result = {}
    for name, gate, reason in (
        ("internal_shadow_recommendation", "internal_shadow_eligible",
         "highest preregistered quality-resource score among exact-revision quality-eligible candidates"),
        ("distribution_candidate_recommendation", "distribution_candidate_eligible",
         "highest score among candidates also passing current license and remote-code supply-chain gates"),
    ):
        eligible = sorted((row for row in rows if row[gate] is True),
                          key=lambda row: (-row["score"], row["model_name"]))
        result[name] = ({"model_name": eligible[0]["model_name"],
                         "receipt_sha256": eligible[0]["receipt_sha256"], "reason": reason}
                        if eligible else None)
    return result


def verify_summary_projection(summary: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                              evaluation_digest: str) -> None:
    """Recompute summary semantics; a rehashed summary is not verified evidence."""
    import json
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    expected = {"models": list(rows), **recommendations(rows),
                "evaluation_profile": EVALUATION_PROFILE,
                "evaluation_implementation_sha256": evaluation_digest,
                "candidate_scope": "synthetic_fixture_only"}
    for key, value in expected.items():
        if key not in summary or encode(summary[key]) != encode(value):
            raise ValueError("summary semantic substitution: " + key)
    for key in ("selection_authority", "runtime_selection_eligible", "operator_acceptance",
                "production_activation", "prospective_future_window_evidence"):
        if summary.get(key) is not False:
            raise ValueError("summary cannot grant " + key)
