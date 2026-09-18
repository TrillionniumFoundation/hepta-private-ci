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
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:generator-contract"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 11,
        knowledge_graph_generation: Generation::new(2).unwrap(),
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(3).unwrap(),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 5,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap()
}

fn cue() -> MemoryCueV1 {
    crate::compile_cue(
        digest("objective"),
        digest("approved-context"),
        snapshot_key(),
        digest("cue-profile"),
    )
    .unwrap()
}

fn policy(maximum_results: u32) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:generator-contract"),
        channel_weights: vec![crate::RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 32,
        }],
        maximum_results,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

fn candidate(cue: &MemoryCueV1) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: id("memory:generator-contract"),
            revision: Revision::new(1).unwrap(),
            kind: MemoryKind::Fact,
            content_digest: digest("content"),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        channel: RetrievalChannelV1::Lexical,
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest("support"),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    }
}

fn batch(cue: &MemoryCueV1) -> RetrievalChannelBatchV1 {
    RetrievalChannelBatchV1 {
        channel: RetrievalChannelV1::Lexical,
        producer_id: id("cognitive-store:sqlite-memory-fts"),
        generator_profile_digest: digest("sqlite-memory-fts-v1"),
        generation_vector_digest: cue.snapshot_key.vector_digest,
        completeness: RetrievalChannelCompletenessV1::Exhausted,
        candidates: vec![candidate(cue)],
    }
}

#[test]
fn typed_batches_recall_under_product_profile() {
    let cue = cue();
    let packet = recall_from_batches(&cue, &policy(16), vec![batch(&cue)]).unwrap();
    assert_eq!(
        packet.recall.disposition,
        crate::RecallDispositionV1::Recalled
    );
    assert_eq!(packet.recall.selections.len(), 1);
    assert_eq!(packet.generator.candidate_count, 1);
    assert!(packet.generator.truncated_channels.is_empty());
    assert!(!packet.generator.manifest_digest.is_zero());
    assert!(!packet.receipt_digest.is_zero());
}

#[test]
fn generator_contract_rejects_generation_drift_and_invalid_truncation() {
    let cue = cue();
    let mut stale = batch(&cue);
    stale.generation_vector_digest = digest("stale");
    assert_eq!(
        recall_from_batches(&cue, &policy(16), vec![stale]),
        Err(GeneratorContractErrorV1::GenerationVectorMismatch(
            RetrievalChannelV1::Lexical
        ))
    );

    let mut truncated = batch(&cue);
    truncated.completeness =
        RetrievalChannelCompletenessV1::Truncated { omitted_at_least: 0 };
    assert_eq!(
        recall_from_batches(&cue, &policy(16), vec![truncated]),
        Err(GeneratorContractErrorV1::InvalidTruncation)
    );
}

#[test]
fn generator_contract_enforces_hnmf_result_ceiling() {
    let cue = cue();
    assert_eq!(
        recall_from_batches(&cue, &policy(17), vec![batch(&cue)]),
        Err(GeneratorContractErrorV1::ResultProfileLimitExceeded)
    );
}


#[test]
fn generator_completeness_changes_product_receipt() {
    let cue = cue();
    let exhausted = recall_from_batches(&cue, &policy(16), vec![batch(&cue)]).unwrap();
    let mut truncated_batch = batch(&cue);
    truncated_batch.completeness =
        RetrievalChannelCompletenessV1::Truncated { omitted_at_least: 1 };
    let truncated =
        recall_from_batches(&cue, &policy(16), vec![truncated_batch]).unwrap();

    assert_eq!(exhausted.recall, truncated.recall);
    assert_ne!(
        exhausted.generator.manifest_digest,
        truncated.generator.manifest_digest
    );
    assert_ne!(exhausted.receipt_digest, truncated.receipt_digest);
    assert_eq!(
        truncated.generator.truncated_channels,
        vec![RetrievalChannelV1::Lexical]
    );
}
