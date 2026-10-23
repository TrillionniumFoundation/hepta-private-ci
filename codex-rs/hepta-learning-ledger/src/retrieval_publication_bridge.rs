//! Retrieval-native assignment -> independent publication intent. There is no
//! exposure flag and no legacy delivery fact is manufactured by this bridge.

use std::collections::BTreeMap;

use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::RetrievalAssignmentBridgeError;
use crate::RetrievalAssignmentIntentV2;
use crate::retrieval_assignment::candidate_identity_digest;
use crate::retrieval_assignment::indices_for;
use crate::retrieval_assignment_record_id_v2;
use crate::retrieval_publication::MAX_CANDIDATES;
use crate::retrieval_publication::MAX_SELECTED;
use crate::retrieval_publication::episode_id;

#[allow(clippy::too_many_arguments)]
pub fn retrieval_assignment_intent_v2(
    owner_id: StableId,
    body_generation: u64,
    request_id: u64,
    observation: &RetrievalAssignmentObservationV1,
    planned_candidates: &[RetrievalCandidateIdentityV1],
    snapshot_digest: Digest32,
    control_schema_version: u32,
    response_frame_digest: Digest32,
    response_frame_bytes: u32,
    downstream_policy_digest: Option<Digest32>,
    delivery_propensity: ProbabilityQ32,
) -> Result<RetrievalAssignmentIntentV2, RetrievalAssignmentBridgeError> {
    if observation.enumerated_candidates.len() > MAX_CANDIDATES
        || observation.legal_candidates.len() > MAX_CANDIDATES
        || observation.selected_candidates.len() > MAX_SELECTED
        || planned_candidates.len() > MAX_SELECTED
    {
        return Err(RetrievalAssignmentBridgeError::CandidateLimitExceeded);
    }
    observation
        .validate()
        .map_err(|error| RetrievalAssignmentBridgeError::InvalidObservation(error.to_string()))?;
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
    let binding_error = |error: crate::LedgerError| {
        RetrievalAssignmentBridgeError::InvalidPublicationBinding(error.to_string())
    };
    let mut intent = RetrievalAssignmentIntentV2 {
        record_id: StableId::new("pending-intent").map_err(|error| {
            RetrievalAssignmentBridgeError::InvalidPublicationBinding(error.to_string())
        })?,
        episode_id: episode_id(&owner_id, body_generation, request_id).map_err(binding_error)?,
        owner_id,
        body_generation,
        request_id,
        control_schema_version,
        response_frame_digest,
        response_frame_bytes,
        snapshot_digest,
        cue_digest: observation.cue_digest,
        policy_digest: observation.policy_digest,
        source_completeness_digest: observation.source_completeness_digest,
        candidate_union_digest: observation.candidate_union_digest,
        recall_packet_digest: observation.recall_packet_digest,
        legal_candidate_indices: indices_for(&observation.legal_candidates, &index)?,
        selected_candidate_indices: indices_for(&observation.selected_candidates, &index)?,
        planned_candidate_indices: indices_for(planned_candidates, &index)?,
        enumerated_candidate_digests: enumerated,
        omitted_by_policy_limits: observation.omitted_by_policy_limits,
        assignment_propensity: observation.assignment_propensity,
        downstream_policy_digest,
        delivery_propensity,
        completeness: match observation.completeness {
            RetrievalAssignmentCompletenessV1::Complete => CandidateSetCompleteness::Complete,
            RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete => {
                CandidateSetCompleteness::Incomplete
            }
        },
        support_digest: observation.observation_digest,
    };
    crate::retrieval_publication_validation::normalize_intent(&mut intent)
        .map_err(binding_error)?;
    intent.record_id = retrieval_assignment_record_id_v2(&intent).map_err(binding_error)?;
    crate::retrieval_publication_validation::validate_intent(&intent).map_err(binding_error)?;
    Ok(intent)
}
