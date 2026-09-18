//! Typed cue compilation and bounded retrieval-channel generation contracts.
//!
//! This module keeps candidate generation separate from recall. A caller cannot
//! relabel one channel as another: every channel has one declared generation
//! owner role and every batch carries explicit completeness and generation
//! evidence before it is admitted to the canonical union.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CandidateUnionV1;
use crate::MAX_GENERATION_BOUND_CANDIDATES;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCueCompileRequestV1 {
    pub cue_id: StableId,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub cue_profile_digest: Digest32,
}

pub fn compile_cue(request: MemoryCueCompileRequestV1) -> Result<MemoryCueV1, RecallErrorV1> {
    let cue = MemoryCueV1 {
        cue_id: request.cue_id,
        objective_digest: request.objective_digest,
        approved_context_digest: request.approved_context_digest,
        snapshot_key: request.snapshot_key,
        cue_profile_digest: request.cue_profile_digest,
    };
    cue.validate()?;
    Ok(cue)
}

/// Role that owns the generation digest for one retrieval channel.
///
/// These are contract roles, not authority grants. The real host must obtain
/// the digest from the named owner and bind it into the frozen snapshot.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RetrievalGenerationOwnerV1 {
    CognitiveRead,
    KnowledgeGraph,
    EncoderProjection,
    ProcedureProjection,
}

impl RetrievalChannelV1 {
    pub const fn generation_owner(self) -> RetrievalGenerationOwnerV1 {
        match self {
            Self::Lexical | Self::Temporal => RetrievalGenerationOwnerV1::CognitiveRead,
            Self::Entity | Self::Causal | Self::ContradictionSupport => {
                RetrievalGenerationOwnerV1::KnowledgeGraph
            }
            Self::Vector => RetrievalGenerationOwnerV1::EncoderProjection,
            Self::Procedural => RetrievalGenerationOwnerV1::ProcedureProjection,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalCoverageV1 {
    Exhausted,
    Truncated { omitted_lower_bound: u32 },
    Unavailable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelBatchV1 {
    pub channel: RetrievalChannelV1,
    pub generation_owner: RetrievalGenerationOwnerV1,
    pub source_generation_digest: Digest32,
    pub coverage: RetrievalCoverageV1,
    pub candidates: Vec<RetrievalChannelCandidateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelCoverageV1 {
    pub channel: RetrievalChannelV1,
    pub generation_owner: RetrievalGenerationOwnerV1,
    pub source_generation_digest: Digest32,
    pub coverage: RetrievalCoverageV1,
    pub admitted_candidates: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalCandidateUnionV1 {
    pub union: CandidateUnionV1,
    pub coverage: Vec<RetrievalChannelCoverageV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ChannelContractErrorV1 {
    Recall(RecallErrorV1),
    DuplicateChannelBatch(RetrievalChannelV1),
    WrongGenerationOwner(RetrievalChannelV1),
    EmptySourceGeneration(RetrievalChannelV1),
    InvalidTruncation(RetrievalChannelV1),
    UnavailableChannelHasCandidates(RetrievalChannelV1),
    CandidateChannelMismatch(RetrievalChannelV1),
    CandidateLimitExceeded,
}

impl fmt::Display for ChannelContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ChannelContractErrorV1 {}

impl From<RecallErrorV1> for ChannelContractErrorV1 {
    fn from(error: RecallErrorV1) -> Self {
        Self::Recall(error)
    }
}

impl RetrievalChannelBatchV1 {
    pub fn validate(&self) -> Result<(), ChannelContractErrorV1> {
        if self.generation_owner != self.channel.generation_owner() {
            return Err(ChannelContractErrorV1::WrongGenerationOwner(self.channel));
        }
        if self.source_generation_digest.is_zero() {
            return Err(ChannelContractErrorV1::EmptySourceGeneration(self.channel));
        }
        match self.coverage {
            RetrievalCoverageV1::Truncated {
                omitted_lower_bound: 0,
            } => return Err(ChannelContractErrorV1::InvalidTruncation(self.channel)),
            RetrievalCoverageV1::Unavailable if !self.candidates.is_empty() => {
                return Err(ChannelContractErrorV1::UnavailableChannelHasCandidates(
                    self.channel,
                ));
            }
            RetrievalCoverageV1::Exhausted
            | RetrievalCoverageV1::Truncated { .. }
            | RetrievalCoverageV1::Unavailable => {}
        }
        if self.candidates.len() > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(ChannelContractErrorV1::CandidateLimitExceeded);
        }
        if self
            .candidates
            .iter()
            .any(|candidate| candidate.channel != self.channel)
        {
            return Err(ChannelContractErrorV1::CandidateChannelMismatch(
                self.channel,
            ));
        }
        Ok(())
    }
}

pub fn build_candidate_union_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<RetrievalCandidateUnionV1, ChannelContractErrorV1> {
    cue.validate()?;
    policy.validate()?;

    let mut seen = BTreeSet::new();
    let mut total_candidates = 0_usize;
    let mut coverage = Vec::with_capacity(batches.len());
    let mut candidates = Vec::new();

    for batch in batches {
        batch.validate()?;
        if !seen.insert(batch.channel) {
            return Err(ChannelContractErrorV1::DuplicateChannelBatch(
                batch.channel,
            ));
        }
        total_candidates = total_candidates
            .checked_add(batch.candidates.len())
            .ok_or(ChannelContractErrorV1::CandidateLimitExceeded)?;
        if total_candidates > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(ChannelContractErrorV1::CandidateLimitExceeded);
        }
        coverage.push(RetrievalChannelCoverageV1 {
            channel: batch.channel,
            generation_owner: batch.generation_owner,
            source_generation_digest: batch.source_generation_digest,
            coverage: batch.coverage,
            admitted_candidates: u32::try_from(batch.candidates.len()).unwrap_or(u32::MAX),
        });
        candidates.extend(batch.candidates);
    }

    coverage.sort_by_key(|row| row.channel);
    let union = build_candidate_union(cue, policy, candidates)?;
    Ok(RetrievalCandidateUnionV1 { union, coverage })
}

#[cfg(test)]
#[path = "channel_contract_tests.rs"]
mod tests;
