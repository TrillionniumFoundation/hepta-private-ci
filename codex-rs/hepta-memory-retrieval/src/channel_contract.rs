//! Typed contract between bounded owner/channel generators and deterministic recall.
//!
//! The retrieval engine does not trust caller assertions of completeness. A host
//! executes each channel against one exact generation vector, then supplies one
//! batch per enabled positive-weight channel with explicit coverage semantics.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::CandidateUnionV1;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalChannelCompletenessV1 {
    /// The generator observed the end of its eligible source under this cut.
    Exhausted,
    /// A known channel bound was reached. More eligible rows may exist.
    Truncated,
    /// The source was only partially available; absence is not negative evidence.
    Partial,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelBatchV1 {
    pub channel: RetrievalChannelV1,
    pub generation_vector_digest: Digest32,
    pub candidates: Vec<RetrievalChannelCandidateV1>,
    pub completeness: RetrievalChannelCompletenessV1,
    /// Known lower bound on eligible candidates omitted before publication.
    pub omitted_lower_bound: u32,
}

impl RetrievalChannelBatchV1 {
    pub fn validate(
        &self,
        cue: &MemoryCueV1,
        policy: &RetrievalPolicyV1,
    ) -> Result<(), ChannelContractErrorV1> {
        cue.validate().map_err(ChannelContractErrorV1::Recall)?;
        policy.validate().map_err(ChannelContractErrorV1::Recall)?;
        if self.generation_vector_digest != cue.snapshot_key.vector_digest {
            return Err(ChannelContractErrorV1::GenerationVectorMismatch(self.channel));
        }
        let Some(row) = policy
            .channel_weights
            .iter()
            .find(|row| row.channel == self.channel)
        else {
            return Err(ChannelContractErrorV1::ChannelNotEnabled(self.channel));
        };
        if row.weight == FixedQ32::ZERO {
            return Err(ChannelContractErrorV1::ZeroWeightChannel(self.channel));
        }
        if self.candidates.len() > usize::try_from(row.maximum_candidates).unwrap_or(usize::MAX) {
            return Err(ChannelContractErrorV1::ChannelLimitExceeded(self.channel));
        }
        if matches!(self.completeness, RetrievalChannelCompletenessV1::Exhausted)
            && self.omitted_lower_bound != 0
        {
            return Err(ChannelContractErrorV1::InvalidCompleteness(self.channel));
        }
        if matches!(self.completeness, RetrievalChannelCompletenessV1::Truncated)
            && self.omitted_lower_bound == 0
        {
            return Err(ChannelContractErrorV1::InvalidCompleteness(self.channel));
        }
        let mut identities = BTreeSet::new();
        for candidate in &self.candidates {
            if candidate.channel != self.channel {
                return Err(ChannelContractErrorV1::MixedChannelBatch(self.channel));
            }
            if candidate.generation_vector_digest != self.generation_vector_digest {
                return Err(ChannelContractErrorV1::GenerationVectorMismatch(self.channel));
            }
            if !identities.insert((
                candidate.record.record_id.clone(),
                candidate.record.revision,
            )) {
                return Err(ChannelContractErrorV1::DuplicateCandidate(self.channel));
            }
        }
        Ok(())
    }
}

pub trait RetrievalChannelGeneratorV1 {
    fn channel(&self) -> RetrievalChannelV1;

