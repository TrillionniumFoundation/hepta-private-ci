use crate::replay::FederationReplayKeyV1;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use hmac::Hmac;
use hmac::Mac;
use rand::TryRngCore;
use rand::rngs::OsRng;
use sha2::Sha256;

use crate::credential::CredentialError;
use crate::credential::PeerCredentialRegistryV1;
use crate::credential::PeerCredentialV1;
use crate::replay::ReplayCacheV1;
use crate::replay::ReplayError;

pub const FEDERATION_NONCE_BYTES: usize = 32;
pub const FEDERATION_MAC_BYTES: usize = 32;
pub const MAX_AUTHENTICATED_FRAME_LIFETIME_MS: u64 = 5 * 60 * 1_000;

const FRAME_MAC_DOMAIN: &[u8] = b"hepta.memory-federation.authenticated-frame.v1";
const FRONTIER_DOMAIN: &[u8] = b"hepta.memory-federation.frontier-witness.v1";
const MESSAGE_DOMAIN: &[u8] = b"hepta.memory-federation.wire-message.v1";

type HmacSha256 = Hmac<Sha256>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FederationNonceV1([u8; FEDERATION_NONCE_BYTES]);

impl FederationNonceV1 {
    pub fn generate() -> Result<Self, FederationProtocolError> {
        let mut bytes = <[u8; FEDERATION_NONCE_BYTES]>::default();
        OsRng
            .try_fill_bytes(&mut bytes)
            .map_err(|_| FederationProtocolError::EntropyUnavailable)?;
        Ok(Self(bytes))
    }

    pub const fn from_bytes(bytes: [u8; FEDERATION_NONCE_BYTES]) -> Self {
        Self(bytes)
    }

    pub const fn as_bytes(&self) -> &[u8; FEDERATION_NONCE_BYTES] {
        &self.0
    }

