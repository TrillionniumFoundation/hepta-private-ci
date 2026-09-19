use std::io::Cursor;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("test generation")
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct TypedMessage {
    objective: String,
    step: u64,
}

impl TypedWirePayload for TypedMessage {
    fn schema_id() -> &'static str {
        "hepta.typed-message.v2"
    }
}

fn typed_schema() -> SchemaDefinition {
    SchemaDefinition::new(
        id(TypedMessage::schema_id()),
        &["objective", "step"],
        &[],
        UnknownFieldPolicy::Reject,
        4_096,
    )
    .expect("test schema")
}

#[test]
fn v2_binds_metadata_payload_and_out_of_band_binding() {
    let envelope = WireEnvelopeV2::new(
        id("hepta.test.v2"),
        id("platform.wire"),
        generation(7),
        br#"{"a":1}"#.to_vec(),
    )
    .expect("valid V2 envelope");
    let encoded = envelope.encode();
    assert_eq!(WireEnvelopeV2::decode(&encoded), Ok(envelope.clone()));
    assert_eq!(
        WireEnvelopeV2::decode_bound(&encoded, envelope.frame_digest()),
        Ok(envelope.clone())
    );

    let mut schema_tamper = encoded.clone();
    schema_tamper[HPTA_V2_HEADER_BYTES] = b'i';
    assert!(matches!(
        WireEnvelopeV2::decode(&schema_tamper),
        Err(WireV2Error::FrameDigestMismatch { .. })
    ));

    let mut generation_tamper = encoded.clone();
    generation_tamper[17] ^= 1;
    assert!(matches!(
        WireEnvelopeV2::decode(&generation_tamper),
        Err(WireV2Error::FrameDigestMismatch { .. })
    ));

    assert!(matches!(
        WireEnvelopeV2::decode_bound(&encoded, Digest32::of_bytes(b"wrong binding")),
        Err(WireV2Error::BindingMismatch { .. })
    ));
}

#[test]
fn negotiation_selects_highest_common_and_never_downgrades_critical_features() {
    let frame_digest = id(CAP_FRAME_DIGEST_V2);
    let negotiated = negotiate(&[HPTA_V1, HPTA_V2], &[HPTA_V2, HPTA_V1], &[frame_digest])
        .expect("V2 negotiation");
    assert_eq!(negotiated.version(), HPTA_V2);
    assert!(negotiated.supports(CAP_FRAME_DIGEST_V2));

    let required = id(CAP_SCHEMA_ADMISSION_V1);
    assert!(matches!(
        negotiate(&[HPTA_V1], &[HPTA_V1], &[required]),
        Err(NegotiationError::MissingCriticalCapability(_))
    ));
    assert_eq!(
        negotiate(&[99], &[99], &[]),
        Err(NegotiationError::NoCommonImplementedVersion)
    );
}

#[test]
fn schema_admission_rejects_missing_unknown_and_unregistered_payloads() {
    let message = TypedMessage {
        objective: "ndu".to_owned(),
        step: 1,
    };
    let mut registry = SchemaRegistry::new();
    registry.register(typed_schema()).expect("register schema");
    let envelope = registry
        .encode_typed(id("producer"), generation(2), &message)
        .expect("encode typed");
    let decoded: TypedMessage = registry.decode_typed(&envelope).expect("decode typed");
    assert_eq!(decoded, message);

    let unknown = WireEnvelopeV2::new(
        id(TypedMessage::schema_id()),
        id("producer"),
        generation(2),
        br#"{"objective":"ndu","step":1,"extra":true}"#.to_vec(),
    )
    .expect("raw envelope");
    assert_eq!(
        registry.admit(&unknown),
        Err(AdmissionError::UnknownField("extra".to_owned()))
    );

    let missing = WireEnvelopeV2::new(
        id(TypedMessage::schema_id()),
        id("producer"),
        generation(2),
        br#"{"objective":"ndu"}"#.to_vec(),
    )
    .expect("raw envelope");
    assert_eq!(
        registry.admit(&missing),
        Err(AdmissionError::MissingRequiredField("step".to_owned()))
    );

    let unregistered = WireEnvelopeV2::new(
        id("unknown.schema.v1"),
        id("producer"),
        generation(2),
        br#"{"objective":"ndu","step":1}"#.to_vec(),
    )
    .expect("raw envelope");
    assert_eq!(
        registry.admit(&unregistered),
        Err(AdmissionError::UnknownSchema("unknown.schema.v1".to_owned()))
    );
}

