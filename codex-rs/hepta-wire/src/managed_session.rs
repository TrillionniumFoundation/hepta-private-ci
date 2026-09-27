use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthenticatedSessionError;
use crate::AuthenticatedWireSession;
use crate::DecodedEnvelope;
use crate::PayloadCodec;
use crate::SessionEndpoint;
use crate::SessionMacKey;
use crate::WireSession;

/// Explicit lifecycle for one authenticated connection-local wire session.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SessionLifecycleState {
    Active,
    Poisoned,
    Retired,
}

/// Lifecycle owner for an authenticated directional session.
///
/// Rotation consumes the old owner and requires a distinct session identity,
/// which in turn requires a fresh negotiation transcript/channel binding. This
/// prevents sequence counters from being reset under the same authenticated
/// identity. Retirement drops all key-bearing session state and is terminal.
#[derive(Debug)]
pub struct ManagedAuthenticatedWireSession {
    inner: Option<AuthenticatedWireSession>,
    endpoint: SessionEndpoint,
    session_id: Digest32,
    state: SessionLifecycleState,
}

impl ManagedAuthenticatedWireSession {
    pub fn new(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, ManagedSessionError> {
        let session_id = session.session_id();
        let inner = AuthenticatedWireSession::new(session, master_key, endpoint)
            .map_err(ManagedSessionError::Authenticated)?;
        Ok(Self {
            inner: Some(inner),
            endpoint,
            session_id,
            state: SessionLifecycleState::Active,
        })
    }

    pub const fn endpoint(&self) -> SessionEndpoint {
        self.endpoint
    }

    pub const fn session_id(&self) -> Digest32 {
        self.session_id
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

    pub fn session(&self) -> Result<&WireSession, ManagedSessionError> {
        if self.state() != SessionLifecycleState::Active {
            return Err(ManagedSessionError::Inactive(self.state()));
        }
        self.inner
            .as_ref()
            .map(AuthenticatedWireSession::session)
            .ok_or(ManagedSessionError::Inactive(self.state()))
    }

    /// Destroy connection-local key state and make this owner permanently
    /// unusable. Establish a fresh owner to communicate again.
    pub fn retire(&mut self) {
        self.inner = None;
        self.state = SessionLifecycleState::Retired;
    }

    /// Rotate to a newly negotiated session and a newly derived master key.
    ///
    /// The endpoint direction is preserved. A caller cannot use rotation to
    /// silently exchange initiator/responder roles.
    pub fn rotate(
        self,
        new_session: WireSession,
        new_master_key: SessionMacKey,
    ) -> Result<Self, ManagedSessionError> {
        let state = self.state();
        if state != SessionLifecycleState::Active {
            return Err(ManagedSessionError::Inactive(state));
        }
        let previous = self.session()?;
        if previous.role() != new_session.role()
            || previous.negotiated() != new_session.negotiated()
            || previous.registry().snapshot_digest() != new_session.registry().snapshot_digest()
        {
            return Err(ManagedSessionError::RotationPolicyChanged);
        }
        let new_session_id = new_session.session_id();
        if new_session_id == self.session_id {
            return Err(ManagedSessionError::FreshSessionIdentityRequired {
                previous: self.session_id,
            });
        }
        Self::new(new_session, new_master_key, self.endpoint)
    }

    pub fn seal_envelope(
        &mut self,
        envelope: &DecodedEnvelope,
    ) -> Result<Vec<u8>, ManagedSessionError> {
        self.with_active(|session| session.seal_envelope(envelope))
    }

    pub fn seal_typed<C: PayloadCodec>(
        &mut self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, ManagedSessionError> {
        self.with_active(|session| session.seal_typed(producer, generation, codec, value))
    }

    pub fn open_record(&mut self, record: &[u8]) -> Result<DecodedEnvelope, ManagedSessionError> {
        self.with_active(|session| session.open_record(record))
    }

    pub fn open_typed<C: PayloadCodec>(
        &mut self,
        record: &[u8],
        codec: &C,
    ) -> Result<C::Value, ManagedSessionError> {
        self.with_active(|session| session.open_typed(record, codec))
    }

    fn with_active<T>(
        &mut self,
        operation: impl FnOnce(&mut AuthenticatedWireSession) -> Result<T, AuthenticatedSessionError>,
    ) -> Result<T, ManagedSessionError> {
        if self.state() != SessionLifecycleState::Active {
            return Err(ManagedSessionError::Inactive(self.state()));
        }
        let Some(inner) = self.inner.as_mut() else {
            self.state = SessionLifecycleState::Retired;
            return Err(ManagedSessionError::Inactive(self.state));
        };
        match operation(inner) {
            Ok(value) => Ok(value),
            Err(error) => {
                self.state = SessionLifecycleState::Poisoned;
                self.inner = None;
                Err(ManagedSessionError::Authenticated(error))
            }
        }
    }
}

#[derive(Debug)]
pub enum ManagedSessionError {
    RotationPolicyChanged,
    Inactive(SessionLifecycleState),
    FreshSessionIdentityRequired { previous: Digest32 },
    Authenticated(AuthenticatedSessionError),
}

impl fmt::Display for ManagedSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RotationPolicyChanged => {
                formatter.write_str("key rotation cannot change session admission policy")
            }
            Self::Inactive(state) => {
                write!(
                    formatter,
                    "authenticated wire session is not active: {state:?}"
                )
            }
            Self::FreshSessionIdentityRequired { previous } => write!(
                formatter,
                "wire key rotation requires a fresh session identity; previous session is {previous}"
            ),
            Self::Authenticated(error) => error.fmt(formatter),
        }
    }
}

