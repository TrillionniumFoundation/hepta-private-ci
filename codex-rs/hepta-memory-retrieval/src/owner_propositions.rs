//! Additive owner projection for multiple explicit assertions per exact record.
//! V1 inputs and preimages stay intact. These are integrity-bound data, not
//! source authentication: the caller must obtain the claims from its same cut.
use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::ContradictionEvidenceV2;
use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::GeneratorErrorV1;
use crate::MemoryCueV1;
use crate::RecallWorkControlV1;
use crate::RetrievalAssignmentObservationV1;
use crate::RetrievalPolicyV1;
use crate::product::ProductGeneratedRecallV1;
use crate::product::ProductRecallErrorV1;
use crate::product::ValidatedCandidateSetV1;

const MAX_OWNER_PROPOSITION_EVIDENCE: usize = 4096;

/// One explicit source-owned assertion, including its original support. No
/// polarity is inferred from record text, relation labels or conflict reports.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct OwnerPropositionEvidenceV2 {
    record_id: StableId,
    revision: Revision,
    record_digest: Digest32,
    claim: ContradictionEvidenceV2,
    source_evidence_digest: Digest32,
}
impl OwnerPropositionEvidenceV2 {
    pub fn new(
        record_id: StableId,
        revision: Revision,
        record_digest: Digest32,
        claim: ContradictionEvidenceV2,
        source_evidence_digest: Digest32,
    ) -> Result<Self, GeneratorErrorV1> {
        if record_digest.is_zero() || source_evidence_digest.is_zero() {
            return Err(GeneratorErrorV1::InvalidRecord(
                "empty owner proposition support".into(),
            ));
        }
        Ok(Self {
            record_id,
            revision,
            record_digest,
            claim,
            source_evidence_digest,
        })
    }
}

/// Semantic admission after the original HNMF assignment. This sealed V2
/// result binds every explicit claim without rewriting any V1 packet/preimage.
/// It is data integrity, not source authenticity or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerPropositionDecisionV2 {
    disposition: crate::RecallDispositionV1,
    selected: Vec<crate::RetrievalCandidateIdentityV1>,
    conflicts: Vec<Digest32>,
    evidence_digest: Digest32,
    policy_digest: Digest32,
    binding_digest: Digest32,
}
impl OwnerPropositionDecisionV2 {
    pub fn disposition(&self) -> crate::RecallDispositionV1 {
        self.disposition
    }
    pub fn selected_candidates(&self) -> &[crate::RetrievalCandidateIdentityV1] {
        &self.selected
    }
    pub fn conflict_digests(&self) -> &[Digest32] {
        &self.conflicts
    }
    pub fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }
    pub fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }
    pub fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRecallWithPropositionsV2 {
    pub product: ProductGeneratedRecallV1,
    pub assignment: Option<RetrievalAssignmentObservationV1>,
    pub semantic: Option<OwnerPropositionDecisionV2>,
}

