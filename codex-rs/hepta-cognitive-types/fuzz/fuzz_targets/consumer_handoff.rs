#![no_main]

use codex_hepta_cognitive_types::consumer::{
    CanonicalConsumerV1, CanonicalMigrationPostureV1,
};
use codex_hepta_cognitive_types::handoff::CanonicalParityV1;
use codex_hepta_cognitive_types::hnmf::{ContractIdV1, MemoryEventV1};
use codex_hepta_cognitive_types::hnmf_learning::{
    ForgetPropagationReceiptV1, RecallPacketV1,
};
use codex_hepta_cognitive_types::prepared_consumer::{
    bind_prepared_forget_receipt_consumer_v1, bind_prepared_memory_event_consumer_v1,
    bind_prepared_recall_packet_consumer_v1,
};
use codex_hepta_cognitive_types::wire::decode_validated_canonical_payload_v1;
use libfuzzer_sys::fuzz_target;

fn operation_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("static operation id")
}

fuzz_target!(|data: &[u8]| {
    if let Ok(payload) = decode_validated_canonical_payload_v1::<MemoryEventV1>(data) {
        let digest = payload.frozen_digest().digest();
        if let Ok(binding) = bind_prepared_memory_event_consumer_v1(
            operation_id("fuzz:memory-event"),
            CanonicalConsumerV1::CognitiveRead,
            &payload,
            digest,
            digest,
            Some(digest),
            CanonicalMigrationPostureV1::CompatibilityBound,
        ) {
            let handoff = binding
                .compare_canonical_projection_v1(payload.value(), data)
                .expect("same checked event projection");
            assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
            assert!(handoff.require_match_for_current_binding(&binding).is_ok());
        }
    }

    if let Ok(payload) = decode_validated_canonical_payload_v1::<RecallPacketV1>(data) {
        let digest = payload.frozen_digest().digest();
        if let Ok(binding) = bind_prepared_recall_packet_consumer_v1(
            operation_id("fuzz:recall-packet"),
            CanonicalConsumerV1::MemoryRetrieval,
            &payload,
            digest,
            digest,
            Some(digest),
            CanonicalMigrationPostureV1::CompatibilityBound,
        ) {
            let handoff = binding
                .compare_canonical_projection_v1(payload.value(), data)
                .expect("same checked recall projection");
            assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
            assert!(handoff.require_match_for_current_binding(&binding).is_ok());
        }
    }

    if let Ok(payload) =
        decode_validated_canonical_payload_v1::<ForgetPropagationReceiptV1>(data)
    {
        let digest = payload.frozen_digest().digest();
        if let Ok(binding) = bind_prepared_forget_receipt_consumer_v1(
            operation_id("fuzz:forget-receipt"),
            CanonicalConsumerV1::CompactEngine,
            &payload,
            digest,
            digest,
            Some(digest),
            CanonicalMigrationPostureV1::CompatibilityBound,
        ) {
            let handoff = binding
                .compare_canonical_projection_v1(payload.value(), data)
                .expect("same checked forget projection");
            assert_eq!(handoff.parity(), CanonicalParityV1::Matched);
            assert!(handoff.require_match_for_current_binding(&binding).is_ok());
        }
    }
});
