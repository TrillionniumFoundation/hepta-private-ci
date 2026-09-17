use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error}"))
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:v2"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        snapshot_key: CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: id("scope:recall-v2"),
            purpose_id: id("purpose:recall-v2"),
            memory_ledger_frontier: 10,
            knowledge_fact_frontier: 8,
            tombstone_frontier: 1,
            source_ledger_frontier: 11,
            knowledge_graph_generation: generation(2),
            compact_checkpoint_generation: generation(1),
            prompt_registry_revision: revision(2),
            retrieval_profile_digest: digest("retrieval-profile"),
            encoder_preprocessor_digest: digest("encoder-profile"),
            authority_epoch: 5,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        })
        .unwrap_or_else(|error| panic!("valid snapshot: {error}")),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn policy(maximum_results: u32, minimum_channels: u32) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:v2"),
        channel_weights: vec![
            crate::RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::ONE,
                maximum_candidates: 128,
            },
            crate::RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::ONE,
                maximum_candidates: 128,
            },
        ],
        maximum_results,
        minimum_total_score: FixedQ32::from_raw(1),
        maximum_ood: probability(1_u64 << 30),
        minimum_distinct_channels: minimum_channels,
        abstain_on_contradiction: true,
    }
}

fn record(number: usize) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:v2:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(
    number: usize,
    channel: RetrievalChannelV1,
    rank: u32,
    score: i64,
    ood: ProbabilityQ32,
    contradiction: Option<Digest32>,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(number),
        channel,
        channel_rank: rank,
        normalized_score: FixedQ32::from_raw(score),
        ood,
        support_digest: digest(&format!("support:{number}:{channel:?}")),
        contradiction_group_digest: contradiction,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

#[test]
fn unrelated_low_rank_ood_does_not_poison_top_k() {
    let packet = recall_v2(
        &cue(),
        &policy(1, 1),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                1,
                1_i64 << 31,
                probability(1_u64 << 28),
                None,
            ),
            candidate(
                2,
                RetrievalChannelV1::Lexical,
                2,
                1_i64 << 28,
                ProbabilityQ32::ONE,
                None,
            ),
        ],
    )
    .unwrap_or_else(|error| panic!("recall succeeds: {error}"));
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:v2:1"));
}

#[test]
fn unrelated_low_rank_contradiction_population_does_not_poison_top_k() {
    let group = digest("low-only-contradiction");
    let packet = recall_v2(
        &cue(),
        &policy(1, 1),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                1,
                1_i64 << 31,
                probability(1_u64 << 28),
                None,
            ),
            candidate(
                2,
                RetrievalChannelV1::Lexical,
                2,
                1_i64 << 28,
                probability(1_u64 << 28),
                Some(group),
            ),
            candidate(
                3,
                RetrievalChannelV1::Lexical,
                3,
                1_i64 << 27,
                probability(1_u64 << 28),
                Some(group),
            ),
        ],
    )
    .unwrap_or_else(|error| panic!("recall succeeds: {error}"));
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
}

#[test]
fn contradiction_touching_top_k_still_forces_abstention() {
    let group = digest("selected-contradiction");
    let packet = recall_v2(
        &cue(),
        &policy(1, 1),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                1,
                1_i64 << 31,
                probability(1_u64 << 28),
                Some(group),
            ),
            candidate(
                2,
                RetrievalChannelV1::Lexical,
                2,
                1_i64 << 28,
                probability(1_u64 << 28),
                Some(group),
            ),
        ],
    )
    .unwrap_or_else(|error| panic!("abstention is a valid packet: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(packet.selections.is_empty());
}

#[test]
fn low_rank_channel_cannot_satisfy_top_k_coverage() {
    let packet = recall_v2(
        &cue(),
        &policy(1, 2),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                1,
                1_i64 << 31,
                probability(1_u64 << 28),
                None,
            ),
            candidate(
                2,
                RetrievalChannelV1::Entity,
                1,
                1_i64 << 28,
                probability(1_u64 << 28),
                None,
            ),
        ],
    )
    .unwrap_or_else(|error| panic!("coverage abstention is valid: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    );
}

#[test]
fn v2_enforces_product_candidate_and_result_ceilings() {
    let mut too_many_results = policy(17, 1);
    assert_eq!(
        recall_v2(&cue(), &too_many_results, Vec::new()),
        Err(RecallErrorV1::InvalidMaximumResults)
    );
    too_many_results.maximum_results = 1;

    let candidates = (0..=MAX_PRODUCT_RETRIEVAL_CANDIDATES)
        .map(|index| {
            candidate(
                index,
                RetrievalChannelV1::Lexical,
                u32::try_from(index + 1).unwrap_or(u32::MAX),
                1,
                ProbabilityQ32::ZERO,
                None,
            )
        })
        .collect();
    assert_eq!(
        recall_v2(&cue(), &too_many_results, candidates),
        Err(RecallErrorV1::CandidateLimitExceeded)
    );
}