#[test]
fn streaming_reader_admits_header_before_bounded_body_allocation() {
    let v1 = WireEnvelope::new(id("s"), id("p"), generation(1), vec![1, 2, 3])
        .expect("valid V1");
    let v2 = WireEnvelopeV2::new(id("s"), id("p"), generation(2), vec![4, 5, 6])
        .expect("valid V2");

    let mut bytes = v1.encode();
    bytes.extend_from_slice(&v2.encode());
    let mut reader = FramedReader::new(Cursor::new(bytes));
    assert!(matches!(
        reader.read_next().expect("first"),
        Some(VersionedEnvelope::V1(_))
    ));
    assert!(matches!(
        reader.read_next().expect("second"),
        Some(VersionedEnvelope::V2(_))
    ));
    assert_eq!(reader.read_next().expect("eof"), None);

    let mut oversized = v1.encode();
    oversized[50..54]
        .copy_from_slice(&(MAX_WIRE_PAYLOAD_BYTES as u32 + 1).to_be_bytes());
    oversized.truncate(54);
    let mut reader = FramedReader::new(Cursor::new(oversized));
    assert_eq!(reader.read_next(), Err(StreamError::PayloadLength));
}

fn next_random(state: &mut u64) -> u64 {
    *state = state
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    *state
}

#[test]
fn deterministic_property_corpus_round_trips_and_arbitrary_bytes_never_panic() {
    let mut state = 0x9e37_79b9_7f4a_7c15_u64;
    for case in 0..256_u64 {
        let length = usize::try_from(next_random(&mut state) % 4_096 + 1).expect("bounded length");
        let mut payload = vec![0_u8; length];
        for byte in &mut payload {
            *byte = next_random(&mut state).to_le_bytes()[0];
        }
        let schema = id(&format!("property.schema.{case}"));
        let producer = id(&format!("property.producer.{case}"));
        let generation = generation(case + 1);

        let v1 = WireEnvelope::new(
            schema.clone(),
            producer.clone(),
            generation,
            payload.clone(),
        )
        .expect("property V1");
        let v1_bytes = v1.encode();
        let v1_decoded = WireEnvelope::decode(&v1_bytes).expect("decode V1");
        assert_eq!(v1_decoded, v1);
        assert_eq!(v1_decoded.encode(), v1_bytes);

        let v2 = WireEnvelopeV2::new(schema, producer, generation, payload)
            .expect("property V2");
        let v2_bytes = v2.encode();
        let v2_decoded = WireEnvelopeV2::decode(&v2_bytes).expect("decode V2");
        assert_eq!(v2_decoded, v2);
        assert_eq!(v2_decoded.encode(), v2_bytes);
    }

    for length in 0..2_048_usize {
        let mut bytes = vec![0_u8; length];
        for byte in &mut bytes {
            *byte = next_random(&mut state).to_le_bytes()[0];
        }
        assert!(
            std::panic::catch_unwind(|| {
                let _ = WireEnvelope::decode(&bytes);
                let _ = WireEnvelopeV2::decode(&bytes);
                let mut reader = FramedReader::new(Cursor::new(bytes.as_slice()));
                let _ = reader.read_next();
            })
            .is_ok()
        );
    }
}

