use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn record(value: &str) -> MemoryRecord {
    MemoryRecord {
        record_id: id(value),
        revision: Revision::new(1).unwrap(),
        kind: MemoryKind::Fact,
        content_digest: digest(value),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn channel(
    channel: OwnerRetrievalChannelV1,
    candidate_count: u32,
    completeness: OwnerChannelCompletenessV1,
) -> OwnerChannelObservationV1 {
    OwnerChannelObservationV1 {
        channel,
        candidate_count,
        completeness,
    }
}

#[test]
fn owner_adapter_maps_physical_channels_without_inventing_causal_evidence() {
    let generation = digest("generation");
    let batches = adapt_owner_observation(OwnerRetrievalObservationV1 {
        generation_vector_digest: generation,
        channels: vec![
            channel(
                OwnerRetrievalChannelV1::MemoryFts,
                1,
                OwnerChannelCompletenessV1::Exhausted,
            ),
            channel(
                OwnerRetrievalChannelV1::EntityFts,
                1,
                OwnerChannelCompletenessV1::Exhausted,
            ),
            channel(
                OwnerRetrievalChannelV1::GraphOneHop,
                1,
                OwnerChannelCompletenessV1::LimitReached,
            ),
            channel(
                OwnerRetrievalChannelV1::Recency,
                1,
                OwnerChannelCompletenessV1::Exhausted,
            ),
        ],
        candidates: vec![OwnerObservedCandidateV1 {
            record: record("memory:one"),
            support_digest: digest("support"),
            channel_ranks: vec![
                OwnerChannelRankV1 {
                    channel: OwnerRetrievalChannelV1::MemoryFts,
                    rank: 1,
                },
                OwnerChannelRankV1 {
                    channel: OwnerRetrievalChannelV1::EntityFts,
                    rank: 1,
                },
                OwnerChannelRankV1 {
                    channel: OwnerRetrievalChannelV1::GraphOneHop,
                    rank: 1,
                },
                OwnerChannelRankV1 {
                    channel: OwnerRetrievalChannelV1::Recency,
                    rank: 1,
                },
            ],
        }],
    })
    .unwrap();

    assert_eq!(batches.len(), 3);
    assert_eq!(
        batches
            .iter()
            .map(|batch| batch.channel)
            .collect::<Vec<_>>(),
        vec![
            RetrievalChannelV1::Lexical,
            RetrievalChannelV1::Entity,
            RetrievalChannelV1::Temporal,
        ]
    );
    let entity = batches
        .iter()
        .find(|batch| batch.channel == RetrievalChannelV1::Entity)
        .unwrap();
    assert_eq!(
        entity.completeness,
        RetrievalChannelCompletenessV1::Truncated {
            omitted_at_least: 1
        }
    );
    assert_eq!(entity.candidates.len(), 1);
    assert_eq!(entity.candidates[0].channel_rank, 1);
    assert_eq!(entity.candidates[0].generation_vector_digest, generation);
    assert_eq!(entity.candidates[0].ood, ProbabilityQ32::ZERO);
}

#[test]
fn owner_adapter_rejects_unobserved_or_out_of_range_ranks() {
    let mut observation = OwnerRetrievalObservationV1 {
        generation_vector_digest: digest("generation"),
        channels: vec![channel(
            OwnerRetrievalChannelV1::MemoryFts,
            1,
            OwnerChannelCompletenessV1::Exhausted,
        )],
        candidates: vec![OwnerObservedCandidateV1 {
            record: record("memory:one"),
            support_digest: digest("support"),
            channel_ranks: vec![OwnerChannelRankV1 {
                channel: OwnerRetrievalChannelV1::MemoryFts,
                rank: 2,
            }],
        }],
    };
    assert!(matches!(
        adapt_owner_observation(observation.clone()),
        Err(OwnerAdapterErrorV1::InvalidOwnerRank(_))
    ));
    observation.candidates[0].channel_ranks[0].channel = OwnerRetrievalChannelV1::Recency;
    assert_eq!(
        adapt_owner_observation(observation),
        Err(OwnerAdapterErrorV1::MissingOwnerChannel(
            OwnerRetrievalChannelV1::Recency
        ))
    );
}
