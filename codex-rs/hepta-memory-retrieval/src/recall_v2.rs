//! Product recall semantics with bounded risk aggregation.
//!
//! V1 intentionally remains byte/behavior compatible.  V2 applies the target
//! 512/16 ceilings and evaluates coverage/OOD on the potential top-k horizon,
//! while contradiction groups touching that horizon are checked against the
//! complete bounded union.  Unrelated low-ranked candidates therefore cannot
//! force an abstention, but evidence contradicting a potential selection can.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::MAX_PRODUCT_RETRIEVAL_CANDIDATES;
use crate::MAX_PRODUCT_RETRIEVAL_RESULTS;
use crate::MemoryCueV1;
use crate::RecallAbstentionReasonV1;
use crate::RecallDispositionV1;
use crate::RecallErrorV1;
use crate::RecallSelectionV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;

const RECALL_PACKET_V2_DOMAIN: &[u8] = b"hepta.recall-packet.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallPacketV2 {
    pub receipt_version: u32,
    pub cue_digest: Digest32,
    pub policy_digest: Digest32,
    pub candidate_union_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub disposition: RecallDispositionV1,
    pub selections: Vec<RecallSelectionV1>,
    pub omitted_count: u32,
    /// Number of highest-ranked union entries that were eligible to become a
    /// returned result under this policy.  Risk aggregation is scoped here.
    pub risk_horizon_count: u32,
    /// Distinct channels represented inside the risk horizon, not the complete
    /// candidate union.  Low-ranked channels cannot satisfy coverage.
    pub risk_horizon_distinct_channels: u32,
    pub packet_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RecallPacketV2 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        for (name, digest) in [
            ("cue", self.cue_digest),
            ("policy", self.policy_digest),
            ("candidate_union", self.candidate_union_digest),
            ("generation_vector", self.generation_vector_digest),
            ("recall_packet_v2", self.packet_digest),
        ] {
            if digest.is_zero() {
                return Err(RecallErrorV1::EmptyDigest(name));
            }
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
        if self.selections.len() > MAX_PRODUCT_RETRIEVAL_RESULTS
            || usize::try_from(self.risk_horizon_count).unwrap_or(usize::MAX)
                > MAX_PRODUCT_RETRIEVAL_RESULTS
        {
            return Err(RecallErrorV1::InvalidMaximumResults);
        }
        if self.authority.grants_any() {
            return Err(RecallErrorV1::AuthorityGranted);
        }
        if self.packet_digest != self.compute_packet_digest() {
            return Err(RecallErrorV1::DigestMismatch("recall_packet_v2"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_packet_digest(&self) -> Digest32 {
        let mut bytes = RECALL_PACKET_V2_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.receipt_version.to_be_bytes());
        push_digest(&mut bytes, self.cue_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.candidate_union_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_disposition(&mut bytes, self.disposition);
        push_u64(&mut bytes, u64::from(self.omitted_count));
        push_u64(&mut bytes, u64::from(self.risk_horizon_count));
        push_u64(
            &mut bytes,
            u64::from(self.risk_horizon_distinct_channels),
        );
        push_len(&mut bytes, self.selections.len());
        for selection in &self.selections {
            push_id(&mut bytes, selection.record_id.as_str());
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

pub fn recall_v2(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV2, RecallErrorV1> {
    if candidates.len() > MAX_PRODUCT_RETRIEVAL_CANDIDATES {
        return Err(RecallErrorV1::CandidateLimitExceeded);
    }
    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(usize::MAX);
    if maximum_results == 0 || maximum_results > MAX_PRODUCT_RETRIEVAL_RESULTS {
        return Err(RecallErrorV1::InvalidMaximumResults);
    }
    for row in &policy.channel_weights {
        if usize::try_from(row.maximum_candidates).unwrap_or(usize::MAX)
            > MAX_PRODUCT_RETRIEVAL_CANDIDATES
        {
            return Err(RecallErrorV1::InvalidChannelLimit(row.channel));
        }
    }

    let union = build_candidate_union(cue, policy, candidates)?;
    let risk_horizon = union
        .entries
        .iter()
        .take(maximum_results)
        .collect::<Vec<_>>();
    let mut risk_channels = BTreeSet::new();
    let mut selected_contradiction_groups = BTreeSet::new();
    for entry in &risk_horizon {
        risk_channels.extend(entry.channels.iter().copied());
        selected_contradiction_groups.extend(entry.contradiction_group_digests.iter().copied());
    }

    let mut relevant_contradiction_population = BTreeMap::<Digest32, usize>::new();
    if policy.abstain_on_contradiction && !selected_contradiction_groups.is_empty() {
        for entry in &union.entries {
            for group in &entry.contradiction_group_digests {
                if selected_contradiction_groups.contains(group) {
                    *relevant_contradiction_population.entry(*group).or_insert(0) += 1;
                }
            }
        }
    }
    let has_relevant_contradiction = relevant_contradiction_population
        .values()
        .any(|count| *count > 1);
    let maximum_ood = risk_horizon
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(ProbabilityQ32::ZERO);
    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);

    let reason = if risk_horizon.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if risk_channels.len() < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if has_relevant_contradiction {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if risk_horizon[0].weighted_score < policy.minimum_total_score {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else {
        None
    };

    let omitted_count = union.entries.len().saturating_sub(maximum_results);
    let (disposition, selections) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new()),
        None => (
            RecallDispositionV1::Recalled,
            risk_horizon
                .iter()
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
                .collect(),
        ),
    };

    let mut packet = RecallPacketV2 {
        receipt_version: 2,
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        candidate_union_digest: union.union_digest,
        generation_vector_digest: union.generation_vector_digest,
        disposition,
        selections,
        omitted_count: u32::try_from(omitted_count).unwrap_or(u32::MAX),
        risk_horizon_count: u32::try_from(risk_horizon.len()).unwrap_or(u32::MAX),
        risk_horizon_distinct_channels: u32::try_from(risk_channels.len()).unwrap_or(u32::MAX),
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate()?;
    Ok(packet)
}

fn push_disposition(bytes: &mut Vec<u8>, value: RecallDispositionV1) {
    match value {
        RecallDispositionV1::Recalled => bytes.push(0),
        RecallDispositionV1::Abstained(reason) => {
            bytes.push(1);
            bytes.push(match reason {
                RecallAbstentionReasonV1::NoCandidate => 0,
                RecallAbstentionReasonV1::InsufficientChannelCoverage => 1,
                RecallAbstentionReasonV1::ScoreBelowFloor => 2,
                RecallAbstentionReasonV1::OutOfDistribution => 3,
                RecallAbstentionReasonV1::ContradictoryEvidence => 4,
            });
        }
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value.as_bytes());
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

#[cfg(test)]
#[path = "recall_v2_tests.rs"]
mod tests;
