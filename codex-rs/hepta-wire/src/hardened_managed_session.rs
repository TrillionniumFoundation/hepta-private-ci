use std::error::Error;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthenticatedSessionError;
use crate::BoundPayloadCodec;
use crate::FrozenSchemaRegistry;
use crate::HardenedWireSessionError;
use crate::NegotiationError;
use crate::NegotiationOffer;
use crate::SessionEndpoint;
use crate::SessionLifecycleState;
use crate::SessionMacKey;
use crate::WireCapabilities;
use crate::WireSessionError;
use crate::hardened_session::HardenedWireSession;
use crate::hardened_session::WireSessionMetadata;
use crate::negotiate;
use crate::secure_session::NegotiationTranscript;
use crate::secure_session::WireSession;

/// Final production owner for one authenticated platform.wire session.
///
/// Construction performs negotiation and transcript/session binding internally,
/// so a production caller cannot obtain or clone the lower-level `WireSession`.
/// The sole key-bearing child is an `Option<HardenedWireSession>`; every terminal
/// error takes and drops it. Rotation consumes the old owner and requires a new
/// session identity while preserving endpoint, role, negotiated posture and the
/// frozen registry digest.
#[derive(Debug)]
pub struct HardenedManagedWireSession {
    inner: Option<HardenedWireSession>,
    metadata: WireSessionMetadata,
    state: SessionLifecycleState,
}

