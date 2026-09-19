//! Adapter from the canonical SQLite owner's bounded retrieval observation into
//! the memory.retrieval generator contract.
//!
//! This module does not query another store and does not mint source scores.
//! It converts ranks and completeness already observed by CognitiveStore into
//! typed, generation-bound retrieval evidence.

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::GeneratedCandidateInputV1;
use codex_hepta_memory_retrieval::GeneratedRecallV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalChannelCandidateV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalGeneratorBatchV1;
use codex_hepta_memory_retrieval::RetrievalGeneratorOwnerV1;
use codex_hepta_memory_retrieval::RetrievalGeneratorReceiptV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_memory_retrieval::RetrievalSourceCompletenessV1;
use codex_hepta_memory_retrieval::compile_cue;
use codex_hepta_memory_retrieval::observe_retrieval_assignment;
use codex_hepta_memory_retrieval::recall_generated_with_engram;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::MAX_RETRIEVAL_CHANNEL_CANDIDATES;
use crate::MemoryRevalidationBinding;
use crate::RetrievalChannel;
use crate::RetrievalChannelObservation;
use crate::RetrievalChannelRank;
use crate::RetrievalLimitObservation;
use crate::RetrievalObservation;

const OWNER_GENERATION_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-owner-generation.v1";
const OWNER_SUPPORT_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-support.v1";
const OWNER_POLICY_ID: &str = "policy:sqlite-owner-retrieval-v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalExecutionContextV1 {
    pub generation_vector: LaneCGenerationVectorV1,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub cue_profile_digest: Digest32,
    pub retrieval_policy: RetrievalPolicyV1,
    pub engram_snapshot: EngramSnapshotV1,
    pub dynamics_policy: EngramDynamicsPolicyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerRetrievalExecutionV1 {
    pub recall: GeneratedRecallV1,
    pub assignment: RetrievalAssignmentObservationV1,
}