impl Error for ManagedSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Authenticated(error) => Some(error),
            Self::Inactive(_)
            | Self::FreshSessionIdentityRequired { .. }
            | Self::RotationPolicyChanged => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use crate::FrozenSchemaRegistryBuilder;
    use crate::NegotiationOffer;
    use crate::NegotiationTranscript;
    use crate::SchemaDescriptor;
    use crate::SchemaPolicy;
    use crate::WireCapabilities;
    use crate::WireEnvelopeV2;
    use crate::WireVersion;
    use crate::negotiate;

    use super::*;

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn session(channel: u8) -> Result<WireSession, Box<dyn Error>> {
        let descriptor = SchemaDescriptor::new(
            id("schema.managed-session.v1")?,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?;
        let required =
            WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new(
            descriptor,
            vec![id("producer.managed-session")?],
            vec![id("role.managed-session")?],
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
            &[channel; 32],
        )?;
        Ok(WireSession::new(
            negotiated,
            id("role.managed-session")?,
            registry,
            transcript,
        )?)
    }

    fn envelope(generation: u64) -> Result<DecodedEnvelope, Box<dyn Error>> {
        Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
            id("schema.managed-session.v1")?,
            id("producer.managed-session")?,
            Generation::new(generation)?,
            b"hello".to_vec(),
        )?))
    }

    #[test]
    fn retirement_destroys_the_active_session() -> Result<(), Box<dyn Error>> {
        let mut managed = ManagedAuthenticatedWireSession::new(
            session(1)?,
            SessionMacKey::new([9; 32])?,
            SessionEndpoint::Initiator,
        )?;
        managed.retire();
        assert_eq!(managed.state(), SessionLifecycleState::Retired);
        assert!(matches!(
            managed.seal_envelope(&envelope(1)?),
            Err(ManagedSessionError::Inactive(
                SessionLifecycleState::Retired
            ))
        ));
        Ok(())
    }

    #[test]
    fn rotation_requires_a_fresh_session_identity() -> Result<(), Box<dyn Error>> {
        let original = session(1)?;
        let duplicate = original.clone();
        let managed = ManagedAuthenticatedWireSession::new(
            original,
            SessionMacKey::new([9; 32])?,
            SessionEndpoint::Initiator,
        )?;
        assert!(matches!(
            managed.rotate(duplicate, SessionMacKey::new([8; 32])?),
            Err(ManagedSessionError::FreshSessionIdentityRequired { .. })
        ));
        Ok(())
    }

    #[test]
    fn peers_rotate_to_new_identity_and_key() -> Result<(), Box<dyn Error>> {
        let key = SessionMacKey::new([9; 32])?;
        let initiator = ManagedAuthenticatedWireSession::new(
            session(1)?,
            key.clone(),
            SessionEndpoint::Initiator,
        )?;
        let responder =
            ManagedAuthenticatedWireSession::new(session(1)?, key, SessionEndpoint::Responder)?;
        let new_key = SessionMacKey::new([7; 32])?;
        let mut initiator = initiator.rotate(session(2)?, new_key.clone())?;
        let mut responder = responder.rotate(session(2)?, new_key)?;
        let frame = envelope(2)?;
        let record = initiator.seal_envelope(&frame)?;
        assert_eq!(responder.open_record(&record)?, frame);
        assert_eq!(initiator.state(), SessionLifecycleState::Active);
        assert_eq!(responder.state(), SessionLifecycleState::Active);
        Ok(())
    }
    #[test]
    fn rotation_cannot_change_the_runtime_role() -> Result<(), Box<dyn Error>> {
        let old = session(1)?;
        let next = session(2)?;
        let altered = WireSession::new(
            next.negotiated(),
            id("role.other")?,
            Arc::new(next.registry().clone()),
            next.transcript(),
        )?;
        let owner = ManagedAuthenticatedWireSession::new(
            old,
            SessionMacKey::new([1; 32])?,
            SessionEndpoint::Initiator,
        )?;
        assert!(matches!(
            owner.rotate(altered, SessionMacKey::new([2; 32])?),
            Err(ManagedSessionError::RotationPolicyChanged)
        ));
        Ok(())
    }

    #[test]
    fn poison_drops_key_bearing_state_immediately() -> Result<(), Box<dyn Error>> {
        let mut owner = ManagedAuthenticatedWireSession::new(
            session(1)?,
            SessionMacKey::new([1; 32])?,
            SessionEndpoint::Initiator,
        )?;
        assert!(owner.open_record(b"invalid").is_err());
        assert_eq!(owner.state(), SessionLifecycleState::Poisoned);
        assert!(owner.inner.is_none());
        assert!(owner.session().is_err());
        Ok(())
    }
}
