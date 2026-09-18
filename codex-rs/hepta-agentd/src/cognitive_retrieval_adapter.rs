//! Canonical owner-to-retrieval adapter for the Agentd composition boundary.
//!
//! The SQLite owner supplies identities, per-channel ranks and limit evidence.
//! This adapter derives normalized scores deterministically; callers never pass
//! learned or free-form scores into the retrieval engine through this path.

use std::collections::BTreeMap;

use codex_hepta_cognitive_read::ReadResultV2;
use codex_hepta_memory::RetrievalChannel as OwnerRetrievalChannel;
use codex_hepta_memory::RetrievalChannelRankObservation;
use codex_hepta_memory::RetrievalLimitObservation;
use codex_hepta_memory::RetrievalObservation;
use codex_hepta_memory_retrieval::RetrievalChannelBatchV1;
use codex_hepta_memory_retrieval::RetrievalChannelCandidateV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalCoverageV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

const SCORE_SCALE: u128 = 1_u128 << 32;
const ADAPTER_DOMAIN: &[u8] = b"hepta.agentd.owner-retrieval-adapter.v1";

/// Convert one exact owner observation and the coherent read result that admits
/// its records into canonical retrieval-channel batches.
///
/// The current SQLite generator has lexical, entity-FTS, one-hop graph and
/// recency channels. Entity FTS and generic one-hop graph evidence both map to
/// the target Entity channel; the adapter does not mislabel generic graph edges
/// as causal, procedural or contradiction evidence. OOD remains uncalibrated
/// and is therefore emitted as ONE so a stricter recall policy abstains.
pub fn adapt_owner_retrieval(
    observation: &RetrievalObservation,
    read: &ReadResultV2,
    generation_vector_digest: Digest32,
) -> Result<Vec<RetrievalChannelBatchV1>, String> {
    if generation_vector_digest.is_zero() {
        return Err("retrieval generation vector digest is empty".to_string());
    }

    let mut generated = BTreeMap::<RetrievalChannelV1, Vec<RetrievalChannelCandidateV1>>::new();
    for observed in observation.candidates() {
        let record = read
            .records()
            .iter()
            .find(|record| {
                record.record_id.as_str() == observed.revalidation.memory.memory_id.as_str()
                    && record.revision.get() == observed.revalidation.memory.revision
            })
            .cloned()
            .ok_or_else(|| {
                format!(
                    "owner retrieval candidate {}@{} is absent from the coherent read cut",
                    observed.revalidation.memory.memory_id.as_str(),
                    observed.revalidation.memory.revision
                )
            })?;

        let mut source_ranks =
            BTreeMap::<RetrievalChannelV1, Vec<RetrievalChannelRankObservation>>::new();
        for rank in &observed.channel_ranks {
            source_ranks
                .entry(target_channel(rank.channel))
                .or_default()
                .push(*rank);
        }
        if source_ranks.is_empty() {
            return Err(format!(
                "owner retrieval candidate {} has no channel-rank evidence",
                record.record_id
            ));
        }

        for (channel, mut ranks) in source_ranks {
            ranks.sort_by_key(|rank| rank.channel);
            let channel_rank = ranks
                .iter()
                .map(|rank| rank.rank)
                .min()
                .ok_or_else(|| "retrieval channel rank set is empty".to_string())?;
            generated
                .entry(channel)
                .or_default()
                .push(RetrievalChannelCandidateV1 {
                    support_digest: support_digest(
                        observation,
                        &record.record_digest(),
                        channel,
                        &ranks,
                    ),
                    record: record.clone(),
                    channel,
                    channel_rank,
                    normalized_score: reciprocal_rank_score(channel_rank)?,
                    ood: ProbabilityQ32::ONE,
                    contradiction_group_digest: None,
                    generation_vector_digest,
                });
        }
    }

    let mut batches = Vec::new();
    for channel in [
        RetrievalChannelV1::Lexical,
        RetrievalChannelV1::Entity,
        RetrievalChannelV1::Temporal,
    ] {
        let mut candidates = generated.remove(&channel).unwrap_or_default();
        candidates.sort_by(|left, right| {
            left.channel_rank
                .cmp(&right.channel_rank)
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        batches.push(RetrievalChannelBatchV1 {
            channel,
            generation_owner: channel.generation_owner(),
            source_generation_digest: generation_vector_digest,
            coverage: coverage_for_target(observation, channel),
            candidates,
        });
    }
    Ok(batches)
}

fn target_channel(channel: OwnerRetrievalChannel) -> RetrievalChannelV1 {
    match channel {
        OwnerRetrievalChannel::MemoryFts => RetrievalChannelV1::Lexical,
        OwnerRetrievalChannel::EntityFts | OwnerRetrievalChannel::GraphOneHop => {
            RetrievalChannelV1::Entity
        }
        OwnerRetrievalChannel::Recency => RetrievalChannelV1::Temporal,
    }
}

fn coverage_for_target(
    observation: &RetrievalObservation,
    target: RetrievalChannelV1,
) -> RetrievalCoverageV1 {
    let saturated = observation
        .channels()
        .iter()
        .filter(|row| target_channel(row.channel) == target)
        .filter(|row| row.limit == RetrievalLimitObservation::LimitReached)
        .count();
    if saturated == 0 {
        RetrievalCoverageV1::Exhausted
    } else {
        RetrievalCoverageV1::Truncated {
            omitted_lower_bound: u32::try_from(saturated).unwrap_or(u32::MAX),
        }
    }
}

fn reciprocal_rank_score(rank: u32) -> Result<FixedQ32, String> {
    if rank == 0 {
        return Err("owner retrieval channel rank must be nonzero".to_string());
    }
    let raw = SCORE_SCALE / u128::from(rank);
    let raw = i64::try_from(raw).map_err(|_| "retrieval score overflow".to_string())?;
    Ok(FixedQ32::from_raw(raw))
}

fn support_digest(
    observation: &RetrievalObservation,
    record_digest: &Digest32,
    target: RetrievalChannelV1,
    ranks: &[RetrievalChannelRankObservation],
) -> Digest32 {
    let mut bytes = ADAPTER_DOMAIN.to_vec();
    bytes.extend_from_slice(observation.observation_sha256().as_str().as_bytes());
    bytes.extend_from_slice(record_digest.as_array());
    bytes.push(target_code(target));
    for rank in ranks {
        bytes.push(owner_channel_code(rank.channel));
        bytes.extend_from_slice(&rank.rank.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

const fn owner_channel_code(channel: OwnerRetrievalChannel) -> u8 {
    match channel {
        OwnerRetrievalChannel::MemoryFts => 0,
        OwnerRetrievalChannel::EntityFts => 1,
        OwnerRetrievalChannel::GraphOneHop => 2,
        OwnerRetrievalChannel::Recency => 3,
    }
}

const fn target_code(channel: RetrievalChannelV1) -> u8 {
    match channel {
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
#[path = "cognitive_retrieval_adapter_tests.rs"]
mod tests;
