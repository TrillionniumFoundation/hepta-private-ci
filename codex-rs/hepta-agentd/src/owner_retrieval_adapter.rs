//! Single adapter from the canonical SQLite owner observation to memory.retrieval.
//!
//! It maps only semantics the owner actually proves. Generic graph one-hop
//! evidence is intentionally not relabeled as causal/procedural evidence.
//! Owner channel saturation is Partial because the current SQL limit witness
//! does not prove that an omitted row actually exists.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_read::AuthoritativeReadResultV1;
use codex_hepta_memory::RetrievalChannel;
use codex_hepta_memory::RetrievalLimitObservation;
use codex_hepta_memory::RetrievalObservation;
use codex_hepta_memory_retrieval::MemoryCueV1;
use codex_hepta_memory_retrieval::RetrievalChannelBatchV1;
use codex_hepta_memory_retrieval::RetrievalChannelCandidateV1;
use codex_hepta_memory_retrieval::RetrievalChannelCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

pub fn adapt_owner_retrieval(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    read: &AuthoritativeReadResultV1,
    observation: &RetrievalObservation,
) -> Result<Vec<RetrievalChannelBatchV1>, String> {
    cue.validate().map_err(|error| error.to_string())?;
    policy.validate().map_err(|error| error.to_string())?;
    if read.generation_vector_digest != cue.snapshot_key.vector_digest {
        return Err("authoritative read and retrieval cue generation differ".to_string());
    }

    let enabled = policy
        .channel_weights
        .iter()
        .filter(|row| row.weight > FixedQ32::ZERO)
        .map(|row| row.channel)
        .collect::<BTreeSet<_>>();
    let supported = [
        RetrievalChannelV1::Lexical,
        RetrievalChannelV1::Entity,
        RetrievalChannelV1::Temporal,
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    if let Some(channel) = enabled.iter().find(|channel| !supported.contains(channel)) {
        return Err(format!(
            "owner retrieval adapter cannot prove channel semantics for {channel:?}"
        ));
    }

    let records = read
        .read_result
        .records()
        .iter()
        .map(|record| {
            (
                (record.record_id.as_str().to_string(), record.revision.get()),
                record,
            )
        })
        .collect::<BTreeMap<_, _>>();
    let channel_observations = observation
        .channels()
        .iter()
        .map(|row| (row.channel, row))
        .collect::<BTreeMap<_, _>>();

    let mut by_channel =
        BTreeMap::<RetrievalChannelV1, Vec<RetrievalChannelCandidateV1>>::new();
    for owner_candidate in observation.materialized_candidates() {
        let key = (
            owner_candidate.memory.id.memory_id.as_str().to_string(),
            owner_candidate.memory.id.revision,
        );
        let Some(record) = records.get(&key) else {
            continue;
        };
        if record.content_digest.to_string() != owner_candidate.memory.content_sha256.as_str() {
            continue;
        }
        for (owner_channel, rank) in &owner_candidate.channel_ranks {
            let Some(channel) = map_owner_channel(*owner_channel) else {
                continue;
            };
            if !enabled.contains(&channel) || *rank == 0 {
                continue;
            }
            let raw = FixedQ32::ONE.raw() / i64::from(*rank);
            let support_digest = owner_support_digest(
                observation,
                record.record_digest(),
                *owner_channel,
                *rank,
            );
            by_channel
                .entry(channel)
                .or_default()
                .push(RetrievalChannelCandidateV1 {
                    record: (*record).clone(),
                    channel,
                    channel_rank: *rank,
                    normalized_score: FixedQ32::from_raw(raw),
                    // The legacy owner does not produce an OOD estimate. Use
                    // the fail-closed worst case rather than fabricating confidence.
                    ood: ProbabilityQ32::ONE,
                    support_digest,
                    contradiction_group_digest: None,
                    generation_vector_digest: cue.snapshot_key.vector_digest,
                });
        }
    }

    let mut batches = Vec::new();
    for channel in enabled {
        let owner_channel = reverse_owner_channel(channel)
            .ok_or_else(|| format!("unsupported owner channel mapping for {channel:?}"))?;
        let observation_row = channel_observations
            .get(&owner_channel)
            .ok_or_else(|| format!("missing owner channel observation for {owner_channel:?}"))?;
        let completeness = match observation_row.limit {
            RetrievalLimitObservation::Exhausted => RetrievalChannelCompletenessV1::Exhausted,
            RetrievalLimitObservation::LimitReached => RetrievalChannelCompletenessV1::Partial,
        };
        let mut candidates = by_channel.remove(&channel).unwrap_or_default();
        candidates.sort_by(|left, right| {
            left.channel_rank
                .cmp(&right.channel_rank)
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        batches.push(RetrievalChannelBatchV1 {
            channel,
            generation_vector_digest: cue.snapshot_key.vector_digest,
            candidates,
            completeness,
            omitted_lower_bound: 0,
        });
    }
    Ok(batches)
}

const fn map_owner_channel(channel: RetrievalChannel) -> Option<RetrievalChannelV1> {
    match channel {
        RetrievalChannel::MemoryFts => Some(RetrievalChannelV1::Lexical),
        RetrievalChannel::EntityFts => Some(RetrievalChannelV1::Entity),
        RetrievalChannel::Recency => Some(RetrievalChannelV1::Temporal),
        RetrievalChannel::GraphOneHop => None,
    }
}

const fn reverse_owner_channel(channel: RetrievalChannelV1) -> Option<RetrievalChannel> {
    match channel {
        RetrievalChannelV1::Lexical => Some(RetrievalChannel::MemoryFts),
        RetrievalChannelV1::Entity => Some(RetrievalChannel::EntityFts),
        RetrievalChannelV1::Temporal => Some(RetrievalChannel::Recency),
        RetrievalChannelV1::Vector
        | RetrievalChannelV1::Causal
        | RetrievalChannelV1::Procedural
        | RetrievalChannelV1::ContradictionSupport => None,
    }
}

fn owner_support_digest(
    observation: &RetrievalObservation,
    record_digest: Digest32,
    channel: RetrievalChannel,
    rank: u32,
) -> Digest32 {
    let mut bytes = b"hepta.owner-retrieval-support.v1".to_vec();
    bytes.extend_from_slice(record_digest.as_array());
    bytes.extend_from_slice(observation.observation_sha256().as_str().as_bytes());
    bytes.push(match channel {
        RetrievalChannel::MemoryFts => 0,
        RetrievalChannel::EntityFts => 1,
        RetrievalChannel::GraphOneHop => 2,
        RetrievalChannel::Recency => 3,
    });
    bytes.extend_from_slice(&rank.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "owner_retrieval_adapter_tests.rs"]
mod tests;
