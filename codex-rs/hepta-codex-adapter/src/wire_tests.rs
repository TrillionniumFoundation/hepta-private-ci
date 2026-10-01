use std::error::Error as StdError;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::NegotiationTranscript;
use codex_hepta_wire::RecordStreamLimits;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::SchemaPolicy;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionMacKey;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::negotiate;

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

fn managed_product_owner(
    channel: u8,
    endpoint: SessionEndpoint,
) -> Result<ManagedAuthenticatedWireSession, Box<dyn StdError>> {
    let descriptor = codex_operation_intent_wire_schema_v3()?;
    let role = id("role.runtime-codex-product");
    let required =
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![id(CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2)],
        vec![role.clone()],
        required,
    )?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let negotiated = negotiate(&offer, &offer, required)?;
    let transcript = NegotiationTranscript::from_offers(
        &offer,
        &offer,
        negotiated,
        registry.snapshot_digest(),
        &[channel; 32],
    )?;
    let session = WireSession::new(negotiated, role, registry, transcript)?;
    Ok(ManagedAuthenticatedWireSession::new(
        session,
        SessionMacKey::new([41; 32])?,
        endpoint,
    )?)
}

fn adapt_admitted_product_frame(
    now_ms: u64,
    frame: &DecodedEnvelope,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let DecodedEnvelope::V2(envelope) = frame else {
        return Err(WireAdapterError::Payload(SchemaCodecError::Rejected(
            "product-bound runtime.codex requires HPTA V2",
        )));
    };
    let intent = decode_codex_operation_intent_wire_v3(envelope)?;
    adapt_request(now_ms, intent).map_err(WireAdapterError::Adapter)
}

#[test]
fn managed_wire_v3_fragmentation_preserves_adapter_digest_and_authority_boundary()
-> Result<(), Box<dyn StdError>> {
    let intent = bound();
    let expected_digest = crate::request_digest(&intent);
    let envelope = encode_codex_operation_intent_wire_v3(
        &intent,
        id(CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2),
        Generation::new(3)?,
    )?;
    let mut sender = managed_product_owner(7, SessionEndpoint::Initiator)?;
    let record = sender.seal_envelope(&DecodedEnvelope::V2(envelope))?;
    let limits = RecordStreamLimits {
        max_feed_bytes: 7,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream =
        managed_product_owner(7, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut offset = 0;
    let mut delivered = Vec::new();
    while offset < record.len() {
        let end = (offset + 19).min(record.len());
        while offset < end {
            let feed = stream.feed(&record[offset..end]);
            let consumed = feed.bytes_consumed();
            assert!(consumed > 0 && consumed <= limits.max_feed_bytes);
            assert!(feed.batch().terminal_error().is_none());
            let (batch, _) = feed.into_parts();
            delivered.extend(batch.into_parts().0);
            offset += consumed;
        }
    }
    assert_eq!(delivered.len(), 1);
    let receipt = adapt_admitted_product_frame(1, &delivered[0])?;
    assert_eq!(receipt.request_digest, expected_digest);
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    stream.finish()?;
    sender.retire();
    Ok(())
}

#[test]
fn managed_wire_v3_terminal_suffix_commits_only_the_authenticated_prefix()
-> Result<(), Box<dyn StdError>> {
    let intent = bound();
    let envelope = encode_codex_operation_intent_wire_v3(
        &intent,
        id(CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2),
        Generation::new(3)?,
    )?;
    let frame = DecodedEnvelope::V2(envelope);
    let mut sender = managed_product_owner(9, SessionEndpoint::Initiator)?;
    let first = sender.seal_envelope(&frame)?;
    let mut tampered = sender.seal_envelope(&frame)?;
    let tag = tampered.last_mut().expect("record tag");
    *tag = tag.wrapping_add(1);
    let mut bytes = first.clone();
    bytes.extend(tampered);

    let mut stream = managed_product_owner(9, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), bytes.len());
    assert_eq!(feed.batch().frames().len(), 1);
    assert!(feed.batch().terminal_error().is_some());

    let (batch, _) = feed.into_parts();
    let (frames, terminal_error) = batch.into_parts();
    let mut committed_prefix = 0_u64;
    for accepted in &frames {
        let receipt = adapt_admitted_product_frame(1, accepted)?;
        assert_eq!(receipt.request_digest, crate::request_digest(&intent));
        committed_prefix += 1;
    }
    assert_eq!(committed_prefix, 1);
    assert!(terminal_error.is_some());
    assert!(stream.is_terminal());
    assert_eq!(stream.buffer_capacity_bytes(), 0);

    let replay = stream.feed(&first);
    assert_eq!(replay.bytes_consumed(), 0);
    assert!(replay.batch().frames().is_empty());
    assert_eq!(committed_prefix, 1);
    Ok(())
}

#[test]
fn managed_wire_v3_unauthenticated_record_never_reaches_the_adapter()
-> Result<(), Box<dyn StdError>> {
    let envelope = encode_codex_operation_intent_wire_v3(
        &bound(),
        id(CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2),
        Generation::new(3)?,
    )?;
    let mut sender = managed_product_owner(11, SessionEndpoint::Initiator)?;
    let mut record = sender.seal_envelope(&DecodedEnvelope::V2(envelope))?;
    *record.last_mut().expect("record tag") ^= 1;

    let mut stream = managed_product_owner(11, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&record);
    assert_eq!(feed.bytes_consumed(), record.len());
    assert!(feed.batch().frames().is_empty());
    assert!(feed.batch().terminal_error().is_some());
    assert!(stream.is_terminal());
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    Ok(())
}
