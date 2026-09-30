use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthenticatedSessionError;
use crate::BoundPayloadCodec;
use crate::BoundWireSessionError;
use crate::NegotiatedWire;
use crate::SchemaCodecError;
use crate::SessionEndpoint;
use crate::SessionLifecycleState;
use crate::SessionMacKey;
use crate::WireSession;
use crate::directional_session::AuthenticatedWireSession;
use crate::verify_codec_binding;

/// Non-secret immutable posture exposed by a hardened owner.
///
/// This snapshot deliberately carries no registry object, codec, replay
/// counter, transport handle or key-bearing session. It can therefore be used
/// for diagnostics after retirement without recreating a lower-level wire
/// escape hatch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireSessionMetadata {
    session_id: Digest32,
    endpoint: SessionEndpoint,
    role: StableId,
    negotiated: NegotiatedWire,
    registry_digest: Digest32,
    transcript_digest: Digest32,
}

impl WireSessionMetadata {
    fn from_session(session: &WireSession, endpoint: SessionEndpoint) -> Self {
        Self {
            session_id: session.session_id(),
            endpoint,
            role: session.role().clone(),
            negotiated: session.negotiated(),
            registry_digest: session.registry().snapshot_digest(),
            transcript_digest: session.transcript().digest(),
        }
    }

    pub const fn session_id(&self) -> Digest32 {
        self.session_id
    }

    pub const fn endpoint(&self) -> SessionEndpoint {
        self.endpoint
    }

    pub fn role(&self) -> &StableId {
        &self.role
    }

    pub const fn negotiated(&self) -> NegotiatedWire {
        self.negotiated
    }

    pub const fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    pub const fn transcript_digest(&self) -> Digest32 {
        self.transcript_digest
    }
}

/// Bound authenticated owner used internally by the final managed facade.
///
/// The key-bearing directional session is stored in an `Option`. Every
/// authentication, admission, binding, typed-decoding or canonicalization
/// failure takes and drops that state immediately. Only immutable metadata is
/// observable after failure; the underlying `WireSession` is never returned.
#[derive(Debug)]
pub struct HardenedWireSession {
    inner: Option<AuthenticatedWireSession>,
    metadata: WireSessionMetadata,
    state: SessionLifecycleState,
}

