#![no_main]

use codex_hepta_cognitive_types::consumer::{
    CanonicalConsumerV1, CanonicalMigrationPostureV1,
};
use codex_hepta_cognitive_types::handoff::CanonicalParityV1;
use codex_hepta_cognitive_types::hnmf::{ContractIdV1, MemoryEventV1};
use codex_hepta_cognitive_types::hnmf_learning::{
    ForgetPropagationReceiptV1, RecallPacketV1,
};
use codex_hepta_cognitive_types::identity_policy::validate_consumer_semantic_identity_v1;
use codex_hepta_cognitive_types::prepared_consumer::{
    bind_prepared_forget_receipt_consumer_v1, bind_prepared_memory_event_consumer_v1,
    bind_prepared_recall_packet_consumer_v1,
};
use codex_hepta_cognitive_types::wire::{
    ValidatedCanonicalPayload, decode_validated_canonical_payload_v1,
};
use libfuzzer_sys::fuzz_target;

fn operation_id(consumer: CanonicalConsumerV1, value: &str) -> ContractIdV1 {
    validate_consumer_semantic_identity_v1(consumer, value)
        .expect("static operation id must satisfy the registered owner policy")
}

fn exercise_memory_event(
    data: &[u8],
    payload: &ValidatedCanonicalPayload<MemoryEventV1>,
    consumer: CanonicalConsumerV1,
    operation: &str,
) {
    let digest = payload.frozen_digest().digest();
    let binding = bind_prepared_memory_event_consumer_v1(
        operation_id(consumer, operation),
        consumer,
        payload,
        digest,
        digest,
        Some(digest),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("registered event consumer must accept its reviewed payload family");
    let handoff = binding
        .compare_canonical_projection_v1(payload.value(), data)
        .expect("same checked event projection");
    assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
    assert!(handoff.require_match_for_current_binding(&binding).is_ok());
}

fn exercise_recall_packet(
    data: &[u8],
    payload: &ValidatedCanonicalPayload<RecallPacketV1>,
    consumer: CanonicalConsumerV1,
    operation: &str,
) {
    let digest = payload.frozen_digest().digest();
    let binding = bind_prepared_recall_packet_consumer_v1(
        operation_id(consumer, operation),
        consumer,
        payload,
        digest,
        digest,
        Some(digest),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("registered recall consumer must accept its reviewed payload family");
    let handoff = binding
        .compare_canonical_projection_v1(payload.value(), data)
        .expect("same checked recall projection");
    assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
    assert!(handoff.require_match_for_current_binding(&binding).is_ok());
}

fn exercise_forget_receipt(
    data: &[u8],
    payload: &ValidatedCanonicalPayload<ForgetPropagationReceiptV1>,
    consumer: CanonicalConsumerV1,
    operation: &str,
) {
    let digest = payload.frozen_digest().digest();
    let binding = bind_prepared_forget_receipt_consumer_v1(
        operation_id(consumer, operation),
        consumer,
        payload,
        digest,
        digest,
        Some(digest),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("registered forget consumer must accept its reviewed payload family");
    let handoff = binding
        .compare_canonical_projection_v1(payload.value(), data)
        .expect("same checked forget projection");
    assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
    assert!(handoff.require_match_for_current_binding(&binding).is_ok());
}

fuzz_target!(|data: &[u8]| {
    if let Ok(payload) = decode_validated_canonical_payload_v1::<MemoryEventV1>(data) {
        for (consumer, operation) in [
            (
                CanonicalConsumerV1::CognitiveRead,
                "fuzz:memory-event:cognitive-read",
            ),
            (
                CanonicalConsumerV1::CognitiveStore,
                "fuzz:memory-event:cognitive-store",
            ),
            (
                CanonicalConsumerV1::CompactEngine,
                "fuzz:memory-event:compact-engine",
            ),
        ] {
            exercise_memory_event(data, &payload, consumer, operation);
        }
    }

    if let Ok(payload) = decode_validated_canonical_payload_v1::<RecallPacketV1>(data) {
        for (consumer, operation) in [
            (
                CanonicalConsumerV1::MemoryRetrieval,
                "fuzz:recall-packet:memory-retrieval",
            ),
            (
                CanonicalConsumerV1::IntelligenceControl,
                "fuzz:recall-packet:intelligence-control",
            ),
        ] {
            exercise_recall_packet(data, &payload, consumer, operation);
        }
    }

    if let Ok(payload) =
        decode_validated_canonical_payload_v1::<ForgetPropagationReceiptV1>(data)
    {
        for (consumer, operation) in [
            (
                CanonicalConsumerV1::CognitiveRead,
                "fuzz:forget-receipt:cognitive-read",
            ),
            (
                CanonicalConsumerV1::CognitiveStore,
                "fuzz:forget-receipt:cognitive-store",
            ),
            (
                CanonicalConsumerV1::CompactEngine,
                "fuzz:forget-receipt:compact-engine",
            ),
        ] {
            exercise_forget_receipt(data, &payload, consumer, operation);
        }
    }
});
