use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2;
use crate::RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2;
use crate::RetrievalAssignmentIntentV2;
use crate::RetrievalPublicationConfirmedV2;
use crate::retrieval_assignment_record_id_v2;
use crate::retrieval_publication::MAX_CANDIDATES;
use crate::retrieval_publication::MAX_SELECTED;
use crate::retrieval_publication::confirmation_record_id;
use crate::retrieval_publication::episode_id;

pub(crate) fn validate_intent(value: &RetrievalAssignmentIntentV2) -> Result<(), LedgerError> {
    if value.body_generation == 0
        || value.control_schema_version != RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2
        || !(1..=RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2).contains(&value.response_frame_bytes)
        || value.record_id != retrieval_assignment_record_id_v2(value)?
        || value.episode_id != episode_id(&value.owner_id, value.body_generation, value.request_id)?
    {
        return Err(LedgerError::RetrievalPublicationBindingMismatch);
    }
    for (name, digest) in [
        ("retrieval response frame", value.response_frame_digest),
        ("retrieval snapshot", value.snapshot_digest),
        ("retrieval cue", value.cue_digest),
        ("retrieval policy", value.policy_digest),
        (
            "retrieval source completeness",
            value.source_completeness_digest,
        ),
        ("retrieval candidate union", value.candidate_union_digest),
        ("retrieval recall packet", value.recall_packet_digest),
        ("retrieval assignment support", value.support_digest),
    ] {
        if digest.is_zero() {
            return Err(LedgerError::EmptyDigest(name));
        }
    }
    if value
        .downstream_policy_digest
        .is_some_and(Digest32::is_zero)
    {
        return Err(LedgerError::EmptyDigest("retrieval downstream policy"));
    }
    if value
        .enumerated_candidate_digests
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(LedgerError::EmptyDigest("retrieval candidate identity"));
    }
    if value.assignment_propensity.raw() == 0 {
        return Err(LedgerError::ZeroSelectedPropensity);
    }
    if value.delivery_propensity.raw() == 0 {
        return Err(LedgerError::ZeroDeliveryPropensity);
    }
    let legal: BTreeSet<_> = value.legal_candidate_indices.iter().copied().collect();
    if value
        .selected_candidate_indices
        .iter()
        .any(|index| !legal.contains(index))
    {
        return Err(LedgerError::RetrievalSelectionOutsideLegal);
    }
    let selected: BTreeSet<_> = value.selected_candidate_indices.iter().copied().collect();
    if value
        .planned_candidate_indices
        .iter()
        .any(|index| !selected.contains(index))
    {
        return Err(LedgerError::RetrievalDeliveryOutsideSelection);
    }
    Ok(())
}

pub(crate) fn normalize_intent(value: &mut RetrievalAssignmentIntentV2) -> Result<(), LedgerError> {
    check_candidate_limits(value)?;
    let original = &value.enumerated_candidate_digests;
    let mut order: Vec<usize> = (0..original.len()).collect();
    order.sort_by_key(|index| original[*index]);
    let mut remapped = vec![0_u32; original.len()];
    for (canonical, previous) in order.iter().copied().enumerate() {
        remapped[previous] =
            u32::try_from(canonical).map_err(|_| LedgerError::RetrievalIndexOutOfRange)?;
    }
    let canonical = order.iter().map(|index| original[*index]).collect();
    for indices in [
        &mut value.legal_candidate_indices,
        &mut value.selected_candidate_indices,
        &mut value.planned_candidate_indices,
    ] {
        for index in indices.iter_mut() {
            *index = *remapped
                .get(usize::try_from(*index).map_err(|_| LedgerError::RetrievalIndexOutOfRange)?)
                .ok_or(LedgerError::RetrievalIndexOutOfRange)?;
        }
        indices.sort_unstable();
        if indices.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(LedgerError::DuplicateRetrievalIndex);
        }
    }
    value.enumerated_candidate_digests = canonical;
    if value
        .enumerated_candidate_digests
        .windows(2)
        .any(|pair| pair[0] == pair[1])
    {
        return Err(LedgerError::DuplicateCandidate(
            "retrieval-candidate-digest".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn check_candidate_limits(
    value: &RetrievalAssignmentIntentV2,
) -> Result<(), LedgerError> {
    if value.enumerated_candidate_digests.len() > MAX_CANDIDATES
        || value.legal_candidate_indices.len() > MAX_CANDIDATES
        || value.selected_candidate_indices.len() > MAX_SELECTED
        || value.planned_candidate_indices.len() > MAX_SELECTED
    {
        return Err(LedgerError::RetrievalCandidateLimitExceeded);
    }
    Ok(())
}

pub(crate) fn validate_confirmation(
    ledger: &LearningLedger,
    value: &RetrievalPublicationConfirmedV2,
) -> Result<(), LedgerError> {
    if value.intent_event_digest.is_zero() || value.response_frame_digest.is_zero() {
        return Err(LedgerError::EmptyDigest(
            "retrieval publication confirmation",
        ));
    }
    if value.record_id
        != confirmation_record_id(&value.intent_record_id, value.intent_event_digest)?
    {
        return Err(LedgerError::RetrievalPublicationBindingMismatch);
    }
    // A withdrawal after the actual write cannot make that historical write
    // un-happen. Admission uses historical identity, activity is projected apart.
    let record = ledger
        .record_by_id(&value.intent_record_id)?
        .ok_or(LedgerError::RetrievalPublicationIntentRequired)?;
    let LedgerEvent::RetrievalAssignmentIntentV2(intent) = &record.event else {
        return Err(LedgerError::RetrievalPublicationIntentRequired);
    };
    if record.event_digest != value.intent_event_digest
        || intent.response_frame_digest != value.response_frame_digest
        || intent.response_frame_bytes != value.response_frame_bytes
    {
        return Err(LedgerError::RetrievalPublicationBindingMismatch);
    }
    Ok(())
}
