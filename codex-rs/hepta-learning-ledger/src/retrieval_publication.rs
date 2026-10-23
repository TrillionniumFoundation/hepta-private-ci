//! Two-stage owner-native retrieval publication. Intent is durable before a
//! response is written; confirmation records only a host-observed full write.
//! Missing confirmation is unknown, including after recovery. Neither stage
//! proves peer receipt, model attachment, or current memory-source eligibility.

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;

/// Native publication profile, owned here without an Agentd dependency. A future
/// wire schema requires an explicitly admitted profile, never numeric fallback.
pub const RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2: u32 = 2;
pub const RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2: u32 = 64 * 1024;
pub(crate) const MAX_CANDIDATES: usize = 512;
pub(crate) const MAX_SELECTED: usize = 16;

/// Immutable plan for one Agentd Unix-control CognitiveContext response.
/// The V2 identity binds the complete canonical plan, including owner/body/request
/// correlation, frame and causal observation. Request counters are client-local.
/// Equal complete plans deduplicate; this is not a count of physical writes.
/// Legacy tag-9 identities keep their original meaning.
/// An active intent remains a plan; publication consumers must use the linked
/// projection rather than interpreting generic ledger activity as exposure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalAssignmentIntentV2 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub owner_id: StableId,
    pub body_generation: u64,
    pub request_id: u64,
    pub control_schema_version: u32,
    /// Exact bounded serialized success response including its newline.
    pub response_frame_digest: Digest32,
    pub response_frame_bytes: u32,
    /// Exact serialized snapshot, including when its item set is empty.
    pub snapshot_digest: Digest32,
    pub cue_digest: Digest32,
    pub policy_digest: Digest32,
    pub source_completeness_digest: Digest32,
    pub candidate_union_digest: Digest32,
    pub recall_packet_digest: Digest32,
    pub enumerated_candidate_digests: Vec<Digest32>,
    pub legal_candidate_indices: Vec<u32>,
    pub selected_candidate_indices: Vec<u32>,
    /// Planned subset only. It is not an assertion of exposure or delivery.
    pub planned_candidate_indices: Vec<u32>,
    pub omitted_by_policy_limits: u32,
    pub assignment_propensity: ProbabilityQ32,
    pub downstream_policy_digest: Option<Digest32>,
    pub delivery_propensity: ProbabilityQ32,
    pub completeness: CandidateSetCompleteness,
    pub support_digest: Digest32,
}

