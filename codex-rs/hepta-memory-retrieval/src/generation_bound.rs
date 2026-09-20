//! Generation-bound multi-channel recall.
//!
//! The legacy retrieval API remains a deterministic score sorter. This module
//! closes the cross-channel and snapshot gaps: every cue and candidate binds one
//! exact `CognitiveSnapshotKeyV1`; channel unions are order independent; scores
//! are range checked and policy weighted; stale, contradictory, low-coverage or
//! OOD candidate sets abstain instead of fabricating a confident recall.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_GENERATION_BOUND_CANDIDATES: usize = 16_384;
pub const MAX_GENERATION_BOUND_RESULTS: usize = 256;
const CUE_DOMAIN: &[u8] = b"hepta.memory-cue.v1";
const POLICY_DOMAIN: &[u8] = b"hepta.retrieval-policy.v1";
const CANDIDATE_UNION_DOMAIN: &[u8] = b"hepta.retrieval-candidate-union.v1";
const RECALL_PACKET_DOMAIN: &[u8] = b"hepta.recall-packet.v1";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RetrievalChannelV1 {
    Lexical,
    Vector,
    Entity,
    Temporal,
    Causal,
    Procedural,
    ContradictionSupport,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCueV1 {
    pub cue_id: StableId,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub cue_profile_digest: Digest32,
}

impl MemoryCueV1 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        self.snapshot_key
            .validate()
            .map_err(RecallErrorV1::Contract)?;
        ensure_digest("objective", self.objective_digest)?;
        ensure_digest("approved_context", self.approved_context_digest)?;
        ensure_digest("cue_profile", self.cue_profile_digest)
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CUE_DOMAIN);
        push_id(&mut bytes, &self.cue_id);
        push_digest(&mut bytes, self.objective_digest);
        push_digest(&mut bytes, self.approved_context_digest);
        push_digest(&mut bytes, self.snapshot_key.vector_digest);
        push_digest(&mut bytes, self.cue_profile_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelWeightV1 {
    pub channel: RetrievalChannelV1,
    pub weight: FixedQ32,
    pub maximum_candidates: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalPolicyV1 {
    pub policy_id: StableId,
    pub channel_weights: Vec<RetrievalChannelWeightV1>,
    pub maximum_results: u32,
    pub minimum_total_score: FixedQ32,
    pub maximum_ood: ProbabilityQ32,
    pub minimum_distinct_channels: u32,
    pub abstain_on_contradiction: bool,
}

impl RetrievalPolicyV1 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        let maximum_results = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_GENERATION_BOUND_RESULTS {
            return Err(RecallErrorV1::InvalidMaximumResults);
        }
        if self.minimum_total_score < FixedQ32::ZERO || self.minimum_total_score > FixedQ32::ONE {
            return Err(RecallErrorV1::ScoreOutOfRange("minimum_total_score"));
        }
        if self.minimum_distinct_channels == 0
            || usize::try_from(self.minimum_distinct_channels).unwrap_or(usize::MAX)
                > self.channel_weights.len()
        {
            return Err(RecallErrorV1::InvalidMinimumCoverage);
        }
        let mut channels = BTreeSet::new();
        let mut positive_weight = false;
        for row in &self.channel_weights {
            if !channels.insert(row.channel) {
                return Err(RecallErrorV1::DuplicateChannelPolicy(row.channel));
            }
            if row.weight < FixedQ32::ZERO || row.weight > FixedQ32::ONE {
                return Err(RecallErrorV1::ScoreOutOfRange("channel_weight"));
            }
            positive_weight |= row.weight > FixedQ32::ZERO;
            let maximum_candidates = usize::try_from(row.maximum_candidates).unwrap_or(usize::MAX);
            if maximum_candidates == 0 || maximum_candidates > MAX_GENERATION_BOUND_CANDIDATES {
                return Err(RecallErrorV1::InvalidChannelLimit(row.channel));
            }
        }
        if self.channel_weights.is_empty() || !positive_weight {
            return Err(RecallErrorV1::EmptyChannelPolicy);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut rows = self.channel_weights.iter().collect::<Vec<_>>();
        rows.sort_by_key(|row| row.channel);
        let mut bytes = Vec::new();
        bytes.extend_from_slice(POLICY_DOMAIN);
        push_id(&mut bytes, &self.policy_id);
        push_len(&mut bytes, rows.len());
        for row in rows {
            bytes.push(channel_code(row.channel));
            push_i64(&mut bytes, row.weight.raw());
            push_u64(&mut bytes, u64::from(row.maximum_candidates));
        }
        push_u64(&mut bytes, u64::from(self.maximum_results));
        push_i64(&mut bytes, self.minimum_total_score.raw());
        push_u64(&mut bytes, self.maximum_ood.raw());
        push_u64(&mut bytes, u64::from(self.minimum_distinct_channels));
        bytes.push(u8::from(self.abstain_on_contradiction));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalChannelCandidateV1 {
    pub record: MemoryRecord,
    pub channel: RetrievalChannelV1,
    pub channel_rank: u32,
    pub normalized_score: FixedQ32,
    pub ood: ProbabilityQ32,
    pub support_digest: Digest32,
    pub contradiction_group_digest: Option<Digest32>,
    pub generation_vector_digest: Digest32,
}

impl RetrievalChannelCandidateV1 {
    fn validate(&self, expected_generation_vector_digest: Digest32) -> Result<(), RecallErrorV1> {
        self.record
            .validate()
            .map_err(|error| RecallErrorV1::InvalidRecord(error.to_string()))?;
        if self.record.state != RecordState::Live {
            return Err(RecallErrorV1::TombstoneCandidate(
                self.record.record_id.to_string(),
            ));
        }
        if self.channel_rank == 0 {
            return Err(RecallErrorV1::ZeroChannelRank);
        }
        if self.normalized_score < FixedQ32::ZERO || self.normalized_score > FixedQ32::ONE {
            return Err(RecallErrorV1::ScoreOutOfRange("candidate_score"));
        }
        ensure_digest("candidate_support", self.support_digest)?;
        if let Some(group) = self.contradiction_group_digest {
            ensure_digest("contradiction_group", group)?;
        }
        ensure_digest("candidate_generation_vector", self.generation_vector_digest)?;
        if self.generation_vector_digest != expected_generation_vector_digest {
            return Err(RecallErrorV1::GenerationVectorMismatch(
                self.record.record_id.to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateUnionEntryV1 {
    pub record: MemoryRecord,
    pub channels: Vec<RetrievalChannelV1>,
    pub weighted_score: FixedQ32,
    pub maximum_ood: ProbabilityQ32,
    pub support_digests: Vec<Digest32>,
    pub contradiction_group_digests: Vec<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateUnionV1 {
    pub cue_digest: Digest32,
    pub policy_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub entries: Vec<CandidateUnionEntryV1>,
    pub distinct_channels: u32,
    pub omitted_by_channel_limits: u32,
    pub union_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CandidateUnionV1 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        for (name, digest) in [
            ("cue", self.cue_digest),
            ("policy", self.policy_digest),
            ("generation_vector", self.generation_vector_digest),
            ("candidate_union", self.union_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.entries.len() > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(RecallErrorV1::CandidateLimitExceeded);
        }
        if self.authority.grants_any() {
            return Err(RecallErrorV1::AuthorityGranted);
        }
        let mut identities = BTreeSet::new();
        for entry in &self.entries {
            if !identities.insert((entry.record.record_id.clone(), entry.record.revision)) {
                return Err(RecallErrorV1::DuplicateUnionIdentity(
                    entry.record.record_id.to_string(),
                ));
            }
            if entry.channels.is_empty() || entry.support_digests.is_empty() {
                return Err(RecallErrorV1::InvalidUnionEntry(
                    entry.record.record_id.to_string(),
                ));
            }
        }
        if self.union_digest != self.compute_union_digest() {
            return Err(RecallErrorV1::DigestMismatch("candidate_union"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_union_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANDIDATE_UNION_DOMAIN);
        push_digest(&mut bytes, self.cue_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_u64(&mut bytes, u64::from(self.distinct_channels));
        push_u64(&mut bytes, u64::from(self.omitted_by_channel_limits));
        push_len(&mut bytes, self.entries.len());
        for entry in &self.entries {
            push_id(&mut bytes, &entry.record.record_id);
            push_u64(&mut bytes, entry.record.revision.get());
            push_digest(&mut bytes, entry.record.record_digest());
            push_i64(&mut bytes, entry.weighted_score.raw());
            push_u64(&mut bytes, entry.maximum_ood.raw());
            push_len(&mut bytes, entry.channels.len());
            for channel in &entry.channels {
                bytes.push(channel_code(*channel));
            }
            push_len(&mut bytes, entry.support_digests.len());
            for digest in &entry.support_digests {
                push_digest(&mut bytes, *digest);
            }
            push_len(&mut bytes, entry.contradiction_group_digests.len());
            for digest in &entry.contradiction_group_digests {
                push_digest(&mut bytes, *digest);
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallAbstentionReasonV1 {
    NoCandidate,
    InsufficientChannelCoverage,
    ScoreBelowFloor,
    OutOfDistribution,
    ContradictoryEvidence,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallDispositionV1 {
    Recalled,
    Abstained(RecallAbstentionReasonV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallSelectionV1 {
    pub record_id: StableId,
    pub record_revision: Revision,
    pub record_digest: Digest32,
    pub weighted_score: FixedQ32,
    pub maximum_ood: ProbabilityQ32,
    pub channels: Vec<RetrievalChannelV1>,
    pub support_digests: Vec<Digest32>,
    pub contradiction_group_digests: Vec<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallPacketV1 {
    pub cue_digest: Digest32,
    pub policy_digest: Digest32,
    pub candidate_union_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub disposition: RecallDispositionV1,
    pub selections: Vec<RecallSelectionV1>,
    pub omitted_count: u32,
    pub distinct_channels: u32,
    pub packet_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RecallPacketV1 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        for (name, digest) in [
            ("cue", self.cue_digest),
            ("policy", self.policy_digest),
            ("candidate_union", self.candidate_union_digest),
            ("generation_vector", self.generation_vector_digest),
            ("recall_packet", self.packet_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        match self.disposition {
            RecallDispositionV1::Recalled if self.selections.is_empty() => {
                return Err(RecallErrorV1::InvalidRecallDisposition);
            }
            RecallDispositionV1::Abstained(_) if !self.selections.is_empty() => {
                return Err(RecallErrorV1::InvalidRecallDisposition);
            }
            _ => {}
        }
        if self.selections.len() > MAX_GENERATION_BOUND_RESULTS {
            return Err(RecallErrorV1::InvalidMaximumResults);
        }
        if self.authority.grants_any() {
            return Err(RecallErrorV1::AuthorityGranted);
        }
        if self.packet_digest != self.compute_packet_digest() {
            return Err(RecallErrorV1::DigestMismatch("recall_packet"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_packet_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RECALL_PACKET_DOMAIN);
        push_digest(&mut bytes, self.cue_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.candidate_union_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_recall_disposition(&mut bytes, self.disposition);
        push_u64(&mut bytes, u64::from(self.omitted_count));
        push_u64(&mut bytes, u64::from(self.distinct_channels));
        push_len(&mut bytes, self.selections.len());
        for selection in &self.selections {
            push_id(&mut bytes, &selection.record_id);
            push_u64(&mut bytes, selection.record_revision.get());
            push_digest(&mut bytes, selection.record_digest);
            push_i64(&mut bytes, selection.weighted_score.raw());
            push_u64(&mut bytes, selection.maximum_ood.raw());
            push_len(&mut bytes, selection.channels.len());
            for channel in &selection.channels {
                bytes.push(channel_code(*channel));
            }
            push_len(&mut bytes, selection.support_digests.len());
            for digest in &selection.support_digests {
                push_digest(&mut bytes, *digest);
            }
            push_len(&mut bytes, selection.contradiction_group_digests.len());
            for digest in &selection.contradiction_group_digests {
                push_digest(&mut bytes, *digest);
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_candidate_union(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<CandidateUnionV1, RecallErrorV1> {
    cue.validate()?;
    policy.validate()?;
    if candidates.len() > MAX_GENERATION_BOUND_CANDIDATES {
        return Err(RecallErrorV1::CandidateLimitExceeded);
    }
    let generation_vector_digest = cue.snapshot_key.vector_digest;
    let policy_rows = policy
        .channel_weights
        .iter()
        .map(|row| (row.channel, row))
        .collect::<BTreeMap<_, _>>();
    let mut per_channel_counts = BTreeMap::<RetrievalChannelV1, u32>::new();
    let mut distinct_channels = BTreeSet::new();
    let mut omitted_by_channel_limits = 0_u32;
    let mut seen_channel_identity = BTreeSet::new();
    let mut union = BTreeMap::<(StableId, Revision), UnionBuilder>::new();

    let mut candidates = candidates;
    candidates.sort_by(|left, right| {
        left.channel
            .cmp(&right.channel)
            .then_with(|| left.channel_rank.cmp(&right.channel_rank))
            .then_with(|| left.record.record_id.cmp(&right.record.record_id))
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });

    for candidate in candidates {
        candidate.validate(generation_vector_digest)?;
        let Some(policy_row) = policy_rows.get(&candidate.channel) else {
            return Err(RecallErrorV1::ChannelNotEnabled(candidate.channel));
        };
        let identity = (
            candidate.record.record_id.clone(),
            candidate.record.revision,
        );
        if !seen_channel_identity.insert((candidate.channel, identity.clone())) {
            return Err(RecallErrorV1::DuplicateChannelCandidate(
                candidate.record.record_id.to_string(),
            ));
        }
        let count = per_channel_counts.entry(candidate.channel).or_insert(0);
        if *count >= policy_row.maximum_candidates {
            omitted_by_channel_limits = omitted_by_channel_limits
                .checked_add(1)
                .ok_or(RecallErrorV1::Arithmetic)?;
            continue;
        }
        *count += 1;
        distinct_channels.insert(candidate.channel);
        let weighted = candidate
            .normalized_score
            .checked_mul(policy_row.weight)
            .map_err(|_| RecallErrorV1::Arithmetic)?;
        let builder = union.entry(identity).or_insert_with(|| UnionBuilder {
            record: candidate.record.clone(),
            channels: BTreeSet::new(),
            weighted_score: FixedQ32::ZERO,
            maximum_ood: ProbabilityQ32::ZERO,
            support_digests: BTreeSet::new(),
            contradiction_group_digests: BTreeSet::new(),
        });
        if builder.record.record_digest() != candidate.record.record_digest() {
            return Err(RecallErrorV1::ConflictingRecordRevision(
                candidate.record.record_id.to_string(),
            ));
        }
        builder.channels.insert(candidate.channel);
        builder.weighted_score = builder
            .weighted_score
            .checked_add(weighted)
            .map_err(|_| RecallErrorV1::Arithmetic)?
            .clamp(FixedQ32::ZERO, FixedQ32::ONE)
            .map_err(|_| RecallErrorV1::Arithmetic)?;
        if candidate.ood > builder.maximum_ood {
            builder.maximum_ood = candidate.ood;
        }
        builder.support_digests.insert(candidate.support_digest);
        if let Some(group) = candidate.contradiction_group_digest {
            builder.contradiction_group_digests.insert(group);
        }
    }

    let mut entries = union
        .into_values()
        .map(UnionBuilder::finish)
        .collect::<Vec<_>>();
    entries.sort_by(|left, right| {
        right
            .weighted_score
            .cmp(&left.weighted_score)
            .then_with(|| left.record.record_id.cmp(&right.record.record_id))
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });
    let mut result = CandidateUnionV1 {
        cue_digest: cue.digest(),
        policy_digest: policy.digest(),
        generation_vector_digest,
        entries,
        distinct_channels: u32::try_from(distinct_channels.len()).unwrap_or(u32::MAX),
        omitted_by_channel_limits,
        union_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.union_digest = result.compute_union_digest();
    result.validate()?;
    Ok(result)
}

pub fn recall(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV1, RecallErrorV1> {
    let union = build_candidate_union(cue, policy, candidates)?;
    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let observed_channels = usize::try_from(union.distinct_channels).unwrap_or(0);
    let contradiction_count = contradiction_population_count(&union.entries);
    let maximum_ood = union
        .entries
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(ProbabilityQ32::ZERO);
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if observed_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if policy.abstain_on_contradiction && contradiction_count > 0 {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if union.entries[0].weighted_score < policy.minimum_total_score {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new(), 0),
        None => {
            let omitted_count = union.entries.len().saturating_sub(maximum_results);
            let selections = union
                .entries
                .iter()
                .take(maximum_results)
                .map(|entry| RecallSelectionV1 {
                    record_id: entry.record.record_id.clone(),
                    record_revision: entry.record.revision,
                    record_digest: entry.record.record_digest(),
                    weighted_score: entry.weighted_score,
                    maximum_ood: entry.maximum_ood,
                    channels: entry.channels.clone(),
                    support_digests: entry.support_digests.clone(),
                    contradiction_group_digests: entry.contradiction_group_digests.clone(),
                })
                .collect();
            (
                RecallDispositionV1::Recalled,
                selections,
                u32::try_from(omitted_count).unwrap_or(u32::MAX),
            )
        }
    };
    let mut packet = RecallPacketV1 {
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        candidate_union_digest: union.union_digest,
        generation_vector_digest: union.generation_vector_digest,
        disposition,
        selections,
        omitted_count,
        distinct_channels: union.distinct_channels,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate()?;
    Ok(packet)
}

struct UnionBuilder {
    record: MemoryRecord,
    channels: BTreeSet<RetrievalChannelV1>,
    weighted_score: FixedQ32,
    maximum_ood: ProbabilityQ32,
    support_digests: BTreeSet<Digest32>,
    contradiction_group_digests: BTreeSet<Digest32>,
}

impl UnionBuilder {
    fn finish(self) -> CandidateUnionEntryV1 {
        CandidateUnionEntryV1 {
            record: self.record,
            channels: self.channels.into_iter().collect(),
            weighted_score: self.weighted_score,
            maximum_ood: self.maximum_ood,
            support_digests: self.support_digests.into_iter().collect(),
            contradiction_group_digests: self.contradiction_group_digests.into_iter().collect(),
        }
    }
}

fn contradiction_population_count(entries: &[CandidateUnionEntryV1]) -> usize {
    let mut populations = BTreeMap::<Digest32, usize>::new();
    for entry in entries {
        for group in &entry.contradiction_group_digests {
            *populations.entry(*group).or_insert(0) += 1;
        }
    }
    populations.values().filter(|count| **count > 1).count()
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RecallErrorV1 {
    Contract(LaneCContractError),
    EmptyDigest(&'static str),
    EmptyChannelPolicy,
    DuplicateChannelPolicy(RetrievalChannelV1),
    InvalidChannelLimit(RetrievalChannelV1),
    ChannelNotEnabled(RetrievalChannelV1),
    InvalidMaximumResults,
    InvalidMinimumCoverage,
    CandidateLimitExceeded,
    DuplicateChannelCandidate(String),
    ConflictingRecordRevision(String),
    GenerationVectorMismatch(String),
    InvalidRecord(String),
    TombstoneCandidate(String),
    ZeroChannelRank,
    ScoreOutOfRange(&'static str),
    DuplicateUnionIdentity(String),
    InvalidUnionEntry(String),
    InvalidRecallDisposition,
    DigestMismatch(&'static str),
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for RecallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RecallErrorV1 {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), RecallErrorV1> {
    if digest.is_zero() {
        return Err(RecallErrorV1::EmptyDigest(name));
    }
    Ok(())
}

fn push_recall_disposition(bytes: &mut Vec<u8>, value: RecallDispositionV1) {
    match value {
        RecallDispositionV1::Recalled => bytes.push(0),
        RecallDispositionV1::Abstained(reason) => {
            bytes.push(1);
            bytes.push(abstention_reason_code(reason));
        }
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
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

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
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

const fn abstention_reason_code(value: RecallAbstentionReasonV1) -> u8 {
    match value {
        RecallAbstentionReasonV1::NoCandidate => 0,
        RecallAbstentionReasonV1::InsufficientChannelCoverage => 1,
        RecallAbstentionReasonV1::ScoreBelowFloor => 2,
        RecallAbstentionReasonV1::OutOfDistribution => 3,
        RecallAbstentionReasonV1::ContradictoryEvidence => 4,
    }
}

#[cfg(test)]
#[path = "generation_bound_tests.rs"]
mod tests;
