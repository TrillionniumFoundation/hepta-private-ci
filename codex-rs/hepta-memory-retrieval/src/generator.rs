//! Owner-bound retrieval generator contracts and complete source-coverage receipts.
//!
//! These types keep candidate generation separate from ranking. A product host
//! must obtain each batch from the named owner and bind its exact owner
//! generation before calling the deterministic ranking/recall core.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CandidateUnionV1;
use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::MAX_GENERATION_BOUND_CANDIDATES;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RecallPacketV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;
use crate::recall;

pub const MAX_RETRIEVAL_GENERATORS: usize = 8;

const GENERATOR_RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-generator-receipt.v1";
const SOURCE_COMPLETENESS_DOMAIN: &[u8] = b"hepta.retrieval-source-completeness.v1";
const GENERATED_UNION_DOMAIN: &[u8] = b"hepta.generated-candidate-union.v1";
const GENERATED_RECALL_DOMAIN: &[u8] = b"hepta.generated-recall.v1";

/// The concrete owner/generator class that produced one bounded candidate batch.
///
/// CognitiveAssociative is the current SQLite entity-seeded one-hop graph
/// generator. It contributes associative/entity evidence, not causal evidence.
/// Causal/procedural/contradiction channels remain owned by the knowledge-graph
/// projection and vector similarity remains owned by the encoder/index owner.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RetrievalGeneratorOwnerV1 {
    CognitiveLexical,
    CognitiveEntity,
    CognitiveTemporal,
    CognitiveAssociative,
    EncoderVector,
    KnowledgeGraphCausal,
    KnowledgeGraphProcedural,
    KnowledgeGraphContradiction,
}

