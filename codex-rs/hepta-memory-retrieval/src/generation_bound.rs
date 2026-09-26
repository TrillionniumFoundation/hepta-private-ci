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
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_cognitive_types::hnmf_learning::ActivationPathV1 as CanonicalActivationPathV1;
use codex_hepta_cognitive_types::hnmf_learning::ActiveNodeV1 as CanonicalActiveNodeV1;
use codex_hepta_cognitive_types::hnmf_learning::ContradictionV1 as CanonicalContradictionV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallAbstainReasonV1 as CanonicalRecallAbstainReasonV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1 as CanonicalRecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1 as CanonicalRecallResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SelectedEventRefV1 as CanonicalSelectedEventRefV1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::engram::EngramRecallReceiptV1;

pub const MAX_GENERATION_BOUND_CANDIDATES: usize = 512;
pub const MAX_GENERATION_BOUND_RESULTS: usize = 16;
const CUE_DOMAIN: &[u8] = b"hepta.memory-cue.v1";
const POLICY_DOMAIN: &[u8] = b"hepta.retrieval-policy.v1";
const CANDIDATE_UNION_DOMAIN: &[u8] = b"hepta.retrieval-candidate-union.v2";
const RECALL_PACKET_DOMAIN: &[u8] = b"hepta.recall-packet.v2";
const RETRIEVAL_CHANNEL_COUNT: u32 = 8;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RetrievalChannelV1 {
    Lexical,
    Vector,
    Entity,
    Temporal,
    Causal,
    Procedural,
    ContradictionSupport,
    /// Owner-native associative knowledge-graph expansion. This is not a
    /// claim that the relation is causal or procedural.
    Graph,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContradictionPolarityV1 {
    Supports,
    Opposes,
}

/// Proposition-scoped contradiction evidence. Two records conflict only when
/// they bind the same proposition and carry opposite polarities. Multiple
/// independent records on the same side are corroboration, not contradiction.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContradictionEvidenceV1 {
    pub proposition_digest: Digest32,
    pub polarity: ContradictionPolarityV1,
}

