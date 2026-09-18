use std::error::Error;
use std::io::Cursor;
use std::str;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::HPTA_V2;
use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::NegotiationError;
use crate::NegotiationPolicy;
use crate::PayloadCodec;
use crate::SchemaError;
use crate::SchemaRegistry;
use crate::StaticSchemaAdmission;
use crate::StreamWireError;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireFeature;
use crate::WireFrame;
use crate::WireOffer;
use crate::WireVersion;
use crate::negotiate;
use crate::read_frame;

fn strict_record(payload: &[u8]) -> Result<(), &'static str> {
    let text = str::from_utf8(payload).map_err(|_| "payload is not utf-8")?;
    let mut kind = false;
    let mut body = false;
    for field in text.split(';') {
        let Some((name, value)) = field.split_once('=') else {
            return Err("field is not key=value");
        };
        if value.is_empty() {
            return Err("field value is empty");
        }
        match name {
            "kind" if !kind => kind = true,
            "body" if !body => body = true,
            "kind" | "body" => return Err("duplicate field"),
            _ => return Err("unknown field"),
        }
    }
    if !kind || !body {
        return Err("missing required field");
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Record {
    kind: String,
    body: String,
}

struct RecordCodec {
    schema: StableId,
}

impl RecordCodec {
    fn new() -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            schema: StableId::new("hepta.record.v1")?,
        })
    }
}

impl PayloadCodec for RecordCodec {
    type Value = Record;

    fn schema_id(&self) -> &StableId {
        &self.schema
    }

    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaError> {
        if value
            .kind
            .bytes()
            .chain(value.body.bytes())
            .any(|byte| matches!(byte, b';' | b'='))
        {
            return Err(SchemaError::CodecRejected {
                schema: self.schema.clone(),
                reason: "reserved delimiter in field".to_owned(),
            });
        }
        Ok(format!("kind={};body={}", value.kind, value.body).into_bytes())
    }

    fn decode(&self, payload: &[u8]) -> Result<Self::Value, SchemaError> {
        let text = str::from_utf8(payload).map_err(|_| SchemaError::CodecRejected {
            schema: self.schema.clone(),
            reason: "payload is not utf-8".to_owned(),
        })?;
        let mut kind = None;
        let mut body = None;
        for field in text.split(';') {
            let Some((name, value)) = field.split_once('=') else {
                return Err(SchemaError::CodecRejected {
                    schema: self.schema.clone(),
                    reason: "field is not key=value".to_owned(),
                });
            };
            match name {
                "kind" => kind = Some(value.to_owned()),
                "body" => body = Some(value.to_owned()),
                _ => {
                    return Err(SchemaError::CodecRejected {
                        schema: self.schema.clone(),
                        reason: "unknown field".to_owned(),
                    });
                }
            }
        }
        let Some(kind) = kind else {
            return Err(SchemaError::CodecRejected {
                schema: self.schema.clone(),
                reason: "missing kind".to_owned(),
            });
        };
        let Some(body) = body else {
            return Err(SchemaError::CodecRejected {
                schema: self.schema.clone(),
                reason: "missing body".to_owned(),
            });
        };
        Ok(Record { kind, body })
    }
}

#[test]
fn v2_complete_frame_digest_binds_metadata_and_payload() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        StableId::new("s")?,
        StableId::new("p")?,
        Generation::new(1)?,
        vec![1, 2, 3],
    )?;
    let encoded = envelope.encode();
    for index in [54_usize, 55, 17, encoded.len() - 1] {
        let mut tampered = encoded.clone();
        if index == 17 {
            tampered[index] = 2;
        } else {
            tampered[index] ^= 1;
        }
        assert!(matches!(
            WireEnvelopeV2::decode(&tampered),
            Err(WireError::FrameDigestMismatch { .. })
        ));
    }
    assert_eq!(WireEnvelopeV2::decode(&encoded)?, envelope);
    Ok(())
}

#[test]
fn v2_frame_matches_frozen_bytes_not_only_its_own_encoder() -> Result<(), Box<dyn Error>> {
    // Independently computed HPTA V2 vector:
    // schema=s, producer=p, generation=1, payload=010203.
    let golden: [u8; 59] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x01, 0x11, 0x1f, 0x5b, 0xfd, 0x88, 0x14, 0x5a, 0x71, 0x5c, 0x61, 0xa8, 0xd0,
        0x90, 0xbf, 0x0e, 0xe8, 0x20, 0xb9, 0x24, 0xd4, 0x64, 0x96, 0x16, 0x04, 0x73, 0xc8, 0x47,
        0x05, 0x73, 0xb6, 0x31, 0x5d, 0x00, 0x00, 0x00, 0x03, b's', b'p', 0x01, 0x02, 0x03,
    ];
    let expected = WireEnvelopeV2::new(
        StableId::new("s")?,
        StableId::new("p")?,
        Generation::new(1)?,
        vec![1, 2, 3],
    )?;
    assert_eq!(expected.encode(), golden);
    assert_eq!(WireEnvelopeV2::decode(&golden)?, expected);
    Ok(())
}

