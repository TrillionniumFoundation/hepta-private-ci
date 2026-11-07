//! Bind a shared-worker BP result to the existing fenced candidate publisher.
//!
//! These checks establish identity and payload consistency. A worker receipt is
//! not a proof of correct derivatives, independent evaluation, or NDU gain. The
//! host must obtain `expected` from its admitted job, not from worker output.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactKind;
use crate::ArtifactPublicationReceiptV1;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::ProvenanceModeV1;

const HANDOFF_MAGIC: &[u8] = b"hepta.hcsn.task-bp-handoff.v1\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnLearningRuleV1 {
    TaskLossBackpropagation,
    EligibilityModulation,
    NduCredit,
}

/// Immutable job facts retained by the caller before dispatching one worker.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnTrainingBindingV1 {
    pub operation_id: StableId,
    /// Binds scope, owner/writer/clock epochs, inputs, targets and resource cap.
    pub request_digest: Digest32,
    pub training_code_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub graph_digest: Digest32,
    pub time_profile_digest: Digest32,
    pub base_checkpoint_digest: Digest32,
    pub dataset_digest: Digest32,
    pub target_generation: Generation,
    pub optimizer_steps: u64,
    pub logical_cells: u32,
    pub trainable_parameters: u64,
}

/// Result of a pinned worker, kept separate from credit or local plasticity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnTrainingOutcomeV1 {
    pub binding: HcsnTrainingBindingV1,
    pub rule: HcsnLearningRuleV1,
    pub candidate_digest: Digest32,
    pub gradient_digest: Digest32,
    /// Hash of the complete immutable worker receipt, including costs/failures.
    pub receipt_digest: Digest32,
    pub completed_optimizer_steps: u64,
    pub gradient_parameters: u64,
    pub gradient_cells: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnCandidateErrorV1 {
    InvalidHandoff,
    InvalidBinding,
    RequestMismatch,
    LearningRuleMismatch,
    IncompleteBackpropagation,
    PayloadMismatch,
    ManifestMismatch,
    MissingLineage,
}

impl std::fmt::Display for HcsnCandidateErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "HCSN candidate rejected: {self:?}")
    }
}

impl std::error::Error for HcsnCandidateErrorV1 {}

/// A checked handoff; publication still revalidates the signed owner lease,
/// withdrawal frontier, predecessor registry and immutable payload on disk.
#[derive(Clone, Debug)]
pub struct PreparedHcsnPublicationV1 {
    request: LearningArtifactPublishRequestV1,
}

impl PreparedHcsnPublicationV1 {
    pub fn publish(
        self,
        owner: &mut LearningArtifactOwnerService,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        owner.publish(self.request)
    }
}

pub fn prepare_hcsn_publication_v1(
    expected: &HcsnTrainingBindingV1,
    handoff_bytes: &[u8],
    receipt_bytes: &[u8],
    request: LearningArtifactPublishRequestV1,
) -> Result<PreparedHcsnPublicationV1, HcsnCandidateErrorV1> {
    let outcome = decode_hcsn_handoff_v1(&expected.operation_id, handoff_bytes)?;
    if expected.optimizer_steps == 0
        || !(2..=16).contains(&expected.logical_cells)
        || expected.trainable_parameters == 0
        || [
            expected.request_digest,
            expected.training_code_digest,
            expected.runtime_tuple_digest,
            expected.graph_digest,
            expected.time_profile_digest,
            expected.base_checkpoint_digest,
            expected.dataset_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(HcsnCandidateErrorV1::InvalidBinding);
    }
    if outcome.binding != *expected || request.operation_id != expected.operation_id {
        return Err(HcsnCandidateErrorV1::RequestMismatch);
    }
    if outcome.rule != HcsnLearningRuleV1::TaskLossBackpropagation {
        return Err(HcsnCandidateErrorV1::LearningRuleMismatch);
    }
    if outcome.completed_optimizer_steps != expected.optimizer_steps
        || outcome.gradient_parameters != expected.trainable_parameters
        || outcome.gradient_cells != expected.logical_cells
        || outcome.gradient_digest.is_zero()
        || receipt_bytes.is_empty()
        || receipt_bytes.len() > 1024 * 1024
        || Digest32::of_bytes(receipt_bytes) != outcome.receipt_digest
    {
        return Err(HcsnCandidateErrorV1::IncompleteBackpropagation);
    }
    let manifest = &request.admission.validated_manifest.manifest;
    if request.payload.is_empty()
        || request.payload.len() > 64 * 1024 * 1024
        || Digest32::of_bytes(&request.payload) != outcome.candidate_digest
        || manifest.bytes_digest != outcome.candidate_digest
        || manifest.encoded_size_bytes != request.payload.len() as u64
    {
        return Err(HcsnCandidateErrorV1::PayloadMismatch);
    }
    if !matches!(
        manifest.kind,
        ArtifactKind::Model | ArtifactKind::Parameters
    ) || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
        || manifest.generation != expected.target_generation
        || manifest.training_code_digest != expected.training_code_digest
        || manifest.runtime_tuple_digest != expected.runtime_tuple_digest
        || manifest.source_dataset_digests != vec![expected.dataset_digest]
    {
        return Err(HcsnCandidateErrorV1::ManifestMismatch);
    }
    if [
        expected.request_digest,
        expected.graph_digest,
        expected.time_profile_digest,
        expected.base_checkpoint_digest,
        outcome.gradient_digest,
        outcome.receipt_digest,
        Digest32::of_bytes(handoff_bytes),
    ]
    .iter()
    .any(|digest| !manifest.lineage_digests.contains(digest))
    {
        return Err(HcsnCandidateErrorV1::MissingLineage);
    }
    Ok(PreparedHcsnPublicationV1 { request })
}

