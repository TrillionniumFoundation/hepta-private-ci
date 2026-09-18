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

fn request() -> CompilationRequest {
    CompilationRequest {
        compilation_id: id("compilation:wire"),
        run_snapshot_digest: digest(b"snapshot"),
        objective_digest: digest(b"objective"),
        token_budget: 128,
        items: vec![
            ContextItem {
                item_id: id("instruction:wire"),
                role: ContextRole::TrustedInstruction,
                content_digest: digest(b"instruction"),
                source_digest: digest(b"trusted-source"),
                token_count: 16,
                contains_secret: false,
            },
            ContextItem {
                item_id: id("evidence:wire"),
                role: ContextRole::UntrustedEvidence,
                content_digest: digest(b"evidence"),
                source_digest: digest(b"untrusted-source"),
                token_count: 8,
                contains_secret: false,
            },
        ],
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

fn ingress_policy() -> ContextWireIngressPolicy {
    ContextWireIngressPolicy::new(
        negotiated_v2(),
        id("intelligence.control"),
        generation(),
    )
}

fn encode_request(value: &CompilationRequest) -> (StableId, Vec<u8>) {
    let mut registry = SchemaRegistry::new();
    let Ok(codec) = register_context_wire_schema(&mut registry) else {
        panic!("context.compiler wire schema must register");
    };
    let Ok(payload) = registry.encode_typed(&codec, value) else {
        panic!("valid context compilation request must encode");
    };
    (codec.schema_id().clone(), payload)
}

#[test]
fn negotiated_v2_wire_request_enters_existing_context_compiler() {
    let value = request();
    let (schema, payload) = encode_request(&value);
    let Ok(envelope) = WireEnvelopeV2::new(
        schema,
        id("intelligence.control"),
        generation(),
        payload,
    ) else {
        panic!("valid V2 context request envelope must construct");
    };
    let frame = WireFrame::V2(envelope);

    let Ok(decoded) = decode_wire_request(&frame, &ingress_policy()) else {
        panic!("registered V2 context request must decode");
    };
    assert_eq!(decoded, value);

    let Ok(receipt) = compile_wire(&frame, &ingress_policy()) else {
        panic!("wire request must enter the existing context compiler");
    };
    assert_eq!(receipt.compilation_id, value.compilation_id);
    assert!(!receipt.authority.grants_any());
    assert_eq!(receipt.used_tokens, 24);
}

#[test]
fn negotiated_v2_context_ingress_rejects_v1_downgrade() {
    let value = request();
    let (schema, payload) = encode_request(&value);
    let Ok(envelope) = WireEnvelope::new(
        schema,
        id("intelligence.control"),
        generation(),
        payload,
    ) else {
        panic!("valid V1 frame must construct");
    };

    assert_eq!(
        decode_wire_request(&WireFrame::V1(envelope), &ingress_policy()),
        Err(ContextWireIngressError::VersionMismatch {
            expected: 2,
            observed: 1,
        })
    );
}

#[test]
fn context_wire_ingress_rejects_wrong_source_context() {
    let value = request();
    let (schema, payload) = encode_request(&value);

    let Ok(wrong_producer) = WireEnvelopeV2::new(
        schema.clone(),
        id("unexpected.producer"),
        generation(),
        payload.clone(),
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    assert!(matches!(
        decode_wire_request(&WireFrame::V2(wrong_producer), &ingress_policy()),
        Err(ContextWireIngressError::ProducerMismatch { .. })
    ));

    let Ok(other_generation) = Generation::new(2) else {
        panic!("test generation must be valid");
    };
    let Ok(wrong_generation) = WireEnvelopeV2::new(
        schema,
        id("intelligence.control"),
        other_generation,
        payload,
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    assert!(matches!(
        decode_wire_request(&WireFrame::V2(wrong_generation), &ingress_policy()),
        Err(ContextWireIngressError::GenerationMismatch { .. })
    ));
}

#[test]
fn context_wire_ingress_rejects_schema_and_payload_mismatch() {
    let (_, payload) = encode_request(&request());
    let Ok(wrong_schema) = WireEnvelopeV2::new(
        id("context.compiler.wrong-schema.v1"),
        id("intelligence.control"),
        generation(),
        payload,
    ) else {
        panic!("structurally valid V2 frame must construct");
    };
    assert!(matches!(
        decode_wire_request(&WireFrame::V2(wrong_schema), &ingress_policy()),
        Err(ContextWireIngressError::Schema(
            SchemaError::CodecSchemaMismatch { .. }
        ))
    ));

    let Ok(codec) = ContextCompilationRequestWireCodec::new() else {
        panic!("context.compiler schema must be valid");
    };
    let Ok(malformed) = WireEnvelopeV2::new(
        codec.schema_id().clone(),
        id("intelligence.control"),
        generation(),
        vec![1],
    ) else {
        panic!("framing accepts opaque payload before schema admission");
    };
    assert!(matches!(
        decode_wire_request(&WireFrame::V2(malformed), &ingress_policy()),
        Err(ContextWireIngressError::Schema(
            SchemaError::AdmissionRejected { .. }
        ))
    ));
}
