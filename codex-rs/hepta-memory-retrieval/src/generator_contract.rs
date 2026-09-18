//! Typed candidate-generator contract for generation-bound retrieval.
//!
//! This is a native Rust boundary, not a registered wire protocol. Producers
//! identify the exact generation vector and generator profile that produced a
//! bounded channel batch, and state whether their own source enumeration was
//! exhausted or truncated. memory.retrieval still grants no authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CandidateUnionV1;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RecallPacketV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;
use crate::recall;

/// Product-profile ceiling from the HNMF retrieval design.
pub const HNMF_MAX_CANDIDATE_EVENTS: usize = 512;
/// Product-profile ceiling from the HNMF retrieval design.
pub const HNMF_MAX_RETURNED_EVENTS: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalChannelCompletenessV1 {
    /// The producer exhausted the bounded source it is responsible for.
    Exhausted,
    /// The producer hit its own source/query bound. The exact number of rows
    /// outside that bound is intentionally not claimed.
    Truncated { omitted_at_least: u32 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelBatchV1 {
    pub channel: RetrievalChannelV1,
    /// Actual owner/producer of this channel's generator.
    pub producer_id: StableId,
    /// Immutable algorithm/index/profile identity for this producer.
    pub generator_profile_digest: Digest32,
    /// Exact Lane-C generation vector this batch was generated against.
    pub generation_vector_digest: Digest32,
    pub completeness: RetrievalChannelCompletenessV1,
    pub candidates: Vec<RetrievalChannelCandidateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorContractErrorV1 {
    Recall(RecallErrorV1),
    EmptyGeneratorProfile,
    DuplicateChannel(RetrievalChannelV1),
    GenerationVectorMismatch(RetrievalChannelV1),
    CandidateChannelMismatch(RetrievalChannelV1),
    InvalidTruncation,
    CandidateProfileLimitExceeded,
    ResultProfileLimitExceeded,
}

impl fmt::Display for GeneratorContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GeneratorContractErrorV1 {}

impl From<RecallErrorV1> for GeneratorContractErrorV1 {
    fn from(value: RecallErrorV1) -> Self {
        Self::Recall(value)
    }
}

fn flatten_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<Vec<RetrievalChannelCandidateV1>, GeneratorContractErrorV1> {
    cue.validate()?;
    policy.validate()?;
    if usize::try_from(policy.maximum_results).unwrap_or(usize::MAX)
        > HNMF_MAX_RETURNED_EVENTS
    {
        return Err(GeneratorContractErrorV1::ResultProfileLimitExceeded);
    }

    let expected_generation = cue.snapshot_key.vector_digest;
    let mut channels = BTreeSet::new();
    let mut total = 0usize;
    for batch in &batches {
        if !channels.insert(batch.channel) {
            return Err(GeneratorContractErrorV1::DuplicateChannel(batch.channel));
        }
        if batch.generator_profile_digest.is_zero() {
            return Err(GeneratorContractErrorV1::EmptyGeneratorProfile);
        }
        if batch.generation_vector_digest != expected_generation {
            return Err(GeneratorContractErrorV1::GenerationVectorMismatch(
                batch.channel,
            ));
        }
        if matches!(
            batch.completeness,
            RetrievalChannelCompletenessV1::Truncated {
                omitted_at_least: 0
            }
        ) {
            return Err(GeneratorContractErrorV1::InvalidTruncation);
        }
        total = total
            .checked_add(batch.candidates.len())
            .ok_or(GeneratorContractErrorV1::CandidateProfileLimitExceeded)?;
        if total > HNMF_MAX_CANDIDATE_EVENTS {
            return Err(GeneratorContractErrorV1::CandidateProfileLimitExceeded);
        }
        for candidate in &batch.candidates {
            if candidate.channel != batch.channel {
                return Err(GeneratorContractErrorV1::CandidateChannelMismatch(
                    batch.channel,
                ));
            }
            if candidate.generation_vector_digest != expected_generation {
                return Err(GeneratorContractErrorV1::GenerationVectorMismatch(
                    batch.channel,
                ));
            }
        }
    }

    Ok(batches
        .into_iter()
        .flat_map(|batch| batch.candidates)
        .collect())
}

/// Build the deterministic candidate union only from typed owner generator batches.
pub fn build_candidate_union_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<CandidateUnionV1, GeneratorContractErrorV1> {
    let candidates = flatten_batches(cue, policy, batches)?;
    Ok(build_candidate_union(cue, policy, candidates)?)
}

/// Recall from typed owner generator batches under the HNMF product ceilings.
pub fn recall_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<RecallPacketV1, GeneratorContractErrorV1> {
    let candidates = flatten_batches(cue, policy, batches)?;
    Ok(recall(cue, policy, candidates)?)
}

#[cfg(test)]
#[path = "generator_contract_tests.rs"]
mod tests;
