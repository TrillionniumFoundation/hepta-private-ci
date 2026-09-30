use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthenticatedSessionError;
use crate::AuthenticatedWireSession;
use crate::BoundPayloadCodec;
use crate::BoundWireSessionError;
use crate::SchemaCodecError;
use crate::SessionEndpoint;
use crate::SessionMacKey;
use crate::WireSession;

/// Single production-facing owner for an authenticated, policy-bound wire
/// session.
///
/// This facade deliberately does not expose raw frame, unbound typed, replay
/// counter, reset, or inner-session escape hatches. Inbound records are opened
/// in the following order: authenticate and sequence-check, frozen registry
/// admission, exact codec binding, typed decode, then byte-for-byte canonical
/// re-encoding. Any terminal failure poisons this owner; recovery requires a
/// fresh transport, channel binding, negotiation transcript and session key.
#[derive(Debug)]
pub struct HardenedWireSession {
    inner: AuthenticatedWireSession,
    poisoned: bool,
}

impl HardenedWireSession {
    pub fn new(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, AuthenticatedSessionError> {
        Ok(Self {
            inner: AuthenticatedWireSession::new(session, master_key, endpoint)?,
            poisoned: false,
        })
    }

    pub fn session(&self) -> &WireSession {
        self.inner.session()
    }

    pub fn is_poisoned(&self) -> bool {
        self.poisoned || self.inner.is_poisoned()
    }

    /// Encode through the exact semantic codec frozen into the session and
    /// seal the admitted envelope with the direction-specific record key.
    pub fn seal_bound_typed<C: BoundPayloadCodec>(
        &mut self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, HardenedWireSessionError> {
        self.ensure_live()?;
        let envelope = match self
            .inner
            .session()
            .encode_bound_typed_envelope(producer, generation, codec, value)
        {
            Ok(envelope) => envelope,
            Err(error) => return self.fail(HardenedWireSessionError::Bound(error)),
        };
        match self.inner.seal_envelope(&envelope) {
            Ok(record) => Ok(record),
            Err(error) => self.fail(HardenedWireSessionError::Authenticated(error)),
        }
    }

    /// Authenticate and decode one record, then prove that the exact received
    /// payload bytes are the canonical encoding of the decoded value.
    pub fn open_bound_typed<C: BoundPayloadCodec>(
        &mut self,
        record: &[u8],
        codec: &C,
    ) -> Result<C::Value, HardenedWireSessionError> {
        self.ensure_live()?;
        let envelope = match self.inner.open_record(record) {
            Ok(envelope) => envelope,
            Err(error) => return self.fail(HardenedWireSessionError::Authenticated(error)),
        };
        let value = match self
            .inner
            .session()
            .decode_bound_typed_envelope(&envelope, codec)
        {
            Ok(value) => value,
            Err(error) => return self.fail(HardenedWireSessionError::Bound(error)),
        };
        let canonical = match codec.encode_value(&value) {
            Ok(payload) => payload,
            Err(error) => return self.fail(HardenedWireSessionError::CanonicalEncode(error)),
        };
        if canonical.as_slice() != envelope.payload() {
            let error = HardenedWireSessionError::NonCanonicalPayload {
                schema: envelope.schema().clone(),
                received_bytes: envelope.payload().len(),
                canonical_bytes: canonical.len(),
            };
            return self.fail(error);
        }
        Ok(value)
    }

    fn ensure_live(&self) -> Result<(), HardenedWireSessionError> {
        if self.is_poisoned() {
            Err(HardenedWireSessionError::Poisoned)
        } else {
            Ok(())
        }
    }

    fn fail<T>(
        &mut self,
        error: HardenedWireSessionError,
    ) -> Result<T, HardenedWireSessionError> {
        self.poisoned = true;
        Err(error)
    }
}

#[derive(Debug)]
pub enum HardenedWireSessionError {
    Poisoned,
    Authenticated(AuthenticatedSessionError),
    Bound(BoundWireSessionError),
    CanonicalEncode(SchemaCodecError),
    NonCanonicalPayload {
        schema: StableId,
        received_bytes: usize,
        canonical_bytes: usize,
    },
}

impl fmt::Display for HardenedWireSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Poisoned => formatter.write_str(
                "hardened wire session is poisoned; establish a fresh authenticated session",
            ),
            Self::Authenticated(error) => error.fmt(formatter),
            Self::Bound(error) => error.fmt(formatter),
            Self::CanonicalEncode(error) => {
                write!(formatter, "canonical payload re-encoding failed: {error}")
            }
            Self::NonCanonicalPayload {
                schema,
                received_bytes,
                canonical_bytes,
            } => write!(
                formatter,
                "schema {schema} payload is not canonical: received {received_bytes} bytes, canonical encoding has {canonical_bytes} bytes"
            ),
        }
    }
}

