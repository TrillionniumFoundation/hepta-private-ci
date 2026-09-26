//! Policy-admitted generation-bound recall semantics.
//!
//! The original V1 structures remain wire-compatible. This module wraps the
//! legacy constructors and validators, but changes decision semantics so OOD,
//! channel coverage and contradiction checks are evaluated only over the
//! policy-admitted set. Contradiction groups are proposition digests; polarity
//! is derived from the evidence channel (`ContradictionSupport` opposes, every
//! other admitted channel supports). Same-side evidence never conflicts.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

mod legacy {
    include!("generation_bound.rs");
}

pub use legacy::CandidateUnionEntryV1;
pub use legacy::CandidateUnionV1;
pub use legacy::CanonicalRecallSelectionBindingV1;
pub use legacy::CanonicalRecallShadowContextV1;
pub use legacy::MAX_GENERATION_BOUND_CANDIDATES;
pub use legacy::MAX_GENERATION_BOUND_RESULTS;
pub use legacy::MemoryCueV1;
pub use legacy::RecallAbstentionReasonV1;
pub use legacy::RecallDispositionV1;
pub use legacy::RecallErrorV1;
pub use legacy::RecallPacketV1;
pub use legacy::RecallSelectionV1;
pub use legacy::RetrievalChannelCandidateV1;
pub use legacy::RetrievalChannelV1;
pub use legacy::RetrievalChannelWeightV1;
pub use legacy::RetrievalPolicyV1;
pub use legacy::adapt_generation_bound_recall_to_canonical_shadow_v1;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContradictionPolarityV1 {
    Supports,
    Opposes,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContradictionEvidenceV1 {
    pub proposition_digest: Digest32,
    pub polarity: ContradictionPolarityV1,
}

impl RetrievalChannelCandidateV1 {
    #[must_use]
    pub fn contradiction_evidence(&self) -> Option<ContradictionEvidenceV1> {
        self.contradiction_group_digest
            .map(|proposition_digest| ContradictionEvidenceV1 {
                proposition_digest,
                polarity: polarity_for_channel(self.channel),
            })
    }
}

impl CandidateUnionEntryV1 {
    #[must_use]
    pub fn contradiction_evidence(&self) -> Vec<ContradictionEvidenceV1> {
        let polarities = self
            .channels
            .iter()
            .copied()
            .map(polarity_for_channel)
            .collect::<BTreeSet<_>>();
        let mut evidence = self
            .contradiction_group_digests
            .iter()
            .flat_map(|proposition_digest| {
                polarities.iter().map(move |polarity| ContradictionEvidenceV1 {
                    proposition_digest: *proposition_digest,
                    polarity: *polarity,
                })
            })
            .collect::<Vec<_>>();
        evidence.sort();
        evidence.dedup();
        evidence
    }
}

const fn polarity_for_channel(channel: RetrievalChannelV1) -> ContradictionPolarityV1 {
    if matches!(channel, RetrievalChannelV1::ContradictionSupport) {
        ContradictionPolarityV1::Opposes
    } else {
        ContradictionPolarityV1::Supports
    }
}

pub fn build_candidate_union(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<CandidateUnionV1, RecallErrorV1> {
    policy.validate()?;
    let weights = policy
        .channel_weights
        .iter()
        .map(|row| (row.channel, row.weight))
        .collect::<BTreeMap<_, _>>();
    let candidates = candidates
        .into_iter()
        .filter(|candidate| {
            weights
                .get(&candidate.channel)
                .map_or(true, |weight| *weight > FixedQ32::ZERO)
        })
        .collect();
    legacy::build_candidate_union(cue, policy, candidates)
}

pub fn recall(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV1, RecallErrorV1> {
    let union = build_candidate_union(cue, policy, candidates)?;
    let admitted = policy_admitted_union(&union, policy)?;
    let minimum_channels =
        usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let observed_channels = usize::try_from(admitted.distinct_channels).unwrap_or(0);
    let maximum_ood = admitted
        .entries
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(ProbabilityQ32::ZERO);
    let contradiction = contradiction_population_count(&admitted.entries) > 0;

    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted.entries.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if observed_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if contradiction && policy.abstain_on_contradiction {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = if let Some(reason) = reason {
        (RecallDispositionV1::Abstained(reason), Vec::new(), 0)
    } else {
        let selections = admitted
            .entries
            .iter()
            .take(maximum_results)
            .map(selection_from_entry)
            .collect::<Vec<_>>();
        if selections.is_empty() {
            (
                RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ScoreBelowFloor),
                Vec::new(),
                0,
            )
        } else {
            let omitted_count =
                u32::try_from(union.entries.len().saturating_sub(selections.len()))
                    .unwrap_or(u32::MAX);
            (RecallDispositionV1::Recalled, selections, omitted_count)
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
        distinct_channels: admitted.distinct_channels,
        engram: None,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate()?;
    Ok(packet)
}

pub(crate) fn policy_admitted_union(
    union: &CandidateUnionV1,
    policy: &RetrievalPolicyV1,
) -> Result<CandidateUnionV1, RecallErrorV1> {
    union.validate()?;
    policy.validate()?;
    let entries = union
        .entries
        .iter()
        .filter(|entry| entry.weighted_score >= policy.minimum_total_score)
        .cloned()
        .collect::<Vec<_>>();
    let channels = entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>();
    let mut admitted = CandidateUnionV1 {
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        generation_vector_digest: union.generation_vector_digest,
        entries,
        distinct_channels: u32::try_from(channels.len()).unwrap_or(u32::MAX),
        omitted_by_channel_limits: union.omitted_by_channel_limits,
        union_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    admitted.union_digest = admitted.compute_union_digest();
    admitted.validate()?;
    Ok(admitted)
}

pub(crate) fn contradiction_population_count(entries: &[CandidateUnionEntryV1]) -> usize {
    let mut groups = BTreeMap::<Digest32, BTreeSet<ContradictionPolarityV1>>::new();
    for evidence in entries
        .iter()
        .flat_map(CandidateUnionEntryV1::contradiction_evidence)
    {
        groups
            .entry(evidence.proposition_digest)
            .or_default()
            .insert(evidence.polarity);
    }
    groups
        .values()
        .filter(|polarities| {
            polarities.contains(&ContradictionPolarityV1::Supports)
                && polarities.contains(&ContradictionPolarityV1::Opposes)
        })
        .count()
}

fn selection_from_entry(entry: &CandidateUnionEntryV1) -> RecallSelectionV1 {
    RecallSelectionV1 {
        record_id: entry.record.record_id.clone(),
        record_revision: entry.record.revision,
        record_digest: entry.record.record_digest(),
        weighted_score: entry.weighted_score,
        maximum_ood: entry.maximum_ood,
        channels: entry.channels.clone(),
        support_digests: entry.support_digests.clone(),
        contradiction_group_digests: entry.contradiction_group_digests.clone(),
    }
}

#[cfg(test)]
#[path = "generation_bound_semantic_tests.rs"]
mod semantic_tests;