/// HostTransportWriteCompleted for the exact previously committed intent.
/// The trusted host may create this only after its full frame write succeeds.
/// Ledger linkage validates content, not the physical transport observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalPublicationConfirmedV2 {
    pub record_id: StableId,
    pub intent_record_id: StableId,
    pub intent_event_digest: Digest32,
    pub response_frame_digest: Digest32,
    pub response_frame_bytes: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalPublicationStateV2 {
    /// Original immutable tag-9 assertion; never upgraded to confirmation.
    LegacyOwnerAsserted,
    /// No host full-write confirmation. This is not non-exposure or zero reward.
    Unknown,
    HostTransportWriteCompleted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalPublicationProjectionV2 {
    pub assignment_record_id: StableId,
    pub state: RetrievalPublicationStateV2,
    pub intent_event_digest: Option<Digest32>,
    pub confirmation_event_digest: Option<Digest32>,
    /// Current confirmed V2 ledger lineage only. Unknown and legacy are false.
    /// Memory sources and model attachment require
    /// their respective owners' independent currentness/evidence checks.
    pub ledger_lineage_active: bool,
}

/// Content identity of the complete canonical intent excluding record_id itself.
/// Different causal assignments may serialize the same response, and different
/// clients may reuse a request counter, so neither alone is a durable identity.
pub fn retrieval_assignment_record_id_v2(
    intent: &RetrievalAssignmentIntentV2,
) -> Result<StableId, LedgerError> {
    crate::retrieval_publication_validation::check_candidate_limits(intent)?;
    let mut canonical = intent.clone();
    crate::retrieval_publication_validation::normalize_intent(&mut canonical)?;
    let mut bytes = b"hepta.agentd.retrieval-assignment-intent.v2".to_vec();
    crate::retrieval_publication_codec::encode_intent_body(&mut bytes, &canonical);
    StableId::new(format!("retrieval-intent:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| LedgerError::RetrievalPublicationBindingMismatch)
}

pub(crate) fn episode_id(
    owner_id: &StableId,
    body_generation: u64,
    request_id: u64,
) -> Result<StableId, LedgerError> {
    StableId::new(format!(
        "retrieval-episode:{}:{body_generation}:{request_id}",
        owner_id.as_str()
    ))
    .map_err(|_| LedgerError::RetrievalPublicationBindingMismatch)
}

pub(crate) fn confirmation_record_id(
    intent_record_id: &StableId,
    intent_event_digest: Digest32,
) -> Result<StableId, LedgerError> {
    let mut bytes = b"hepta.learning.retrieval-publication-confirmed.v2".to_vec();
    let id = intent_record_id.as_str().as_bytes();
    let length = u64::try_from(id.len()).map_err(|_| LedgerError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(intent_event_digest.as_array());
    StableId::new(format!(
        "retrieval-confirmed:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| LedgerError::RetrievalPublicationBindingMismatch)
}

/// Build a linked confirmation from the canonical append receipt's event digest.
/// This constructor does not itself observe a transport or grant admission.
pub fn retrieval_publication_confirmation_v2(
    intent: &RetrievalAssignmentIntentV2,
    intent_event_digest: Digest32,
) -> Result<RetrievalPublicationConfirmedV2, LedgerError> {
    if intent_event_digest.is_zero() {
        return Err(LedgerError::EmptyDigest("retrieval intent event"));
    }
    Ok(RetrievalPublicationConfirmedV2 {
        record_id: confirmation_record_id(&intent.record_id, intent_event_digest)?,
        intent_record_id: intent.record_id.clone(),
        intent_event_digest,
        response_frame_digest: intent.response_frame_digest,
        response_frame_bytes: intent.response_frame_bytes,
    })
}

impl LearningLedger {
    /// Historical publication state remains truthful after revocation. The
    /// separate activity flag prevents it from resurrecting eligible lineage.
    /// Lookup is bounded through the existing replay-built identity index.
    pub fn retrieval_publication(
        &self,
        assignment_record_id: &StableId,
    ) -> Result<Option<RetrievalPublicationProjectionV2>, LedgerError> {
        let Some(record) = self.record_by_id(assignment_record_id)? else {
            return Ok(None);
        };
        let active = self.active_record_by_id(assignment_record_id)?.is_some();
        let intent = match &record.event {
            LedgerEvent::RetrievalAssignment(_) => {
                return Ok(Some(RetrievalPublicationProjectionV2 {
                    assignment_record_id: assignment_record_id.clone(),
                    state: RetrievalPublicationStateV2::LegacyOwnerAsserted,
                    intent_event_digest: None,
                    confirmation_event_digest: None,
                    ledger_lineage_active: false,
                }));
            }
            LedgerEvent::RetrievalAssignmentIntentV2(value) => value,
            _ => return Err(LedgerError::RetrievalPublicationIntentRequired),
        };
        let confirmed_id = confirmation_record_id(&intent.record_id, record.event_digest)?;
        let confirmed = self.record_by_id(&confirmed_id)?;
        if let Some(confirmed) = confirmed {
            let LedgerEvent::RetrievalPublicationConfirmedV2(value) = &confirmed.event else {
                return Err(LedgerError::RetrievalPublicationBindingMismatch);
            };
            crate::retrieval_publication_validation::validate_confirmation(self, value)?;
        }
        Ok(Some(RetrievalPublicationProjectionV2 {
            assignment_record_id: assignment_record_id.clone(),
            state: if confirmed.is_some() {
                RetrievalPublicationStateV2::HostTransportWriteCompleted
            } else {
                RetrievalPublicationStateV2::Unknown
            },
            intent_event_digest: Some(record.event_digest),
            confirmation_event_digest: confirmed.map(|value| value.event_digest),
            ledger_lineage_active: active
                && confirmed.is_some()
                && self.active_record_by_id(&confirmed_id)?.is_some(),
        }))
    }
}

#[cfg(test)]
#[path = "retrieval_publication_tests.rs"]
pub(crate) mod tests;
