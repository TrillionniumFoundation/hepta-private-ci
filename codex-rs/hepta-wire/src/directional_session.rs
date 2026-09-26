use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DecodedEnvelope;
use crate::PayloadCodec;
use crate::secure_session::AuthenticatedSessionError;
use crate::secure_session::AuthenticatedWireSession as UndirectedAuthenticatedWireSession;
use crate::secure_session::SessionMacKey as UndirectedSessionMacKey;
use crate::secure_session::WireSession;

const DIRECTIONAL_KEY_DOMAIN: &[u8] = b"HPTA-AUTHENTICATED-RECORD-KEY-V1\0";
const INITIATOR_TO_RESPONDER: &[u8] = b"initiator-to-responder";
const RESPONDER_TO_INITIATOR: &[u8] = b"responder-to-initiator";

/// Connection role used to derive disjoint transmit and receive MAC keys.
///
/// The endpoint role is local: an initiator transmits with the
/// initiator-to-responder key and receives with the responder-to-initiator key.
/// A responder uses the inverse mapping. This prevents a valid outbound record
/// from being reflected back and accepted as inbound traffic.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SessionEndpoint {
    Initiator,
    Responder,
}

impl SessionEndpoint {
    const fn direction_labels(self) -> (&'static [u8], &'static [u8]) {
        match self {
            Self::Initiator => (INITIATOR_TO_RESPONDER, RESPONDER_TO_INITIATOR),
            Self::Responder => (RESPONDER_TO_INITIATOR, INITIATOR_TO_RESPONDER),
        }
    }
}

/// A fixed-size master key for one authenticated wire session.
///
/// Distinct transmit and receive keys are derived from this key, the immutable
/// session identifier, and the endpoint direction. Debug output never exposes
/// key bytes and an all-zero master key is rejected.
#[derive(Clone)]
pub struct SessionMacKey([u8; 32]);

impl SessionMacKey {
    pub fn new(bytes: [u8; 32]) -> Result<Self, AuthenticatedSessionError> {
        if bytes.iter().all(|byte| *byte == 0) {
            return Err(AuthenticatedSessionError::ZeroMacKey);
        }
        Ok(Self(bytes))
    }
}

impl fmt::Debug for SessionMacKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SessionMacKey([REDACTED])")
    }
}

/// Direction-separated authenticated record layer for a completed wire
/// session.
///
/// Internally, each direction owns an independent replay counter and a key
/// derived from the master key plus the immutable session identifier. Any
/// terminal record error poisons both directions. Establish a fresh transport
/// channel and negotiate a new session instead of resetting this object.
#[derive(Debug)]
pub struct AuthenticatedWireSession {
    endpoint: SessionEndpoint,
    outbound: UndirectedAuthenticatedWireSession,
    inbound: UndirectedAuthenticatedWireSession,
    poisoned: bool,
}

impl AuthenticatedWireSession {
    pub fn new(
        session: WireSession,
        master_key: SessionMacKey,
        endpoint: SessionEndpoint,
    ) -> Result<Self, AuthenticatedSessionError> {
        let (send_label, receive_label) = endpoint.direction_labels();
        let session_id = session.session_id();
        let send_key = derive_directional_key(&master_key.0, session_id, send_label);
        let receive_key = derive_directional_key(&master_key.0, session_id, receive_label);
        debug_assert_ne!(send_key, receive_key);
        let outbound = UndirectedAuthenticatedWireSession::new(
            session.clone(),
            UndirectedSessionMacKey::new(send_key)?,
        );
        let inbound = UndirectedAuthenticatedWireSession::new(
            session,
            UndirectedSessionMacKey::new(receive_key)?,
        );
        Ok(Self {
            endpoint,
            outbound,
            inbound,
            poisoned: false,
        })
    }

    pub fn session(&self) -> &WireSession {
        self.outbound.session()
    }

    pub const fn endpoint(&self) -> SessionEndpoint {
        self.endpoint
    }

    pub fn is_poisoned(&self) -> bool {
        self.poisoned || self.outbound.is_poisoned() || self.inbound.is_poisoned()
    }

    pub fn seal_envelope(
        &mut self,
        envelope: &DecodedEnvelope,
    ) -> Result<Vec<u8>, AuthenticatedSessionError> {
        self.ensure_live()?;
        match self.outbound.seal_envelope(envelope) {
            Ok(record) => Ok(record),
            Err(error) => {
                self.poisoned = true;
                Err(error)
            }
        }
    }