impl Error for HardenedWireSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Authenticated(error) => Some(error),
            Self::Bound(error) => Some(error),
            Self::CanonicalEncode(error) => Some(error),
            Self::Poisoned | Self::NonCanonicalPayload { .. } => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use codex_hepta_types::Digest32;

    use crate::CanonicalizationProfile;
    use crate::DecodedEnvelope;
    use crate::FrozenSchemaRegistry;
    use crate::FrozenSchemaRegistryBuilder;
    use crate::GenerationPolicy;
    use crate::NegotiationOffer;
    use crate::NegotiationTranscript;
    use crate::PayloadCodec;
    use crate::PayloadCodecBinding;
    use crate::SchemaDescriptor;
    use crate::SchemaPolicy;
    use crate::WireCapabilities;
    use crate::WireEnvelopeV2;
    use crate::WireVersion;
    use crate::negotiate;

    use super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct Message(String);

    struct CanonicalCodec {
        descriptor: SchemaDescriptor,
    }

    impl PayloadCodec for CanonicalCodec {
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
            let raw = std::str::from_utf8(payload)
                .map_err(|_| SchemaCodecError::Rejected("message is not UTF-8"))?;
            let canonical = raw.trim();
            if canonical.is_empty() {
                return Err(SchemaCodecError::Rejected("empty message"));
            }
            Ok(Message(canonical.to_string()))
        }
    }

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    struct Fixture {
        initiator: WireSession,
        responder: WireSession,
        codec: CanonicalCodec,
        revision: Digest32,
        producer: StableId,
    }

    fn wire_session(
        registry: Arc<FrozenSchemaRegistry>,
        required: WireCapabilities,
    ) -> Result<WireSession, Box<dyn Error>> {
        let offer = NegotiationOffer::current();
        let negotiated = negotiate(&offer, &offer, required)?;
        let transcript = NegotiationTranscript::from_offers(
            &offer,
            &offer,
            negotiated,
            registry.snapshot_digest(),
            &[0x51; 32],
        )?;
        Ok(WireSession::new(
            negotiated,
            id("role.hardened-wire")?,
            registry,
            transcript,
        )?)
    }

    fn fixture() -> Result<Fixture, Box<dyn Error>> {
        let schema = id("schema.hardened-wire.v1")?;
        let producer = id("producer.hardened-wire")?;
        let descriptor =
            SchemaDescriptor::new(schema, WireVersion::V2, WireVersion::V2, 256)?;
        let revision = Digest32::of_bytes(b"hardened-wire-revision-v1");
        let required =
            WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new_bound(
            descriptor.clone(),
            revision,
            GenerationPolicy::NonZero,
            CanonicalizationProfile::CanonicalJsonV1,
            vec![producer.clone()],
            vec![id("role.hardened-wire")?],
            required,
        )?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(policy)?;
        let registry = Arc::new(builder.freeze()?);
        Ok(Fixture {
            initiator: wire_session(Arc::clone(&registry), required)?,
            responder: wire_session(registry, required)?,
            codec: CanonicalCodec { descriptor },
            revision,
            producer,
        })
    }

    #[test]
    fn bound_canonical_records_round_trip() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let key = SessionMacKey::new([0x31; 32])?;
        let mut sender = HardenedWireSession::new(
            fixture.initiator,
            key.clone(),
            SessionEndpoint::Initiator,
        )?;
        let mut receiver = HardenedWireSession::new(
            fixture.responder,
            key,
            SessionEndpoint::Responder,
        )?;
        let bound = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let expected = Message("hello".to_string());
        let record = sender.seal_bound_typed(
            fixture.producer,
            Generation::new(1)?,
            &bound,
            &expected,
        )?;
        assert_eq!(receiver.open_bound_typed(&record, &bound)?, expected);
        assert!(!receiver.is_poisoned());
        Ok(())
    }

    #[test]
    fn noncanonical_authenticated_payload_is_rejected_and_poisons_owner(
    ) -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let key = SessionMacKey::new([0x31; 32])?;
        let mut weak_sender = AuthenticatedWireSession::new(
            fixture.initiator,
            key.clone(),
            SessionEndpoint::Initiator,
        )?;
        let mut receiver = HardenedWireSession::new(
            fixture.responder,
            key,
            SessionEndpoint::Responder,
        )?;
        let bound = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let envelope = DecodedEnvelope::V2(WireEnvelopeV2::new(
            bound.descriptor().schema().clone(),
            fixture.producer,
            Generation::new(1)?,
            b" hello ".to_vec(),
        )?);
        let record = weak_sender.seal_envelope(&envelope)?;
        assert!(matches!(
            receiver.open_bound_typed(&record, &bound),
            Err(HardenedWireSessionError::NonCanonicalPayload { .. })
        ));
        assert!(receiver.is_poisoned());
        assert!(matches!(
            receiver.open_bound_typed(&record, &bound),
            Err(HardenedWireSessionError::Poisoned)
        ));
        Ok(())
    }
}
