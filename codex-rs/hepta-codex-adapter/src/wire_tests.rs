use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::NegotiatedWire;
use codex_hepta_wire::NegotiationPolicy;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::SchemaError;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::WireEnvelope;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireFrame;
use codex_hepta_wire::WireOffer;
use codex_hepta_wire::negotiate;

use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation() -> Generation {
    let Ok(value) = Generation::new(1) else {
        panic!("test generation must be valid");
    };
    value
}

fn intent() -> CodexOperationIntent {
    CodexOperationIntent {
        operation_id: id("operation:wire"),
        thread_id: id("thread:wire"),
        method_id: id("method:wire"),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        deadline_ms: 2_000,
    }
}

fn negotiated_v2() -> NegotiatedWire {
    let local = WireOffer::hpta_supported();
    let remote = WireOffer::hpta_supported();
    let Ok(negotiated) = negotiate(
        &local,
        &remote,
        &NegotiationPolicy::require_complete_frame_digest(),
    ) else {
        panic!("V2 peers must negotiate complete-frame integrity");
    };
    negotiated
}

fn ingress_policy() -> CodexWireIngressPolicy {
    CodexWireIngressPolicy::new(negotiated_v2(), id("runtime.agentd"), generation())
}

fn encode_intent(value: &CodexOperationIntent) -> (StableId, Vec<u8>) {
    let mut registry = SchemaRegistry::new();
    let Ok(codec) = register_wire_schema(&mut registry) else {
        panic!("runtime.codex wire schema must register");
    };
    let Ok(payload) = registry.encode_typed(&codec, value) else {
        panic!("valid runtime.codex operation intent must encode");
    };
    (codec.schema_id().clone(), payload)
}

#[test]
fn negotiated_v2_wire_intent_enters_existing_codex_adapter() {
    let value = intent();
    let (schema, payload) = encode_intent(&value);
    let Ok(envelope) = WireEnvelopeV2::new(
        schema,
        id("runtime.agentd"),
        generation(),
        payload,
    ) else {
        panic!("valid V2 runtime.codex envelope must construct");
    };
    let frame = WireFrame::V2(envelope);

    let Ok(decoded) = decode_wire_intent(&frame, &ingress_policy()) else {
        panic!("registered V2 runtime.codex intent must decode");
    };
    assert_eq!(decoded, value);

    let Ok(receipt) = adapt_wire(1_000, &frame, &ingress_policy(), None) else {
        panic!("wire intent must enter the existing adapter");
    };
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.operation_id, value.operation_id);
}

#[test]
fn negotiated_v2_wire_ingress_rejects_v1_downgrade() {
    let value = intent();
    let (schema, payload) = encode_intent(&value);
    let Ok(envelope) = WireEnvelope::new(
        schema,
        id("runtime.agentd"),
        generation(),
        payload,
    ) else {
        panic!("valid V1 frame must construct");
    };
    let frame = WireFrame::V1(envelope);

    assert_eq!(
        decode_wire_intent(&frame, &ingress_policy()),
        Err(WireIngressError::VersionMismatch {
            expected: 2,
            observed: 1,
        })
    );
}

#[test]
fn wire_ingress_rejects_wrong_producer_and_generation() {
    let value = intent();
    let (schema, payload) = encode_intent(&value);
    let Ok(wrong_producer) = WireEnvelopeV2::new(
        schema.clone(),
        id("unexpected.producer"),
        generation(),
        payload.clone(),
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    assert!(matches!(
        decode_wire_intent(&WireFrame::V2(wrong_producer), &ingress_policy()),
        Err(WireIngressError::ProducerMismatch { .. })
    ));

    let Ok(other_generation) = Generation::new(2) else {
        panic!("test generation must be valid");
    };
    let Ok(wrong_generation) = WireEnvelopeV2::new(
        schema,
        id("runtime.agentd"),
        other_generation,
        payload,
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    assert!(matches!(
        decode_wire_intent(&WireFrame::V2(wrong_generation), &ingress_policy()),
        Err(WireIngressError::GenerationMismatch { .. })
    ));
}

#[test]
fn wire_ingress_rejects_wrong_schema_before_adapter_entry() {
    let (_, payload) = encode_intent(&intent());
    let Ok(envelope) = WireEnvelopeV2::new(
        id("runtime.codex.wrong-schema.v1"),
        id("runtime.agentd"),
        generation(),
        payload,
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    let frame = WireFrame::V2(envelope);

    assert!(matches!(
        decode_wire_intent(&frame, &ingress_policy()),
        Err(WireIngressError::Schema(
            SchemaError::CodecSchemaMismatch { .. }
        ))
    ));
}

#[test]
fn wire_ingress_rejects_malformed_registered_payload() {
    let Ok(codec) = CodexOperationIntentWireCodec::new() else {
        panic!("runtime.codex schema must be valid");
    };
    let Ok(envelope) = WireEnvelopeV2::new(
        codec.schema_id().clone(),
        id("runtime.agentd"),
        generation(),
        vec![1],
    ) else {
        panic!("framing accepts opaque payload before schema admission");
    };
    let frame = WireFrame::V2(envelope);

    assert!(matches!(
        decode_wire_intent(&frame, &ingress_policy()),
        Err(WireIngressError::Schema(
            SchemaError::AdmissionRejected { .. }
        ))
    ));
}