    pub fn seal_typed<C: PayloadCodec>(
        &mut self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, AuthenticatedSessionError> {
        self.ensure_live()?;
        match self
            .outbound
            .seal_typed(producer, generation, codec, value)
        {
            Ok(record) => Ok(record),
            Err(error) => {
                self.poisoned = true;
                Err(error)
            }
        }
    }

    pub fn open_record(
        &mut self,
        record: &[u8],
    ) -> Result<DecodedEnvelope, AuthenticatedSessionError> {
        self.ensure_live()?;
        match self.inbound.open_record(record) {
            Ok(envelope) => Ok(envelope),
            Err(error) => {
                self.poisoned = true;
                Err(error)
            }
        }
    }

    pub fn open_typed<C: PayloadCodec>(
        &mut self,
        record: &[u8],
        codec: &C,
    ) -> Result<C::Value, AuthenticatedSessionError> {
        self.ensure_live()?;
        match self.inbound.open_typed(record, codec) {
            Ok(value) => Ok(value),
            Err(error) => {
                self.poisoned = true;
                Err(error)
            }
        }
    }

    fn ensure_live(&self) -> Result<(), AuthenticatedSessionError> {
        if self.is_poisoned() {
            Err(AuthenticatedSessionError::Poisoned)
        } else {
            Ok(())
        }
    }
}

fn derive_directional_key(
    master_key: &[u8; 32],
    session_id: Digest32,
    direction: &[u8],
) -> [u8; 32] {
    hmac_sha256(
        master_key,
        &[DIRECTIONAL_KEY_DOMAIN, session_id.as_array(), direction],
    )
    .into_array()
}

fn hmac_sha256(key: &[u8; 32], parts: &[&[u8]]) -> Digest32 {
    let mut inner_pad = [0x36_u8; 64];
    let mut outer_pad = [0x5c_u8; 64];
    for (index, key_byte) in key.iter().enumerate() {
        inner_pad[index] ^= key_byte;
        outer_pad[index] ^= key_byte;
    }
    let capacity = parts
        .iter()
        .fold(inner_pad.len(), |total, part| total.saturating_add(part.len()));
    let mut inner = Vec::with_capacity(capacity);
    inner.extend_from_slice(&inner_pad);
    for part in parts {
        inner.extend_from_slice(part);
    }
    let inner_digest = Digest32::of_bytes(&inner);
    Digest32::of_parts(&[&outer_pad, inner_digest.as_array()])
}

#[cfg(test)]
mod tests {
    use std::error::Error;
    use std::sync::Arc;

    use crate::FrozenSchemaRegistryBuilder;
    use crate::NegotiationOffer;
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

    fn session(channel_binding: &[u8]) -> Result<WireSession, Box<dyn Error>> {
        let schema = id("schema.directional-record.v1")?;
        let producer = id("producer.directional-test")?;
        let role = id("role.directional-test")?;
        let descriptor = SchemaDescriptor::new(
            schema,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?;
        let required = WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new(
            descriptor,
            vec![producer],
            vec![role.clone()],
            required,
        )?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(policy)?;
        let registry = Arc::new(builder.freeze()?);
        let offer = NegotiationOffer::current();
        let negotiated = negotiate(&offer, &offer, required)?;
        let transcript = crate::NegotiationTranscript::from_offers(
            &offer,
            &offer,
            negotiated,
            registry.snapshot_digest(),
            channel_binding,
        )?;
        Ok(WireSession::new(negotiated, role, registry, transcript))
    }

    fn envelope() -> Result<DecodedEnvelope, Box<dyn Error>> {
        Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
            id("schema.directional-record.v1")?,
            id("producer.directional-test")?,
            Generation::new(1)?,
            b"hello".to_vec(),
        )?))
    }

    #[test]
    fn opposite_endpoints_exchange_records() -> Result<(), Box<dyn Error>> {
        let key = SessionMacKey::new([9_u8; 32])?;
        let mut initiator = AuthenticatedWireSession::new(
            session(&[7_u8; 32])?,
            key.clone(),
            SessionEndpoint::Initiator,
        )?;
        let mut responder = AuthenticatedWireSession::new(
            session(&[7_u8; 32])?,
            key,
            SessionEndpoint::Responder,
        )?;
        let outbound = envelope()?;
        let record = initiator.seal_envelope(&outbound)?;
        assert_eq!(responder.open_record(&record)?, outbound);
        Ok(())
    }

    #[test]
    fn reflected_outbound_record_is_rejected_and_poisons_session() -> Result<(), Box<dyn Error>> {
        let mut initiator = AuthenticatedWireSession::new(
            session(&[7_u8; 32])?,
            SessionMacKey::new([9_u8; 32])?,
            SessionEndpoint::Initiator,
        )?;
        let record = initiator.seal_envelope(&envelope()?)?;
        assert!(matches!(
            initiator.open_record(&record),
            Err(AuthenticatedSessionError::MacMismatch { .. })
        ));
        assert!(initiator.is_poisoned());
        assert!(matches!(
            initiator.seal_envelope(&envelope()?),
            Err(AuthenticatedSessionError::Poisoned)
        ));
        Ok(())
    }

    #[test]
    fn same_endpoint_direction_is_not_interoperable() -> Result<(), Box<dyn Error>> {
        let key = SessionMacKey::new([9_u8; 32])?;
        let mut sender = AuthenticatedWireSession::new(
            session(&[7_u8; 32])?,
            key.clone(),
            SessionEndpoint::Initiator,
        )?;
        let mut wrong_receiver = AuthenticatedWireSession::new(
            session(&[7_u8; 32])?,
            key,
            SessionEndpoint::Initiator,
        )?;
        let record = sender.seal_envelope(&envelope()?)?;
        assert!(matches!(
            wrong_receiver.open_record(&record),
            Err(AuthenticatedSessionError::MacMismatch { .. })
        ));
        Ok(())
    }
}
