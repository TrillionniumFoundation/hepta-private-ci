//! Product-side composition for governed plasticity proposal persistence.
//!
//! This adapter is deliberately proposal-only. It provides a preparation phase
//! that generates the exact content-addressed candidate set to sign/evaluate,
//! followed by final authenticated admission, durable proposal persistence and
//! durable external-anchor acknowledgement. Product success is not returned
//! until the host anchor store confirms the current registry head.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::{
    DatasetSnapshotReceiptV3, LearningEvidenceVerifierV1, SignedLearningEvidenceV1,
};
use codex_hepta_plasticity::{
    AppendDisposition, DurableProposalAppendReceiptV1, DurableRegistryAnchorV1,
    GovernedParameterPreparationV3, GovernedParameterProposalRequestV3,
    GovernedParameterProposalV3, GovernedProposalError, ParameterEvidenceBindingV3,
    ParameterGenerationPolicyV3, PlasticityEvidencePortV3, ProductionProposalRegistry,
    ProductionProposalRegistryError, prepare_governed_parameter_candidates_v3,
    propose_governed_v3,
};
use codex_hepta_types::{Digest32, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityAnchorPersistenceRequestV1 {
    pub registry_scope_digest: Digest32,
    pub writer_fence: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub proposal_sequence: u64,
    pub proposal_frame_digest: Digest32,
    pub disposition: AppendDisposition,
    pub previous_anchor: Option<DurableRegistryAnchorV1>,
    pub next_anchor: DurableRegistryAnchorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityAnchorPersistenceReceiptV1 {
    /// Digest of the exact persistence request acknowledged by the host store.
    pub request_digest: Digest32,
    /// Exact registry head durably retained outside the proposal-file rollback domain.
    pub persisted_anchor: DurableRegistryAnchorV1,
    /// Non-zero receipt from the independently durable anchor store.
    pub store_receipt_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityAnchorStoreErrorV1 {
    Unavailable,
    Rejected,
    Indeterminate,
    InvalidReceipt,
}

impl fmt::Display for PlasticityAnchorStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityAnchorStoreErrorV1 {}

/// Host-owned persistence boundary for anti-rollback anchors.
///
/// Implementations MUST place `next_anchor` in a trust/durability domain that
/// cannot be rolled back by replacing the proposal registry file. Returning a
/// receipt before that durability boundary is crossed violates this contract.
pub trait PlasticityAnchorStoreV1 {
    fn persist(
        &self,
        request: &PlasticityAnchorPersistenceRequestV1,
    ) -> Result<PlasticityAnchorPersistenceReceiptV1, PlasticityAnchorStoreErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableGovernedPlasticityReceiptV3 {
    pub governed: GovernedParameterProposalV3,
    pub durable: DurableProposalAppendReceiptV1,
    pub next_anchor: DurableRegistryAnchorV1,
    /// Proof that the exact current head crossed the independent anchor durability boundary.
    pub anchor_persistence: PlasticityAnchorPersistenceReceiptV1,
}

#[derive(Debug)]
pub enum PlasticityHostErrorV3 {
    Governed(GovernedProposalError),
    Durable(ProductionProposalRegistryError),
    AnchorReceiptMismatch,
    AnchorPersistence(PlasticityAnchorStoreErrorV1),
}

impl fmt::Display for PlasticityHostErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityHostErrorV3 {}
impl From<GovernedProposalError> for PlasticityHostErrorV3 {
    fn from(value: GovernedProposalError) -> Self {
        Self::Governed(value)
    }
}
impl From<ProductionProposalRegistryError> for PlasticityHostErrorV3 {
    fn from(value: ProductionProposalRegistryError) -> Self {
        Self::Durable(value)
    }
}
impl From<PlasticityAnchorStoreErrorV1> for PlasticityHostErrorV3 {
    fn from(value: PlasticityAnchorStoreErrorV1) -> Self {
        Self::AnchorPersistence(value)
    }
}

/// Canonical digest the independent anchor store must echo in its receipt.
pub fn plasticity_anchor_persistence_request_digest_v1(
    request: &PlasticityAnchorPersistenceRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.plasticity-anchor-persistence.v1\0".to_vec();
    bytes.extend_from_slice(request.registry_scope_digest.as_array());
    bytes.extend_from_slice(&request.writer_fence.to_be_bytes());
    push_id(&mut bytes, &request.proposal_id);
    bytes.extend_from_slice(request.proposal_digest.as_array());
    bytes.extend_from_slice(&request.proposal_sequence.to_be_bytes());
    bytes.extend_from_slice(request.proposal_frame_digest.as_array());
    bytes.push(match request.disposition {
        AppendDisposition::Inserted => 0,
        AppendDisposition::Unchanged => 1,
    });
    push_anchor(&mut bytes, request.previous_anchor);
    push_anchor(&mut bytes, Some(request.next_anchor));
    Digest32::of_bytes(&bytes)
}

/// Prepare the exact candidate set that the generator signs and the independent
/// evaluator evaluates. Final persistence recomputes the same state and fails
/// closed if owner evidence, artifact state, trust context or generated bytes
/// drift between preparation and finalization.
pub fn prepare_plasticity_v3(
    binding: &ParameterEvidenceBindingV3,
    policy: &ParameterGenerationPolicyV3,
    source_evidence: &SignedLearningEvidenceV1,
    dataset: &DatasetSnapshotReceiptV3,
    verifier: &LearningEvidenceVerifierV1,
    artifacts: &ArtifactRegistry,
    evidence_port: &dyn PlasticityEvidencePortV3,
    now: u64,
) -> Result<GovernedParameterPreparationV3, PlasticityHostErrorV3> {
    prepare_governed_parameter_candidates_v3(
        binding,
        policy,
        source_evidence,
        dataset,
        verifier,
        artifacts,
        evidence_port,
        now,
    )
    .map_err(Into::into)
}

/// Construct, durably append and independently acknowledge one governed proposal.
///
/// `evidence_port` must resolve every update-rule/modulator/eligibility/parameter
/// evidence digest against its authoritative owner store; there is no no-op
/// production path. `anchor_store` must durably retain the resulting current head
/// outside the proposal-file rollback domain. If anchor persistence fails after
/// the file append, this function returns an error rather than product success;
/// recovery starts from the last externally acknowledged anchor and reconciles
/// the valid later file prefix. This function never activates, selects, promotes,
/// releases, or installs the proposal.
pub fn propose_and_persist_plasticity_v3(
    request: GovernedParameterProposalRequestV3<'_>,
    verifier: &LearningEvidenceVerifierV1,
    artifacts: &ArtifactRegistry,
    evidence_port: &dyn PlasticityEvidencePortV3,
    registry: &mut ProductionProposalRegistry,
    anchor_store: &dyn PlasticityAnchorStoreV1,
    expected_predecessor_frame_digest: Digest32,
    now: u64,
) -> Result<DurableGovernedPlasticityReceiptV3, PlasticityHostErrorV3> {
    let previous_anchor = registry.current_anchor()?;
    let governed = propose_governed_v3(request, verifier, artifacts, evidence_port, now)?;
    let durable = registry.append_v2(
        expected_predecessor_frame_digest,
        governed.proposal.clone(),
    )?;
    let next_anchor = registry.acknowledged_anchor_after_append()?;

    match durable.disposition {
        AppendDisposition::Inserted => {
            if next_anchor.sequence != durable.sequence
                || next_anchor.frame_digest != durable.frame_digest
            {
                return Err(PlasticityHostErrorV3::AnchorReceiptMismatch);
            }
        }
        AppendDisposition::Unchanged => {
            if next_anchor.sequence < durable.sequence
                || (next_anchor.sequence == durable.sequence
                    && next_anchor.frame_digest != durable.frame_digest)
            {
                return Err(PlasticityHostErrorV3::AnchorReceiptMismatch);
            }
        }
    }

    let persistence_request = PlasticityAnchorPersistenceRequestV1 {
        registry_scope_digest: durable.registry_scope_digest,
        writer_fence: durable.writer_fence,
        proposal_id: durable.proposal_id.clone(),
        proposal_digest: durable.proposal_digest,
        proposal_sequence: durable.sequence,
        proposal_frame_digest: durable.frame_digest,
        disposition: durable.disposition,
        previous_anchor,
        next_anchor,
    };
    let request_digest = plasticity_anchor_persistence_request_digest_v1(&persistence_request);
    let anchor_persistence = anchor_store.persist(&persistence_request)?;
    if anchor_persistence.request_digest != request_digest
        || anchor_persistence.persisted_anchor != next_anchor
        || anchor_persistence.store_receipt_digest.is_zero()
    {
        return Err(PlasticityHostErrorV3::AnchorPersistence(
            PlasticityAnchorStoreErrorV1::InvalidReceipt,
        ));
    }

    Ok(DurableGovernedPlasticityReceiptV3 {
        governed,
        durable,
        next_anchor,
        anchor_persistence,
    })
}

fn push_anchor(bytes: &mut Vec<u8>, anchor: Option<DurableRegistryAnchorV1>) {
    match anchor {
        Some(anchor) => {
            bytes.push(1);
            bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
            bytes.extend_from_slice(anchor.frame_digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
