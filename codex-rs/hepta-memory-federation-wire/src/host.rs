use crate::replay::FederationReplayKeyV1;
use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::codec::decode_registered_frame_v1;
use crate::codec::encode_registered_frame_v1;
use crate::codec::registered_codec_v1;
use crate::credential::CredentialError;
use crate::credential::PeerCredentialRegistryV1;
use crate::credential::PeerCredentialV1;
use crate::protocol::AuthenticatedFederationFrameV1;
use crate::protocol::AuthenticatedFrontierV1;
use crate::protocol::FederationNonceV1;
use crate::protocol::FederationProtocolError;
use crate::protocol::FederationQueryMessageV1;
use crate::protocol::FederationResponseMessageV1;
use crate::protocol::FederationWireMessageV1;
use crate::protocol::MAX_AUTHENTICATED_FRAME_LIFETIME_MS;
use crate::protocol::VerifiedFederationFrameV1;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryError;
use crate::recovery::FederationRecoveryLimitsV1;
use crate::recovery::FederationRecoveryStoreV1;
use crate::replay::ReplayCacheV1;
use crate::replay::ReplayError;

pub const MAX_FEDERATION_HOST_PEERS: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationOutboundCredentialV1 {
    key_id: StableId,
    generation: u64,
}

impl FederationOutboundCredentialV1 {
    pub fn new(key_id: StableId, generation: u64) -> Result<Self, FederationHostError> {
        if generation == 0 {
            return Err(FederationHostError::InvalidOutboundCredential);
        }
        Ok(Self { key_id, generation })
    }

    pub fn key_id(&self) -> &StableId {
        &self.key_id
    }

    pub const fn generation(&self) -> u64 {
        self.generation
    }
}

/// A query whose authenticated transport identity, frame MAC, replay record,
/// and durable pending-attempt intent have all been admitted.
///
/// Fields are private so callers cannot forge an admission token and bypass the
/// durable replay/attempt boundary. The issuing host and directional request
/// credential remain bound to the token and are checked again before completion.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedFederationQueryV1 {
    peer_id: StableId,
    receiver_peer_id: StableId,
    request_key_id: StableId,
    request_key_generation: u64,
    query: FederationQueryMessageV1,
    admitted_unix_ms: u64,
    response_expiry_ceiling_unix_ms: u64,
}

impl AdmittedFederationQueryV1 {
    pub fn peer_id(&self) -> &StableId {
        &self.peer_id
    }

    pub const fn query(&self) -> &FederationQueryMessageV1 {
        &self.query
    }

    pub const fn admitted_unix_ms(&self) -> u64 {
        self.admitted_unix_ms
    }

