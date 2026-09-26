//! Explainable, snapshot-revalidated local memory retrieval.

#![forbid(unsafe_code)]

mod decision;
#[path = "engram_v2.rs"]
mod engram;
#[path = "generation_bound_v2.rs"]
mod generation_bound;
mod generator;
mod v2;
mod vector_owner;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub use decision::AssignmentErrorV1;
pub use decision::RetrievalAssignmentCompletenessV1;
pub use decision::RetrievalAssignmentObservationV1;
pub use decision::RetrievalCandidateIdentityV1;
pub use decision::observe_retrieval_assignment;
pub use engram::ActiveEngramNodeV1;
pub use engram::EngramActivationPathV1;
pub use engram::EngramContradictionV1;
pub use engram::EngramDynamicsPolicyV1;
pub use engram::EngramErrorV1;
pub use engram::EngramNodeV1;
pub use engram::EngramPopulationV1;
pub use engram::EngramRecallReceiptV1;
pub use engram::EngramResourceReceiptV1;
pub use engram::EngramSnapshotV1;
pub use engram::EngramSupportV1;
pub use engram::MAX_ACTIVATION_PATHS;
pub use engram::MAX_ACTIVE_NODES;
pub use engram::MAX_ACTIVE_PER_POPULATION;
pub use engram::MAX_ENGRAM_GRAPH_HOPS;
pub use engram::MAX_ENGRAM_NODES;
pub use engram::MAX_ENGRAM_SETTLING_STEPS;
pub use engram::MAX_ENGRAM_SYNAPSES;
pub use engram::SynapseRelationV1;
pub use engram::SynapseV1;
pub use engram::recall_with_engram;
pub use engram::settle_engram;
pub use generation_bound::CandidateUnionEntryV1;
pub use generation_bound::CandidateUnionV1;
pub use generation_bound::CanonicalRecallSelectionBindingV1;
pub use generation_bound::CanonicalRecallShadowContextV1;
pub use generation_bound::ContradictionEvidenceV1;
pub use generation_bound::ContradictionPolarityV1;
pub use generation_bound::MAX_GENERATION_BOUND_CANDIDATES;
pub use generation_bound::MAX_GENERATION_BOUND_RESULTS;
pub use generation_bound::MemoryCueV1;
pub use generation_bound::RecallAbstentionReasonV1;
pub use generation_bound::RecallDispositionV1;
pub use generation_bound::RecallErrorV1;
pub use generation_bound::RecallPacketV1;
pub use generation_bound::RecallSelectionV1;
pub use generation_bound::RetrievalChannelCandidateV1;
pub use generation_bound::RetrievalChannelV1;
pub use generation_bound::RetrievalChannelWeightV1;
pub use generation_bound::RetrievalPolicyV1;
pub use generation_bound::adapt_generation_bound_recall_to_canonical_shadow_v1;
pub use generation_bound::build_candidate_union;
pub use generation_bound::recall;
pub use generator::GeneratedCandidateInputV1;
pub use generator::GeneratedCandidateUnionV1;
pub use generator::GeneratedRecallV1;
pub use generator::GeneratorErrorV1;
pub use generator::MAX_RETRIEVAL_GENERATORS;
pub use generator::RetrievalGeneratorBatchV1;
pub use generator::RetrievalGeneratorOwnerV1;
pub use generator::RetrievalGeneratorReceiptV1;
pub use generator::RetrievalSourceCompletenessV1;
pub use generator::build_candidate_union_from_generated;
pub use generator::compile_cue;
pub use generator::recall_generated;
pub use generator::recall_generated_with_engram;
pub use v2::RetrievalReceiptV2;
pub use v2::retrieve_v2;
pub use vector_owner::MAX_VECTOR_DIMENSIONS;
pub use vector_owner::MAX_VECTOR_INDEX_RECORDS;
pub use vector_owner::VectorIndexRecordV1;
pub use vector_owner::VectorIndexSnapshotV1;
pub use vector_owner::VectorOwnerErrorV1;
pub use vector_owner::VectorQueryV1;
pub use vector_owner::generate_vector_batch_v1;

