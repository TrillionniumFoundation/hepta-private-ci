use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:channel-contract"),
        purpose_id: id("purpose:retrieval"),
        memory_ledger_frontier: 11,
        knowledge_fact_frontier: 7,
        tombstone_frontier: 3,
        source_ledger_frontier: 13,
        knowledge_graph_generation: Generation::new(/*value*/ 2).expect("generation"),
        compact_checkpoint_generation: Generation::new(/*value*/ 1).expect("generation"),
        prompt_registry_revision: Revision::new(/*value*/ 5).expect("revision"),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 9,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("snapshot key")
}

fn cue() -> MemoryCueV1 {
    compile_cue(MemoryCueCompileRequestV1 {
        cue_id: id("cue:channel-contract"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("context"),
        snapshot_key: snapshot_key(),
        cue_profile_digest: digest("cue-profile"),
    })
    .expect("compiled cue")
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
        abstain_on_contradiction: true,
    }
}

fn record() -> MemoryRecord {
    MemoryRecord {
        record_id: id("memory:channel-contract"),
        revision: Revision::new(/*value*/ 1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(channel: RetrievalChannelV1) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(),
        channel,
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support-{channel:?}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

#[test]
fn compile_cue_validates_before_publication() {
    let expected = cue();
    let mut invalid = MemoryCueCompileRequestV1 {
        cue_id: expected.cue_id.clone(),
        objective_digest: Digest32::ZERO,
        approved_context_digest: expected.approved_context_digest,
        snapshot_key: expected.snapshot_key.clone(),
        cue_profile_digest: expected.cue_profile_digest,
    };
    assert_eq!(
        compile_cue(invalid.clone()),
        Err(RecallErrorV1::EmptyDigest("objective"))
    );

    invalid.objective_digest = expected.objective_digest;
    assert_eq!(compile_cue(invalid).expect("valid cue"), expected);
}

#[test]
fn channel_batches_bind_owner_completeness_and_generation() {
    let cue = cue();
    let union = build_candidate_union_from_batches(
        &cue,
        &policy(),
        vec![
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Lexical,
                generation_owner: RetrievalGenerationOwnerV1::CognitiveRead,
                source_generation_digest: cue.snapshot_key.vector_digest,
                coverage: RetrievalCoverageV1::Exhausted,
                candidates: vec![candidate(RetrievalChannelV1::Lexical)],
            },
            RetrievalChannelBatchV1 {
                channel: RetrievalChannelV1::Entity,
                generation_owner: RetrievalGenerationOwnerV1::KnowledgeGraph,
                source_generation_digest: digest("kg-generation"),
                coverage: RetrievalCoverageV1::Truncated {
                    omitted_lower_bound: 2,
                },
                candidates: vec![candidate(RetrievalChannelV1::Entity)],
            },
        ],
    )
    .expect("valid generated union");

    assert_eq!(union.union.entries.len(), 1);
    assert_eq!(
        union.coverage,
        vec![
            RetrievalChannelCoverageV1 {
                channel: RetrievalChannelV1::Lexical,
                generation_owner: RetrievalGenerationOwnerV1::CognitiveRead,
                source_generation_digest: cue.snapshot_key.vector_digest,
                coverage: RetrievalCoverageV1::Exhausted,
                admitted_candidates: 1,
            },
            RetrievalChannelCoverageV1 {
                channel: RetrievalChannelV1::Entity,
                generation_owner: RetrievalGenerationOwnerV1::KnowledgeGraph,
                source_generation_digest: digest("kg-generation"),
                coverage: RetrievalCoverageV1::Truncated {
                    omitted_lower_bound: 2,
                },
                admitted_candidates: 1,
            },
        ]
    );
}

#[test]
fn malformed_channel_batches_fail_closed() {
    let cue = cue();
    let wrong_owner = RetrievalChannelBatchV1 {
        channel: RetrievalChannelV1::Vector,
        generation_owner: RetrievalGenerationOwnerV1::CognitiveRead,
        source_generation_digest: digest("vector-generation"),
        coverage: RetrievalCoverageV1::Exhausted,
        candidates: Vec::new(),
    };
    assert_eq!(
        wrong_owner.validate(),
        Err(ChannelContractErrorV1::WrongGenerationOwner(
            RetrievalChannelV1::Vector
        ))
    );

    let unavailable_with_data = RetrievalChannelBatchV1 {
        channel: RetrievalChannelV1::Lexical,
        generation_owner: RetrievalGenerationOwnerV1::CognitiveRead,
        source_generation_digest: cue.snapshot_key.vector_digest,
        coverage: RetrievalCoverageV1::Unavailable,
        candidates: vec![candidate(RetrievalChannelV1::Lexical)],
    };
    assert_eq!(
        unavailable_with_data.validate(),
        Err(ChannelContractErrorV1::UnavailableChannelHasCandidates(
            RetrievalChannelV1::Lexical
        ))
    );
}
