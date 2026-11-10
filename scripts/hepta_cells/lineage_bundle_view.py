"""Read-only join of a declared 1+2+7 Cell to the existing native Bundle wire.

This adapter reuses the *existing* Python/native-compatible Bundle codec and
local-update validator. It creates no state owner, signature, evidence receipt,
cutover, training execution or adoption capability. A caller must still obtain
the original native CellStatePartition owner and signed independent evaluation.
"""

from dataclasses import asdict, dataclass
import hashlib

from .bundle import Bundle, stable_id_bytes, validate_local_update
from .lineage_policy import (
    CellRoster,
    LineagePolicyError,
    UpdateEvidence,
    review_update,
)


_PARTITION_KEYS = ("principal_id", "agent_id", "cell_id", "run_id")


@dataclass(frozen=True)
class NativeBundleClaimReview:
    status: str
    source_bundle_digest: str
    candidate_bundle_digest: str
    state_partition_digest: str
    original_state_owner_claim: str
    missing: tuple[str, ...]
    original_owner_authenticated: bool = False
    independent_signature_authenticated: bool = False
    adoption_authorized: bool = False


def review_native_bundle_claims(
    roster: CellRoster,
    evidence: UpdateEvidence,
    source: Bundle,
    candidate: Bundle,
    state_partition: dict[str, str],
) -> NativeBundleClaimReview:
    """Cross-check exact native wire claims; never admit or publish a candidate.

    A source/candidate Bundle can be supplied by an untrusted caller. Matching
    their canonical wire hashes is only an internal consistency check; an actual
    artifacts owner must authenticate the source/model/data bytes, a Cell state
    owner must confirm the partition and generation, and the original evaluator
    must authenticate its signatures. This function performs none of those acts.
    """
    if not isinstance(source, Bundle) or not isinstance(candidate, Bundle):
        raise LineagePolicyError("native-compatible source and candidate Bundle required")
    if type(state_partition) is not dict or set(state_partition) != set(_PARTITION_KEYS):
        raise LineagePolicyError("complete native CellStatePartitionV1 required")

    # review_update already bounds generation, changed component scope, costs,
    # missing receipts and source/evaluator declarations; it never grants Adopt.
    review = review_update(roster, evidence)
    cell = roster.cell(evidence.partition)
    if tuple(state_partition[k] for k in _PARTITION_KEYS) != cell.partition:
        raise LineagePolicyError("native state partition differs from enrolled Cell")

    try:
        state_bytes = b"hepta.cell.state-partition.v1\0" + b"".join(
            stable_id_bytes(state_partition[k]) for k in _PARTITION_KEYS
        )
        state_digest = hashlib.sha256(state_bytes).hexdigest()
        source_digest, candidate_digest = source.digest(), candidate.digest()
        # Reuse the already-existing native-mirror component/update check rather
        # than defining a second policy or producer-side adoption path.
        validated_candidate = validate_local_update(
            cell.kernel, source, candidate, cell.trainable_scope
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise LineagePolicyError("invalid original native bundle or partition claim") from error

    if (
        source_digest != cell.bundle_digest
        or source_digest != evidence.source_bundle
        or candidate_digest != evidence.candidate_bundle
        or validated_candidate != candidate_digest
        or source.generation != cell.generation
        or candidate.generation != evidence.candidate_generation
        or source.components != asdict(cell.components)
        or candidate.components != asdict(evidence.candidate_components)
    ):
        raise LineagePolicyError("native Bundle bytes disagree with frozen lineage declarations")

    # The original bundle wire *includes* these fields. Requiring their equality
    # prevents re-labeling a candidate trained on another dataset or profile.
    if candidate.training_lineage != {
        "source_bundle": source_digest,
        "dataset": evidence.dataset_digest,
        "update_rule": cell.update_rule,
        "evaluation_profile": cell.evaluation_profile,
    }:
        raise LineagePolicyError("candidate native training lineage disagrees with frozen evidence")

    return NativeBundleClaimReview(
        status=review.status,
        source_bundle_digest=source_digest,
        candidate_bundle_digest=candidate_digest,
        state_partition_digest=state_digest,
        original_state_owner_claim=cell.state_owner,
        missing=tuple(review.reasons) + (
            "original native state owner and Bundle artifact custody authentication",
            "original independent evaluator signature and held-out source authentication",
            "full-cost measured net benefit, old-task retention and cold owner recovery",
        ),
    )
