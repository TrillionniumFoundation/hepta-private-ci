use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CanonicalizationProfile;
use crate::DecodedEnvelope;
use crate::FrozenSchemaRegistry;
use crate::PayloadCodec;
use crate::SchemaCodecError;
use crate::SchemaDescriptor;
use crate::WireSession;
use crate::WireSessionError;

/// Typed payload codec whose semantic revision and canonicalization contract
/// are explicit inputs to the frozen session policy.
///
/// `PayloadCodec` alone proves only that a descriptor and typed serializer are
/// available. Production session code should require this trait so a different
/// codec cannot reuse the same schema identifier while silently changing field
/// semantics or canonical bytes.
pub trait BoundPayloadCodec: PayloadCodec {
    fn schema_revision(&self) -> Digest32;

    fn canonicalization_profile(&self) -> CanonicalizationProfile;
}

/// Attach immutable semantic metadata to an existing codec without changing
/// its value type or serialization implementation.
#[derive(Clone, Copy)]
pub struct PayloadCodecBinding<'a, C: PayloadCodec> {
    codec: &'a C,
    schema_revision: Digest32,
    canonicalization_profile: CanonicalizationProfile,
}

impl<'a, C: PayloadCodec> PayloadCodecBinding<'a, C> {
    pub fn new(
        codec: &'a C,
        schema_revision: Digest32,
        canonicalization_profile: CanonicalizationProfile,
    ) -> Result<Self, CodecBindingError> {
        if schema_revision.is_zero() {
            return Err(CodecBindingError::ZeroSchemaRevision(
                codec.descriptor().schema().clone(),
            ));
        }
        Ok(Self {
            codec,
            schema_revision,
            canonicalization_profile,
        })
    }

    pub const fn codec(&self) -> &'a C {
        self.codec
    }
}

impl<C: PayloadCodec> PayloadCodec for PayloadCodecBinding<'_, C> {
    type Value = C::Value;

    fn descriptor(&self) -> &SchemaDescriptor {
        self.codec.descriptor()
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        self.codec.encode_value(value)
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        self.codec.decode_value(payload)
    }
}

impl<C: PayloadCodec> BoundPayloadCodec for PayloadCodecBinding<'_, C> {
    fn schema_revision(&self) -> Digest32 {
        self.schema_revision
    }

    fn canonicalization_profile(&self) -> CanonicalizationProfile {
        self.canonicalization_profile
    }
}

/// Verify that a codec is the exact semantic codec frozen into a session
/// registry, not merely a codec with an equal framing descriptor.
pub fn verify_codec_binding<C: BoundPayloadCodec>(
    registry: &FrozenSchemaRegistry,
    codec: &C,
) -> Result<(), CodecBindingError> {
    let descriptor = codec.descriptor();
    let schema = descriptor.schema();
    let policy = registry
        .policy(schema)
        .ok_or_else(|| CodecBindingError::UnknownSchema(schema.clone()))?;
    if policy.descriptor() != descriptor {
        return Err(CodecBindingError::DescriptorMismatch(schema.clone()));
    }
    let expected_revision = policy.schema_revision();
    let actual_revision = codec.schema_revision();
    if expected_revision != actual_revision {
        return Err(CodecBindingError::SchemaRevisionMismatch {
            schema: schema.clone(),
            expected: expected_revision,
            actual: actual_revision,
        });
    }
    let expected_profile = policy.canonicalization_profile();
    let actual_profile = codec.canonicalization_profile();
    if expected_profile != actual_profile {
        return Err(CodecBindingError::CanonicalizationMismatch {
            schema: schema.clone(),
            expected: expected_profile,
            actual: actual_profile,
        });
    }
    Ok(())
}