const MAX_CANDIDATES: usize = 16_384;
const MAX_RESULTS: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalCandidate {
    pub record: MemoryRecord,
    pub snapshot_digest: Digest32,
    pub lexical_score: FixedQ32,
    pub graph_score: FixedQ32,
    pub freshness_score: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalRequest {
    pub query_id: StableId,
    pub query_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub maximum_results: usize,
    pub candidates: Vec<RetrievalCandidate>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalResult {
    pub record_id: StableId,
    pub record_digest: Digest32,
    pub total_score: FixedQ32,
    pub lexical_score: FixedQ32,
    pub graph_score: FixedQ32,
    pub freshness_score: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalReceipt {
    pub query_id: StableId,
    pub snapshot_digest: Digest32,
    pub results: Vec<RetrievalResult>,
    pub omitted_count: usize,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    InvalidMaximumResults,
    CandidateLimitExceeded,
    SnapshotMismatch(String),
    DuplicateRecord(String),
    InvalidRecord(String),
    TombstoneRecord(String),
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn retrieve(request: RetrievalRequest) -> Result<RetrievalReceipt, Error> {
    retrieve_request(&request)
}

fn retrieve_request(request: &RetrievalRequest) -> Result<RetrievalReceipt, Error> {
    if request.query_digest.is_zero() {
        return Err(Error::EmptyDigest("query"));
    }
    if request.snapshot_digest.is_zero() {
        return Err(Error::EmptyDigest("snapshot"));
    }
    if request.maximum_results == 0 || request.maximum_results > MAX_RESULTS {
        return Err(Error::InvalidMaximumResults);
    }
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(Error::CandidateLimitExceeded);
    }

    let mut seen = BTreeSet::new();
    let mut results = Vec::with_capacity(request.candidates.len());
    for candidate in &request.candidates {
        if candidate.snapshot_digest != request.snapshot_digest {
            return Err(Error::SnapshotMismatch(
                candidate.record.record_id.to_string(),
            ));
        }
        candidate
            .record
            .validate()
            .map_err(|error| Error::InvalidRecord(error.to_string()))?;
        if candidate.record.state == RecordState::Tombstone {
            return Err(Error::TombstoneRecord(
                candidate.record.record_id.to_string(),
            ));
        }
        if !seen.insert(candidate.record.record_id.clone()) {
            return Err(Error::DuplicateRecord(
                candidate.record.record_id.to_string(),
            ));
        }
        let score = candidate
            .lexical_score
            .checked_add(candidate.graph_score)
            .and_then(|value| value.checked_add(candidate.freshness_score))
            .map_err(|_| Error::Arithmetic)?;
        let record_digest = candidate.record.record_digest();
        results.push(RetrievalResult {
            record_id: candidate.record.record_id.clone(),
            record_digest,
            total_score: score,
            lexical_score: candidate.lexical_score,
            graph_score: candidate.graph_score,
            freshness_score: candidate.freshness_score,
        });
    }
    results.sort_by(|left, right| {
        right
            .total_score
            .cmp(&left.total_score)
            .then_with(|| left.record_id.cmp(&right.record_id))
    });
    let omitted_count = results.len().saturating_sub(request.maximum_results);
    results.truncate(request.maximum_results);

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory.retrieval.v1");
    push_id(&mut bytes, &request.query_id);
    bytes.extend_from_slice(request.query_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    for result in &results {
        push_id(&mut bytes, &result.record_id);
        bytes.extend_from_slice(result.record_digest.as_array());
        bytes.extend_from_slice(&result.total_score.raw().to_be_bytes());
        bytes.extend_from_slice(&result.lexical_score.raw().to_be_bytes());
        bytes.extend_from_slice(&result.graph_score.raw().to_be_bytes());
        bytes.extend_from_slice(&result.freshness_score.raw().to_be_bytes());
    }

    Ok(RetrievalReceipt {
        query_id: request.query_id.clone(),
        snapshot_digest: request.snapshot_digest,
        results,
        omitted_count,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "generator_property_tests.rs"]
mod generator_property_tests;
