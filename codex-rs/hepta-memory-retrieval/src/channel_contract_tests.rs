use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn cue() -> MemoryCueV1 {
    let snapshot_key = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:channel-contract"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 9,
        tombstone_frontier: 2,
        source_ledger_frontier: 11,
        knowledge_graph_generation: Generation::new(2).unwrap(),
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 4,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .unwrap();
    compile_cue(
        id("cue:channel-contract"),
        digest("objective"),
        digest("context"),
        snapshot_key,
        digest("cue-profile"),
    )
    .unwrap()
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:channel-contract"),
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::ONE,
                maximum_candidates: 8,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::ONE,
                maximum_candidates: 8,
            },
        ],
        maximum_results: 4,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: false,
    }
}

fn candidate(
    cue: &MemoryCueV1,
    name: &str,
    channel: RetrievalChannelV1,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: id(name),
            revision: Revision::new(1).unwrap(),
            kind: MemoryKind::Fact,
            content_digest: digest(name),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        channel,
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{name}:{channel:?}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    }
}

#[test]
fn complete_batches_produce_bound_coverage_receipt() {
    let cue = cue();
    let policy = policy();
    let result = build_candidate_union_from_batches(
        &cue,
        &policy,
        vec![
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Lexical,
                generation_vector_digest: cue.snapshot_key.vector_digest,
                candidates: vec![candidate(&cue, "memory:a", RetrievalChannelV1::Lexical)],
                completeness: RetrievalChannelCompletenessV1::Exhausted,
                omitted_lower_bound: 0,
            },
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Entity,
                generation_vector_digest: cue.snapshot_key.vector_digest,
                candidates: vec![candidate(&cue, "memory:b", RetrievalChannelV1::Entity)],
                completeness: RetrievalChannelCompletenessV1::Exhausted,
                omitted_lower_bound: 0,
            },
        ],
    )
    .unwrap();
    assert!(result.all_enabled_channels_exhausted);
    assert_eq!(result.coverage.len(), 2);
    result.validate().unwrap();
}

#[test]
fn missing_enabled_channel_and_fake_exhaustion_fail_closed() {
    let cue = cue();
    let policy = policy();
    let lexical = RetrievalChannelBatchV1 {
        channel: RetrievalChannelV1::Lexical,
        generation_vector_digest: cue.snapshot_key.vector_digest,
        candidates: vec![candidate(&cue, "memory:a", RetrievalChannelV1::Lexical)],
        completeness: RetrievalChannelCompletenessV1::Exhausted,
        omitted_lower_bound: 0,
    };
    assert_eq!(
        build_candidate_union_from_batches(&cue, &policy, vec![lexical.clone()]),
        Err(ChannelContractErrorV1::MissingChannelBatch(
            RetrievalChannelV1::Entity
        ))
    );
    let mut invalid = lexical;
    invalid.omitted_lower_bound = 1;
    assert_eq!(
        invalid.validate(&cue, &policy),
        Err(ChannelContractErrorV1::InvalidCompleteness(
            RetrievalChannelV1::Lexical
        ))
    );
}

#[test]
fn truncated_batch_binds_omission_lower_bound() {
    let cue = cue();
    let policy = policy();
    let result = build_candidate_union_from_batches(
        &cue,
        &policy,
        vec![
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Lexical,
                generation_vector_digest: cue.snapshot_key.vector_digest,
                candidates: vec![candidate(&cue, "memory:a", RetrievalChannelV1::Lexical)],
                completeness: RetrievalChannelCompletenessV1::Truncated,
                omitted_lower_bound: 7,
            },
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Entity,
                generation_vector_digest: cue.snapshot_key.vector_digest,
                candidates: vec![candidate(&cue, "memory:b", RetrievalChannelV1::Entity)],
                completeness: RetrievalChannelCompletenessV1::Partial,
                omitted_lower_bound: 0,
            },
        ],
    )
    .unwrap();
    assert!(!result.all_enabled_channels_exhausted);
    assert_eq!(result.union.omitted_by_channel_limits, 7);
    result.validate().unwrap();
}
