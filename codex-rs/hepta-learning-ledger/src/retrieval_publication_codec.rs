//! Additive private event tags 10/11. Legacy event bytes and framing stay exact.

use codex_hepta_types::ProbabilityQ32;

use crate::CandidateSetCompleteness;
use crate::DurableLedgerError;
use crate::RetrievalAssignmentIntentV2;
use crate::RetrievalPublicationConfirmedV2;
use crate::durable_codec::Reader;
use crate::ledger::push_digest;
use crate::ledger::push_id;
use crate::ledger::push_len;
use crate::retrieval_publication::MAX_CANDIDATES;
use crate::retrieval_publication::MAX_SELECTED;

pub(crate) fn encode_intent(bytes: &mut Vec<u8>, value: &RetrievalAssignmentIntentV2) {
    push_id(bytes, &value.record_id);
    encode_intent_body(bytes, value);
}

/// Shared canonical body for event encoding and content identity. The identity
/// excludes only record_id itself, avoiding a self-referential digest preimage.
pub(crate) fn encode_intent_body(bytes: &mut Vec<u8>, value: &RetrievalAssignmentIntentV2) {
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.owner_id);
    bytes.extend_from_slice(&value.body_generation.to_be_bytes());
    bytes.extend_from_slice(&value.request_id.to_be_bytes());
    bytes.extend_from_slice(&value.control_schema_version.to_be_bytes());
    push_digest(bytes, value.response_frame_digest);
    bytes.extend_from_slice(&value.response_frame_bytes.to_be_bytes());
    push_digest(bytes, value.snapshot_digest);
    push_digest(bytes, value.cue_digest);
    push_digest(bytes, value.policy_digest);
    push_digest(bytes, value.source_completeness_digest);
    push_digest(bytes, value.candidate_union_digest);
    push_digest(bytes, value.recall_packet_digest);
    push_len(bytes, value.enumerated_candidate_digests.len());
    for digest in &value.enumerated_candidate_digests {
        push_digest(bytes, *digest);
    }
    for indices in [
        &value.legal_candidate_indices,
        &value.selected_candidate_indices,
        &value.planned_candidate_indices,
    ] {
        push_len(bytes, indices.len());
        for index in indices {
            bytes.extend_from_slice(&index.to_be_bytes());
        }
    }
    bytes.extend_from_slice(&value.omitted_by_policy_limits.to_be_bytes());
    bytes.extend_from_slice(&value.assignment_propensity.raw().to_be_bytes());
    match value.downstream_policy_digest {
        None => bytes.push(0),
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
    }
    bytes.extend_from_slice(&value.delivery_propensity.raw().to_be_bytes());
    bytes.push(value.completeness.tag());
    push_digest(bytes, value.support_digest);
}

pub(crate) fn decode_intent(
    reader: &mut Reader<'_>,
) -> Result<RetrievalAssignmentIntentV2, DurableLedgerError> {
    Ok(RetrievalAssignmentIntentV2 {
        record_id: reader.id()?,
        episode_id: reader.id()?,
        owner_id: reader.id()?,
        body_generation: u64::from_be_bytes(reader.take()?),
        request_id: u64::from_be_bytes(reader.take()?),
        control_schema_version: u32::from_be_bytes(reader.take()?),
        response_frame_digest: reader.digest()?,
        response_frame_bytes: u32::from_be_bytes(reader.take()?),
        snapshot_digest: reader.digest()?,
        cue_digest: reader.digest()?,
        policy_digest: reader.digest()?,
        source_completeness_digest: reader.digest()?,
        candidate_union_digest: reader.digest()?,
        recall_packet_digest: reader.digest()?,
        enumerated_candidate_digests: {
            let count = count(reader, MAX_CANDIDATES)?;
            (0..count)
                .map(|_| reader.digest())
                .collect::<Result<_, _>>()?
        },
        legal_candidate_indices: indices(reader, MAX_CANDIDATES)?,
        selected_candidate_indices: indices(reader, MAX_SELECTED)?,
        planned_candidate_indices: indices(reader, MAX_SELECTED)?,
        omitted_by_policy_limits: u32::from_be_bytes(reader.take()?),
        assignment_propensity: propensity(reader)?,
        downstream_policy_digest: reader.optional_digest()?,
        delivery_propensity: propensity(reader)?,
        completeness: match reader.byte()? {
            0 => CandidateSetCompleteness::Complete,
            1 => CandidateSetCompleteness::Incomplete,
            _ => return Err(DurableLedgerError::Corrupt),
        },
        support_digest: reader.digest()?,
    })
}

pub(crate) fn encode_confirmation(bytes: &mut Vec<u8>, value: &RetrievalPublicationConfirmedV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.intent_record_id);
    push_digest(bytes, value.intent_event_digest);
    push_digest(bytes, value.response_frame_digest);
    bytes.extend_from_slice(&value.response_frame_bytes.to_be_bytes());
}

pub(crate) fn decode_confirmation(
    reader: &mut Reader<'_>,
) -> Result<RetrievalPublicationConfirmedV2, DurableLedgerError> {
    Ok(RetrievalPublicationConfirmedV2 {
        record_id: reader.id()?,
        intent_record_id: reader.id()?,
        intent_event_digest: reader.digest()?,
        response_frame_digest: reader.digest()?,
        response_frame_bytes: u32::from_be_bytes(reader.take()?),
    })
}

fn count(reader: &mut Reader<'_>, maximum: usize) -> Result<usize, DurableLedgerError> {
    let count = u32::from_be_bytes(reader.take()?) as usize;
    if count > maximum {
        return Err(DurableLedgerError::Corrupt);
    }
    Ok(count)
}

fn indices(reader: &mut Reader<'_>, maximum: usize) -> Result<Vec<u32>, DurableLedgerError> {
    let count = count(reader, maximum)?;
    (0..count)
        .map(|_| Ok(u32::from_be_bytes(reader.take()?)))
        .collect()
}

fn propensity(reader: &mut Reader<'_>) -> Result<ProbabilityQ32, DurableLedgerError> {
    ProbabilityQ32::from_raw(u64::from_be_bytes(reader.take()?))
        .map_err(|_| DurableLedgerError::Corrupt)
}