impl RetrievalExecutionContextV1 {
    pub fn validate(&self) -> Result<(), CognitiveStoreError> {
        self.generation_vector
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        for (name, digest) in [
            ("retrieval objective", self.objective_digest),
            ("approved context", self.approved_context_digest),
            ("cue profile", self.cue_profile_digest),
        ] {
            if digest.is_zero() {
                return Err(CognitiveStoreError::Invalid(format!(
                    "{name} digest must be non-zero"
                )));
            }
        }
        self.retrieval_policy
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if self.generation_vector.retrieval_profile_digest != self.retrieval_policy.digest() {
            return Err(CognitiveStoreError::Conflict(
                "retrieval policy differs from the bound Lane C retrieval profile".to_string(),
            ));
        }
        self.engram_snapshot
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        self.dynamics_policy
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if self.engram_snapshot.generation_vector_digest != self.generation_vector.digest() {
            return Err(CognitiveStoreError::Conflict(
                "engram snapshot belongs to another Lane C generation".to_string(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.retrieval-execution-context.v1".to_vec();
        bytes.extend_from_slice(self.generation_vector.digest().as_array());
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(self.approved_context_digest.as_array());
        bytes.extend_from_slice(self.cue_profile_digest.as_array());
        bytes.extend_from_slice(self.retrieval_policy.digest().as_array());
        bytes.extend_from_slice(self.engram_snapshot.snapshot_digest.as_array());
        bytes.extend_from_slice(self.dynamics_policy.digest().as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub fn recall_owner_observation(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
) -> Result<GeneratedRecallV1, CognitiveStoreError> {
    execute_owner_observation(
        observation,
        cut,
        context,
        request_digest,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
    )
    .map(|execution| execution.recall)
}

pub fn execute_owner_observation(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
) -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError> {
    context.validate()?;
    if request_digest.is_zero() {
        return Err(CognitiveStoreError::Invalid(
            "retrieval request digest must be non-zero".to_string(),
        ));
    }
    let authoritative = cut
        .bind_context(
            context.generation_vector.clone(),
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
        .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let generated = generated_input_from_owner_observation(
        observation,
        authoritative.snapshot_key(),
        authoritative.snapshot(),
    )?;
    let mut cue_bytes = b"hepta.owner-retrieval-cue.v1".to_vec();
    cue_bytes.extend_from_slice(request_digest.as_array());
    cue_bytes.extend_from_slice(authoritative.snapshot_key().vector_digest.as_array());
    let cue_id = StableId::new(format!("cue:{}", Digest32::of_bytes(&cue_bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let cue = compile_cue(
        cue_id,
        context.objective_digest,
        context.approved_context_digest,
        request_digest,
        authoritative.snapshot_key().clone(),
        context.cue_profile_digest,
    )
    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let recall = recall_generated_with_engram(
        &cue,
        &context.retrieval_policy,
        &generated,
        &context.engram_snapshot,
        &context.dynamics_policy,
    )
    .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let assignment =
        observe_retrieval_assignment(&cue, &context.retrieval_policy, &generated, &recall)
            .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    Ok(OwnerRetrievalExecutionV1 { recall, assignment })
}

pub fn generated_input_from_owner_observation(
    observation: &RetrievalObservation,
    snapshot_key: &CognitiveSnapshotKeyV1,
    snapshot: &CognitiveSnapshot,
) -> Result<GeneratedCandidateInputV1, CognitiveStoreError> {
    snapshot_key
        .validate()
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let owner_observation_digest: Digest32 = observation
        .observation_sha256()
        .as_str()
        .parse()
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "invalid owner retrieval observation digest: {error}"
            ))
        })?;

    let mut batches = Vec::with_capacity(observation.channels().len());
    for channel_observation in observation.channels() {
        let generator = generator_for_channel(channel_observation.channel);
        let semantic_channel = generator.channel();
        let mut candidates = Vec::new();
        for observed in observation.candidates() {
            let Some(channel_rank) = observed
                .channel_ranks
                .iter()
                .find(|rank| rank.channel == channel_observation.channel)
            else {
                continue;
            };
            let record = exact_snapshot_record(snapshot, &observed.revalidation)?;
            candidates.push(RetrievalChannelCandidateV1 {
                record: record.clone(),
                channel: semantic_channel,
                channel_rank: channel_rank.rank,
                normalized_score: reciprocal_rank_score(channel_rank.rank)?,
                ood: ProbabilityQ32::ZERO,
                support_digest: owner_support_digest(
                    owner_observation_digest,
                    &record,
                    *channel_rank,
                ),
                contradiction_group_digest: None,
                generation_vector_digest: snapshot_key.vector_digest,
            });
        }
        if candidates.len() != channel_observation.candidate_count {
            return Err(CognitiveStoreError::Conflict(format!(
                "owner retrieval channel {:?} observed {} candidates but {} survived exact snapshot binding",
                channel_observation.channel,
                channel_observation.candidate_count,
                candidates.len()
            )));
        }
        let owner_generation_digest =
            owner_generation_digest(owner_observation_digest, channel_observation);
        let receipt = RetrievalGeneratorReceiptV1::new(
            generator,
            snapshot_key.vector_digest,
            owner_generation_digest,
            u32::try_from(candidates.len()).map_err(|_| {
                CognitiveStoreError::Invalid(
                    "owner retrieval candidate count exceeds u32".to_string(),
                )
            })?,
            completeness(channel_observation.limit),
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        batches.push(RetrievalGeneratorBatchV1 {
            receipt,
            candidates,
        });
    }
    GeneratedCandidateInputV1::new(batches)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
}

/// Current owner-native product profile. Four existing SQLite generators each
/// receive one quarter of the Q32 score range so their sum cannot saturate.
/// Learned policy reranking remains a downstream optional ordering stage.
pub fn sqlite_owner_retrieval_policy_v1() -> Result<RetrievalPolicyV1, CognitiveStoreError> {
    let quarter = FixedQ32::from_raw(1_i64 << 30);
    let channel_limit = u32::try_from(MAX_RETRIEVAL_CHANNEL_CANDIDATES).map_err(|_| {
        CognitiveStoreError::Invalid("retrieval channel bound exceeds u32".to_string())
    })?;
    let policy = RetrievalPolicyV1 {
        policy_id: StableId::new(OWNER_POLICY_ID)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: quarter,
                maximum_candidates: channel_limit,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: quarter,
                maximum_candidates: channel_limit,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Temporal,
                weight: quarter,
                maximum_candidates: channel_limit,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Graph,
                weight: quarter,
                maximum_candidates: channel_limit,
            },
        ],
        maximum_results: 16,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    policy
        .validate()
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    Ok(policy)
}

pub fn sqlite_owner_cue_profile_digest() -> Digest32 {
    Digest32::of_bytes(b"hepta.sqlite.retrieval-cue-profile.v1")
}

fn exact_snapshot_record(
    snapshot: &CognitiveSnapshot,
    binding: &MemoryRevalidationBinding,
) -> Result<MemoryRecord, CognitiveStoreError> {
    let content_digest: Digest32 = binding.content_sha256.as_str().parse().map_err(|error| {
        CognitiveStoreError::Corrupt(format!("invalid memory content digest: {error}"))
    })?;
    snapshot
        .records
        .iter()
        .find(|record| {
            record.record_id.as_str() == binding.memory.memory_id.as_str()
                && record.revision.get() == binding.memory.revision
                && record.content_digest == content_digest
        })
        .cloned()
        .ok_or_else(|| {
            CognitiveStoreError::Conflict(format!(
                "owner retrieval candidate {}@{} is outside the exact Lane C snapshot",
                binding.memory.memory_id.as_str(),
                binding.memory.revision
            ))
        })
}

fn reciprocal_rank_score(rank: u32) -> Result<FixedQ32, CognitiveStoreError> {
    if rank == 0 || usize::try_from(rank).unwrap_or(usize::MAX) > MAX_RETRIEVAL_CHANNEL_CANDIDATES {
        return Err(CognitiveStoreError::Corrupt(
            "owner retrieval channel rank is outside bounds".to_string(),
        ));
    }
    // Normalize the existing RRF component 1/(60+rank) so rank 1 == 1.0.
    let numerator = 61_u128 << 32;
    let denominator = 60_u128 + u128::from(rank);
    let raw = numerator / denominator;
    let raw = i64::try_from(raw).map_err(|_| {
        CognitiveStoreError::Corrupt("normalized retrieval rank overflow".to_string())
    })?;
    Ok(FixedQ32::from_raw(raw))
}

fn generator_for_channel(channel: RetrievalChannel) -> RetrievalGeneratorOwnerV1 {
    match channel {
        RetrievalChannel::MemoryFts => RetrievalGeneratorOwnerV1::CognitiveLexical,
        RetrievalChannel::EntityFts => RetrievalGeneratorOwnerV1::CognitiveEntity,
        RetrievalChannel::GraphOneHop => RetrievalGeneratorOwnerV1::CognitiveAssociative,
        RetrievalChannel::Recency => RetrievalGeneratorOwnerV1::CognitiveTemporal,
    }
}

fn completeness(limit: RetrievalLimitObservation) -> RetrievalSourceCompletenessV1 {
    match limit {
        RetrievalLimitObservation::Exhausted => RetrievalSourceCompletenessV1::Exhausted,
        RetrievalLimitObservation::LimitReached => RetrievalSourceCompletenessV1::LimitReached,
    }
}

fn owner_generation_digest(
    observation_digest: Digest32,
    channel: &RetrievalChannelObservation,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(OWNER_GENERATION_DOMAIN);
    bytes.extend_from_slice(observation_digest.as_array());
    bytes.push(owner_channel_code(channel.channel));
    bytes.extend_from_slice(
        &u64::try_from(channel.candidate_count)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.push(match channel.limit {
        RetrievalLimitObservation::Exhausted => 0,
        RetrievalLimitObservation::LimitReached => 1,
    });
    Digest32::of_bytes(&bytes)
}

fn owner_support_digest(
    observation_digest: Digest32,
    record: &MemoryRecord,
    rank: RetrievalChannelRank,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(OWNER_SUPPORT_DOMAIN);
    bytes.extend_from_slice(observation_digest.as_array());
    bytes.extend_from_slice(record.record_digest().as_array());
    bytes.push(owner_channel_code(rank.channel));
    bytes.extend_from_slice(&rank.rank.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

const fn owner_channel_code(channel: RetrievalChannel) -> u8 {
    match channel {
        RetrievalChannel::MemoryFts => 0,
        RetrievalChannel::EntityFts => 1,
        RetrievalChannel::GraphOneHop => 2,
        RetrievalChannel::Recency => 3,
    }
}

#[cfg(test)]
#[path = "cognitive_retrieval_adapter_tests.rs"]
mod tests;