    fn validate(&self) -> Result<(), FederationProtocolError> {
        if self.0.iter().all(|byte| *byte == 0) {
            return Err(FederationProtocolError::ZeroNonce);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedFrontierV1 {
    pub owner_peer_id: StableId,
    pub generation: u64,
    pub frontier: u64,
    pub state_digest: Digest32,
    pub parent_witness_digest: Digest32,
    pub observed_unix_ms: u64,
}

impl AuthenticatedFrontierV1 {
    pub fn validate(&self) -> Result<(), FederationProtocolError> {
        if self.generation == 0 {
            return Err(FederationProtocolError::ZeroValue("frontier_generation"));
        }
        if self.observed_unix_ms == 0 {
            return Err(FederationProtocolError::ZeroValue("frontier_observed_at"));
        }
        require_digest("frontier_state", self.state_digest)
    }

    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FRONTIER_DOMAIN);
        push_id(&mut bytes, &self.owner_peer_id);
        push_u64(&mut bytes, self.generation);
        push_u64(&mut bytes, self.frontier);
        push_digest(&mut bytes, self.state_digest);
        push_digest(&mut bytes, self.parent_witness_digest);
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }

    pub fn require_successor_of(&self, previous: &Self) -> Result<(), FederationProtocolError> {
        self.validate()?;
        previous.validate()?;
        if self.owner_peer_id != previous.owner_peer_id {
            return Err(FederationProtocolError::FrontierOwnerMismatch);
        }
        if self.generation < previous.generation || self.frontier < previous.frontier {
            return Err(FederationProtocolError::FrontierRollback);
        }
        if self.parent_witness_digest != previous.binding_digest() {
            return Err(FederationProtocolError::FrontierParentMismatch);
        }
        if self.observed_unix_ms < previous.observed_unix_ms {
            return Err(FederationProtocolError::ClockRegression);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationQueryMessageV1 {
    pub query_id: StableId,
    pub query_binding_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub maximum_results: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationResponseMessageV1 {
    pub query_id: StableId,
    pub query_binding_digest: Digest32,
    pub response_digest: Digest32,
    pub result_digest: Digest32,
    pub frontier: AuthenticatedFrontierV1,
    pub terminal_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationCancellationReasonV1 {
    CallerCancelled,
    DeadlineExpired,
    AuthorityRevoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancelMessageV1 {
    pub query_id: StableId,
    pub query_binding_digest: Digest32,
    pub cancellation_id: StableId,
    pub reason: FederationCancellationReasonV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationCancellationDispositionV1 {
    ObservedBeforeTerminal,
    TerminalAlreadyObserved,
    UnknownAttempt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancelAckMessageV1 {
    pub query_id: StableId,
    pub query_binding_digest: Digest32,
    pub cancellation_id: StableId,
    pub disposition: FederationCancellationDispositionV1,
    pub observed_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationWireMessageV1 {
    Query(FederationQueryMessageV1),
    Response(FederationResponseMessageV1),
    Cancel(FederationCancelMessageV1),
    CancelAck(FederationCancelAckMessageV1),
}

impl FederationWireMessageV1 {
    pub fn validate(&self) -> Result<(), FederationProtocolError> {
        match self {
            Self::Query(query) => {
                for (name, digest) in [
                    ("query_binding", query.query_binding_digest),
                    ("scope", query.scope_digest),
                    ("purpose", query.purpose_digest),
                    ("generation_vector", query.generation_vector_digest),
                ] {
                    require_digest(name, digest)?;
                }
                if query.maximum_results == 0 {
                    return Err(FederationProtocolError::ZeroValue("maximum_results"));
                }
            }
            Self::Response(response) => {
                for (name, digest) in [
                    ("query_binding", response.query_binding_digest),
                    ("response", response.response_digest),
                    ("result", response.result_digest),
                ] {
                    require_digest(name, digest)?;
                }
                if !response.terminal_observed {
                    return Err(FederationProtocolError::MissingTerminalObservation);
                }
                response.frontier.validate()?;
            }
            Self::Cancel(cancel) => {
                require_digest("query_binding", cancel.query_binding_digest)?;
            }
            Self::CancelAck(ack) => {
                require_digest("query_binding", ack.query_binding_digest)?;
                if ack.observed_unix_ms == 0 {
                    return Err(FederationProtocolError::ZeroValue(
                        "cancellation_observed_at",
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MESSAGE_DOMAIN);
        crate::codec::encode_message_into(self, &mut bytes);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedFederationFrameV1 {
    pub sender_peer_id: StableId,
    pub receiver_peer_id: StableId,
    pub key_id: StableId,
    pub key_generation: u64,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub nonce: FederationNonceV1,
    pub message: FederationWireMessageV1,
    pub(crate) mac: [u8; FEDERATION_MAC_BYTES],
}

/// Unchecked codec output. Verification, replay admission and authority remain
/// separate operations; this type is never exported outside the crate.
pub(crate) struct DecodedFederationFrameV1 {
    pub(crate) sender_peer_id: StableId,
    pub(crate) receiver_peer_id: StableId,
    pub(crate) key_id: StableId,
    pub(crate) key_generation: u64,
    pub(crate) issued_unix_ms: u64,
    pub(crate) expires_unix_ms: u64,
    pub(crate) nonce: FederationNonceV1,
    pub(crate) message: FederationWireMessageV1,
    pub(crate) mac: [u8; FEDERATION_MAC_BYTES],
}

/// A request-local MAC proof, not an admission or authority token.
/// Its immutable borrow prevents mutation between MAC verification and replay.
pub(crate) struct AuthenticatedFrameProofV1<'a> {
    frame: &'a AuthenticatedFederationFrameV1,
    observed_unix_ms: u64,
    frame_digest: Digest32,
}

impl AuthenticatedFrameProofV1<'_> {
    pub(crate) fn admit_replay(
        self,
        replay: &mut ReplayCacheV1,
    ) -> Result<VerifiedFederationFrameV1, FederationProtocolError> {
        let frame = self.frame;
        replay.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &frame.sender_peer_id,
                receiver_peer_id: &frame.receiver_peer_id,
                key_id: &frame.key_id,
                generation: frame.key_generation,
                nonce: frame.nonce.as_bytes(),
            },
            frame.expires_unix_ms,
            self.observed_unix_ms,
        )?;
        Ok(VerifiedFederationFrameV1 {
            sender_peer_id: frame.sender_peer_id.clone(),
            receiver_peer_id: frame.receiver_peer_id.clone(),
            key_id: frame.key_id.clone(),
            key_generation: frame.key_generation,
            issued_unix_ms: frame.issued_unix_ms,
            expires_unix_ms: frame.expires_unix_ms,
            nonce: frame.nonce,
            message: frame.message.clone(),
            frame_digest: self.frame_digest,
        })
    }
}

impl AuthenticatedFederationFrameV1 {
    pub fn seal(
        credential: &PeerCredentialV1,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
        nonce: FederationNonceV1,
        message: FederationWireMessageV1,
    ) -> Result<Self, FederationProtocolError> {
        if issued_unix_ms < credential.effective_unix_ms()
            || issued_unix_ms >= credential.expires_unix_ms()
            || expires_unix_ms > credential.expires_unix_ms()
        {
            return Err(FederationProtocolError::Credential(
                CredentialError::Expired,
            ));
        }
        let mut frame = Self {
            sender_peer_id: credential.sender_peer_id().clone(),
            receiver_peer_id: credential.receiver_peer_id().clone(),
            key_id: credential.key_id().clone(),
            key_generation: credential.generation(),
            issued_unix_ms,
            expires_unix_ms,
            nonce,
            message,
            mac: <[u8; FEDERATION_MAC_BYTES]>::default(),
        };
        frame.validate_shape(issued_unix_ms)?;
        frame.mac = compute_mac(credential.secret(), &frame.mac_input())?;
        Ok(frame)
    }

    pub fn verify(
        &self,
        expected_receiver_peer_id: &StableId,
        now_unix_ms: u64,
        credentials: &PeerCredentialRegistryV1,
        replay: &mut ReplayCacheV1,
    ) -> Result<VerifiedFederationFrameV1, FederationProtocolError> {
        self.authenticate(expected_receiver_peer_id, now_unix_ms, credentials)?
            .admit_replay(replay)
    }

    /// Authenticate immutable frame bytes before allocating transaction state.
    /// This proof is crate-private and borrows the frame: it cannot authorize a
    /// modified frame, expose an admitted query, or skip replay admission.
    pub(crate) fn authenticate(
        &self,
        expected_receiver_peer_id: &StableId,
        now_unix_ms: u64,
        credentials: &PeerCredentialRegistryV1,
    ) -> Result<AuthenticatedFrameProofV1<'_>, FederationProtocolError> {
        self.validate_shape(now_unix_ms)?;
        if &self.receiver_peer_id != expected_receiver_peer_id {
            return Err(FederationProtocolError::ReceiverMismatch);
        }
        let credential = credentials.require_current(
            &self.sender_peer_id,
            &self.receiver_peer_id,
            &self.key_id,
            self.key_generation,
            now_unix_ms,
        )?;
        let input = self.mac_input();
        let mut verifier = HmacSha256::new_from_slice(credential.secret())
            .map_err(|_| FederationProtocolError::InvalidMacKey)?;
        verifier.update(&input);
        verifier
            .verify_slice(&self.mac)
            .map_err(|_| FederationProtocolError::MacMismatch)?;
        Ok(AuthenticatedFrameProofV1 {
            frame: self,
            observed_unix_ms: now_unix_ms,
            frame_digest: Digest32::of_bytes(&input),
        })
    }

    pub fn mac(&self) -> &[u8; FEDERATION_MAC_BYTES] {
        &self.mac
    }

    pub(crate) fn from_decoded_parts(parts: DecodedFederationFrameV1) -> Self {
        Self {
            sender_peer_id: parts.sender_peer_id,
            receiver_peer_id: parts.receiver_peer_id,
            key_id: parts.key_id,
            key_generation: parts.key_generation,
            issued_unix_ms: parts.issued_unix_ms,
            expires_unix_ms: parts.expires_unix_ms,
            nonce: parts.nonce,
            message: parts.message,
            mac: parts.mac,
        }
    }

    fn validate_shape(&self, now_unix_ms: u64) -> Result<(), FederationProtocolError> {
        if self.sender_peer_id == self.receiver_peer_id {
            return Err(FederationProtocolError::SamePeer);
        }
        if self.key_generation == 0 {
            return Err(FederationProtocolError::ZeroValue("key_generation"));
        }
        if self.issued_unix_ms == 0 || self.issued_unix_ms >= self.expires_unix_ms {
            return Err(FederationProtocolError::InvalidLifetime);
        }
        if self.expires_unix_ms.saturating_sub(self.issued_unix_ms)
            > MAX_AUTHENTICATED_FRAME_LIFETIME_MS
        {
            return Err(FederationProtocolError::LifetimeExceeded);
        }
        if now_unix_ms < self.issued_unix_ms {
            return Err(FederationProtocolError::NotYetValid);
        }
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationProtocolError::Expired);
        }
        self.nonce.validate()?;
        self.message.validate()
    }

    fn mac_input(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FRAME_MAC_DOMAIN);
        push_id(&mut bytes, &self.sender_peer_id);
        push_id(&mut bytes, &self.receiver_peer_id);
        push_id(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.key_generation);
        push_u64(&mut bytes, self.issued_unix_ms);
        push_u64(&mut bytes, self.expires_unix_ms);
        bytes.extend_from_slice(self.nonce.as_bytes());
        push_digest(&mut bytes, self.message.binding_digest());
        bytes
    }
}

/// An authenticated frame whose MAC, directional credential, lifetime, receiver,
/// and replay admission were all verified by [`AuthenticatedFederationFrameV1::verify`].
///
/// All fields are deliberately private. External callers can inspect them only
/// through read-only accessors and therefore cannot construct a fake verified
/// value or mutate an authenticated message after verification.
///
/// ```compile_fail
/// use codex_hepta_memory_federation_wire::VerifiedFederationFrameV1;
/// let mut verified: VerifiedFederationFrameV1 = todo!();
/// verified.message = todo!();
/// ```
///
/// ```compile_fail
/// use codex_hepta_memory_federation_wire::VerifiedFederationFrameV1;
/// let _ = VerifiedFederationFrameV1 {
///     sender_peer_id: todo!(),
///     receiver_peer_id: todo!(),
///     key_id: todo!(),
///     key_generation: 1,
///     issued_unix_ms: 1,
///     expires_unix_ms: 2,
///     nonce: todo!(),
///     message: todo!(),
///     frame_digest: todo!(),
/// };
/// ```
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFederationFrameV1 {
    sender_peer_id: StableId,
    receiver_peer_id: StableId,
    key_id: StableId,
    key_generation: u64,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    nonce: FederationNonceV1,
    message: FederationWireMessageV1,
    frame_digest: Digest32,
}

impl VerifiedFederationFrameV1 {
    pub const fn sender_peer_id(&self) -> &StableId {
        &self.sender_peer_id
    }

    pub const fn receiver_peer_id(&self) -> &StableId {
        &self.receiver_peer_id
    }

    pub const fn key_id(&self) -> &StableId {
        &self.key_id
    }

    pub const fn key_generation(&self) -> u64 {
        self.key_generation
    }

    pub const fn issued_unix_ms(&self) -> u64 {
        self.issued_unix_ms
    }

    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    pub const fn nonce(&self) -> FederationNonceV1 {
        self.nonce
    }

    pub const fn message(&self) -> &FederationWireMessageV1 {
        &self.message
    }

    pub const fn frame_digest(&self) -> Digest32 {
        self.frame_digest
    }

    pub fn into_message(self) -> FederationWireMessageV1 {
        self.message
    }
}

fn compute_mac(
    secret: &[u8],
    input: &[u8],
) -> Result<[u8; FEDERATION_MAC_BYTES], FederationProtocolError> {
    let mut mac =
        HmacSha256::new_from_slice(secret).map_err(|_| FederationProtocolError::InvalidMacKey)?;
    mac.update(input);
    let bytes = mac.finalize().into_bytes();
    let mut result = <[u8; FEDERATION_MAC_BYTES]>::default();
    result.copy_from_slice(&bytes);
    Ok(result)
}

fn require_digest(name: &'static str, digest: Digest32) -> Result<(), FederationProtocolError> {
    if digest.is_zero() {
        return Err(FederationProtocolError::EmptyDigest(name));
    }
    Ok(())
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

pub(crate) fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

pub(crate) fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[derive(Debug)]
pub enum FederationProtocolError {
    EntropyUnavailable,
    ZeroNonce,
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    SamePeer,
    InvalidLifetime,
    LifetimeExceeded,
    NotYetValid,
    Expired,
    MissingTerminalObservation,
    ReceiverMismatch,
    InvalidMacKey,
    MacMismatch,
    FrontierOwnerMismatch,
    FrontierRollback,
    FrontierParentMismatch,
    ClockRegression,
    Credential(CredentialError),
    Replay(ReplayError),
}

impl fmt::Display for FederationProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EntropyUnavailable => {
                formatter.write_str("operating-system entropy is unavailable")
            }
            Self::ZeroNonce => formatter.write_str("federation nonce cannot be all zero"),
            Self::ZeroValue(name) => write!(formatter, "{name} must be non-zero"),
            Self::EmptyDigest(name) => write!(formatter, "{name} digest cannot be zero"),
            Self::SamePeer => formatter.write_str("sender and receiver peers must differ"),
            Self::InvalidLifetime => formatter.write_str("authenticated frame lifetime is invalid"),
            Self::LifetimeExceeded => {
                formatter.write_str("authenticated frame lifetime exceeds the protocol bound")
            }
            Self::NotYetValid => formatter.write_str("authenticated frame is not yet valid"),
            Self::Expired => formatter.write_str("authenticated frame is expired"),
            Self::MissingTerminalObservation => {
                formatter.write_str("response is missing a terminal observation")
            }
            Self::ReceiverMismatch => {
                formatter.write_str("authenticated frame receiver does not match this host")
            }
            Self::InvalidMacKey => formatter.write_str("federation MAC key is invalid"),
            Self::MacMismatch => formatter.write_str("federation frame MAC did not verify"),
            Self::FrontierOwnerMismatch => formatter.write_str("frontier witness owner changed"),
            Self::FrontierRollback => formatter.write_str("frontier witness regressed"),
            Self::FrontierParentMismatch => {
                formatter.write_str("frontier witness parent binding is invalid")
            }
            Self::ClockRegression => formatter.write_str("frontier observation clock regressed"),
            Self::Credential(error) => error.fmt(formatter),
            Self::Replay(error) => error.fmt(formatter),
        }
    }
}

impl Error for FederationProtocolError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Credential(error) => Some(error),
            Self::Replay(error) => Some(error),
            _ => None,
        }
    }
}

impl From<CredentialError> for FederationProtocolError {
    fn from(value: CredentialError) -> Self {
        Self::Credential(value)
    }
}

impl From<ReplayError> for FederationProtocolError {
    fn from(value: ReplayError) -> Self {
        Self::Replay(value)
    }
}