#[test]
fn v2_matches_independent_frozen_vector() {
    let golden: [u8; 91] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x01, 0x03, 0x90, 0x58, 0xc6, 0xf2, 0xc0, 0xcb, 0x49, 0x2c, 0x53,
        0x3b, 0x0a, 0x4d, 0x14, 0xef, 0x77, 0xcc, 0x0f, 0x78, 0xab, 0xcc, 0xce, 0xd5, 0x28,
        0x7d, 0x84, 0xa1, 0xa2, 0x01, 0x1c, 0xfb, 0x81, 0x4b, 0xec, 0xc4, 0x58, 0x4b, 0xe7,
        0xf0, 0xab, 0xff, 0x19, 0x2c, 0x04, 0x9e, 0x90, 0x48, 0xbc, 0xea, 0x17, 0x17, 0x82,
        0xe0, 0xdb, 0x89, 0x1c, 0x79, 0xfd, 0x8d, 0x6d, 0x84, 0xd7, 0x7b, 0x52, 0x00, 0x00,
        0x00, 0x03, 0x73, 0x70, 0x01, 0x02, 0x03,
    ];
    let envelope = WireEnvelopeV2::new(id("s"), id("p"), generation(1), vec![1, 2, 3])
        .expect("valid frozen V2");
    assert_eq!(envelope.encode(), golden);
    assert_eq!(WireEnvelopeV2::decode(&golden), Ok(envelope));
}

#[test]
fn rejected_duplicate_schema_registration_does_not_replace_original_policy() {
    let schema_id = id("hepta.duplicate-schema.v1");
    let original = SchemaDefinition::new(
        schema_id.clone(),
        &["required"],
        &[],
        UnknownFieldPolicy::Reject,
        128,
    )
    .expect("original schema");
    let replacement = SchemaDefinition::new(
        schema_id.clone(),
        &["different"],
        &[],
        UnknownFieldPolicy::Allow,
        256,
    )
    .expect("replacement schema");
    let mut registry = SchemaRegistry::new();
    registry.register(original.clone()).expect("register original");
    assert_eq!(
        registry.register(replacement),
        Err(SchemaError::DuplicateSchema(schema_id.to_string()))
    );
    assert_eq!(registry.definition(&schema_id), Some(&original));
}

#[test]
fn unknown_critical_capability_reports_capability_failure_not_version_failure() {
    let unknown = id("hpta.future-critical.v1");
    assert_eq!(
        negotiate(&[HPTA_V2], &[HPTA_V2], &[unknown.clone()]),
        Err(NegotiationError::MissingCriticalCapability(
            unknown.to_string()
        ))
    );
}

#[test]
fn duplicate_json_keys_are_rejected_before_typed_decode() {
    let mut registry = SchemaRegistry::new();
    registry.register(typed_schema()).expect("register schema");
    let envelope = WireEnvelopeV2::new(
        id(TypedMessage::schema_id()),
        id("producer"),
        generation(2),
        br#"{"objective":"first","objective":"second","step":1}"#.to_vec(),
    )
    .expect("raw duplicate-key envelope");
    assert!(matches!(
        registry.admit(&envelope),
        Err(AdmissionError::Json(message))
            if message.contains("duplicate JSON object key objective")
    ));
}

#[test]
fn producer_registry_rejects_payload_that_does_not_satisfy_registered_schema() {
    let schema = SchemaDefinition::new(
        id(TypedMessage::schema_id()),
        &["objective", "step", "required_extra"],
        &[],
        UnknownFieldPolicy::Reject,
        4_096,
    )
    .expect("schema with extra required field");
    let mut registry = SchemaRegistry::new();
    registry.register(schema).expect("register schema");
    let value = TypedMessage {
        objective: "ndu".to_owned(),
        step: 1,
    };
    assert_eq!(
        registry.encode_typed(id("producer"), generation(2), &value),
        Err(TypedPayloadError::Admission(
            AdmissionError::MissingRequiredField("required_extra".to_owned())
        ))
    );
}

#[test]
fn streaming_reader_rejects_zero_generation_before_body_read() {
    let envelope = WireEnvelopeV2::new(id("s"), id("p"), generation(1), vec![1, 2, 3])
        .expect("valid V2");
    let mut header_only = envelope.encode();
    header_only[10..18].fill(0);
    header_only.truncate(HPTA_V2_HEADER_BYTES);
    let mut reader = FramedReader::new(Cursor::new(header_only));
    assert_eq!(reader.read_next(), Err(StreamError::Generation));
}
