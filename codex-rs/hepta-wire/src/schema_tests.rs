use std::error::Error;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::decode_envelope;

#[derive(Clone, Debug, Eq, PartialEq)]
struct DemoValue {
    sequence: u32,
    body: String,
}

#[derive(Debug)]
struct DemoCodec {
    schema: StableId,
}

impl DemoCodec {
    fn new() -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            schema: StableId::new("hepta.demo.message.v1")?,
        })
    }
}

fn decode_demo_payload(payload: &[u8]) -> Result<DemoValue, PayloadCodecError> {
    if payload.len() < 6 {
        return Err(PayloadCodecError::new("demo payload is truncated"));
    }
    let sequence = u32::from_be_bytes(
        payload[..4]
            .try_into()
            .map_err(|_| PayloadCodecError::new("demo sequence is truncated"))?,
    );
    let body_length = usize::from(u16::from_be_bytes(
        payload[4..6]
            .try_into()
            .map_err(|_| PayloadCodecError::new("demo body length is truncated"))?,
    ));
    let expected = 6_usize
        .checked_add(body_length)
        .ok_or_else(|| PayloadCodecError::new("demo payload length overflow"))?;
    if payload.len() != expected {
        return Err(PayloadCodecError::new(
            "demo payload has unknown or trailing fields",
        ));
    }
    let body = std::str::from_utf8(&payload[6..])
        .map_err(|_| PayloadCodecError::new("demo body is not UTF-8"))?
        .to_string();
    Ok(DemoValue { sequence, body })
}

impl PayloadCodec for DemoCodec {
    type Value = DemoValue;

    fn schema(&self) -> &StableId {
        &self.schema
    }

    fn encode_payload(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError> {
        let body = value.body.as_bytes();
        let body_length = u16::try_from(body.len())
            .map_err(|_| PayloadCodecError::new("demo body is too large"))?;
        let mut bytes = Vec::with_capacity(6 + body.len());
        bytes.extend_from_slice(&value.sequence.to_be_bytes());
        bytes.extend_from_slice(&body_length.to_be_bytes());
        bytes.extend_from_slice(body);
        Ok(bytes)
    }

    fn decode_payload(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError> {
        decode_demo_payload(payload)
    }
}

fn validate_demo(payload: &[u8]) -> Result<(), PayloadValidationError> {
    decode_demo_payload(payload)
        .map(|_| ())
        .map_err(|_| PayloadValidationError::new("demo payload validation failed"))
}

fn policy(
    codec: &DemoCodec,
    producer: StableId,
) -> Result<(SchemaRegistry, ProducerAdmission), Box<dyn Error>> {
    let mut registry = SchemaRegistry::new();
    registry.register(SchemaRule::new(
        codec.schema().clone(),
        4096,
        validate_demo,
    )?)?;
    let producers = ProducerAdmission::allow_list([producer])?;
    Ok((registry, producers))
}

#[test]
fn typed_v2_round_trip_requires_schema_and_producer_admission() -> Result<(), Box<dyn Error>> {
    let codec = DemoCodec::new()?;
    let producer = StableId::new("runtime.codex")?;
    let generation = Generation::new(9)?;
    let value = DemoValue {
        sequence: 7,
        body: "bounded".to_string(),
    };
    let encoded = encode_typed(
        &codec,
        producer.clone(),
        generation,
        &value,
        WireVersion::V2,
    )?;
    let decoded = decode_envelope(&encoded)?;
    let (registry, producers) = policy(&codec, producer)?;
    let admitted = AdmissionPolicy::new(&registry, &producers).admit(&decoded)?;
    let typed = decode_typed(&codec, admitted)?;
    assert_eq!(
        typed,
        TypedEnvelope {
            version: WireVersion::V2,
            schema: codec.schema().clone(),
            producer: StableId::new("runtime.codex")?,
            generation,
            value,
        }
    );
    Ok(())
}

#[test]
fn unknown_schema_and_producer_fail_closed() -> Result<(), Box<dyn Error>> {
    let codec = DemoCodec::new()?;
    let allowed = StableId::new("runtime.codex")?;
    let denied = StableId::new("untrusted.producer")?;
    let generation = Generation::new(1)?;
    let value = DemoValue {
        sequence: 1,
        body: "x".to_string(),
    };
    let (registry, producers) = policy(&codec, allowed.clone())?;

    let denied_bytes = encode_typed(&codec, denied, generation, &value, WireVersion::V2)?;
    let denied_frame = decode_envelope(&denied_bytes)?;
    assert!(matches!(
        AdmissionPolicy::new(&registry, &producers).admit(&denied_frame),
        Err(AdmissionError::ProducerDenied(_))
    ));

    let unknown = WireEnvelopeV2::new(
        StableId::new("hepta.unknown.v1")?,
        allowed,
        generation,
        vec![1],
    )?;
    let unknown = decode_envelope(&unknown.encode())?;
    assert!(matches!(
        AdmissionPolicy::new(&registry, &producers).admit(&unknown),
        Err(AdmissionError::UnknownSchema(_))
    ));
    Ok(())
}

#[test]
fn codec_rejects_unknown_trailing_fields() -> Result<(), Box<dyn Error>> {
    let codec = DemoCodec::new()?;
    let value = DemoValue {
        sequence: 5,
        body: "strict".to_string(),
    };
    let mut payload = codec.encode_payload(&value)?;
    payload.push(0);
    assert!(codec.decode_payload(&payload).is_err());
    Ok(())
}