impl ContradictionEvidenceV1 {
    pub(crate) fn validate(&self) -> Result<(), RecallErrorV1> {
        ensure_digest("contradiction_proposition", self.proposition_digest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCueV1 {
    pub cue_id: StableId,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub request_digest: Digest32,
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
        ensure_digest("request", self.request_digest)?;
        ensure_digest("cue_profile", self.cue_profile_digest)
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CUE_DOMAIN);
        push_id(&mut bytes, &self.cue_id);
        push_digest(&mut bytes, self.objective_digest);
        push_digest(&mut bytes, self.approved_context_digest);
        push_digest(&mut bytes, self.request_digest);
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
        let mut channels = BTreeSet::new();
        let mut positive_weight_channels = 0_usize;
        for row in &self.channel_weights {
            if !channels.insert(row.channel) {
                return Err(RecallErrorV1::DuplicateChannelPolicy(row.channel));
            }
            if row.weight < FixedQ32::ZERO || row.weight > FixedQ32::ONE {
                return Err(RecallErrorV1::ScoreOutOfRange("channel_weight"));
            }
            if row.weight > FixedQ32::ZERO {
                positive_weight_channels = positive_weight_channels
                    .checked_add(1)
                    .ok_or(RecallErrorV1::Arithmetic)?;
            }
            let maximum_candidates = usize::try_from(row.maximum_candidates).unwrap_or(usize::MAX);
            if maximum_candidates == 0 || maximum_candidates > MAX_GENERATION_BOUND_CANDIDATES {
                return Err(RecallErrorV1::InvalidChannelLimit(row.channel));
            }
        }
        if self.channel_weights.is_empty() || positive_weight_channels == 0 {
            return Err(RecallErrorV1::EmptyChannelPolicy);
        }
        let minimum_distinct_channels =
            usize::try_from(self.minimum_distinct_channels).unwrap_or(usize::MAX);
        if minimum_distinct_channels == 0 || minimum_distinct_channels > positive_weight_channels {
            return Err(RecallErrorV1::InvalidMinimumCoverage);
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
    pub contradiction_evidence: Option<ContradictionEvidenceV1>,
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
        if let Some(evidence) = self.contradiction_evidence {
            evidence.validate()?;
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
    pub contradiction_evidence: Vec<ContradictionEvidenceV1>,
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
        let mut observed_channels = BTreeSet::new();
        let mut previous: Option<&CandidateUnionEntryV1> = None;
        for entry in &self.entries {
            entry
                .record
                .validate()
                .map_err(|error| RecallErrorV1::InvalidRecord(error.to_string()))?;
            if entry.record.state != RecordState::Live {
                return Err(RecallErrorV1::TombstoneCandidate(
                    entry.record.record_id.to_string(),
                ));
            }
            if !identities.insert((entry.record.record_id.clone(), entry.record.revision)) {
                return Err(RecallErrorV1::DuplicateUnionIdentity(
                    entry.record.record_id.to_string(),
                ));
            }
            if entry.weighted_score < FixedQ32::ZERO || entry.weighted_score > FixedQ32::ONE {
                return Err(RecallErrorV1::ScoreOutOfRange("union_weighted_score"));
            }
            if entry.channels.is_empty() || entry.support_digests.is_empty() {
                return Err(RecallErrorV1::InvalidUnionEntry(
                    entry.record.record_id.to_string(),
                ));
            }
            if !is_strictly_sorted_unique(&entry.channels) {
                return Err(RecallErrorV1::NonCanonicalCollection("union_channels"));
            }
            if !is_strictly_sorted_unique(&entry.support_digests)
                || entry.support_digests.iter().any(|digest| digest.is_zero())
            {
                return Err(RecallErrorV1::NonCanonicalCollection("union_support"));
            }
            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
            {
                return Err(RecallErrorV1::NonCanonicalCollection(
                    "union_contradiction_groups",
                ));
            }
            observed_channels.extend(entry.channels.iter().copied());
            if let Some(left) = previous {
                let ordered = left.weighted_score > entry.weighted_score
                    || (left.weighted_score == entry.weighted_score
                        && (left.record.record_id < entry.record.record_id
                            || (left.record.record_id == entry.record.record_id
                                && left.record.revision < entry.record.revision)));
                if !ordered {
                    return Err(RecallErrorV1::NonCanonicalCollection("union_entries"));
                }
            }
            previous = Some(entry);
        }
        if u32::try_from(observed_channels.len()).unwrap_or(u32::MAX) != self.distinct_channels {
            return Err(RecallErrorV1::InvalidUnionChannelCount);
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
            push_len(&mut bytes, entry.contradiction_evidence.len());
            for evidence in &entry.contradiction_evidence {
                push_digest(&mut bytes, evidence.proposition_digest);
                bytes.push(contradiction_polarity_code(evidence.polarity));
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
    pub contradiction_evidence: Vec<ContradictionEvidenceV1>,
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
    pub engram: Option<EngramRecallReceiptV1>,
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
            RecallDispositionV1::Abstained(_) if self.omitted_count != 0 => {
                return Err(RecallErrorV1::InvalidRecallDisposition);
            }
            RecallDispositionV1::Recalled if self.distinct_channels == 0 => {
                return Err(RecallErrorV1::InvalidRecallDisposition);
            }
            _ => {}
        }
        if self.selections.len() > MAX_GENERATION_BOUND_RESULTS {
            return Err(RecallErrorV1::InvalidMaximumResults);
        }
        let candidate_count = self
            .selections
            .len()
            .checked_add(usize::try_from(self.omitted_count).unwrap_or(usize::MAX))
            .ok_or(RecallErrorV1::CandidateLimitExceeded)?;
        if candidate_count > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(RecallErrorV1::CandidateLimitExceeded);
        }
        if self.distinct_channels > RETRIEVAL_CHANNEL_COUNT {
            return Err(RecallErrorV1::InvalidRecallChannelCount);
        }
        if let Some(engram) = &self.engram
            && self.disposition == RecallDispositionV1::Recalled
        {
            let engram_candidates =
                usize::try_from(engram.resources.candidate_records).unwrap_or(usize::MAX);
            if engram_candidates < self.selections.len() || engram_candidates > candidate_count {
                return Err(RecallErrorV1::InvalidEngram(
                    "engram candidate count is outside the admitted/full candidate bounds"
                        .to_string(),
                ));
            }
        }
        if self.authority.grants_any() {
            return Err(RecallErrorV1::AuthorityGranted);
        }
        if let Some(engram) = &self.engram {
            engram
                .validate()
                .map_err(|error| RecallErrorV1::InvalidEngram(error.to_string()))?;
            if engram.generation_vector_digest != self.generation_vector_digest {
                return Err(RecallErrorV1::InvalidEngram(
                    "engram generation differs from recall packet".to_string(),
                ));
            }
        }
        let mut identities = BTreeSet::new();
        let mut previous: Option<&RecallSelectionV1> = None;
        for selection in &self.selections {
            ensure_digest("selection_record", selection.record_digest)?;
            if selection.weighted_score < FixedQ32::ZERO || selection.weighted_score > FixedQ32::ONE
            {
                return Err(RecallErrorV1::ScoreOutOfRange("selection_weighted_score"));
            }
            if selection.channels.is_empty() || selection.support_digests.is_empty() {
                return Err(RecallErrorV1::InvalidRecallSelection(
                    selection.record_id.to_string(),
                ));
            }
            if !is_strictly_sorted_unique(&selection.channels)
                || !is_strictly_sorted_unique(&selection.support_digests)
                || selection
                    .support_digests
                    .iter()
                    .any(|digest| digest.is_zero())
                || !is_strictly_sorted_unique(&selection.contradiction_evidence)
                || selection
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
            {
                return Err(RecallErrorV1::NonCanonicalCollection("recall_selection"));
            }
            if !identities.insert((selection.record_id.clone(), selection.record_revision)) {
                return Err(RecallErrorV1::DuplicateRecallSelection(
                    selection.record_id.to_string(),
                ));
            }
            if let Some(left) = previous {
                let ordered = if let Some(engram) = &self.engram {
                    let left_activation = engram
                        .support_strength(&left.record_id, left.record_revision)
                        .ok_or_else(|| {
                            RecallErrorV1::InvalidEngram(
                                "selected record has no active engram support".to_string(),
                            )
                        })?;
                    let right_activation = engram
                        .support_strength(&selection.record_id, selection.record_revision)
                        .ok_or_else(|| {
                            RecallErrorV1::InvalidEngram(
                                "selected record has no active engram support".to_string(),
                            )
                        })?;
                    left_activation > right_activation
                        || (left_activation == right_activation
                            && (left.weighted_score > selection.weighted_score
                                || (left.weighted_score == selection.weighted_score
                                    && (left.record_id < selection.record_id
                                        || (left.record_id == selection.record_id
                                            && left.record_revision < selection.record_revision)))))
                } else {
                    left.weighted_score > selection.weighted_score
                        || (left.weighted_score == selection.weighted_score
                            && (left.record_id < selection.record_id
                                || (left.record_id == selection.record_id
                                    && left.record_revision < selection.record_revision)))
                };
                if !ordered {
                    return Err(RecallErrorV1::NonCanonicalCollection("recall_selections"));
                }
            } else if let Some(engram) = &self.engram
                && engram
                    .support_strength(&selection.record_id, selection.record_revision)
                    .is_none()
            {
                return Err(RecallErrorV1::InvalidEngram(
                    "selected record has no active engram support".to_string(),
                ));
            }
            previous = Some(selection);
        }
        let selected_channels = self
            .selections
            .iter()
            .flat_map(|selection| selection.channels.iter().copied())
            .collect::<BTreeSet<_>>();
        if u32::try_from(selected_channels.len()).unwrap_or(u32::MAX) > self.distinct_channels {
            return Err(RecallErrorV1::InvalidRecallChannelCount);
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
        match &self.engram {
            Some(engram) => {
                bytes.push(1);
                push_digest(&mut bytes, engram.receipt_digest);
            }
            None => bytes.push(0),
        }
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
            push_len(&mut bytes, selection.contradiction_evidence.len());
            for evidence in &selection.contradiction_evidence {
                push_digest(&mut bytes, evidence.proposition_digest);
                bytes.push(contradiction_polarity_code(evidence.polarity));
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Exact identity bridge for one legacy retrieval selection during the
/// side-by-side HNMF migration. The legacy record identity and the canonical
/// event identity are deliberately distinct fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalRecallSelectionBindingV1 {
    pub legacy_record_id: StableId,
    pub legacy_record_revision: Revision,
    pub legacy_record_digest: Digest32,
    pub canonical_event: CanonicalSelectedEventRefV1,
}

/// Extra HNMF evidence needed to project the legacy generation-bound packet
/// into the canonical cognitive.types RecallPacketV1 during shadow migration.
///
/// Canonical cue/event/engram digests are supplied explicitly because the
/// legacy binary digest domains are not interchangeable with canonical JSON
/// contract digests.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalRecallShadowContextV1 {
    pub legacy_cue_digest: Digest32,
    pub legacy_candidate_union_digest: Digest32,
    pub legacy_generation_vector_digest: Digest32,
    pub canonical_cue_digest: ContractDigestV1,
    pub selection_bindings: Vec<CanonicalRecallSelectionBindingV1>,
    pub event_snapshot_digest: ContractDigestV1,
    pub engram_snapshot_digest: ContractDigestV1,
    pub active_nodes: Vec<CanonicalActiveNodeV1>,
    pub activation_paths: Vec<CanonicalActivationPathV1>,
    pub contradictions: Vec<CanonicalContradictionV1>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub resource_receipt: CanonicalRecallResourceReceiptV1,
}

/// Side-by-side migration adapter from the existing retrieval receipt to the
/// canonical HNMF V1 contract.
///
/// This is a shadow projection only. It grants no attachment, model-call,
/// writer, selection, promotion, or release authority and does not replace the
/// legacy packet in place.
pub fn adapt_generation_bound_recall_to_canonical_shadow_v1(
    legacy: &RecallPacketV1,
    context: CanonicalRecallShadowContextV1,
) -> Result<CanonicalRecallPacketV1, RecallErrorV1> {
    legacy.validate()?;
    if context.legacy_cue_digest != legacy.cue_digest
        || context.legacy_candidate_union_digest != legacy.candidate_union_digest
        || context.legacy_generation_vector_digest != legacy.generation_vector_digest
    {
        return Err(RecallErrorV1::CanonicalAdapter(
            "canonical shadow context is bound to a different legacy packet",
        ));
    }

    let (mut selected_events, abstain) = match legacy.disposition {
        RecallDispositionV1::Recalled => {
            if context.selection_bindings.len() != legacy.selections.len() {
                return Err(RecallErrorV1::CanonicalAdapter(
                    "canonical selection binding count mismatch",
                ));
            }
            let mut used = vec![false; context.selection_bindings.len()];
            let mut selected = Vec::with_capacity(legacy.selections.len());
            for selection in &legacy.selections {
                let Some((index, binding)) =
                    context
                        .selection_bindings
                        .iter()
                        .enumerate()
                        .find(|(index, binding)| {
                            !used[*index]
                                && binding.legacy_record_id == selection.record_id
                                && binding.legacy_record_revision == selection.record_revision
                                && binding.legacy_record_digest == selection.record_digest
                        })
                else {
                    return Err(RecallErrorV1::CanonicalAdapter(
                        "missing exact canonical binding for legacy selection",
                    ));
                };
                used[index] = true;
                selected.push(binding.canonical_event.clone());
            }
            if used.iter().any(|used| !used) {
                return Err(RecallErrorV1::CanonicalAdapter(
                    "unused canonical selection binding",
                ));
            }
            (selected, None)
        }
        RecallDispositionV1::Abstained(reason) => {
            if !context.selection_bindings.is_empty() {
                return Err(RecallErrorV1::CanonicalAdapter(
                    "abstained legacy packet cannot carry canonical selection bindings",
                ));
            }
            (
                Vec::new(),
                Some(match reason {
                    RecallAbstentionReasonV1::NoCandidate => {
                        CanonicalRecallAbstainReasonV1::NoCandidate
                    }
                    RecallAbstentionReasonV1::InsufficientChannelCoverage => {
                        CanonicalRecallAbstainReasonV1::InsufficientCoverage
                    }
                    RecallAbstentionReasonV1::ScoreBelowFloor => {
                        CanonicalRecallAbstainReasonV1::LowConfidence
                    }
                    RecallAbstentionReasonV1::OutOfDistribution => {
                        CanonicalRecallAbstainReasonV1::OutOfDistribution
                    }
                    RecallAbstentionReasonV1::ContradictoryEvidence => {
                        CanonicalRecallAbstainReasonV1::UnresolvedContradiction
                    }
                }),
            )
        }
    };
    selected_events.sort();

    let minimum_candidates = selected_events
        .len()
        .checked_add(usize::try_from(legacy.omitted_count).unwrap_or(usize::MAX))
        .ok_or(RecallErrorV1::Arithmetic)?;
    if usize::from(context.resource_receipt.candidate_event_count) < minimum_candidates {
        return Err(RecallErrorV1::CanonicalAdapter(
            "candidate receipt undercounts legacy selected plus omitted events",
        ));
    }

    let canonical = CanonicalRecallPacketV1 {
        cue_digest: context.canonical_cue_digest,
        event_snapshot_digest: context.event_snapshot_digest,
        engram_snapshot_digest: context.engram_snapshot_digest,
        selected_events,
        active_nodes: context.active_nodes,
        activation_paths: context.activation_paths,
        contradictions: context.contradictions,
        coverage_ppm: context.coverage_ppm,
        confidence_ppm: context.confidence_ppm,
        ood_ppm: context.ood_ppm,
        abstain,
        resource_receipt: context.resource_receipt,
    };
    canonical
        .validate()
        .map_err(RecallErrorV1::CanonicalContract)?;
    Ok(canonical)
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
        if policy_row.weight == FixedQ32::ZERO {
            continue;
        }
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
            contradiction_evidence: BTreeSet::new(),
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
        if let Some(evidence) = candidate.contradiction_evidence {
            builder.contradiction_evidence.insert(evidence);
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

pub(crate) fn score_admitted_entries<'a>(
    entries: &'a [CandidateUnionEntryV1],
    policy: &RetrievalPolicyV1,
) -> Vec<&'a CandidateUnionEntryV1> {
    entries
        .iter()
        .filter(|entry| entry.weighted_score >= policy.minimum_total_score)
        .collect()
}

pub(crate) fn risk_admitted_entries<'a>(
    entries: &[&'a CandidateUnionEntryV1],
    policy: &RetrievalPolicyV1,
) -> Vec<&'a CandidateUnionEntryV1> {
    entries
        .iter()
        .copied()
        .filter(|entry| entry.maximum_ood <= policy.maximum_ood)
        .collect()
}

pub(crate) fn admitted_distinct_channel_count(entries: &[&CandidateUnionEntryV1]) -> usize {
    entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>()
        .len()
}

pub fn recall(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV1, RecallErrorV1> {
    let union = build_candidate_union(cue, policy, candidates)?;
    let score_admitted = score_admitted_entries(&union.entries, policy);
    let admitted = risk_admitted_entries(&score_admitted, policy);
    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let admitted_channels = admitted_distinct_channel_count(&admitted);
    let contradiction_count = contradiction_population_count(&admitted);
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if score_admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if admitted_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if policy.abstain_on_contradiction && contradiction_count > 0 {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new(), 0),
        None => {
            let selections = admitted
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
                    contradiction_evidence: entry.contradiction_evidence.clone(),
                })
                .collect::<Vec<_>>();
            let omitted_count = union.entries.len().saturating_sub(selections.len());
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
        distinct_channels: u32::try_from(admitted_channels).unwrap_or(u32::MAX),
        engram: None,
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
    contradiction_evidence: BTreeSet<ContradictionEvidenceV1>,
}

impl UnionBuilder {
    fn finish(self) -> CandidateUnionEntryV1 {
        CandidateUnionEntryV1 {
            record: self.record,
            channels: self.channels.into_iter().collect(),
            weighted_score: self.weighted_score,
            maximum_ood: self.maximum_ood,
            support_digests: self.support_digests.into_iter().collect(),
            contradiction_evidence: self.contradiction_evidence.into_iter().collect(),
        }
    }
}

pub(crate) fn contradiction_population_count(
    entries: &[&CandidateUnionEntryV1],
) -> usize {
    let mut populations = BTreeMap::<Digest32, u8>::new();
    for entry in entries {
        for evidence in &entry.contradiction_evidence {
            let flag = match evidence.polarity {
                ContradictionPolarityV1::Supports => 1,
                ContradictionPolarityV1::Opposes => 2,
            };
            *populations.entry(evidence.proposition_digest).or_insert(0) |= flag;
        }
    }
    populations.values().filter(|flags| **flags == 3).count()
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RecallErrorV1 {
    Contract(LaneCContractError),
    CanonicalContract(HnmfContractError),
    CanonicalAdapter(&'static str),
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
    InvalidUnionChannelCount,
    InvalidRecallChannelCount,
    InvalidRecallDisposition,
    InvalidRecallSelection(String),
    DuplicateRecallSelection(String),
    NonCanonicalCollection(&'static str),
    InvalidEngram(String),
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

fn is_strictly_sorted_unique<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
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
        RetrievalChannelV1::Graph => 7,
    }
}

const fn contradiction_polarity_code(value: ContradictionPolarityV1) -> u8 {
    match value {
        ContradictionPolarityV1::Supports => 0,
        ContradictionPolarityV1::Opposes => 1,
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