#[test]
fn negotiation_selects_highest_common_and_prevents_required_feature_downgrade(
) -> Result<(), Box<dyn Error>> {
    let local = WireOffer::hpta_supported();
    let remote = WireOffer::hpta_supported();
    let negotiated = negotiate(
        &local,
        &remote,
        &NegotiationPolicy::require_complete_frame_digest(),
    )?;
    assert_eq!(negotiated.version(), WireVersion::V2);

    let v1_only = WireOffer::new(vec![WireVersion::V1], Vec::new())?;
    assert_eq!(
        negotiate(
            &local,
            &v1_only,
            &NegotiationPolicy::require_complete_frame_digest()
        ),
        Err(NegotiationError::RequiredFeatureUnavailable(
            WireFeature::CompleteFrameDigest
        ))
    );
    assert_eq!(
        negotiate(
            &local,
            &v1_only,
            &NegotiationPolicy::new(WireVersion::V2, Vec::new())
        ),
        Err(NegotiationError::NoCompatibleVersion)
    );
    Ok(())
}

#[test]
fn schema_registry_enforces_known_schema_required_and_unknown_fields(
) -> Result<(), Box<dyn Error>> {
    let codec = RecordCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(Box::new(StaticSchemaAdmission::new(
        codec.schema_id().clone(),
        256,
        strict_record,
    )?))?;

    let record = Record {
        kind: "note".to_owned(),
        body: "bounded".to_owned(),
    };
    let payload = registry.encode_typed(&codec, &record)?;
    assert_eq!(
        registry.decode_typed(&codec, codec.schema_id(), &payload)?,
        record
    );

    assert!(matches!(
        registry.admit(codec.schema_id(), b"kind=note"),
        Err(SchemaError::AdmissionRejected { .. })
    ));
    assert!(matches!(
        registry.admit(codec.schema_id(), b"kind=note;body=x;critical=y"),
        Err(SchemaError::AdmissionRejected { .. })
    ));
    assert!(matches!(
        registry.admit(&StableId::new("unknown.schema")?, b"x=1"),
        Err(SchemaError::UnknownSchema(_))
    ));
    Ok(())
}

#[test]
fn streaming_reader_admits_header_before_body_allocation() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        StableId::new("stream.schema")?,
        StableId::new("stream.producer")?,
        Generation::new(9)?,
        b"stream-body".to_vec(),
    )?;
    let encoded = envelope.encode();
    let mut cursor = Cursor::new(encoded);
    assert_eq!(read_frame(&mut cursor)?, WireFrame::V2(envelope));

    let mut oversized_header = [0_u8; 54];
    oversized_header[..4].copy_from_slice(b"HPTA");
    oversized_header[4..6].copy_from_slice(&HPTA_V2.to_be_bytes());
    oversized_header[6..8].copy_from_slice(&1_u16.to_be_bytes());
    oversized_header[8..10].copy_from_slice(&1_u16.to_be_bytes());
    oversized_header[10..18].copy_from_slice(&1_u64.to_be_bytes());
    oversized_header[50..54]
        .copy_from_slice(&((MAX_WIRE_PAYLOAD_BYTES as u32) + 1).to_be_bytes());
    let mut header_only = Cursor::new(oversized_header);
    assert!(matches!(
        read_frame(&mut header_only),
        Err(StreamWireError::Wire(WireError::PayloadLength))
    ));
    Ok(())
}

fn xorshift64(state: &mut u64) -> u64 {
    let mut value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    value
}

#[test]
fn deterministic_fuzz_smoke_never_panics_and_valid_v2_roundtrips(
) -> Result<(), Box<dyn Error>> {
    let mut state = 0x6a09_e667_f3bc_c909_u64;
    for _ in 0..4096 {
        let length = (xorshift64(&mut state) as usize) % 512;
        let mut bytes = vec![0_u8; length];
        for byte in &mut bytes {
            *byte = xorshift64(&mut state) as u8;
        }
        let _ = WireFrame::decode(&bytes);

        let payload_length = ((xorshift64(&mut state) as usize) % 256) + 1;
        let mut payload = vec![0_u8; payload_length];
        for byte in &mut payload {
            *byte = xorshift64(&mut state) as u8;
        }
        let generation = (xorshift64(&mut state) | 1).max(1);
        let envelope = WireEnvelopeV2::new(
            StableId::new("property.schema")?,
            StableId::new("property.producer")?,
            Generation::new(generation)?,
            payload,
        )?;
        let encoded = envelope.encode();
        assert_eq!(WireFrame::decode(&encoded)?, WireFrame::V2(envelope));
    }
    Ok(())
}
