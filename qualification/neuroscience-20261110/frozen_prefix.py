"""Fail-closed frozen-prefix Q24 shadow adapter (no owner attestation).

Selection callers cannot receive the full-audit digest or withheld-future
count. This only checks *declared* availability; a production Owner must
independently authenticate every source, action and effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from study import ContractError, Eligibility, Feedback, time_aligned_credit


@dataclass(frozen=True)
class FrozenPrefixProposal:
    arm: str
    group_deltas: tuple[float, ...]
    matched_feedback_count: int
    expired_feedback_count: int
    causal_training_digest: str
    authority: str = "DENY_ALL"
    qualification: str = "UNATTESTED_PREFIX_ONLY"


def frozen_prefix_proposal(
    actions: Iterable[Eligibility],
    declared_visible_feedback: Iterable[Feedback],
    *,
    arm: str,
    cutoff_sequence: int,
    decay: float,
    max_lag: int,
    per_group_limit: float = 0.5,
    global_l1_limit: float = 1.0,
) -> FrozenPrefixProposal:
    """Reject future input and expose only cutoff-visible research features.

    The declared availability is NOT an independently verified owner
    observation. Passing this function never authorizes training, adoption or
    external effects.
    """
    if type(cutoff_sequence) is not int or cutoff_sequence < 0:
        raise ContractError("invalid frozen cutoff")
    frozen_actions = tuple(actions)
    visible = tuple(declared_visible_feedback)
    for item in visible:
        if (type(item.available_sequence) is not int
                or item.available_sequence > cutoff_sequence):
            raise ContractError("post-cutoff feedback cannot enter frozen proposal")
    receipt = time_aligned_credit(
        frozen_actions, visible,
        arm=arm,
        cutoff_sequence=cutoff_sequence,
        decay=decay,
        max_lag=max_lag,
        per_group_limit=per_group_limit,
        global_l1_limit=global_l1_limit,
    )
    if receipt.future_withheld != 0:
        raise ContractError("unexpected future feedback in frozen proposal")
    return FrozenPrefixProposal(
        arm=receipt.arm,
        group_deltas=receipt.deltas,
        matched_feedback_count=receipt.matched,
        expired_feedback_count=receipt.expired,
        causal_training_digest=receipt.causal_training_digest,
    )
