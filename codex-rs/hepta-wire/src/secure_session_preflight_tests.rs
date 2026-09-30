use std::cell::Cell;

use crate::CanonicalizationProfile;
use crate::FrozenSchemaRegistryBuilder;
use crate::GenerationPolicy;
use crate::SchemaAdmissionError;
use crate::SchemaDescriptor;
use crate::SchemaPolicy;
use crate::WireCapabilities;

use super::*;

struct CountingCodec {
    descriptor: SchemaDescriptor,
    encode_calls: Cell<usize>,
}

impl PayloadCodec for CountingCodec {
    type Value = String;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        self.encode_calls.set(self.encode_calls.get() + 1);
        Ok(value.as_bytes().to_vec())
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        String::from_utf8(payload.to_vec())
            .map_err(|_| SchemaCodecError::Rejected("non-UTF-8 message"))
    }
}

#[derive(Clone, Copy)]
enum Rejection {
    Version,
    Producer,
    Role,
    Capability,
    Generation,
}

fn session(
    offer: &NegotiationOffer,
    role: StableId,
) -> Result<(WireSession, CountingCodec), Box<dyn Error>> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.preflight.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        256,
    )?;
    let policy = SchemaPolicy::new_bound(
        descriptor.clone(),
        Digest32::of_bytes(b"preflight-schema-v1"),
        GenerationPolicy::AtLeast(7),
        CanonicalizationProfile::CodecOwnedStrictV1,
        vec![StableId::new("producer.allowed")?],
        vec![StableId::new("role.allowed")?],
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION),
    )?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let negotiated = negotiate(offer, offer, WireCapabilities::NONE)?;
    let transcript = NegotiationTranscript::from_offers(
        offer,
        offer,
        negotiated,
        registry.snapshot_digest(),
        &[7; 32],
    )?;
    Ok((
        WireSession::new(negotiated, role, registry, transcript)?,
        CountingCodec {
            descriptor,
            encode_calls: Cell::new(0),
        },
    ))
}

#[test]
fn denied_session_metadata_never_invokes_payload_encoder() -> Result<(), Box<dyn Error>> {
    for rejection in [
        Rejection::Version,
        Rejection::Producer,
        Rejection::Role,
        Rejection::Capability,
        Rejection::Generation,
    ] {
        let offer = match rejection {
            Rejection::Version => {
                NegotiationOffer::new(vec![1], WireCapabilities::SCHEMA_ADMISSION)?
            }
            Rejection::Capability => {
                NegotiationOffer::new(vec![2], WireCapabilities::METADATA_BOUND_DIGEST)?
            }
            Rejection::Producer | Rejection::Role | Rejection::Generation => {
                NegotiationOffer::current()
            }
        };
        let role = match rejection {
            Rejection::Role => "role.denied",
            Rejection::Version
            | Rejection::Producer
            | Rejection::Capability
            | Rejection::Generation => "role.allowed",
        };
        let producer = match rejection {
            Rejection::Producer => "producer.denied",
            Rejection::Version
            | Rejection::Role
            | Rejection::Capability
            | Rejection::Generation => "producer.allowed",
        };
        let generation = match rejection {
            Rejection::Generation => 6,
            Rejection::Version | Rejection::Producer | Rejection::Role | Rejection::Capability => 7,
        };
        let (session, codec) = session(&offer, StableId::new(role)?)?;
        let error = session
            .encode_typed_envelope(
                StableId::new(producer)?,
                Generation::new(generation)?,
                &codec,
                &"hello".to_string(),
            )
            .expect_err("denied session metadata must reject");
        assert!(matches!(
            (rejection, error),
            (
                Rejection::Version,
                WireSessionError::Codec(SchemaCodecError::Admission(
                    SchemaAdmissionError::UnsupportedSchemaVersion { .. }
                ))
            ) | (
                Rejection::Producer,
                WireSessionError::Admission {
                    source: FrozenAdmissionError::ProducerDenied { .. },
                    ..
                }
            ) | (
                Rejection::Role,
                WireSessionError::Admission {
                    source: FrozenAdmissionError::RoleDenied { .. },
                    ..
                }
            ) | (
                Rejection::Capability,
                WireSessionError::Admission {
                    source: FrozenAdmissionError::CapabilityDenied { .. },
                    ..
                }
            ) | (
                Rejection::Generation,
                WireSessionError::Admission {
                    source: FrozenAdmissionError::GenerationDenied { .. },
                    ..
                }
            )
        ));
        assert_eq!(codec.encode_calls.get(), 0);
    }
    Ok(())
}

#[test]
fn admitted_metadata_still_checks_payload_bounds_after_encoding() -> Result<(), Box<dyn Error>> {
    let (session, codec) = session(&NegotiationOffer::current(), StableId::new("role.allowed")?)?;
    let value = "hello".to_string();
    let envelope = session.encode_typed_envelope(
        StableId::new("producer.allowed")?,
        Generation::new(7)?,
        &codec,
        &value,
    )?;
    assert_eq!(session.decode_typed_envelope(&envelope, &codec)?, value);
    assert_eq!(codec.encode_calls.get(), 1);
    assert!(matches!(
        session.encode_typed_envelope(
            StableId::new("producer.allowed")?,
            Generation::new(7)?,
            &codec,
            &"x".repeat(257),
        ),
        Err(WireSessionError::Codec(SchemaCodecError::Admission(
            SchemaAdmissionError::PayloadLength { .. }
        )))
    ));
    assert_eq!(codec.encode_calls.get(), 2);
    Ok(())
}
