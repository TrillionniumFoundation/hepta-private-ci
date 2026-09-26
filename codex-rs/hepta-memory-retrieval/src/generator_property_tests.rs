use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:generator-property"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 15,
        knowledge_fact_frontier: 12,
        tombstone_frontier: 4,
        source_ledger_frontier: 16,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(2),
        prompt_registry_revision: revision(5),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("snapshot key")
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidates(count: usize) -> Vec<RetrievalChannelCandidateV1> {
    (0..count)
        .map(|index| {
            let number = u64::try_from(index + 1).expect("candidate number");
            RetrievalChannelCandidateV1 {
                record: record(number),
                channel: RetrievalChannelV1::Lexical,
                channel_rank: u32::try_from(index + 1).expect("channel rank"),
                normalized_score: FixedQ32::ONE,
                ood: ProbabilityQ32::ZERO,
                support_digest: digest(&format!("support:{number}")),
                contradiction_group_digest: None,
                generation_vector_digest: snapshot_key().vector_digest,
            }
        })
        .collect()
}

fn batch(count: usize) -> RetrievalGeneratorBatchV1 {
    let candidates = candidates(count);
    let receipt = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        snapshot_key().vector_digest,
        digest(&format!("owner-generation:{count}")),
        u32::try_from(count).expect("candidate count"),
        RetrievalSourceCompletenessV1::Exhausted,
    )
    .expect("receipt");
    RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    }
}

#[test]
fn property_receipt_count_matches_candidates_at_all_representative_bounds() {
    for count in [0_usize, 1, 2, 7, 16, 31, 32, 127, 255, 511, 512] {
        let input = GeneratedCandidateInputV1::new(vec![batch(count)])
            .expect("matching receipt");
        assert_eq!(
            input.flattened_candidates().expect("flattened").len(),
            count
        );
        assert_eq!(
            usize::try_from(input.batches[0].receipt.candidate_count)
                .expect("receipt count"),
            count
        );
    }
}

#[test]
fn property_any_receipt_count_drift_fails_closed() {
    for count in [0_usize, 1, 2, 31, 32, 255, 511] {
        let mut candidate_batch = batch(count);
        candidate_batch.receipt = RetrievalGeneratorReceiptV1::new(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            snapshot_key().vector_digest,
            digest(&format!("owner-generation:mismatch:{count}")),
            u32::try_from(count + 1).expect("mismatched count"),
            RetrievalSourceCompletenessV1::Exhausted,
        )
        .expect("structurally valid receipt");
        assert_eq!(
            GeneratedCandidateInputV1::new(vec![candidate_batch]),
            Err(GeneratorErrorV1::CandidateCountMismatch)
        );
    }
}

#[test]
fn property_capacity_above_global_ceiling_is_rejected() {
    let count = MAX_GENERATION_BOUND_CANDIDATES + 1;
    assert!(matches!(
        RetrievalGeneratorReceiptV1::new(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            snapshot_key().vector_digest,
            digest("owner-generation:overflow"),
            u32::try_from(count).expect("overflow count"),
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        Err(GeneratorErrorV1::CandidateLimitExceeded)
    ));
}
