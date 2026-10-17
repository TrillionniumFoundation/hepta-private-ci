"""Late-label P0 four-arm science audit; always HOLD_NO_GO on this research lane.

The caller must supply externally sealed original predictions and independent
original held labels. A self-declared seal is NOT an external custody attestation.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from math import comb
from fabric import Denied, digest

REQUIRED = ("no_change", "split", "type_prior", "zero_feature")


@dataclass(frozen=True)
class HeldCase:
    case_id: str
    source_root: str
    route_type: str
    gold: int


@dataclass(frozen=True)
class Probability:
    case_id: str
    value: float


@dataclass(frozen=True)
class SealedArm:
    name: str
    source_digest: str
    predictions: tuple[Probability, ...]
    sealed_prediction_sha256: str
    sgd_steps: int
    encoder_forwards: int


def canonical_bytes(arm: SealedArm) -> bytes:
    return json.dumps({"arm": arm.name, "source_digest": arm.source_digest,
                       "predictions": [[p.case_id, p.value] for p in arm.predictions],
                       "sgd_steps": arm.sgd_steps,
                       "encoder_forwards": arm.encoder_forwards},
                      ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def seal(arm: SealedArm) -> str:
    return sha256(canonical_bytes(arm)).hexdigest()


def exact_mcnemar(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n)


def review(*, gold: tuple[HeldCase, ...], arms: tuple[SealedArm, ...],
           registered_source_digest: str, fit_roots: frozenset[str]) -> dict:
    """No model selection, no production activation, no physical CellSplit."""
    digest(registered_source_digest)
    if not gold or len(gold) > 4096 or len({c.case_id for c in gold}) != len(gold):
        raise Denied("invalid held panel")
    if any(not c.case_id or not c.source_root or not c.route_type or (type(c.gold) is not int or c.gold not in (0, 1)) for c in gold):
        raise Denied("bad human labels/identities")
    if fit_roots & {c.source_root for c in gold}:
        raise Denied("correlated root leakage")
    if len(arms) != len(REQUIRED) or set(a.name for a in arms) != set(REQUIRED):
        raise Denied("incomplete four-arm comparison")
    expected_ids = tuple(c.case_id for c in gold)
    values = {}
    for arm in arms:
        if arm.source_digest != registered_source_digest or arm.sgd_steps < 0 or arm.encoder_forwards < 0:
            raise Denied("unmatched source or missing physical cost scope")
        if tuple(p.case_id for p in arm.predictions) != expected_ids:
            raise Denied("changed case order or incomplete predictions")
        if any(not isinstance(p.value, (int, float)) or isinstance(p.value, bool)
               or not math.isfinite(p.value) or p.value < 0 or p.value > 1 for p in arm.predictions):
            raise Denied("invalid probability")
        if digest(arm.sealed_prediction_sha256) != seal(arm):
            raise Denied("altered sealed model predictions")
        values[arm.name] = tuple(float(p.value) for p in arm.predictions)

    metrics = {}
    truth = tuple(c.gold for c in gold)
    for name, probs in values.items():
        decisions = tuple(int(p >= 0.5) for p in probs)
        metrics[name] = {"correct": sum(d == t for d, t in zip(decisions, truth)),
                         "n": len(truth),
                         "brier": sum((p - t)**2 for p, t in zip(probs, truth)) / len(truth),
                         "sgd_steps": next(a.sgd_steps for a in arms if a.name == name),
                         "encoder_forwards": next(a.encoder_forwards for a in arms if a.name == name)}
    decisions = {name: tuple(p >= 0.5 for p in v) for name, v in values.items()}
    wins = sum(d == t and b != t for d, b, t in zip(decisions["split"], decisions["no_change"], truth))
    losses = sum(d != t and b == t for d, b, t in zip(decisions["split"], decisions["no_change"], truth))
    prior_parity = sum(a == b for a, b in zip(decisions["split"], decisions["type_prior"]))
    zero_parity = sum(a == b for a, b in zip(decisions["split"], decisions["zero_feature"]))
    return {"kind": "descriptive_late_label_four_arm", "status": "HOLD_NO_GO",
            "decision_owner": "external_independent_review_required",
            "root_count": len({x.source_root for x in gold}),
            "case_count": len(gold), "arm_metrics": metrics,
            "split_wins_vs_no_change": wins, "split_losses_vs_no_change": losses,
            "paired_exact_mcnemar_p": exact_mcnemar(wins, losses),
            "split_vs_type_prior_decision_parity": prior_parity,
            "split_vs_zero_feature_decision_parity": zero_parity,
            "learned_representation_effect_verified": False,
            "ndu_real_task_gain_verified": False,
            "model_selection_authorized": False,
            "cell_split_authorized": False,
            "native_effect_authorized": False}
