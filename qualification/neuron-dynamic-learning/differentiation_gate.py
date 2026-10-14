"""Conservative advisory decision for Cell reuse/split/transfer/consolidation.

Never verifies cryptographic signatures or issues production authorization;
original experiment/evaluation owners must independently check every claim.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ACTIONS = frozenset({"reuse", "cell_head", "organ_adapter", "cell_lora",
                     "split", "merge", "retire", "stem_consolidation"})


class DifferentiationError(ValueError):
    """Malformed candidate or self-certified score."""


def advisory_gate(candidate: dict) -> dict:
    required = {"action", "candidate_digest", "base_digest", "source_snapshot_digest",
                "evaluator_digest", "predecessor_digest", "revocation_frontier",
                "real_pretrained_encoder", "independent_outcome", "training_groups",
                "future_groups", "future_windows", "current_model_unchanged",
                "deleted_sources_excluded", "task_gain_lcb95", "worst_retention_delta",
                "max_ece", "ood_false_accept_rate", "matched_total_cost_ratio",
                "cross_scope_training_authorized"}
    if not isinstance(candidate, dict) or set(candidate) != required:
        raise DifferentiationError("exact proposal schema required")
    if candidate["action"] not in ACTIONS:
        raise DifferentiationError("unknown differentiation action")
    for k in ("candidate_digest", "base_digest", "source_snapshot_digest",
              "evaluator_digest", "predecessor_digest", "revocation_frontier"):
        v = candidate[k]
        if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise DifferentiationError("missing immutable artifact lineage")
    for k in ("real_pretrained_encoder", "independent_outcome", "current_model_unchanged",
              "deleted_sources_excluded", "cross_scope_training_authorized"):
        if type(candidate[k]) is not bool:
            raise DifferentiationError("false or untyped evidence flag")
    for k in ("training_groups", "future_groups"):
        if not isinstance(candidate[k], list) or not candidate[k] or any(
            not isinstance(v, str) or not v for v in candidate[k]
        ) or len(set(candidate[k])) != len(candidate[k]):
            raise DifferentiationError("group lineage required")
    if type(candidate["future_windows"]) is not int or candidate["future_windows"] < 0:
        raise DifferentiationError("invalid future windows")
    metrics = ("task_gain_lcb95", "worst_retention_delta", "max_ece",
               "ood_false_accept_rate", "matched_total_cost_ratio")
    if any(type(candidate[k]) not in (float, int) or not math.isfinite(candidate[k])
           for k in metrics):
        raise DifferentiationError("missing finite preregistered metrics")
    failures = []
    if not candidate["real_pretrained_encoder"]:
        failures.append("no_real_encoder_execution")
    if not candidate["independent_outcome"]:
        failures.append("missing_independent_outcome")
    if set(candidate["training_groups"]) & set(candidate["future_groups"]):
        failures.append("training_future_group_leakage")
    if candidate["future_windows"] < 3:
        failures.append("three_future_windows_required")
    if candidate["task_gain_lcb95"] <= 0:
        failures.append("no_positive_conservative_task_gain")
    if candidate["worst_retention_delta"] < -0.02:
        failures.append("negative_transfer_or_forgetting")
    if candidate["max_ece"] > 0.03:
        failures.append("calibration_gate_failed")
    if candidate["ood_false_accept_rate"] >= 0.005:
        failures.append("ood_gate_failed")
    if candidate["matched_total_cost_ratio"] > 1.0 or candidate["matched_total_cost_ratio"] <= 0:
        failures.append("unmatched_or_increased_total_cost")
    if not candidate["current_model_unchanged"]:
        failures.append("selected_weights_modified")
    if not candidate["deleted_sources_excluded"]:
        failures.append("revoked_data_in_lineage")
    if candidate["action"] == "stem_consolidation" and not candidate["cross_scope_training_authorized"]:
        failures.append("no_cross_scope_training_authority")
    return {
        "action": candidate["action"], "candidate_digest": candidate["candidate_digest"],
        "screening": "READY_FOR_INDEPENDENT_REVIEW" if not failures else "REJECTED",
        "blocking_reasons": failures,
        "claims_independently_authenticated": False,
        "production_promotion": "DENY_ALL",
        "selected_artifact_mutation": False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Non-authorizing Stem/Cell candidate screening")
    p.add_argument("--candidate", required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(advisory_gate(json.loads(a.candidate.read_text(encoding="utf-8"))), sort_keys=True))