/// Decode the authoritative fixed-width BP handoff. The separately hashed JSON
/// contains diagnostics; callers cannot substitute hand-entered outcome fields.
pub fn decode_hcsn_handoff_v1(
    operation_id: &StableId,
    bytes: &[u8],
) -> Result<HcsnTrainingOutcomeV1, HcsnCandidateErrorV1> {
    if bytes.len() != HANDOFF_MAGIC.len() + 1 + 11 * 32 + 7 * 8 || !bytes.starts_with(HANDOFF_MAGIC)
    {
        return Err(HcsnCandidateErrorV1::InvalidHandoff);
    }
    let rule = match bytes[HANDOFF_MAGIC.len()] {
        0 => HcsnLearningRuleV1::TaskLossBackpropagation,
        1 => HcsnLearningRuleV1::EligibilityModulation,
        2 => HcsnLearningRuleV1::NduCredit,
        _ => return Err(HcsnCandidateErrorV1::InvalidHandoff),
    };
    let mut digests = [Digest32::ZERO; 11];
    let offset = HANDOFF_MAGIC.len() + 1;
    for (index, value) in digests.iter_mut().enumerate() {
        let mut raw = [0; 32];
        raw.copy_from_slice(&bytes[offset + index * 32..offset + (index + 1) * 32]);
        *value = Digest32::from_array(raw);
    }
    if digests[0] != Digest32::of_bytes(operation_id.as_str().as_bytes()) {
        return Err(HcsnCandidateErrorV1::RequestMismatch);
    }
    let mut counts = [0_u64; 7];
    let offset = offset + 11 * 32;
    for (index, value) in counts.iter_mut().enumerate() {
        let mut raw = [0; 8];
        raw.copy_from_slice(&bytes[offset + index * 8..offset + (index + 1) * 8]);
        *value = u64::from_be_bytes(raw);
    }
    Ok(HcsnTrainingOutcomeV1 {
        binding: HcsnTrainingBindingV1 {
            operation_id: operation_id.clone(),
            request_digest: digests[1],
            training_code_digest: digests[2],
            runtime_tuple_digest: digests[3],
            graph_digest: digests[4],
            time_profile_digest: digests[5],
            base_checkpoint_digest: digests[6],
            dataset_digest: digests[7],
            target_generation: Generation::new(counts[0])
                .map_err(|_| HcsnCandidateErrorV1::InvalidHandoff)?,
            optimizer_steps: counts[1],
            logical_cells: counts[2]
                .try_into()
                .map_err(|_| HcsnCandidateErrorV1::InvalidHandoff)?,
            trainable_parameters: counts[3],
        },
        rule,
        candidate_digest: digests[8],
        gradient_digest: digests[9],
        receipt_digest: digests[10],
        completed_optimizer_steps: counts[4],
        gradient_cells: counts[5]
            .try_into()
            .map_err(|_| HcsnCandidateErrorV1::InvalidHandoff)?,
        gradient_parameters: counts[6],
    })
}

#[cfg(test)]
#[path = "hcsn_candidate_tests.rs"]
mod tests;