impl HardenedManagedWireSession {
    /// Establish the unique production owner from authenticated channel inputs.
    ///
    /// `initiator_offer` and `responder_offer` are ordered by protocol role, not
    /// by the local endpoint. `channel_binding` must identify the fresh
    /// authenticated transport. The resulting wire object carries no effect
    /// authority.
    #[allow(clippy::too_many_arguments)]
    pub fn establish(
        initiator_offer: &NegotiationOffer,
        responder_offer: &NegotiationOffer,
        required_capabilities: WireCapabilities,
        role: StableId,
        registry: Arc<FrozenSchemaRegistry>,
        channel_binding: &[u8],
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, HardenedManagedSessionError> {
        let negotiated = negotiate(
            initiator_offer,
            responder_offer,
            required_capabilities,
        )
        .map_err(HardenedManagedSessionError::Negotiation)?;
        let transcript = NegotiationTranscript::from_offers(
            initiator_offer,
            responder_offer,
            negotiated,
            registry.snapshot_digest(),
            channel_binding,
        )
        .map_err(HardenedManagedSessionError::Session)?;
        let session = WireSession::new(negotiated, role, registry, transcript)
            .map_err(HardenedManagedSessionError::Session)?;
        Self::from_session(session, master_key, endpoint)
    }

    pub(crate) fn from_session(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, HardenedManagedSessionError> {
        let hardened = HardenedWireSession::from_parts(session, master_key, endpoint)
            .map_err(HardenedManagedSessionError::Authenticated)?;
        let metadata = hardened.metadata().clone();
        Ok(Self {
            inner: Some(hardened),
            metadata,
            state: SessionLifecycleState::Active,
        })
    }

    pub fn metadata(&self) -> &WireSessionMetadata {
        &self.metadata
    }

    pub const fn session_id(&self) -> Digest32 {
        self.metadata.session_id()
    }

    pub const fn endpoint(&self) -> SessionEndpoint {
        self.metadata.endpoint()
    }

    pub fn state(&self) -> SessionLifecycleState {
        if self.state == SessionLifecycleState::Active
            && self
                .inner
                .as_ref()
                .is_some_and(|owner| owner.state() != SessionLifecycleState::Active)
        {
            SessionLifecycleState::Poisoned
        } else {
            self.state
        }
    }

    /// Destroy connection-local keys and make the owner permanently unusable.
    pub fn retire(&mut self) {
        if let Some(mut inner) = self.inner.take() {
            inner.retire();
        }
        self.state = SessionLifecycleState::Retired;
    }

    /// Encode, admit and authenticate only through the exact bound codec.
    pub fn seal_bound_typed<C: BoundPayloadCodec>(
        &mut self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, HardenedManagedSessionError> {
        self.with_active(|owner| owner.seal_bound_typed(producer, generation, codec, value))
    }

    /// Authenticate, sequence-check, admit, bind, decode and canonicalize one
    /// record before returning its typed value.
    pub fn open_bound_typed<C: BoundPayloadCodec>(
        &mut self,
        record: &[u8],
        codec: &C,
    ) -> Result<C::Value, HardenedManagedSessionError> {
        self.with_active(|owner| owner.open_bound_typed(record, codec))
    }

    pub(crate) fn verify_bound_codec<C: BoundPayloadCodec>(
        &mut self,
        codec: &C,
    ) -> Result<(), HardenedManagedSessionError> {
        self.with_active(|owner| owner.verify_bound_codec(codec))
    }

    /// Consume this owner and establish a new identity/key pair under the same
    /// immutable admission policy.
    #[allow(clippy::too_many_arguments)]
    pub fn rotate(
        self,
        initiator_offer: &NegotiationOffer,
        responder_offer: &NegotiationOffer,
        required_capabilities: WireCapabilities,
        role: StableId,
        registry: Arc<FrozenSchemaRegistry>,
        channel_binding: &[u8],
        new_master_key: SessionMacKey,
    ) -> Result<Self, HardenedManagedSessionError> {
        let state = self.state();
        if state != SessionLifecycleState::Active {
            return Err(HardenedManagedSessionError::Inactive(state));
        }
        let previous = self.metadata.clone();
        let mut next = Self::establish(
            initiator_offer,
            responder_offer,
            required_capabilities,
            role,
            registry,
            channel_binding,
            new_master_key,
            previous.endpoint(),
        )?;
        let policy_matches = self
            .inner
            .as_ref()
            .is_some_and(|inner| inner.policy_matches(next.metadata()));
        if !policy_matches {
            next.retire();
            return Err(HardenedManagedSessionError::RotationPolicyChanged);
        }
        if next.session_id() == previous.session_id() {
            next.retire();
            return Err(HardenedManagedSessionError::FreshSessionIdentityRequired {
                previous: previous.session_id(),
            });
        }
        Ok(next)
    }

    fn with_active<T>(
        &mut self,
        operation: impl FnOnce(
            &mut HardenedWireSession,
        ) -> Result<T, HardenedWireSessionError>,
    ) -> Result<T, HardenedManagedSessionError> {
        let state = self.state();
        if state != SessionLifecycleState::Active {
            return Err(HardenedManagedSessionError::Inactive(state));
        }
        let Some(inner) = self.inner.as_mut() else {
            self.state = SessionLifecycleState::Retired;
            return Err(HardenedManagedSessionError::Inactive(self.state));
        };
        match operation(inner) {
            Ok(value) => Ok(value),
            Err(error) => {
                self.state = SessionLifecycleState::Poisoned;
                let retired = self.inner.take();
                drop(retired);
                Err(HardenedManagedSessionError::Hardened(error))
            }
        }
    }

    #[cfg(test)]
    fn key_state_retired(&self) -> bool {
        self.inner.is_none()
    }
}

#[derive(Debug)]
pub enum HardenedManagedSessionError {
    Negotiation(NegotiationError),
    Session(WireSessionError),
    Authenticated(AuthenticatedSessionError),
    Hardened(HardenedWireSessionError),
    Inactive(SessionLifecycleState),
    RotationPolicyChanged,
    FreshSessionIdentityRequired { previous: Digest32 },
}

impl fmt::Display for HardenedManagedSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Negotiation(error) => error.fmt(formatter),
            Self::Session(error) => error.fmt(formatter),
            Self::Authenticated(error) => error.fmt(formatter),
            Self::Hardened(error) => error.fmt(formatter),
            Self::Inactive(state) => {
                write!(formatter, "hardened managed wire session is not active: {state:?}")
            }
            Self::RotationPolicyChanged => formatter.write_str(
                "wire session rotation cannot change endpoint, role, negotiated posture or frozen registry",
            ),
            Self::FreshSessionIdentityRequired { previous } => write!(
                formatter,
                "wire session rotation requires a fresh session identity; previous session is {previous}"
            ),
        }
    }
}

