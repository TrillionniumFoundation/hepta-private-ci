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
    let intent = unbound();
    let envelope =
        encode_codex_operation_intent_wire_v2(&intent, id("runtime.agentd"), Generation::new(3)?)?;
    let receipt = adapt_wire_v2(1, &envelope)?;
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(matches!(
        encode_codex_operation_intent_wire_v2(&intent, id("context.compiler"), Generation::new(4)?,),
        Err(WireAdapterError::UnexpectedProducer(_))
    ));
    Ok(())
}

#[test]
fn wire_v2_refuses_to_drop_product_binding() {
    let mut intent = unbound();
    intent.app_server_binding = Some(AppServerRequestBinding {
        source_admission_digest: Digest32::of_bytes(b"source"),
        agent_generation: Generation::new(3).unwrap(),
        session_id: id("session.1"),
        client_user_message_id: id("request.1"),
        user_input_digest: Digest32::of_bytes(b"user-input"),
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
        Err(WireAdapterError::ProductBindingUnsupportedByV2)
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

    let wrong_producer = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2),
        id("context.compiler"),
        Generation::new(3)?,
        format!(
            "{{\"operation_id\":\"operation.1\",\"thread_id\":\"thread.1\",\"method_id\":\"turn.start\",\"payload_digest\":\"{digest}\",\"lease_payload_digest\":\"{digest}\",\"deadline_ms\":100}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        adapt_wire_v2(1, &wrong_producer),
        Err(WireAdapterError::UnexpectedProducer(_))
    ));
    Ok(())
}

fn bound() -> CodexOperationIntent {
    let mut intent = unbound();
    intent.app_server_binding = Some(AppServerRequestBinding {
        source_admission_digest: Digest32::of_bytes(b"source"),
        agent_generation: Generation::new(3).unwrap(),
        session_id: id("session.1"),
        client_user_message_id: id("request.1"),
        user_input_digest: Digest32::of_bytes(b"user-input"),
        protocol_id: id(crate::APP_SERVER_V2_PROTOCOL_ID),
        app_server_version: "1.0".to_string(),
        codex_home_digest: Digest32::of_bytes(b"/home/agent"),
        connection_id: 9,
    });
    intent
}

#[test]
fn wire_v3_round_trips_complete_product_binding_and_request_digest() -> Result<(), Box<dyn StdError>>
{
    let intent = bound();
    let expected_digest = crate::request_digest(&intent);
    let envelope =
        encode_codex_operation_intent_wire_v3(&intent, id("runtime.agentd"), Generation::new(3)?)?;
    assert_eq!(
        envelope.schema().as_str(),
        CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3
    );
    let decoded = decode_codex_operation_intent_wire_v3(&envelope)?;
    assert_eq!(decoded, intent);
    assert_eq!(crate::request_digest(&decoded), expected_digest);

    let receipt = adapt_product_wire_v3(1, &intent, Generation::new(3)?)?;
    assert_eq!(receipt.request_digest, expected_digest);
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    Ok(())
}

#[test]
fn wire_v3_rejects_missing_or_mutated_product_binding() -> Result<(), Box<dyn StdError>> {
    assert!(matches!(
        encode_codex_operation_intent_wire_v3(
            &unbound(),
            id("runtime.agentd"),
            Generation::new(3)?,
        ),
        Err(WireAdapterError::ProductBindingRequired)
    ));

    let intent = bound();
    let envelope =
        encode_codex_operation_intent_wire_v3(&intent, id("runtime.agentd"), Generation::new(3)?)?;
    let mut value: serde_json::Value = serde_json::from_slice(envelope.payload())?;
    value["app_server_binding"]["connection_id"] = serde_json::json!(0);
    let invalid = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3),
        id("runtime.agentd"),
        Generation::new(3)?,
        serde_json::to_vec(&value)?,
    )?;
    assert!(matches!(
        decode_codex_operation_intent_wire_v3(&invalid),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "zero connection_id"
        )))
    ));

    value["app_server_binding"]["connection_id"] = serde_json::json!(9);
    value["app_server_binding"]["unknown"] = serde_json::json!(true);
    let unknown = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3),
        id("runtime.agentd"),
        Generation::new(3)?,
        serde_json::to_vec(&value)?,
    )?;
    assert!(matches!(
        decode_codex_operation_intent_wire_v3(&unknown),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "bound codex operation intent schema rejected"
        )))
    ));
    Ok(())
}

#[test]
fn wire_v3_rejects_frame_generation_different_from_product_binding() -> Result<(), Box<dyn StdError>>
{
    let intent = bound();
    assert!(matches!(
        encode_codex_operation_intent_wire_v3(
            &intent,
            id("runtime.agentd"),
            Generation::new(4)?,
        ),
        Err(WireAdapterError::GenerationBindingMismatch {
            frame,
            binding,
        }) if frame == Generation::new(4)? && binding == Generation::new(3)?
    ));

    let valid =
        encode_codex_operation_intent_wire_v3(&intent, id("runtime.agentd"), Generation::new(3)?)?;
    let mismatched = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3),
        id("runtime.agentd"),
        Generation::new(4)?,
        valid.payload().to_vec(),
    )?;
    assert!(matches!(
        decode_codex_operation_intent_wire_v3(&mismatched),
        Err(WireAdapterError::GenerationBindingMismatch {
            frame,
            binding,
        }) if frame == Generation::new(4)? && binding == Generation::new(3)?
    ));
    Ok(())
}

#[test]
fn wire_v3_rejects_wrong_producer_duplicate_fields_and_expired_admission()
-> Result<(), Box<dyn StdError>> {
    let intent = bound();
    let valid =
        encode_codex_operation_intent_wire_v3(&intent, id("runtime.agentd"), Generation::new(3)?)?;

    let wrong_producer = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3),
        id("context.compiler"),
        Generation::new(3)?,
        valid.payload().to_vec(),
    )?;
    assert!(matches!(
        decode_codex_operation_intent_wire_v3(&wrong_producer),
        Err(WireAdapterError::UnexpectedProducer(_))
    ));

    let payload = String::from_utf8(valid.payload().to_vec())?;
    let duplicated = payload.replacen(
        "\"deadline_ms\":100",
        "\"deadline_ms\":100,\"deadline_ms\":101",
        1,
    );
    assert_ne!(
        duplicated, payload,
        "test fixture did not duplicate deadline_ms"
    );
    let duplicate_field = WireEnvelopeV2::new(
        id(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3),
        id("runtime.agentd"),
        Generation::new(3)?,
        duplicated.into_bytes(),
    )?;
    assert!(matches!(
        decode_codex_operation_intent_wire_v3(&duplicate_field),
        Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "bound codex operation intent schema rejected"
        )))
    ));

    assert!(matches!(
        adapt_product_wire_v3(intent.deadline_ms, &intent, Generation::new(3)?),
        Err(WireAdapterError::Adapter(crate::Error::DeadlineExpired))
    ));
    Ok(())
}