impl RetrievalGeneratorOwnerV1 {
    #[must_use]
    pub const fn channel(self) -> RetrievalChannelV1 {
        match self {
            Self::CognitiveLexical => RetrievalChannelV1::Lexical,
            Self::CognitiveEntity => RetrievalChannelV1::Entity,
            Self::CognitiveTemporal => RetrievalChannelV1::Temporal,
            Self::CognitiveAssociative => RetrievalChannelV1::Graph,
            Self::EncoderVector => RetrievalChannelV1::Vector,
            Self::KnowledgeGraphCausal => RetrievalChannelV1::Causal,
            Self::KnowledgeGraphProcedural => RetrievalChannelV1::Procedural,
            Self::KnowledgeGraphContradiction => RetrievalChannelV1::ContradictionSupport,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalSourceCompletenessV1 {
    /// The owner proved exhaustion within its scoped source cut.
    Exhausted,
    /// The owner hit a declared bound. Additional eligible source rows may exist.
    LimitReached,
    /// The owner was unavailable. A valid batch must contain no candidates.
    Unavailable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalGeneratorReceiptV1 {
    pub generator: RetrievalGeneratorOwnerV1,
    pub generation_vector_digest: Digest32,
    /// Digest supplied by the actual owner for the concrete observed generation
    /// or owner-local bounded observation. It is not caller-minted freshness.
    pub owner_generation_digest: Digest32,
    pub candidate_count: u32,
    pub completeness: RetrievalSourceCompletenessV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RetrievalGeneratorReceiptV1 {
    pub fn new(
        generator: RetrievalGeneratorOwnerV1,
        generation_vector_digest: Digest32,
        owner_generation_digest: Digest32,
        candidate_count: u32,
        completeness: RetrievalSourceCompletenessV1,
    ) -> Result<Self, GeneratorErrorV1> {
        let mut receipt = Self {
            generator,
            generation_vector_digest,
            owner_generation_digest,
            candidate_count,
            completeness,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_receipt_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), GeneratorErrorV1> {
        ensure_digest("generator_vector", self.generation_vector_digest)?;
        ensure_digest("generator_owner_generation", self.owner_generation_digest)?;
        if usize::try_from(self.candidate_count).unwrap_or(usize::MAX)
            > MAX_GENERATION_BOUND_CANDIDATES
        {
            return Err(GeneratorErrorV1::CandidateLimitExceeded);
        }
        if matches!(
            self.completeness,
            RetrievalSourceCompletenessV1::Unavailable
        ) && self.candidate_count != 0
        {
            return Err(GeneratorErrorV1::UnavailableWithCandidates);
        }
        if self.authority.grants_any() {
            return Err(GeneratorErrorV1::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(GeneratorErrorV1::DigestMismatch("generator_receipt"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATOR_RECEIPT_DOMAIN);
        bytes.push(generator_code(self.generator));
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.owner_generation_digest);
        push_u64(&mut bytes, u64::from(self.candidate_count));
        bytes.push(completeness_code(self.completeness));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalGeneratorBatchV1 {
    pub receipt: RetrievalGeneratorReceiptV1,
    pub candidates: Vec<RetrievalChannelCandidateV1>,
}

impl RetrievalGeneratorBatchV1 {
    pub fn validate(&self) -> Result<(), GeneratorErrorV1> {
        self.receipt.validate()?;
        if self.candidates.len()
            != usize::try_from(self.receipt.candidate_count).unwrap_or(usize::MAX)
        {
            return Err(GeneratorErrorV1::CandidateCountMismatch);
        }
        let mut identities = BTreeSet::new();
        for candidate in &self.candidates {
            candidate
                .record
                .validate()
                .map_err(|error| GeneratorErrorV1::InvalidRecord(error.to_string()))?;
            if candidate.record.state != RecordState::Live {
                return Err(GeneratorErrorV1::TombstoneCandidate(
                    candidate.record.record_id.to_string(),
                ));
            }
            if candidate.channel != self.receipt.generator.channel() {
                return Err(GeneratorErrorV1::GeneratorChannelMismatch);
            }
            if candidate.generation_vector_digest != self.receipt.generation_vector_digest {
                return Err(GeneratorErrorV1::GenerationVectorMismatch);
            }
            if candidate.channel_rank == 0 {
                return Err(GeneratorErrorV1::ZeroChannelRank);
            }
            if candidate.channel_rank > self.receipt.candidate_count {
                return Err(GeneratorErrorV1::ChannelRankOutOfRange);
            }
            if candidate.normalized_score < FixedQ32::ZERO
                || candidate.normalized_score > FixedQ32::ONE
            {
                return Err(GeneratorErrorV1::ScoreOutOfRange);
            }
            ensure_digest("generator_candidate_support", candidate.support_digest)?;
            if let Some(group) = candidate.contradiction_group_digest {
                ensure_digest("generator_contradiction_group", group)?;
            }
            let identity = (
                candidate.record.record_id.clone(),
                candidate.record.revision,
            );
            if !identities.insert(identity) {
                return Err(GeneratorErrorV1::DuplicateCandidate(
                    candidate.record.record_id.to_string(),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedCandidateInputV1 {
    pub batches: Vec<RetrievalGeneratorBatchV1>,
    pub source_completeness_digest: Digest32,
}

impl GeneratedCandidateInputV1 {
    pub fn new(mut batches: Vec<RetrievalGeneratorBatchV1>) -> Result<Self, GeneratorErrorV1> {
        batches.sort_by_key(|batch| batch.receipt.generator);
        let source_completeness_digest = completeness_digest(&batches)?;
        let value = Self {
            batches,
            source_completeness_digest,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), GeneratorErrorV1> {
        if self.batches.is_empty() || self.batches.len() > MAX_RETRIEVAL_GENERATORS {
            return Err(GeneratorErrorV1::InvalidGeneratorCount);
        }
        let mut generators = BTreeSet::new();
        let mut previous = None;
        let mut total_candidates = 0_usize;
        for batch in &self.batches {
            batch.validate()?;
            total_candidates = total_candidates
                .checked_add(batch.candidates.len())
                .ok_or(GeneratorErrorV1::CandidateLimitExceeded)?;
            if total_candidates > MAX_GENERATION_BOUND_CANDIDATES {
                return Err(GeneratorErrorV1::CandidateLimitExceeded);
            }
            if !generators.insert(batch.receipt.generator) {
                return Err(GeneratorErrorV1::DuplicateGenerator(
                    batch.receipt.generator,
                ));
            }
            if previous.is_some_and(|value| value >= batch.receipt.generator) {
                return Err(GeneratorErrorV1::NonCanonicalGeneratorOrder);
            }
            previous = Some(batch.receipt.generator);
        }
        if self.source_completeness_digest != completeness_digest(&self.batches)? {
            return Err(GeneratorErrorV1::DigestMismatch("source_completeness"));
        }
        Ok(())
    }

    pub fn flattened_candidates(
        &self,
    ) -> Result<Vec<RetrievalChannelCandidateV1>, GeneratorErrorV1> {
        self.validate()?;
        let mut merged =
            BTreeMap::<(RetrievalChannelV1, StableId, Revision), MergedCandidate>::new();
        for batch in &self.batches {
            for candidate in &batch.candidates {
                let key = (
                    candidate.channel,
                    candidate.record.record_id.clone(),
                    candidate.record.revision,
                );
                let value = merged.entry(key).or_insert_with(|| MergedCandidate {
                    record: candidate.record.clone(),
                    channel: candidate.channel,
                    channel_rank: candidate.channel_rank,
                    normalized_score: candidate.normalized_score,
                    ood: candidate.ood,
                    support_digests: BTreeSet::new(),
                    receipt_digests: BTreeSet::new(),
                    contradiction_group_digest: candidate.contradiction_group_digest,
                    generation_vector_digest: candidate.generation_vector_digest,
                });
                if value.record.record_digest() != candidate.record.record_digest() {
                    return Err(GeneratorErrorV1::ConflictingRecordRevision(
                        candidate.record.record_id.to_string(),
                    ));
                }
                value.channel_rank = value.channel_rank.min(candidate.channel_rank);
                value.normalized_score = value.normalized_score.max(candidate.normalized_score);
                value.ood = value.ood.max(candidate.ood);
                match (
                    value.contradiction_group_digest,
                    candidate.contradiction_group_digest,
                ) {
                    (Some(left), Some(right)) if left != right => {
                        return Err(GeneratorErrorV1::ConflictingContradictionGroup(
                            candidate.record.record_id.to_string(),
                        ));
                    }
                    (None, Some(group)) => value.contradiction_group_digest = Some(group),
                    _ => {}
                }
                value.support_digests.insert(candidate.support_digest);
                value.receipt_digests.insert(batch.receipt.receipt_digest);
            }
        }
        if merged.len() > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(GeneratorErrorV1::CandidateLimitExceeded);
        }
        Ok(merged
            .into_values()
            .map(MergedCandidate::finish)
            .collect::<Vec<_>>())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedCandidateUnionV1 {
    pub union: CandidateUnionV1,
    pub generator_receipts: Vec<RetrievalGeneratorReceiptV1>,
    pub source_completeness_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl GeneratedCandidateUnionV1 {
    pub fn validate(&self) -> Result<(), GeneratorErrorV1> {
        self.union.validate().map_err(GeneratorErrorV1::Recall)?;
        validate_receipts(&self.generator_receipts, self.source_completeness_digest)?;
        if self
            .generator_receipts
            .iter()
            .any(|receipt| receipt.generation_vector_digest != self.union.generation_vector_digest)
        {
            return Err(GeneratorErrorV1::GenerationVectorMismatch);
        }
        if self.authority.grants_any() {
            return Err(GeneratorErrorV1::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(GeneratorErrorV1::DigestMismatch("generated_union"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATED_UNION_DOMAIN);
        push_digest(&mut bytes, self.union.union_digest);
        push_digest(&mut bytes, self.source_completeness_digest);
        push_len(&mut bytes, self.generator_receipts.len());
        for receipt in &self.generator_receipts {
            push_digest(&mut bytes, receipt.receipt_digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedRecallV1 {
    pub packet: RecallPacketV1,
    pub generator_receipts: Vec<RetrievalGeneratorReceiptV1>,
    pub source_completeness_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl GeneratedRecallV1 {
    pub fn validate(&self) -> Result<(), GeneratorErrorV1> {
        self.packet.validate().map_err(GeneratorErrorV1::Recall)?;
        validate_receipts(&self.generator_receipts, self.source_completeness_digest)?;
        if self
            .generator_receipts
            .iter()
            .any(|receipt| receipt.generation_vector_digest != self.packet.generation_vector_digest)
        {
            return Err(GeneratorErrorV1::GenerationVectorMismatch);
        }
        if self.authority.grants_any() {
            return Err(GeneratorErrorV1::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(GeneratorErrorV1::DigestMismatch("generated_recall"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATED_RECALL_DOMAIN);
        push_digest(&mut bytes, self.packet.packet_digest);
        push_digest(&mut bytes, self.source_completeness_digest);
        push_len(&mut bytes, self.generator_receipts.len());
        for receipt in &self.generator_receipts {
            push_digest(&mut bytes, receipt.receipt_digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn compile_cue(
    cue_id: StableId,
    objective_digest: Digest32,
    approved_context_digest: Digest32,
    request_digest: Digest32,
    snapshot_key: CognitiveSnapshotKeyV1,
    cue_profile_digest: Digest32,
) -> Result<MemoryCueV1, RecallErrorV1> {
    let cue = MemoryCueV1 {
        cue_id,
        objective_digest,
        approved_context_digest,
        request_digest,
        snapshot_key,
        cue_profile_digest,
    };
    cue.validate()?;
    Ok(cue)
}

pub fn build_candidate_union_from_generated(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    input: &GeneratedCandidateInputV1,
) -> Result<GeneratedCandidateUnionV1, GeneratorErrorV1> {
    cue.validate().map_err(GeneratorErrorV1::Recall)?;
    input.validate()?;
    ensure_input_generation(cue, input)?;
    ensure_policy_generators(policy, input)?;
    let candidates = input.flattened_candidates()?;
    let union = build_candidate_union(cue, policy, candidates).map_err(GeneratorErrorV1::Recall)?;
    let mut value = GeneratedCandidateUnionV1 {
        union,
        generator_receipts: input
            .batches
            .iter()
            .map(|batch| batch.receipt.clone())
            .collect(),
        source_completeness_digest: input.source_completeness_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.receipt_digest = value.compute_receipt_digest();
    value.validate()?;
    Ok(value)
}

pub fn recall_generated_with_engram(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    input: &GeneratedCandidateInputV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
) -> Result<GeneratedRecallV1, GeneratorErrorV1> {
    cue.validate().map_err(GeneratorErrorV1::Recall)?;
    input.validate()?;
    ensure_input_generation(cue, input)?;
    ensure_policy_generators(policy, input)?;
    let candidates = input.flattened_candidates()?;
    let packet =
        crate::recall_with_engram(cue, policy, candidates, engram_snapshot, dynamics_policy)
            .map_err(|error| GeneratorErrorV1::Engram(error.to_string()))?;
    let mut value = GeneratedRecallV1 {
        packet,
        generator_receipts: input
            .batches
            .iter()
            .map(|batch| batch.receipt.clone())
            .collect(),
        source_completeness_digest: input.source_completeness_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.receipt_digest = value.compute_receipt_digest();
    value.validate()?;
    Ok(value)
}

pub fn recall_generated(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    input: &GeneratedCandidateInputV1,
) -> Result<GeneratedRecallV1, GeneratorErrorV1> {
    cue.validate().map_err(GeneratorErrorV1::Recall)?;
    input.validate()?;
    ensure_input_generation(cue, input)?;
    ensure_policy_generators(policy, input)?;
    let candidates = input.flattened_candidates()?;
    let packet = recall(cue, policy, candidates).map_err(GeneratorErrorV1::Recall)?;
    let mut value = GeneratedRecallV1 {
        packet,
        generator_receipts: input
            .batches
            .iter()
            .map(|batch| batch.receipt.clone())
            .collect(),
        source_completeness_digest: input.source_completeness_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.receipt_digest = value.compute_receipt_digest();
    value.validate()?;
    Ok(value)
}

fn ensure_policy_generators(
    policy: &RetrievalPolicyV1,
    input: &GeneratedCandidateInputV1,
) -> Result<(), GeneratorErrorV1> {
    let enabled = policy
        .channel_weights
        .iter()
        .filter(|row| row.weight > FixedQ32::ZERO)
        .map(|row| row.channel)
        .collect::<BTreeSet<_>>();
    let supplied = input
        .batches
        .iter()
        .map(|batch| batch.receipt.generator.channel())
        .collect::<BTreeSet<_>>();
    if let Some(channel) = enabled.difference(&supplied).next().copied() {
        return Err(GeneratorErrorV1::MissingGeneratorForChannel(channel));
    }
    if let Some(channel) = supplied.difference(&enabled).next().copied() {
        return Err(GeneratorErrorV1::UnexpectedGeneratorForChannel(channel));
    }
    Ok(())
}

fn ensure_input_generation(
    cue: &MemoryCueV1,
    input: &GeneratedCandidateInputV1,
) -> Result<(), GeneratorErrorV1> {
    if input
        .batches
        .iter()
        .any(|batch| batch.receipt.generation_vector_digest != cue.snapshot_key.vector_digest)
    {
        return Err(GeneratorErrorV1::GenerationVectorMismatch);
    }
    Ok(())
}

fn validate_receipts(
    receipts: &[RetrievalGeneratorReceiptV1],
    expected_completeness_digest: Digest32,
) -> Result<(), GeneratorErrorV1> {
    if receipts.is_empty() || receipts.len() > MAX_RETRIEVAL_GENERATORS {
        return Err(GeneratorErrorV1::InvalidGeneratorCount);
    }
    let mut seen = BTreeSet::new();
    let mut previous = None;
    for receipt in receipts {
        receipt.validate()?;
        if !seen.insert(receipt.generator) {
            return Err(GeneratorErrorV1::DuplicateGenerator(receipt.generator));
        }
        if previous.is_some_and(|value| value >= receipt.generator) {
            return Err(GeneratorErrorV1::NonCanonicalGeneratorOrder);
        }
        previous = Some(receipt.generator);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SOURCE_COMPLETENESS_DOMAIN);
    push_len(&mut bytes, receipts.len());
    for receipt in receipts {
        push_digest(&mut bytes, receipt.receipt_digest);
    }
    if Digest32::of_bytes(&bytes) != expected_completeness_digest {
        return Err(GeneratorErrorV1::DigestMismatch("source_completeness"));
    }
    Ok(())
}

fn completeness_digest(
    batches: &[RetrievalGeneratorBatchV1],
) -> Result<Digest32, GeneratorErrorV1> {
    let mut receipts = batches
        .iter()
        .map(|batch| &batch.receipt)
        .collect::<Vec<_>>();
    receipts.sort_by_key(|receipt| receipt.generator);
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SOURCE_COMPLETENESS_DOMAIN);
    push_len(&mut bytes, receipts.len());
    let mut seen = BTreeSet::new();
    for receipt in receipts {
        receipt.validate()?;
        if !seen.insert(receipt.generator) {
            return Err(GeneratorErrorV1::DuplicateGenerator(receipt.generator));
        }
        push_digest(&mut bytes, receipt.receipt_digest);
    }
    Ok(Digest32::of_bytes(&bytes))
}

struct MergedCandidate {
    record: codex_hepta_cognitive_types::MemoryRecord,
    channel: RetrievalChannelV1,
    channel_rank: u32,
    normalized_score: FixedQ32,
    ood: ProbabilityQ32,
    support_digests: BTreeSet<Digest32>,
    receipt_digests: BTreeSet<Digest32>,
    contradiction_group_digest: Option<Digest32>,
    generation_vector_digest: Digest32,
}

impl MergedCandidate {
    fn finish(self) -> RetrievalChannelCandidateV1 {
        let mut bytes = b"hepta.retrieval-merged-support.v1".to_vec();
        push_len(&mut bytes, self.support_digests.len());
        for digest in self.support_digests {
            push_digest(&mut bytes, digest);
        }
        push_len(&mut bytes, self.receipt_digests.len());
        for digest in self.receipt_digests {
            push_digest(&mut bytes, digest);
        }
        RetrievalChannelCandidateV1 {
            record: self.record,
            channel: self.channel,
            channel_rank: self.channel_rank,
            normalized_score: self.normalized_score,
            ood: self.ood,
            support_digest: Digest32::of_bytes(&bytes),
            contradiction_group_digest: self.contradiction_group_digest,
            generation_vector_digest: self.generation_vector_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorErrorV1 {
    Recall(RecallErrorV1),
    Engram(String),
    EmptyDigest(&'static str),
    InvalidGeneratorCount,
    DuplicateGenerator(RetrievalGeneratorOwnerV1),
    NonCanonicalGeneratorOrder,
    CandidateLimitExceeded,
    CandidateCountMismatch,
    GeneratorChannelMismatch,
    MissingGeneratorForChannel(RetrievalChannelV1),
    UnexpectedGeneratorForChannel(RetrievalChannelV1),
    GenerationVectorMismatch,
    UnavailableWithCandidates,
    DuplicateCandidate(String),
    ConflictingRecordRevision(String),
    ConflictingContradictionGroup(String),
    InvalidRecord(String),
    TombstoneCandidate(String),
    ZeroChannelRank,
    ChannelRankOutOfRange,
    ScoreOutOfRange,
    AuthorityGranted,
    DigestMismatch(&'static str),
}

impl fmt::Display for GeneratorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GeneratorErrorV1 {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), GeneratorErrorV1> {
    if digest.is_zero() {
        return Err(GeneratorErrorV1::EmptyDigest(name));
    }
    Ok(())
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn generator_code(value: RetrievalGeneratorOwnerV1) -> u8 {
    match value {
        RetrievalGeneratorOwnerV1::CognitiveLexical => 0,
        RetrievalGeneratorOwnerV1::CognitiveEntity => 1,
        RetrievalGeneratorOwnerV1::CognitiveTemporal => 2,
        RetrievalGeneratorOwnerV1::CognitiveAssociative => 3,
        RetrievalGeneratorOwnerV1::EncoderVector => 4,
        RetrievalGeneratorOwnerV1::KnowledgeGraphCausal => 5,
        RetrievalGeneratorOwnerV1::KnowledgeGraphProcedural => 6,
        RetrievalGeneratorOwnerV1::KnowledgeGraphContradiction => 7,
    }
}

const fn completeness_code(value: RetrievalSourceCompletenessV1) -> u8 {
    match value {
        RetrievalSourceCompletenessV1::Exhausted => 0,
        RetrievalSourceCompletenessV1::LimitReached => 1,
        RetrievalSourceCompletenessV1::Unavailable => 2,
    }
}

#[cfg(test)]
#[path = "generator_tests.rs"]
mod tests;
