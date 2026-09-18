//! Composition-only adapter between the canonical SQLite owner observation and
//! the memory.retrieval generator contract.
//!
//! The caller must supply the exact externally frozen Lane-C generation-vector
//! digest. This module never fabricates prompt/model/authority generations.

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_memory::RetrievalChannel;
use codex_hepta_memory::RetrievalLimitObservation;
use codex_hepta_memory::RetrievalObservation;
use codex_hepta_memory_retrieval::OwnerChannelCompletenessV1;
use codex_hepta_memory_retrieval::OwnerChannelObservationV1;
use codex_hepta_memory_retrieval::OwnerChannelRankV1;
use codex_hepta_memory_retrieval::OwnerObservedCandidateV1;
use codex_hepta_memory_retrieval::OwnerRetrievalChannelV1;
use codex_hepta_memory_retrieval::OwnerRetrievalObservationV1;
use codex_hepta_memory_retrieval::RetrievalChannelBatchV1;
use codex_hepta_memory_retrieval::adapt_owner_observation;
use codex_hepta_types::Digest32;

fn owner_channel(channel: RetrievalChannel) -> OwnerRetrievalChannelV1 {
    match channel {
        RetrievalChannel::MemoryFts => OwnerRetrievalChannelV1::MemoryFts,
        RetrievalChannel::EntityFts => OwnerRetrievalChannelV1::EntityFts,
        RetrievalChannel::GraphOneHop => OwnerRetrievalChannelV1::GraphOneHop,
        RetrievalChannel::Recency => OwnerRetrievalChannelV1::Recency,
    }
}

pub fn adapt_sqlite_owner_observation(
    records: &[MemoryRecord],
    observation: &RetrievalObservation,
    generation_vector_digest: Digest32,
) -> Result<Vec<RetrievalChannelBatchV1>, String> {
    let channels = observation
        .channels()
        .iter()
        .map(|channel| {
            Ok(OwnerChannelObservationV1 {
                channel: owner_channel(channel.channel),
                candidate_count: u32::try_from(channel.candidate_count)
                    .map_err(|_| "owner channel candidate count overflow".to_string())?,
                completeness: match channel.limit {
                    RetrievalLimitObservation::Exhausted => {
                        OwnerChannelCompletenessV1::Exhausted
                    }
                    RetrievalLimitObservation::LimitReached => {
                        OwnerChannelCompletenessV1::LimitReached
                    }
                },
            })
        })
        .collect::<Result<Vec<_>, String>>()?;

    let mut candidates = Vec::with_capacity(observation.candidates().len());
    for observed in observation.candidates() {
        let record = records
            .iter()
            .find(|record| {
                record.record_id.as_str() == observed.revalidation.memory.memory_id.as_str()
                    && record.revision.get() == observed.revalidation.memory.revision
                    && record.content_digest.to_string()
                        == observed.revalidation.content_sha256.as_str()
            })
            .cloned()
            .ok_or_else(|| {
                format!(
                    "owner retrieval candidate {}@{} is absent from the exact read cut",
                    observed.revalidation.memory.memory_id.as_str(),
                    observed.revalidation.memory.revision
                )
            })?;
        let support_digest = observed
            .support_sha256
            .as_str()
            .parse::<Digest32>()
            .map_err(|error| error.to_string())?;
        candidates.push(OwnerObservedCandidateV1 {
            record,
            support_digest,
            channel_ranks: observed
                .channel_ranks
                .iter()
                .map(|rank| OwnerChannelRankV1 {
                    channel: owner_channel(rank.channel),
                    rank: rank.rank,
                })
                .collect(),
        });
    }

    adapt_owner_observation(OwnerRetrievalObservationV1 {
        generation_vector_digest,
        channels,
        candidates,
    })
    .map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "cognitive_retrieval_adapter_tests.rs"]
mod tests;