impl Error for HardenedManagedSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Negotiation(error) => Some(error),
            Self::Session(error) => Some(error),
            Self::Authenticated(error) => Some(error),
            Self::Hardened(error) => Some(error),
            Self::Inactive(_)
            | Self::RotationPolicyChanged
            | Self::FreshSessionIdentityRequired { .. } => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use crate::CanonicalizationProfile;
    use crate::FrozenSchemaRegistryBuilder;
    use crate::GenerationPolicy;
    use crate::PayloadCodec;
    use crate::PayloadCodecBinding;
    use crate::SchemaCodecError;
    use crate::SchemaDescriptor;
    use crate::SchemaPolicy;
    use crate::WireVersion;

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
            Ok(value.0.as_bytes().to_vec())
        }

        fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
            let value = std::str::from_utf8(payload)
                .map_err(|_| SchemaCodecError::Rejected("message is not UTF-8"))?;
            Ok(Message(value.to_string()))
        }
    }

    struct Fixture {
        registry: Arc<FrozenSchemaRegistry>,
        codec: Codec,
        revision: Digest32,
        producer: StableId,
        role: StableId,
        required: WireCapabilities,
        offer: NegotiationOffer,
    }

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn fixture() -> Result<Fixture, Box<dyn Error>> {
        let schema = id("schema.hardened-managed.v1")?;
        let producer = id("producer.hardened-managed")?;
        let role = id("role.hardened-managed")?;
        let descriptor =
            SchemaDescriptor::new(schema, WireVersion::V2, WireVersion::V2, 256)?;
        let revision = Digest32::of_bytes(b"hardened-managed-revision-v1");
        let required =
            WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new_bound(
            descriptor.clone(),
            revision,
            GenerationPolicy::NonZero,
            CanonicalizationProfile::CanonicalJsonV1,
            vec![producer.clone()],
            vec![role.clone()],
            required,
        )?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(policy)?;
        Ok(Fixture {
            registry: Arc::new(builder.freeze()?),
            codec: Codec { descriptor },
            revision,
            producer,
            role,
            required,
            offer: NegotiationOffer::current(),
        })
    }

    fn owner(
        fixture: &Fixture,
        endpoint: SessionEndpoint,
        channel: u8,
        key: u8,
    ) -> Result<HardenedManagedWireSession, HardenedManagedSessionError> {
        HardenedManagedWireSession::establish(
            &fixture.offer,
            &fixture.offer,
            fixture.required,
            fixture.role.clone(),
            Arc::clone(&fixture.registry),
            &[channel; 32],
            SessionMacKey::new([key; 32])
                .map_err(HardenedManagedSessionError::Authenticated)?,
            endpoint,
        )
    }

    #[test]
    fn final_owner_round_trips_bound_values() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let bound = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut initiator = owner(&fixture, SessionEndpoint::Initiator, 1, 9)?;
        let mut responder = owner(&fixture, SessionEndpoint::Responder, 1, 9)?;
        let value = Message("hello".to_string());
        let record = initiator.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &bound,
            &value,
        )?;
        assert_eq!(responder.open_bound_typed(&record, &bound)?, value);
        assert_eq!(responder.state(), SessionLifecycleState::Active);
        Ok(())
    }

    #[test]
    fn terminal_failure_drops_the_only_child_owner() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let bound = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut responder = owner(&fixture, SessionEndpoint::Responder, 1, 9)?;
        assert!(responder.open_bound_typed(b"invalid", &bound).is_err());
        assert_eq!(responder.state(), SessionLifecycleState::Poisoned);
        assert!(responder.key_state_retired());
        Ok(())
    }

    #[test]
    fn rotation_requires_a_fresh_session_identity() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let owner = owner(&fixture, SessionEndpoint::Initiator, 1, 9)?;
        let previous = owner.session_id();
        assert!(matches!(
            owner.rotate(
                &fixture.offer,
                &fixture.offer,
                fixture.required,
                fixture.role.clone(),
                Arc::clone(&fixture.registry),
                &[1; 32],
                SessionMacKey::new([8; 32])?,
            ),
            Err(HardenedManagedSessionError::FreshSessionIdentityRequired {
                previous: observed
            }) if observed == previous
        ));
        Ok(())
    }

    #[test]
    fn rotation_rejects_old_session_records() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let bound = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut old_sender = owner(&fixture, SessionEndpoint::Initiator, 1, 9)?;
        let receiver = owner(&fixture, SessionEndpoint::Responder, 1, 9)?;
        let stale_record = old_sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &bound,
            &Message("stale".to_string()),
        )?;
        let mut rotated = receiver.rotate(
            &fixture.offer,
            &fixture.offer,
            fixture.required,
            fixture.role.clone(),
            Arc::clone(&fixture.registry),
            &[2; 32],
            SessionMacKey::new([7; 32])?,
        )?;
        assert!(rotated.open_bound_typed(&stale_record, &bound).is_err());
        assert_eq!(rotated.state(), SessionLifecycleState::Poisoned);
        Ok(())
    }
}
