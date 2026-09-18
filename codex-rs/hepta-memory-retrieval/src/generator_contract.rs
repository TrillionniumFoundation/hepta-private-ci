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

const GENERATOR_MANIFEST_DOMAIN: &[u8] = b"hepta.retrieval-generator-manifest.v1";
const GENERATOR_UNION_RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-generator-union-receipt.v1";
const GENERATOR_RECALL_RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-generator-recall-receipt.v1";

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

/// Canonical binding of every typed generator batch before union/ranking.
///
/// This distinguishes two identical candidate sets produced under different
/// source coverage, producer profiles or pre-fusion ranks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalGeneratorReceiptV1 {
    pub manifest_digest: Digest32,
    pub candidate_count: u32,
    pub truncated_channels: Vec<RetrievalChannelV1>,
}

/// Candidate union plus the generator manifest that produced its exact input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationBoundCandidateUnionV1 {
    pub union: CandidateUnionV1,
    pub generator: RetrievalGeneratorReceiptV1,
    pub receipt_digest: Digest32,
}

/// Recall result plus the generator manifest that produced its exact input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationBoundRecallV1 {
    pub recall: RecallPacketV1,
    pub generator: RetrievalGeneratorReceiptV1,
    pub receipt_digest: Digest32,
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
    Arithmetic,
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

fn validate_and_bind_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    mut batches: Vec<RetrievalChannelBatchV1>,
) -> Result<
    (
        Vec<RetrievalChannelCandidateV1>,
        RetrievalGeneratorReceiptV1,
    ),
    GeneratorContractErrorV1,
> {
    cue.validate()?;
    policy.validate()?;
    if usize::try_from(policy.maximum_results).unwrap_or(usize::MAX) > HNMF_MAX_RETURNED_EVENTS {
        return Err(GeneratorContractErrorV1::ResultProfileLimitExceeded);
    }
    if policy.channel_weights.iter().any(|row| {
        usize::try_from(row.maximum_candidates).unwrap_or(usize::MAX) > HNMF_MAX_CANDIDATE_EVENTS
    }) {
        return Err(GeneratorContractErrorV1::CandidateProfileLimitExceeded);
    }

    batches.sort_by_key(|batch| batch.channel);
    let expected_generation = cue.snapshot_key.vector_digest;
    let mut channels = BTreeSet::new();
    let mut total = 0usize;
    let mut truncated_channels = Vec::new();
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
        match batch.completeness {
            RetrievalChannelCompletenessV1::Exhausted => {}
            RetrievalChannelCompletenessV1::Truncated {
                omitted_at_least: 0,
            } => return Err(GeneratorContractErrorV1::InvalidTruncation),
            RetrievalChannelCompletenessV1::Truncated { .. } => {
                truncated_channels.push(batch.channel);
            }
        }
        total = total
            .checked_add(batch.candidates.len())
            .ok_or(GeneratorContractErrorV1::Arithmetic)?;
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

    let generator = bind_generator_manifest(&batches, total, truncated_channels)?;
    let candidates = batches
        .into_iter()
        .flat_map(|batch| batch.candidates)
        .collect();
    Ok((candidates, generator))
}

fn bind_generator_manifest(
    batches: &[RetrievalChannelBatchV1],
    candidate_count: usize,
    truncated_channels: Vec<RetrievalChannelV1>,
) -> Result<RetrievalGeneratorReceiptV1, GeneratorContractErrorV1> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(GENERATOR_MANIFEST_DOMAIN);
    push_len(&mut bytes, batches.len())?;
    for batch in batches {
        bytes.push(channel_code(batch.channel));
        push_id(&mut bytes, &batch.producer_id)?;
        bytes.extend_from_slice(batch.generator_profile_digest.as_array());
        bytes.extend_from_slice(batch.generation_vector_digest.as_array());
        match batch.completeness {
            RetrievalChannelCompletenessV1::Exhausted => bytes.push(0),
            RetrievalChannelCompletenessV1::Truncated { omitted_at_least } => {
                bytes.push(1);
                bytes.extend_from_slice(&omitted_at_least.to_be_bytes());
            }
        }
        let mut candidates = batch.candidates.iter().collect::<Vec<_>>();
        candidates.sort_by(|left, right| {
            left.channel_rank
                .cmp(&right.channel_rank)
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        push_len(&mut bytes, candidates.len())?;
        for candidate in candidates {
            bytes.extend_from_slice(candidate.record.record_digest().as_array());
            bytes.extend_from_slice(&candidate.channel_rank.to_be_bytes());
            bytes.extend_from_slice(&candidate.normalized_score.raw().to_be_bytes());
            bytes.extend_from_slice(&candidate.ood.raw().to_be_bytes());
            bytes.extend_from_slice(candidate.support_digest.as_array());
            match candidate.contradiction_group_digest {
                Some(digest) => {
                    bytes.push(1);
                    bytes.extend_from_slice(digest.as_array());
                }
                None => bytes.push(0),
            }
            bytes.extend_from_slice(candidate.generation_vector_digest.as_array());
        }
    }
    Ok(RetrievalGeneratorReceiptV1 {
        manifest_digest: Digest32::of_bytes(&bytes),
        candidate_count: u32::try_from(candidate_count)
            .map_err(|_| GeneratorContractErrorV1::Arithmetic)?,
        truncated_channels,
    })
}

/// Build the deterministic candidate union only from typed owner generator batches.
pub fn build_candidate_union_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<GenerationBoundCandidateUnionV1, GeneratorContractErrorV1> {
    let (candidates, generator) = validate_and_bind_batches(cue, policy, batches)?;
    let union = build_candidate_union(cue, policy, candidates)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(GENERATOR_UNION_RECEIPT_DOMAIN);
    bytes.extend_from_slice(union.union_digest.as_array());
    bytes.extend_from_slice(generator.manifest_digest.as_array());
    Ok(GenerationBoundCandidateUnionV1 {
        union,
        generator,
        receipt_digest: Digest32::of_bytes(&bytes),
    })
}

/// Recall from typed owner generator batches under the HNMF product ceilings.
pub fn recall_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<GenerationBoundRecallV1, GeneratorContractErrorV1> {
    let (candidates, generator) = validate_and_bind_batches(cue, policy, batches)?;
    let recall = recall(cue, policy, candidates)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(GENERATOR_RECALL_RECEIPT_DOMAIN);
    bytes.extend_from_slice(recall.packet_digest.as_array());
    bytes.extend_from_slice(generator.manifest_digest.as_array());
    Ok(GenerationBoundRecallV1 {
        recall,
        generator,
        receipt_digest: Digest32::of_bytes(&bytes),
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), GeneratorContractErrorV1> {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len())?;
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), GeneratorContractErrorV1> {
    bytes.extend_from_slice(
        &u64::try_from(value)
            .map_err(|_| GeneratorContractErrorV1::Arithmetic)?
            .to_be_bytes(),
    );
    Ok(())
}

const fn channel_code(value: RetrievalChannelV1) -> u8 {
    match value {
        RetrievalChannelV1::Lexical => 0,
        RetrievalChannelV1::Vector => 1,
        RetrievalChannelV1::Entity => 2,
        RetrievalChannelV1::Temporal => 3,
        RetrievalChannelV1::Causal => 4,
        RetrievalChannelV1::Procedural => 5,
        RetrievalChannelV1::ContradictionSupport => 6,
    }
}

#[cfg(test)]
#[path = "generator_contract_tests.rs"]
mod tests;
