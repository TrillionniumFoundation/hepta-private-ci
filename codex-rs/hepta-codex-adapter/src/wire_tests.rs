use std::error::Error as StdError;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::WireEnvelopeV2;

use super::*;
use crate::AdapterStatus;
use crate::AppServerRequestBinding;
use crate::CodexOperationIntent;

fn id(v: &str) -> StableId {
    StableId::new(v).expect("valid id")
}

fn unbound() -> CodexOperationIntent {
    let digest = Digest32::of_bytes(b"payload");
    CodexOperationIntent {
        operation_id: id("operation.1"),
        thread_id: id("thread.1"),
        method_id: id("turn.start"),
        payload_digest: digest,
        lease_payload_digest: digest,
        deadline_ms: 100,
        app_server_binding: None,
    }
}

#[test]
fn wire_v2_can_only_produce_indeterminate_authority_free_request() -> Result<(), Box<dyn StdError>>
{
    let envelope = encode_codex_operation_intent_wire_v2(
        &unbound(),
        id("runtime.agentd"),
        Generation::new(3)?,
    )?;
    let receipt = adapt_wire_v2(1, &envelope)?;
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    Ok(())
}

#[test]
fn wire_v2_refuses_to_drop_product_binding() {
    let mut intent = unbound();
    intent.app_server_binding = Some(AppServerRequestBinding {
        source_admission_digest: Digest32::of_bytes(b"source"),
        agent_generation: Generation::new(3).unwrap(),
        protocol_id: id(crate::APP_SERVER_V2_PROTOCOL_ID),
        app_server_version: "1.0".to_string(),
        codex_home_digest: Digest32::of_bytes(b"/home/agent"),
        connection_id: 9,
    });
    assert!(matches!(
        encode_codex_operation_intent_wire_v2(
            &intent,
            id("runtime.agentd"),
            Generation::new(3).unwrap()
        ),
        Err(WireAdapterError::ProductBindingUnsupported)
    ));
}

#[test]
fn wire_v2_rejects_unknown_fields_and_payload_drift() -> Result<(), Box<dyn StdError>> {
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
        adapt_wire_v2(1, &invalid),
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
        adapt_wire_v2(1, &drift),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "payload binding mismatch"
        )))
    ));
    Ok(())
}
