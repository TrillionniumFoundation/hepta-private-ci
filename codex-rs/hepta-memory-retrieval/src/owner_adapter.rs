//! Canonical adapter from the existing SQLite owner's bounded retrieval
//! observation into typed memory.retrieval channel batches.
//!
//! The adapter consumes owner-observed pre-fusion ranks and support digests.
//! Callers cannot replace those facts with arbitrary scores. The adapter does
//! not claim source completeness beyond the owner's explicit channel status.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::RetrievalChannelBatchV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelCompletenessV1;
use crate::RetrievalChannelV1;

const OWNER_RRF_K: u64 = 60;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum OwnerRetrievalChannelV1 {
    MemoryFts,
    EntityFts,
    GraphOneHop,
    Recency,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerChannelCompletenessV1 {
    Exhausted,
    LimitReached,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerChannelObservationV1 {
    pub channel: OwnerRetrievalChannelV1,
    pub candidate_count: u32,
    pub completeness: OwnerChannelCompletenessV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerChannelRankV1 {
    pub channel: OwnerRetrievalChannelV1,
    pub rank: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerObservedCandidateV1 {
    /// Canonical record admitted by the exact owner read cut.
    pub record: MemoryRecord,
    /// Digest of the owner-side revision/source revalidation facts.
    pub support_digest: Digest32,
    pub channel_ranks: Vec<OwnerChannelRankV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerRetrievalObservationV1 {
    /// Exact externally frozen Lane-C generation vector bound to this owner cut.
    pub generation_vector_digest: Digest32,
    pub channels: Vec<OwnerChannelObservationV1>,
    pub candidates: Vec<OwnerObservedCandidateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OwnerAdapterErrorV1 {
    EmptyGenerationVector,
    EmptySupportDigest,
    InvalidRecord(String),
    DuplicateOwnerChannel(OwnerRetrievalChannelV1),
    MissingOwnerChannel(OwnerRetrievalChannelV1),
    MissingCanonicalChannel(RetrievalChannelV1),
    EmptyOwnerCandidateChannels(String),
    DuplicateOwnerCandidateChannel(String),
    InvalidOwnerRank(String),
    CandidateCountMismatch(OwnerRetrievalChannelV1),
    Arithmetic,
    Identity,
}

impl fmt::Display for OwnerAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OwnerAdapterErrorV1 {}

struct BatchBuilder {
    channel: RetrievalChannelV1,
    producer_id: StableId,
    generator_profile_digest: Digest32,
    truncated: bool,
    candidates: Vec<RetrievalChannelCandidateV1>,
}

impl BatchBuilder {
    fn new(channel: RetrievalChannelV1) -> Result<Self, OwnerAdapterErrorV1> {
        let (producer, profile) = match channel {
            RetrievalChannelV1::Lexical => (
                "cognitive-store:sqlite-memory-fts",
                b"hepta.cognitive.sqlite-memory-fts.v1".as_slice(),
            ),
            RetrievalChannelV1::Entity => (
                "cognitive-store:sqlite-entity-graph",
                b"hepta.cognitive.sqlite-entity-graph.v1".as_slice(),
            ),
            RetrievalChannelV1::Temporal => (
                "cognitive-store:sqlite-recency",
                b"hepta.cognitive.sqlite-recency.v1".as_slice(),
            ),
            _ => return Err(OwnerAdapterErrorV1::Identity),
        };
        Ok(Self {
            channel,
            producer_id: StableId::new(producer).map_err(|_| OwnerAdapterErrorV1::Identity)?,
            generator_profile_digest: Digest32::of_bytes(profile),
            truncated: false,
            candidates: Vec::new(),
        })
    }

    fn finish(mut self, generation_vector_digest: Digest32) -> RetrievalChannelBatchV1 {
        self.candidates.sort_by(|left, right| {
            left.channel_rank
                .cmp(&right.channel_rank)
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        RetrievalChannelBatchV1 {
            channel: self.channel,
            producer_id: self.producer_id,
            generator_profile_digest: self.generator_profile_digest,
            generation_vector_digest,
            completeness: if self.truncated {
                RetrievalChannelCompletenessV1::Truncated {
                    omitted_at_least: 1,
                }
            } else {
                RetrievalChannelCompletenessV1::Exhausted
            },
            candidates: self.candidates,
        }
    }
}

fn canonical_channel(channel: OwnerRetrievalChannelV1) -> RetrievalChannelV1 {
    match channel {
        OwnerRetrievalChannelV1::MemoryFts => RetrievalChannelV1::Lexical,
        OwnerRetrievalChannelV1::EntityFts | OwnerRetrievalChannelV1::GraphOneHop => {
            RetrievalChannelV1::Entity
        }
        OwnerRetrievalChannelV1::Recency => RetrievalChannelV1::Temporal,
    }
}

/// RRF-normalized owner rank: rank 1 is exactly 1.0 and later ranks remain
/// monotone in [0,1]. This converts an observed rank, not a caller score.
fn normalized_owner_rank(rank: u32) -> Result<FixedQ32, OwnerAdapterErrorV1> {
    if rank == 0 {
        return Err(OwnerAdapterErrorV1::Arithmetic);
    }
    let numerator = i128::from(FixedQ32::ONE.raw()) * i128::from(OWNER_RRF_K + 1);
    let denominator = i128::from(OWNER_RRF_K + u64::from(rank));
    let raw = numerator / denominator;
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| OwnerAdapterErrorV1::Arithmetic)?,
    ))
}

/// Convert one exact owner observation into canonical retrieval generator batches.
///
/// Entity FTS and generic one-hop graph evidence are intentionally combined into
/// the Entity channel; the adapter does not mislabel arbitrary graph relations as
/// causal evidence. Vector, causal, procedural and contradiction-support batches
/// must come from their actual owners/producers when those capabilities exist.
pub fn adapt_owner_observation(
    observation: OwnerRetrievalObservationV1,
) -> Result<Vec<RetrievalChannelBatchV1>, OwnerAdapterErrorV1> {
    if observation.generation_vector_digest.is_zero() {
        return Err(OwnerAdapterErrorV1::EmptyGenerationVector);
    }

    let mut channel_facts = BTreeMap::new();
    for channel in &observation.channels {
        if channel_facts.insert(channel.channel, *channel).is_some() {
            return Err(OwnerAdapterErrorV1::DuplicateOwnerChannel(channel.channel));
        }
    }

    let observed_by_physical = observation
        .candidates
        .iter()
        .flat_map(|candidate| candidate.channel_ranks.iter().map(|rank| rank.channel))
        .fold(BTreeMap::<OwnerRetrievalChannelV1, usize>::new(), |mut counts, channel| {
            *counts.entry(channel).or_insert(0) += 1;
            counts
        });
    for fact in channel_facts.values() {
        let observed = observed_by_physical.get(&fact.channel).copied().unwrap_or(0);
        if observed > usize::try_from(fact.candidate_count).unwrap_or(usize::MAX) {
            return Err(OwnerAdapterErrorV1::CandidateCountMismatch(fact.channel));
        }
    }

    let mut builders = BTreeMap::<RetrievalChannelV1, BatchBuilder>::new();
    for channel in &observation.channels {
        let canonical = canonical_channel(channel.channel);
        let builder = match builders.entry(canonical) {
            std::collections::btree_map::Entry::Occupied(entry) => entry.into_mut(),
            std::collections::btree_map::Entry::Vacant(entry) => {
                entry.insert(BatchBuilder::new(canonical)?)
            }
        };
        if channel.completeness == OwnerChannelCompletenessV1::LimitReached {
            builder.truncated = true;
        }
    }

    for candidate in observation.candidates {
        candidate
            .record
            .validate()
            .map_err(|error| OwnerAdapterErrorV1::InvalidRecord(error.to_string()))?;
        if candidate.support_digest.is_zero() {
            return Err(OwnerAdapterErrorV1::EmptySupportDigest);
        }
        if candidate.channel_ranks.is_empty() {
            return Err(OwnerAdapterErrorV1::EmptyOwnerCandidateChannels(
                candidate.record.record_id.to_string(),
            ));
        }
        let mut seen_physical = BTreeSet::new();
        let mut best_canonical_rank = BTreeMap::<RetrievalChannelV1, u32>::new();
        for contribution in candidate.channel_ranks {
            if !seen_physical.insert(contribution.channel) {
                return Err(OwnerAdapterErrorV1::DuplicateOwnerCandidateChannel(
                    candidate.record.record_id.to_string(),
                ));
            }
            let Some(channel_fact) = channel_facts.get(&contribution.channel) else {
                return Err(OwnerAdapterErrorV1::MissingOwnerChannel(
                    contribution.channel,
                ));
            };
            if contribution.rank == 0 || contribution.rank > channel_fact.candidate_count {
                return Err(OwnerAdapterErrorV1::InvalidOwnerRank(
                    candidate.record.record_id.to_string(),
                ));
            }
            let canonical = canonical_channel(contribution.channel);
            best_canonical_rank
                .entry(canonical)
                .and_modify(|rank| *rank = (*rank).min(contribution.rank))
                .or_insert(contribution.rank);
        }
        for (channel, rank) in best_canonical_rank {
            let Some(builder) = builders.get_mut(&channel) else {
                return Err(OwnerAdapterErrorV1::MissingCanonicalChannel(channel));
            };
            builder.candidates.push(RetrievalChannelCandidateV1 {
                record: candidate.record.clone(),
                channel,
                channel_rank: rank,
                normalized_score: normalized_owner_rank(rank)?,
                // The SQLite lexical/entity/recency generator does not own an
                // OOD model. Zero is a neutral native value; product policies
                // that require calibrated OOD must use a producer that owns it.
                ood: ProbabilityQ32::ZERO,
                support_digest: candidate.support_digest,
                contradiction_group_digest: None,
                generation_vector_digest: observation.generation_vector_digest,
            });
        }
    }

    Ok(builders
        .into_values()
        .map(|builder| builder.finish(observation.generation_vector_digest))
        .collect())
}

#[cfg(test)]
#[path = "owner_adapter_tests.rs"]
mod tests;