    pub const fn response_expiry_ceiling_unix_ms(&self) -> u64 {
        self.response_expiry_ceiling_unix_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationHostQueryResultV1 {
    response_digest: Digest32,
    result_digest: Digest32,
    frontier: AuthenticatedFrontierV1,
}

impl FederationHostQueryResultV1 {
    pub fn new(
        response_digest: Digest32,
        result_digest: Digest32,
        frontier: AuthenticatedFrontierV1,
    ) -> Result<Self, FederationHostError> {
        if response_digest.is_zero() || result_digest.is_zero() {
            return Err(FederationHostError::EmptyResultDigest);
        }
        frontier.validate().map_err(FederationHostError::Protocol)?;
        Ok(Self {
            response_digest,
            result_digest,
            frontier,
        })
    }
}

pub enum FederationHostAdmissionV1 {
    Query(AdmittedFederationQueryV1),
    /// An authenticated cancellation acknowledgement ready for transport.
    Reply(Vec<u8>),
    /// A verified response or cancellation acknowledgement received by a
    /// client-side host. The verified frame remains immutable.
    Inbound(VerifiedFederationFrameV1),
}

/// Transport-neutral server-side host boundary for the authenticated cross-host
/// candidate.
///
/// The selected network adapter must supply the peer identity authenticated by
/// its secure channel. This host checks that identity against the frame sender,
/// durably commits replay plus query/cancel state before exposing work or bytes,
/// and commits terminal state before returning a response. Recovery transitions
/// are staged and installed only after the recovery store atomically replaces
/// its prior snapshot. Definite pre-commit failures are retryable; a backend
/// reporting an indeterminate commit must fence further operations until reopen.
/// This boundary owns no memory writer.
pub struct FederationWireHostV1<S>
where
    S: FederationRecoveryStoreV1,
{
    local_peer_id: StableId,
    credentials: PeerCredentialRegistryV1,
    outbound_credentials: BTreeMap<String, FederationOutboundCredentialV1>,
    replay: ReplayCacheV1,
    recovery: DurableFederationStateV1,
    recovery_store: S,
}

impl<S> FederationWireHostV1<S>
where
    S: FederationRecoveryStoreV1,
{
    pub fn open(
        local_peer_id: StableId,
        credentials: PeerCredentialRegistryV1,
        replay_capacity: usize,
        replay_per_credential_capacity: usize,
        recovery_limits: FederationRecoveryLimitsV1,
        mut recovery_store: S,
        now_unix_ms: u64,
    ) -> Result<Self, FederationHostError> {
        let replay = ReplayCacheV1::with_limits(replay_capacity, replay_per_credential_capacity)
            .map_err(FederationHostError::Replay)?;
        let recovery = match recovery_store.load()? {
            Some(bytes) => DurableFederationStateV1::restore(
                local_peer_id.clone(),
                recovery_limits,
                now_unix_ms,
                &bytes,
            )?,
            None => DurableFederationStateV1::empty(
                local_peer_id.clone(),
                recovery_limits,
                now_unix_ms,
            )?,
        };
        let mut host = Self {
            local_peer_id,
            credentials,
            outbound_credentials: BTreeMap::new(),
            replay,
            recovery,
            recovery_store,
        };
        host.persist_current()?;
        Ok(host)
    }

    pub fn local_peer_id(&self) -> &StableId {
        &self.local_peer_id
    }

    pub fn bind_outbound_credential(
        &mut self,
        receiver_peer_id: StableId,
        credential: FederationOutboundCredentialV1,
    ) -> Result<(), FederationHostError> {
        if receiver_peer_id == self.local_peer_id {
            return Err(FederationHostError::TransportPeerMismatch);
        }
        if !self
            .outbound_credentials
            .contains_key(receiver_peer_id.as_str())
            && self.outbound_credentials.len() >= MAX_FEDERATION_HOST_PEERS
        {
            return Err(FederationHostError::PeerCapacityExhausted);
        }
        self.outbound_credentials
            .insert(receiver_peer_id.as_str().to_string(), credential);
        Ok(())
    }

    pub fn enroll_credential(
        &mut self,
        credential: PeerCredentialV1,
    ) -> Result<(), FederationHostError> {
        self.credentials
            .enroll(credential)
            .map_err(FederationHostError::Credential)
    }

    pub fn rotate_credential(
        &mut self,
        credential: PeerCredentialV1,
    ) -> Result<(), FederationHostError> {
        self.credentials
            .rotate(credential)
            .map_err(FederationHostError::Credential)
    }

    pub fn revoke_credential(
        &mut self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
    ) -> Result<(), FederationHostError> {
        self.credentials
            .revoke(sender_peer_id, receiver_peer_id, key_id, generation)
            .map_err(FederationHostError::Credential)
    }

    pub fn admit(
        &mut self,
        transport_peer_id: &StableId,
        payload: &[u8],
        now_unix_ms: u64,
    ) -> Result<FederationHostAdmissionV1, FederationHostError> {
        let (schemas, codec) = registered_codec_v1().map_err(|_| FederationHostError::Codec)?;
        let frame = decode_registered_frame_v1(&schemas, &codec, payload)
            .map_err(|_| FederationHostError::Codec)?;
        if &frame.sender_peer_id != transport_peer_id {
            return Err(FederationHostError::TransportPeerMismatch);
        }

        let authentication =
            frame.authenticate(&self.local_peer_id, now_unix_ms, &self.credentials)?;

        let mut next_recovery = self.stage_recovery()?;
        let mut next_replay = self.replay.clone();
        let durable_replay_key = next_recovery.preflight_frame(
            FederationReplayKeyV1 {
                sender_peer_id: &frame.sender_peer_id,
                receiver_peer_id: &frame.receiver_peer_id,
                key_id: &frame.key_id,
                generation: frame.key_generation,
                nonce: frame.nonce.as_bytes(),
            },
            frame.expires_unix_ms,
            now_unix_ms,
        )?;
        let request_key_id = frame.key_id.clone();
        let request_key_generation = frame.key_generation;
        let verified = authentication.admit_replay(&mut next_replay)?;
        next_recovery.record_verified_frame(
            durable_replay_key,
            verified.sender_peer_id(),
            verified.expires_unix_ms(),
        )?;

        let admission = match verified.message().clone() {
            FederationWireMessageV1::Query(query) => {
                next_recovery.begin_attempt(
                    verified.sender_peer_id(),
                    &query.query_id,
                    query.query_binding_digest,
                    verified.expires_unix_ms(),
                    now_unix_ms,
                )?;
                FederationHostAdmissionV1::Query(AdmittedFederationQueryV1 {
                    peer_id: verified.sender_peer_id().clone(),
                    receiver_peer_id: self.local_peer_id.clone(),
                    request_key_id,
                    request_key_generation,
                    query,
                    admitted_unix_ms: now_unix_ms,
                    response_expiry_ceiling_unix_ms: verified.expires_unix_ms(),
                })
            }
            FederationWireMessageV1::Cancel(cancel) => {
                let acknowledgement = next_recovery.observe_cancel(
                    verified.sender_peer_id(),
                    &cancel,
                    now_unix_ms,
                )?;
                let reply = self.seal_outbound(
                    verified.sender_peer_id(),
                    FederationWireMessageV1::CancelAck(acknowledgement),
                    now_unix_ms,
                    verified.expires_unix_ms(),
                )?;
                FederationHostAdmissionV1::Reply(reply)
            }
            FederationWireMessageV1::Response(_) | FederationWireMessageV1::CancelAck(_) => {
                FederationHostAdmissionV1::Inbound(verified)
            }
        };
        self.commit_recovery_and_replay(next_recovery, next_replay)?;
        Ok(admission)
    }

    pub fn complete_query(
        &mut self,
        admitted: AdmittedFederationQueryV1,
        result: FederationHostQueryResultV1,
        now_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationHostError> {
        // Admission is not perpetual authority. A live outbound signing key
        // cannot authorize a response to a request whose inbound credential was
        // revoked, rotated or expired while the owner read was in progress.
        if admitted.receiver_peer_id != self.local_peer_id {
            return Err(FederationHostError::AdmissionHostMismatch);
        }
        self.credentials.require_current(
            &admitted.peer_id,
            &self.local_peer_id,
            &admitted.request_key_id,
            admitted.request_key_generation,
            now_unix_ms,
        )?;
        if result.frontier.owner_peer_id != self.local_peer_id {
            return Err(FederationHostError::FrontierOwnerMismatch);
        }
        if result.frontier.observed_unix_ms < admitted.admitted_unix_ms
            || result.frontier.observed_unix_ms > now_unix_ms
        {
            return Err(FederationHostError::FrontierClockInvalid);
        }
        let message = FederationWireMessageV1::Response(FederationResponseMessageV1 {
            query_id: admitted.query.query_id.clone(),
            query_binding_digest: admitted.query.query_binding_digest,
            response_digest: result.response_digest,
            result_digest: result.result_digest,
            frontier: result.frontier,
            terminal_observed: true,
        });
        let terminal_digest = message.binding_digest();
        let mut next_recovery = self.stage_recovery()?;
        next_recovery.observe_terminal(
            &admitted.peer_id,
            &admitted.query.query_id,
            admitted.query.query_binding_digest,
            terminal_digest,
            now_unix_ms,
        )?;
        let response = self.seal_outbound(
            &admitted.peer_id,
            message,
            now_unix_ms,
            admitted.response_expiry_ceiling_unix_ms,
        )?;
        self.commit_recovery(next_recovery)?;
        Ok(response)
    }

    /// Commit at most one 64-row expiry-maintenance quantum across durable
    /// protocol rows and the live replay cache. This owner operation performs
    /// no remote I/O, query replay, credential change, or authority decision.
    /// Use it between admissions so failed requests cannot stall cleanup by
    /// repeatedly rolling back their temporary transaction state.
    pub fn maintain_expired(&mut self, now_unix_ms: u64) -> Result<usize, FederationHostError> {
        let maximum = crate::recovery::FEDERATION_RECOVERY_CLEANUP_BATCH;
        let before = self.recovery.replay_len() + self.recovery.attempt_len();
        let next = self.recovery.stage_maintenance_at(now_unix_ms, maximum)?;
        let removed = before - next.replay_len() - next.attempt_len();
        let mut replay = self.replay.clone();
        let live_removed = replay
            .purge_expired_bounded(now_unix_ms, maximum.saturating_sub(removed))
            .map_err(FederationHostError::Replay)?;
        self.commit_recovery_and_replay(next, replay)?;
        Ok(removed + live_removed)
    }

    pub fn recovery_snapshot(&self) -> Result<Vec<u8>, FederationHostError> {
        self.recovery
            .snapshot_bytes()
            .map_err(FederationHostError::Recovery)
    }

    pub fn into_recovery_store(self) -> S {
        self.recovery_store
    }

    fn seal_outbound(
        &self,
        receiver_peer_id: &StableId,
        message: FederationWireMessageV1,
        now_unix_ms: u64,
        request_expiry_ceiling_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationHostError> {
        let selector = self
            .outbound_credentials
            .get(receiver_peer_id.as_str())
            .ok_or(FederationHostError::MissingOutboundCredential)?;
        let credential = self.credentials.require_current(
            &self.local_peer_id,
            receiver_peer_id,
            selector.key_id(),
            selector.generation(),
            now_unix_ms,
        )?;
        let expires_unix_ms = request_expiry_ceiling_unix_ms
            .min(credential.expires_unix_ms())
            .min(now_unix_ms.saturating_add(MAX_AUTHENTICATED_FRAME_LIFETIME_MS));
        if expires_unix_ms <= now_unix_ms {
            return Err(FederationHostError::ResponseExpired);
        }
        let frame = AuthenticatedFederationFrameV1::seal(
            credential,
            now_unix_ms,
            expires_unix_ms,
            FederationNonceV1::generate()?,
            message,
        )?;
        let (schemas, codec) = registered_codec_v1().map_err(|_| FederationHostError::Codec)?;
        encode_registered_frame_v1(&schemas, &codec, &frame).map_err(|_| FederationHostError::Codec)
    }

    fn stage_recovery(&self) -> Result<DurableFederationStateV1, FederationHostError> {
        self.recovery
            .stage_at(self.recovery.last_observed_unix_ms())
            .map_err(FederationHostError::Recovery)
    }

    fn commit_recovery(
        &mut self,
        next_recovery: DurableFederationStateV1,
    ) -> Result<(), FederationHostError> {
        let snapshot = next_recovery.snapshot_bytes()?;
        self.recovery_store.store(&snapshot)?;
        self.recovery = next_recovery;
        Ok(())
    }

    fn commit_recovery_and_replay(
        &mut self,
        next_recovery: DurableFederationStateV1,
        next_replay: ReplayCacheV1,
    ) -> Result<(), FederationHostError> {
        let snapshot = next_recovery.snapshot_bytes()?;
        self.recovery_store.store(&snapshot)?;
        self.recovery = next_recovery;
        self.replay = next_replay;
        Ok(())
    }

    fn persist_current(&mut self) -> Result<(), FederationHostError> {
        let snapshot = self.recovery.snapshot_bytes()?;
        self.recovery_store.store(&snapshot)?;
        Ok(())
    }
}

#[derive(Debug)]
pub enum FederationHostError {
    Codec,
    InvalidOutboundCredential,
    MissingOutboundCredential,
    PeerCapacityExhausted,
    TransportPeerMismatch,
    AdmissionHostMismatch,
    EmptyResultDigest,
    FrontierOwnerMismatch,
    FrontierClockInvalid,
    ResponseExpired,
    Credential(CredentialError),
    Protocol(FederationProtocolError),
    Replay(ReplayError),
    Recovery(FederationRecoveryError),
}

impl fmt::Display for FederationHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Codec => formatter.write_str("authenticated federation codec rejected the frame"),
            Self::InvalidOutboundCredential => {
                formatter.write_str("outbound credential selector is invalid")
            }
            Self::MissingOutboundCredential => {
                formatter.write_str("outbound directional credential is not bound")
            }
            Self::PeerCapacityExhausted => {
                formatter.write_str("federation host peer capacity is exhausted")
            }
            Self::TransportPeerMismatch => {
                formatter.write_str("secure transport peer identity does not match frame sender")
            }
            Self::AdmissionHostMismatch => {
                formatter.write_str("query admission was issued by a different federation host")
            }
            Self::EmptyResultDigest => {
                formatter.write_str("federation query result digest cannot be zero")
            }
            Self::FrontierOwnerMismatch => {
                formatter.write_str("owner-cut witness does not belong to this host")
            }
            Self::FrontierClockInvalid => {
                formatter.write_str("owner-cut witness time is outside the admitted query interval")
            }
            Self::ResponseExpired => {
                formatter.write_str("federation response has no remaining authenticated lifetime")
            }
            Self::Credential(error) => error.fmt(formatter),
            Self::Protocol(error) => error.fmt(formatter),
            Self::Replay(error) => error.fmt(formatter),
            Self::Recovery(error) => error.fmt(formatter),
        }
    }
}

impl Error for FederationHostError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Credential(error) => Some(error),
            Self::Protocol(error) => Some(error),
            Self::Replay(error) => Some(error),
            Self::Recovery(error) => Some(error),
            _ => None,
        }
    }
}

impl From<CredentialError> for FederationHostError {
    fn from(value: CredentialError) -> Self {
        Self::Credential(value)
    }
}

impl From<FederationProtocolError> for FederationHostError {
    fn from(value: FederationProtocolError) -> Self {
        Self::Protocol(value)
    }
}

impl From<FederationRecoveryError> for FederationHostError {
    fn from(value: FederationRecoveryError) -> Self {
        Self::Recovery(value)
    }
}
