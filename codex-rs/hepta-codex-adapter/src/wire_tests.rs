use std::error::Error as StdError;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::WireEnvelopeV2;

use super::*;
use crate::AdapterStatus;
use crate::AppServerObservation;
use crate::CodexOperationIntent;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier rejected");
    };
    value
}

#[test]
fn wire_v2_is_admitted_before_existing_runtime_codex_adapter_logic() -> Result<(), Box<dyn StdError>>
{
    let digest = Digest32::of_bytes(b"payload");
    let intent = CodexOperationIntent {
        operation_id: id("operation.1"),
        thread_id: id("thread.1"),
        method_id: id("turn.start"),
        payload_digest: digest,
        lease_payload_digest: digest,
        deadline_ms: 100,
    };
        Generation::new(3)?,
    )?;
    let receipt = adapt_wire_v2(
        1,
        &envelope,
        Some(AppServerObservation {
            terminal_observed: true,
            response_digest: Digest32::of_bytes(b"response"),
        }),
    )?;
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    Ok(())
}

#[test]
fn wire_v2_rejects_unknown_fields_and_payload_binding_drift() -> Result<(), Box<dyn StdError>> {
    let digest = Digest32::of_bytes(b"payload");
    let invalid = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2),
        id("runtime.agentd"),
        Generation::new(3)?,
        format!(
            "{{\"operation_id\":\"operation.1\",\"thread_id\":\"thread.1\",\"method_id\":\"turn.start\",\"payload_digest\":\"{digest}\",\"lease_payload_digest\":\"{digest}\",\"deadline_ms\":100,\"unknown\":true}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        adapt_wire_v2(1, &invalid, None),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "codex operation intent schema rejected"
        )))
    ));

    let other = Digest32::of_bytes(b"other");
    let drift = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2),
        id("runtime.agentd"),
        Generation::new(3)?,
        format!(
            "{{\"operation_id\":\"operation.1\",\"thread_id\":\"thread.1\",\"method_id\":\"turn.start\",\"payload_digest\":\"{digest}\",\"lease_payload_digest\":\"{other}\",\"deadline_ms\":100}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        adapt_wire_v2(1, &drift, None),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "payload binding mismatch"
        )))
    ));
    Ok(())
}
