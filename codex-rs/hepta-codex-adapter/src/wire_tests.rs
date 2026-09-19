use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::AdmissionError;
use codex_hepta_wire::TypedPayloadError;
use codex_hepta_wire::WireEnvelopeV2;

use super::*;
use crate::AdapterStatus;
use crate::AppServerObservation;
use crate::CodexOperationIntent;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

#[test]
fn wire_v2_is_admitted_before_existing_runtime_codex_adapter_logic() {
    let digest = Digest32::of_bytes(b"payload");
    let intent = CodexOperationIntent {
        operation_id: id("operation.1"),
        thread_id: id("thread.1"),
        method_id: id("turn.start"),
        payload_digest: digest,
        lease_payload_digest: digest,
        deadline_ms: 100,
    };
    let envelope = encode_codex_operation_intent_wire_v2(
        &intent,
        id("runtime.agentd"),
        Generation::new(3).expect("generation"),
    )
    .expect("encode");
    let receipt = adapt_wire_v2(
        1,
        &envelope,
        Some(AppServerObservation {
            terminal_observed: true,
            response_digest: Digest32::of_bytes(b"response"),
        }),
    )
    .expect("adapt");
    assert_eq!(receipt.status, AdapterStatus::Succeeded);

    let invalid = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2),
        id("runtime.agentd"),
        Generation::new(3).expect("generation"),
        format!(
            "{{\"operation_id\":\"{}\",\"thread_id\":\"{}\",\"method_id\":\"{}\",\"payload_digest\":\"{}\",\"lease_payload_digest\":\"{}\",\"deadline_ms\":100,\"unknown\":true}}",
            intent.operation_id,
            intent.thread_id,
            intent.method_id,
            intent.payload_digest,
            intent.lease_payload_digest,
        )
        .into_bytes(),
    )
    .expect("raw invalid envelope");
    assert!(matches!(
        adapt_wire_v2(1, &invalid, None),
        Err(WireAdapterError::Payload(TypedPayloadError::Admission(
            AdmissionError::UnknownField(field)
        ))) if field == "unknown"
    ));
}