impl WireSession {
    /// Encode through a codec whose semantic identity matches the immutable
    /// policy snapshot bound into this session's negotiation transcript.
    pub fn encode_bound_typed_envelope<C: BoundPayloadCodec>(
        &self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<DecodedEnvelope, BoundWireSessionError> {
        verify_codec_binding(self.registry(), codec).map_err(BoundWireSessionError::Binding)?;
        self.encode_typed_envelope(producer, generation, codec, value)
            .map_err(BoundWireSessionError::Session)
    }

    /// Decode only after both envelope admission and exact codec-policy binding
    /// have succeeded.
    pub fn decode_bound_typed_envelope<C: BoundPayloadCodec>(
        &self,
        envelope: &DecodedEnvelope,
        codec: &C,
    ) -> Result<C::Value, BoundWireSessionError> {
        verify_codec_binding(self.registry(), codec).map_err(BoundWireSessionError::Binding)?;
        self.decode_typed_envelope(envelope, codec)
            .map_err(BoundWireSessionError::Session)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CodecBindingError {
    ZeroSchemaRevision(StableId),
    UnknownSchema(StableId),
    DescriptorMismatch(StableId),
    SchemaRevisionMismatch {
        schema: StableId,
        expected: Digest32,
        actual: Digest32,
    },
    CanonicalizationMismatch {
        schema: StableId,
        expected: CanonicalizationProfile,
        actual: CanonicalizationProfile,
    },
}

impl fmt::Display for CodecBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ZeroSchemaRevision(schema) => {
                write!(
                    formatter,
                    "codec for schema {schema} has a zero semantic revision"
                )
            }
            Self::UnknownSchema(schema) => {
                write!(
                    formatter,
                    "codec schema {schema} is absent from the frozen registry"
                )
            }
            Self::DescriptorMismatch(schema) => write!(
                formatter,
                "codec descriptor for schema {schema} does not match the frozen policy"
            ),
            Self::SchemaRevisionMismatch {
                schema,
                expected,
                actual,
            } => write!(
                formatter,
                "codec revision for schema {schema} is {actual}, expected {expected}"
            ),
            Self::CanonicalizationMismatch {
                schema,
                expected,
                actual,
            } => write!(
                formatter,
                "codec canonicalization for schema {schema} is {}, expected {}",
                actual.id(),
                expected.id()
            ),
        }
    }
}

impl Error for CodecBindingError {}

#[derive(Debug)]
pub enum BoundWireSessionError {
    Binding(CodecBindingError),
    Session(WireSessionError),
}

impl fmt::Display for BoundWireSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Binding(error) => error.fmt(formatter),
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for BoundWireSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Binding(error) => Some(error),
            Self::Session(error) => Some(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use crate::FrozenSchemaRegistryBuilder;
    use crate::GenerationPolicy;
    use crate::NegotiationOffer;
    use crate::NegotiationTranscript;
    use crate::SchemaPolicy;
    use crate::WireCapabilities;
    use crate::WireVersion;
    use crate::negotiate;

    use super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct Message(String);

    struct Codec {
        descriptor: SchemaDescriptor,
    }

    impl PayloadCodec for Codec {
        type Value = Message;

        fn descriptor(&self) -> &SchemaDescriptor {
            &self.descriptor
        }

        fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
            if value.0.is_empty() {
                return Err(SchemaCodecError::Rejected("empty message"));
            }
            Ok(value.0.as_bytes().to_vec())
        }

        fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
            let value = std::str::from_utf8(payload)
                .map_err(|_| SchemaCodecError::Rejected("message is not UTF-8"))?;
            if value.is_empty() {
                return Err(SchemaCodecError::Rejected("empty message"));
            }
            Ok(Message(value.to_string()))
        }
    }

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn fixture() -> Result<(WireSession, Codec, Digest32), Box<dyn Error>> {
        let descriptor = SchemaDescriptor::new(
            id("schema.codec-binding.v1")?,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?;
        let revision = Digest32::of_bytes(b"codec-binding-revision-v1");
        let required =
            WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new_bound(
            descriptor.clone(),
            revision,
            GenerationPolicy::NonZero,
            CanonicalizationProfile::CanonicalJsonV1,
            vec![id("producer.codec-binding")?],
            vec![id("role.codec-binding")?],
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
            &[0x42; 32],
        )?;
        Ok((
            WireSession::new(negotiated, id("role.codec-binding")?, registry, transcript)?,
            Codec { descriptor },
            revision,
        ))
    }

    #[test]
    fn exact_codec_binding_round_trips() -> Result<(), Box<dyn Error>> {
        let (session, codec, revision) = fixture()?;
        let bound =
            PayloadCodecBinding::new(&codec, revision, CanonicalizationProfile::CanonicalJsonV1)?;
        let value = Message("hello".to_string());
        let envelope = session.encode_bound_typed_envelope(
            id("producer.codec-binding")?,
            Generation::new(1)?,
            &bound,
            &value,
        )?;
        assert_eq!(
            session.decode_bound_typed_envelope(&envelope, &bound)?,
            value
        );
        Ok(())
    }

    #[test]
    fn wrong_revision_and_profile_fail_before_typed_decode() -> Result<(), Box<dyn Error>> {
        let (session, codec, revision) = fixture()?;
        let wrong_revision = PayloadCodecBinding::new(
            &codec,
            Digest32::of_bytes(b"different-revision"),
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        assert!(matches!(
            verify_codec_binding(session.registry(), &wrong_revision),
            Err(CodecBindingError::SchemaRevisionMismatch { .. })
        ));

        let wrong_profile =
            PayloadCodecBinding::new(&codec, revision, CanonicalizationProfile::OpaqueBytesV1)?;
        assert!(matches!(
            verify_codec_binding(session.registry(), &wrong_profile),
            Err(CodecBindingError::CanonicalizationMismatch { .. })
        ));
        Ok(())
    }
}