    fn generate(
        &self,
        cue: &MemoryCueV1,
        maximum_candidates: u32,
    ) -> Result<RetrievalChannelBatchV1, ChannelContractErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelCoverageV1 {
    pub channel: RetrievalChannelV1,
    pub completeness: RetrievalChannelCompletenessV1,
    pub emitted_count: u32,
    pub omitted_lower_bound: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateUnionBuildV1 {
    pub union: CandidateUnionV1,
    pub coverage: Vec<RetrievalChannelCoverageV1>,
    pub coverage_digest: Digest32,
    pub all_enabled_channels_exhausted: bool,
}

impl CandidateUnionBuildV1 {
    pub fn validate(&self) -> Result<(), ChannelContractErrorV1> {
        self.union
            .validate()
            .map_err(ChannelContractErrorV1::Recall)?;
        if self.coverage.is_empty() {
            return Err(ChannelContractErrorV1::EmptyCoverage);
        }
        if self
            .coverage
            .windows(2)
            .any(|pair| pair[0].channel >= pair[1].channel)
        {
            return Err(ChannelContractErrorV1::NonCanonicalCoverage);
        }
        let all_exhausted = self
            .coverage
            .iter()
            .all(|row| row.completeness == RetrievalChannelCompletenessV1::Exhausted);
        if all_exhausted != self.all_enabled_channels_exhausted {
            return Err(ChannelContractErrorV1::CompletenessMismatch);
        }
        if self.coverage_digest != coverage_digest(&self.union, &self.coverage) {
            return Err(ChannelContractErrorV1::CoverageDigestMismatch);
        }
        Ok(())
    }
}

pub fn build_candidate_union_from_batches(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    batches: Vec<RetrievalChannelBatchV1>,
) -> Result<CandidateUnionBuildV1, ChannelContractErrorV1> {
    cue.validate().map_err(ChannelContractErrorV1::Recall)?;
    policy.validate().map_err(ChannelContractErrorV1::Recall)?;
    let enabled = policy
        .channel_weights
        .iter()
        .filter(|row| row.weight > FixedQ32::ZERO)
        .map(|row| row.channel)
        .collect::<BTreeSet<_>>();

    let mut by_channel = BTreeMap::new();
    for batch in batches {
        batch.validate(cue, policy)?;
        let channel = batch.channel;
        if by_channel.insert(channel, batch).is_some() {
            return Err(ChannelContractErrorV1::DuplicateChannelBatch(channel));
        }
    }
    for channel in &enabled {
        if !by_channel.contains_key(channel) {
            return Err(ChannelContractErrorV1::MissingChannelBatch(*channel));
        }
    }
    if by_channel.keys().any(|channel| !enabled.contains(channel)) {
        return Err(ChannelContractErrorV1::UnexpectedChannelBatch);
    }

    let mut candidates = Vec::new();
    let mut coverage = Vec::new();
    let mut upstream_omitted = 0_u32;
    for (channel, batch) in by_channel {
        upstream_omitted = upstream_omitted
            .checked_add(batch.omitted_lower_bound)
            .ok_or(ChannelContractErrorV1::Arithmetic)?;
        coverage.push(RetrievalChannelCoverageV1 {
            channel,
            completeness: batch.completeness,
            emitted_count: u32::try_from(batch.candidates.len()).unwrap_or(u32::MAX),
            omitted_lower_bound: batch.omitted_lower_bound,
        });
        candidates.extend(batch.candidates);
    }

    let mut union =
        build_candidate_union(cue, policy, candidates).map_err(ChannelContractErrorV1::Recall)?;
    union.omitted_by_channel_limits = union
        .omitted_by_channel_limits
        .checked_add(upstream_omitted)
        .ok_or(ChannelContractErrorV1::Arithmetic)?;
    union.union_digest = union.compute_union_digest();
    union.validate().map_err(ChannelContractErrorV1::Recall)?;

    let all_enabled_channels_exhausted = coverage
        .iter()
        .all(|row| row.completeness == RetrievalChannelCompletenessV1::Exhausted);
    let coverage_digest = coverage_digest(&union, &coverage);
    let result = CandidateUnionBuildV1 {
        union,
        coverage,
        coverage_digest,
        all_enabled_channels_exhausted,
    };
    result.validate()?;
    Ok(result)
}

fn coverage_digest(
    union: &CandidateUnionV1,
    coverage: &[RetrievalChannelCoverageV1],
) -> Digest32 {
    let mut bytes = b"hepta.retrieval-channel-coverage.v1".to_vec();
    bytes.extend_from_slice(union.union_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(coverage.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for row in coverage {
        bytes.push(channel_code(row.channel));
        bytes.push(match row.completeness {
            RetrievalChannelCompletenessV1::Exhausted => 0,
            RetrievalChannelCompletenessV1::Truncated => 1,
            RetrievalChannelCompletenessV1::Partial => 2,
        });
        bytes.extend_from_slice(&row.emitted_count.to_be_bytes());
        bytes.extend_from_slice(&row.omitted_lower_bound.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ChannelContractErrorV1 {
    Recall(RecallErrorV1),
    GenerationVectorMismatch(RetrievalChannelV1),
    ChannelNotEnabled(RetrievalChannelV1),
    ZeroWeightChannel(RetrievalChannelV1),
    ChannelLimitExceeded(RetrievalChannelV1),
    InvalidCompleteness(RetrievalChannelV1),
    MixedChannelBatch(RetrievalChannelV1),
    DuplicateCandidate(RetrievalChannelV1),
    DuplicateChannelBatch(RetrievalChannelV1),
    MissingChannelBatch(RetrievalChannelV1),
    UnexpectedChannelBatch,
    EmptyCoverage,
    NonCanonicalCoverage,
    CompletenessMismatch,
    CoverageDigestMismatch,
    Arithmetic,
}

impl fmt::Display for ChannelContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ChannelContractErrorV1 {}