/// Preserve the original HNMF/V1 assignment, then admit the complete explicit
/// owner assertion set against the same legal policy union. The final V2
/// selected set is recorded as downstream delivery, never a forged V1 action.
pub fn recall_product_with_owner_propositions_v2(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: &ValidatedCandidateSetV1,
    propositions: &[OwnerPropositionEvidenceV2],
    snapshot: &EngramSnapshotV1,
    dynamics: &EngramDynamicsPolicyV1,
    work: &RecallWorkControlV1,
) -> Result<ProductRecallWithPropositionsV2, ProductRecallErrorV1> {
    let failure =
        |message: String| ProductRecallErrorV1::Generator(GeneratorErrorV1::InvalidRecord(message));
    work.checkpoint().map_err(|e| failure(e.to_string()))?;
    if propositions.len() > MAX_OWNER_PROPOSITION_EVIDENCE {
        return Err(failure("owner proposition bound exceeded".into()));
    }
    let input = candidates.input();
    let observed = input
        .flattened_candidates()
        .map_err(ProductRecallErrorV1::Generator)?
        .into_iter()
        .map(|c| {
            (
                (c.record.record_id.clone(), c.record.revision),
                c.record.record_digest(),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let mut distinct = BTreeSet::new();
    for evidence in propositions {
        work.checkpoint().map_err(|e| failure(e.to_string()))?;
        evidence
            .claim
            .validate(cue.snapshot_key.vector_digest)
            .map_err(|e| failure(e.to_string()))?;
        if observed.get(&(evidence.record_id.clone(), evidence.revision))
            != Some(&evidence.record_digest)
            || !distinct.insert(evidence)
        {
            return Err(failure(
                "owner proposition revision/support is absent, conflicting or duplicate".into(),
            ));
        }
    }
    let product = crate::product::recall_product_with_engram_v1(
        cue, policy, candidates, snapshot, dynamics, work,
    )?;
    let Some(recall) = &product.recall else {
        return Ok(ProductRecallWithPropositionsV2 {
            product,
            assignment: None,
            semantic: None,
        });
    };
    let assignment = crate::observe_retrieval_assignment(cue, policy, input, recall)
        .map_err(|e| failure(e.to_string()))?;
    let union = crate::build_candidate_union_from_generated(cue, policy, input)
        .map_err(ProductRecallErrorV1::Generator)?;
    let admitted = crate::semantics::policy_admitted_union(&union.union, policy)
        .map_err(|e| failure(e.to_string()))?;
    let admitted = admitted
        .entries
        .iter()
        .map(|entry| (entry.record.record_id.clone(), entry.record.revision))
        .collect::<BTreeSet<_>>();
    let mut masks = BTreeMap::<Digest32, u8>::new();
    let mut evidence_bytes = b"hepta.retrieval.owner-propositions-evidence.v2".to_vec();
    evidence_bytes.extend_from_slice(
        &u64::try_from(distinct.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for evidence in distinct {
        work.checkpoint().map_err(|e| failure(e.to_string()))?;
        let id = evidence.record_id.as_str().as_bytes();
        evidence_bytes
            .extend_from_slice(&u64::try_from(id.len()).unwrap_or(u64::MAX).to_be_bytes());
        evidence_bytes.extend_from_slice(id);
        evidence_bytes.extend_from_slice(&evidence.revision.get().to_be_bytes());
        for digest in [
            evidence.record_digest,
            evidence.claim.digest(),
            evidence.source_evidence_digest,
        ] {
            evidence_bytes.extend_from_slice(digest.as_array());
        }
        if admitted.contains(&(evidence.record_id.clone(), evidence.revision)) {
            let mask = match evidence.claim.polarity() {
                crate::PropositionPolarityV2::Affirmed => 1,
                crate::PropositionPolarityV2::Denied => 2,
                crate::PropositionPolarityV2::ConflictReported => 0,
            };
            *masks
                .entry(evidence.claim.proposition_digest())
                .or_default() |= mask;
        }
    }
    let conflicts = masks
        .into_iter()
        .filter_map(|(digest, mask)| (mask == 3).then_some(digest))
        .collect::<Vec<_>>();
    let veto = !conflicts.is_empty()
        && (policy.abstain_on_contradiction || dynamics.contradiction_forces_abstention);
    let disposition = if veto {
        crate::RecallDispositionV1::Abstained(
            crate::RecallAbstentionReasonV1::ContradictoryEvidence,
        )
    } else {
        recall.packet.disposition
    };
    let selected = if veto {
        Vec::new()
    } else {
        // Keep the original HNMF ranking; the assignment's canonical set is
        // sorted by identity for hashing and is not a delivery order.
        recall
            .packet
            .selections
            .iter()
            .map(|entry| crate::RetrievalCandidateIdentityV1 {
                record_id: entry.record_id.clone(),
                record_revision: entry.record_revision,
                record_digest: entry.record_digest,
            })
            .collect()
    };
    let evidence_digest = Digest32::of_bytes(&evidence_bytes);
    let mut policy_bytes = b"hepta.retrieval.owner-propositions-policy.v2".to_vec();
    policy_bytes.extend_from_slice(policy.digest().as_array());
    policy_bytes.push(u8::from(dynamics.contradiction_forces_abstention));
    let policy_digest = Digest32::of_bytes(&policy_bytes);
    let mut binding = b"hepta.retrieval.owner-propositions-decision.v2".to_vec();
    for digest in [
        assignment.observation_digest,
        recall.receipt_digest,
        evidence_digest,
        policy_digest,
    ] {
        binding.extend_from_slice(digest.as_array());
    }
    binding.push(u8::from(veto));
    work.checkpoint().map_err(|e| failure(e.to_string()))?;
    let semantic = OwnerPropositionDecisionV2 {
        disposition,
        selected,
        conflicts,
        evidence_digest,
        policy_digest,
        binding_digest: Digest32::of_bytes(&binding),
    };
    Ok(ProductRecallWithPropositionsV2 {
        product,
        assignment: Some(assignment),
        semantic: Some(semantic),
    })
}

#[cfg(test)]
#[path = "owner_propositions_tests.rs"]
mod tests;
