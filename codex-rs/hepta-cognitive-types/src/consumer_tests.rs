use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::consumer::CONSUMER_CONVERGENCE_PROFILES_V1;
use crate::consumer::CognitiveConsumerV1;
use crate::consumer::REGISTERED_CONSUMER_COUNT_V1;
use crate::consumer::SchemaFlowV1;
use crate::consumer::ShadowComparisonReceiptV1;
use crate::consumer::decode_registered_for_consumer_v1;
use crate::consumer::validate_consumer_convergence_registry_v1;
use crate::contract::Validated;
use crate::lane_c::CognitiveSnapshotKeyV1;
use crate::lane_c::LaneCGenerationVectorV1;
use crate::lane_c::MemoryWriteIntentV1 as LegacyMemoryWriteIntentV1;
use crate::write_receipt::MemoryWriteReceiptV1;
use crate::write_receipt::MemoryWriteRejectionCodeV1;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot() -> CognitiveSnapshotKeyV1 {
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;

    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:tenant-a"),
        purpose_id: id("purpose:memory"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 4,
        tombstone_frontier: 1,
        source_ledger_frontier: 7,
        knowledge_graph_generation: Generation::new(2)
            .unwrap_or_else(|error| panic!("valid generation: {error}")),
        compact_checkpoint_generation: Generation::new(1)
            .unwrap_or_else(|error| panic!("valid generation: {error}")),
        prompt_registry_revision: Revision::new(3)
            .unwrap_or_else(|error| panic!("valid revision: {error}")),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 2,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn intent() -> LegacyMemoryWriteIntentV1 {
    LegacyMemoryWriteIntentV1 {
        intent_id: id("intent:1"),
        candidate_digest: digest("candidate"),
        expected_snapshot: snapshot(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
    }
}

#[test]
fn registry_covers_every_declared_consumer() {
    validate_consumer_convergence_registry_v1()
        .unwrap_or_else(|error| panic!("valid convergence registry: {error}"));
    assert_eq!(
        CONSUMER_CONVERGENCE_PROFILES_V1.len(),
        REGISTERED_CONSUMER_COUNT_V1
    );
}

#[test]
fn cutover_requires_exact_shadow_equality() {
    let exact = digest("same-semantic-output");
    let matched = ShadowComparisonReceiptV1::new(
        id("comparison:matched"),
        CognitiveConsumerV1::CognitiveStore,
        Some(exact),
        Some(exact),
        1_000,
    )
    .unwrap_or_else(|error| panic!("valid matched receipt: {error}"));
    assert!(matched.cutover_eligible());

    let mismatch = ShadowComparisonReceiptV1::new(
        id("comparison:mismatch"),
        CognitiveConsumerV1::MemoryRetrieval,
        Some(digest("legacy")),
        Some(digest("canonical")),
        1_000,
    )
    .unwrap_or_else(|error| panic!("valid mismatch receipt: {error}"));
    assert!(!mismatch.cutover_eligible());
}

#[test]
fn consumer_decoder_enforces_declared_direction() {
    let receipt = MemoryWriteReceiptV1::rejected(
        &intent(),
        "writer:cognitive-store",
        1_000,
        MemoryWriteRejectionCodeV1::CapacityExceeded,
        Some(digest("observed-snapshot")),
        true,
    )
    .unwrap_or_else(|error| panic!("valid rejection receipt: {error}"));
    let bytes = Validated::from_cognitive_contract(receipt)
        .unwrap_or_else(|error| panic!("validated receipt: {error}"))
        .encode_wire_v1()
        .unwrap_or_else(|error| panic!("encode receipt: {error}"));

    decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
        CognitiveConsumerV1::CognitiveStore,
        SchemaFlowV1::Output,
        &bytes,
    )
    .unwrap_or_else(|error| panic!("registered store output: {error}"));

    assert!(
        decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
            CognitiveConsumerV1::CognitiveRead,
            SchemaFlowV1::Input,
            &bytes,
        )
        .is_err()
    );
}
