//! Owner bridge from memory.retrieval assignment evidence into the durable
//! learning-ledger event model.
//!
//! The bridge preserves the retrieval-native observation digest as support and
//! compresses exact candidate identities to domain-separated 32-byte digests.
//! It grants no authority and does not append by itself.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::LedgerEvent;
use crate::RetrievalAssignmentFact;

const CANDIDATE_IDENTITY_DOMAIN: &[u8] = b"hepta.learning.retrieval-candidate.v1";
const MAX_RETRIEVAL_CANDIDATES: usize = 512;

pub fn retrieval_assignment_event(
    record_id: StableId,
    episode_id: StableId,
    observation: &RetrievalAssignmentObservationV1,
) -> Result<LedgerEvent, RetrievalAssignmentBridgeError> {
    retrieval_assignment_event_with_delivery(
        record_id,
        episode_id,
        observation,
        &observation.selected_candidates,
        !observation.selected_candidates.is_empty(),
    )
}

pub fn retrieval_assignment_event_with_delivery(
    record_id: StableId,
    episode_id: StableId,
    observation: &RetrievalAssignmentObservationV1,
    delivered_candidates: &[RetrievalCandidateIdentityV1],
    context_exposed: bool,
) -> Result<LedgerEvent, RetrievalAssignmentBridgeError> {
    observation
        .validate()
        .map_err(|error| RetrievalAssignmentBridgeError::InvalidObservation(error.to_string()))?;
    if observation.enumerated_candidates.len() > MAX_RETRIEVAL_CANDIDATES {
        return Err(RetrievalAssignmentBridgeError::CandidateLimitExceeded);
    }

    let mut enumerated = observation
        .enumerated_candidates
        .iter()
        .map(candidate_identity_digest)
        .collect::<Vec<_>>();
    enumerated.sort();
    if enumerated.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(RetrievalAssignmentBridgeError::CandidateDigestCollision);
    }
    let index = enumerated
        .iter()
        .enumerate()
        .map(|(position, digest)| {
            let position = u32::try_from(position)
                .map_err(|_| RetrievalAssignmentBridgeError::CandidateLimitExceeded)?;
            Ok((*digest, position))
        })
        .collect::<Result<BTreeMap<_, _>, RetrievalAssignmentBridgeError>>()?;

    let legal_candidate_indices = indices_for(&observation.legal_candidates, &index)?;
    let selected_candidate_indices = indices_for(&observation.selected_candidates, &index)?;
    let delivered_candidate_indices = indices_for(delivered_candidates, &index)?;
    let selected = selected_candidate_indices
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    if delivered_candidate_indices
        .iter()
        .any(|candidate| !selected.contains(candidate))
    {
        return Err(RetrievalAssignmentBridgeError::DeliveredCandidateOutsideSelection);
    }
    if context_exposed != !delivered_candidate_indices.is_empty() {
        return Err(RetrievalAssignmentBridgeError::ExposureStateMismatch);
    }

    Ok(LedgerEvent::RetrievalAssignment(RetrievalAssignmentFact {
        record_id,
        episode_id,
        cue_digest: observation.cue_digest,
        policy_digest: observation.policy_digest,
        source_completeness_digest: observation.source_completeness_digest,
        candidate_union_digest: observation.candidate_union_digest,
        recall_packet_digest: observation.recall_packet_digest,
        enumerated_candidate_digests: enumerated,
        legal_candidate_indices,
        selected_candidate_indices,
        delivered_candidate_indices,
        context_exposed,
        omitted_by_policy_limits: observation.omitted_by_policy_limits,
        assignment_propensity: observation.assignment_propensity,
        completeness: match observation.completeness {
            RetrievalAssignmentCompletenessV1::Complete => CandidateSetCompleteness::Complete,
            RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete => {
                CandidateSetCompleteness::Incomplete
            }
        },
        support_digest: observation.observation_digest,
    }))
}

fn indices_for(
    candidates: &[RetrievalCandidateIdentityV1],
    index: &BTreeMap<Digest32, u32>,
) -> Result<Vec<u32>, RetrievalAssignmentBridgeError> {
    let mut values = candidates
        .iter()
        .map(candidate_identity_digest)
        .map(|digest| {
            index
                .get(&digest)
                .copied()
                .ok_or(RetrievalAssignmentBridgeError::CandidateOutsideEnumeration)
        })
        .collect::<Result<Vec<_>, _>>()?;
    values.sort_unstable();
    if values.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(RetrievalAssignmentBridgeError::DuplicateCandidate);
    }
    Ok(values)
}

fn candidate_identity_digest(candidate: &RetrievalCandidateIdentityV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CANDIDATE_IDENTITY_DOMAIN);
    let raw = candidate.record_id.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
    bytes.extend_from_slice(&candidate.record_revision.get().to_be_bytes());
    bytes.extend_from_slice(candidate.record_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RetrievalAssignmentBridgeError {
    InvalidObservation(String),
    CandidateLimitExceeded,
    CandidateDigestCollision,
    CandidateOutsideEnumeration,
    DuplicateCandidate,
    DeliveredCandidateOutsideSelection,
    ExposureStateMismatch,
}

impl fmt::Display for RetrievalAssignmentBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RetrievalAssignmentBridgeError {}

#[cfg(test)]
#[path = "retrieval_assignment_tests.rs"]
mod tests;