impl HardenedWireSession {
    /// Compatibility constructor for tests and protocol tooling.
    ///
    /// Production-only builds do not export either this type or `WireSession`;
    /// callers establish [`crate::HardenedManagedWireSession`] instead.
    #[cfg(any(
        test,
        all(feature = "protocol-tooling", not(feature = "production"))
    ))]
    pub fn new(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, AuthenticatedSessionError> {
        Self::from_parts(session, master_key, endpoint)
    }

    pub(crate) fn from_parts(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, AuthenticatedSessionError> {
        let metadata = WireSessionMetadata::from_session(&session, endpoint);
        let inner = AuthenticatedWireSession::new(session, master_key, endpoint)?;
        Ok(Self {
            inner: Some(inner),
            metadata,
            state: SessionLifecycleState::Active,
        })
    }

    pub fn metadata(&self) -> &WireSessionMetadata {
        &self.metadata
    }

    pub fn state(&self) -> SessionLifecycleState {
        if self.state == SessionLifecycleState::Active
            && self
                .inner
                .as_ref()
                .is_some_and(AuthenticatedWireSession::is_poisoned)
        {
            SessionLifecycleState::Poisoned
        } else {
            self.state
        }
    }

    pub fn is_poisoned(&self) -> bool {
        self.state() == SessionLifecycleState::Poisoned
    }

    /// Destroy key-bearing state and make this owner terminal.
    pub fn retire(&mut self) {
        self.inner = None;
        self.state = SessionLifecycleState::Retired;
    }

    pub(crate) fn policy_matches(&self, other: &WireSessionMetadata) -> bool {
        self.metadata.role == other.role
            && self.metadata.negotiated == other.negotiated
            && self.metadata.registry_digest == other.registry_digest
            && self.metadata.endpoint == other.endpoint
    }

    pub(crate) fn verify_bound_codec<C: BoundPayloadCodec>(
        &mut self,
        codec: &C,
    ) -> Result<(), HardenedWireSessionError> {
        self.ensure_live()?;
        let result = self
            .inner
            .as_ref()
            .expect("live hardened owner must retain its session")
            .session()
            .registry();
        if let Err(error) = verify_codec_binding(result, codec) {
            return self.fail(HardenedWireSessionError::Bound(
                BoundWireSessionError::Binding(error),
            ));
        }
        Ok(())
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
            .as_ref()
            .expect("live hardened owner must retain its session")
            .session()
            .encode_bound_typed_envelope(producer, generation, codec, value)
        {
            Ok(envelope) => envelope,
            Err(error) => return self.fail(HardenedWireSessionError::Bound(error)),
        };
        match self
            .inner
            .as_mut()
            .expect("live hardened owner must retain its session")
            .seal_envelope(&envelope)
        {
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
        let envelope = match self
            .inner
            .as_mut()
            .expect("live hardened owner must retain its session")
            .open_record(record)
        {
            Ok(envelope) => envelope,
            Err(error) => return self.fail(HardenedWireSessionError::Authenticated(error)),
        };
        let value = match self
            .inner
            .as_ref()
            .expect("live hardened owner must retain its session")
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

    fn ensure_live(&mut self) -> Result<(), HardenedWireSessionError> {
        if self.state != SessionLifecycleState::Active || self.inner.is_none() {
            return Err(HardenedWireSessionError::Poisoned);
        }
        if self
            .inner
            .as_ref()
            .is_some_and(AuthenticatedWireSession::is_poisoned)
        {
            self.state = SessionLifecycleState::Poisoned;
            self.inner = None;
            return Err(HardenedWireSessionError::Poisoned);
        }
        Ok(())
    }

    fn fail<T>(
        &mut self,
        error: HardenedWireSessionError,
    ) -> Result<T, HardenedWireSessionError> {
        self.state = SessionLifecycleState::Poisoned;
        let retired = self.inner.take();
        drop(retired);
        Err(error)
    }

    #[cfg(test)]
    fn key_state_retired(&self) -> bool {
        self.inner.is_none()
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
                "hardened wire session is terminal; establish a fresh authenticated session",
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

    use crate::CanonicalizationProfile;
    use crate::CodecBindingError;
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
            if value.0 == "explode" {
                return Err(SchemaCodecError::Rejected("canonical encode failed"));
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
        let mut sender = HardenedWireSession::new(
            fixture.initiator,
            SessionMacKey::new([0x31; 32])?,
            SessionEndpoint::Initiator,
        )?;
        let mut receiver = HardenedWireSession::new(
            fixture.responder,
            SessionMacKey::new([0x31; 32])?,
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
        assert_eq!(receiver.state(), SessionLifecycleState::Active);
        Ok(())
    }

    #[test]
    fn noncanonical_authenticated_payload_drops_key_state_immediately(
    ) -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let mut weak_sender = AuthenticatedWireSession::new(
            fixture.initiator,
            SessionMacKey::new([0x31; 32])?,
            SessionEndpoint::Initiator,
        )?;
        let mut receiver = HardenedWireSession::new(
            fixture.responder,
            SessionMacKey::new([0x31; 32])?,
            SessionEndpoint::Responder,
        )?;
        let session_id = receiver.metadata().session_id();
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
        assert_eq!(receiver.state(), SessionLifecycleState::Poisoned);
        assert!(receiver.key_state_retired());
        assert_eq!(receiver.metadata().session_id(), session_id);
        assert!(matches!(
            receiver.open_bound_typed(&record, &bound),
            Err(HardenedWireSessionError::Poisoned)
        ));
        Ok(())
    }

    #[test]
    fn wrong_codec_revision_is_terminal_before_sealing() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let mut sender = HardenedWireSession::new(
            fixture.initiator,
            SessionMacKey::new([0x31; 32])?,
            SessionEndpoint::Initiator,
        )?;
        let wrong = PayloadCodecBinding::new(
            &fixture.codec,
            Digest32::of_bytes(b"wrong-revision"),
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        assert!(matches!(
            sender.seal_bound_typed(
                fixture.producer,
                Generation::new(1)?,
                &wrong,
                &Message("hello".to_string()),
            ),
            Err(HardenedWireSessionError::Bound(
                BoundWireSessionError::Binding(CodecBindingError::SchemaRevisionMismatch { .. })
            ))
        ));
        assert!(sender.key_state_retired());
        assert_eq!(sender.state(), SessionLifecycleState::Poisoned);
        Ok(())
    }

    #[test]
    fn canonical_reencode_failure_is_terminal() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let mut weak_sender = AuthenticatedWireSession::new(
            fixture.initiator,
            SessionMacKey::new([0x31; 32])?,
            SessionEndpoint::Initiator,
        )?;
        let mut receiver = HardenedWireSession::new(
            fixture.responder,
            SessionMacKey::new([0x31; 32])?,
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
            b"explode".to_vec(),
        )?);
        let record = weak_sender.seal_envelope(&envelope)?;
        assert!(matches!(
            receiver.open_bound_typed(&record, &bound),
            Err(HardenedWireSessionError::CanonicalEncode(_))
        ));
        assert!(receiver.key_state_retired());
        Ok(())
    }
}
