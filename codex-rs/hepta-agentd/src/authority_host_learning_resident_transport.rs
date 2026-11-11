//! The ordinary A handoff and Root server use one new fixed purpose over the
//! existing held-pidfd command channel. Old 500 ms evidence lanes are unchanged.

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::sync::Semaphore;

use super::authentication;
use super::profile;
use super::profile::RootResidentLearningProfileV3;
use super::profile::RootResidentLearningReadbackAuthorizationV3;
use super::runtime::ResidentRequestModeV3;
use super::runtime::RootResidentLearningHandleV3;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

/// Created only by an authenticated Root reply and local complete-signature
/// validation. A partial cut is an observation, never a completion ACK.
pub struct RootResidentLearningObservationV3 {
    pub(super) snapshot: Option<LearningIterationSnapshotV1>,
    pub(super) attestations: Vec<SignedLearningEvidenceV1>,
    pub(super) dispatch_pending: bool,
}

impl RootResidentLearningObservationV3 {
    pub fn snapshot(&self) -> Option<&LearningIterationSnapshotV1> { self.snapshot.as_ref() }
    pub fn attestations(&self) -> &[SignedLearningEvidenceV1] { &self.attestations }
    pub fn dispatch_pending(&self) -> bool { self.dispatch_pending }
}

struct ResidentChannelV3 {
    peer: HostAuthorityPeerChannel,
    next: u64,
    execution_requested: bool,
    retained: Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
}

enum ClientOriginV3 {
    Fresh,
    Readback(RootResidentLearningReadbackAuthorizationV3),
}

/// No owner writer or execution token crosses this process boundary. A lost
/// exchange consumes the connection; only a new explicit original readback
/// handoff may reconcile the same operation after A or Root exits.
pub struct AgentdRootResidentLearningClientV3 {
    channel: Arc<Mutex<Option<ResidentChannelV3>>>,
    lane: Arc<Semaphore>,
    pub(crate) profile: RootResidentLearningProfileV3,
    verifier: LearningEvidenceVerifierV1,
    authorization: codex_hepta_types::Digest32,
    origin: Arc<ClientOriginV3>,
}

impl AgentdRootResidentLearningClientV3 {
    pub fn from_original_root_stream(
        stream: UnixStream,
        root: AgentdRootAuthorityPeer,
        held_root_pidfd: OwnedFd,
        profile: RootResidentLearningProfileV3,
        verifier: LearningEvidenceVerifierV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind(stream, root, held_root_pidfd, profile, verifier,
            ClientOriginV3::Fresh, None, timeout, lifetime)
    }

    /// The new externally supplied readback intent remains a distinct purpose.
    /// A saved tuple is only an exact comparison pin. It cannot recreate fresh
    /// custody, an execution token, a source lease or a stage signature.
    pub fn recover_original_root_stream(
        stream: UnixStream,
        root: AgentdRootAuthorityPeer,
        held_root_pidfd: OwnedFd,
        profile: RootResidentLearningProfileV3,
        authorization: RootResidentLearningReadbackAuthorizationV3,
        verifier: LearningEvidenceVerifierV1,
        expected: Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind(stream, root, held_root_pidfd, profile, verifier,
            ClientOriginV3::Readback(authorization), expected, timeout, lifetime)
    }

    fn bind(
        stream: UnixStream,
        root: AgentdRootAuthorityPeer,
        held_root_pidfd: OwnedFd,
        profile: RootResidentLearningProfileV3,
        verifier: LearningEvidenceVerifierV1,
        origin: ClientOriginV3,
        expected: Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if verifier.trust_digest() != profile.initial.owners.evidence_trust_digest {
            return Err(Error::WrongScope);
        }
        let readonly = matches!(&origin, ClientOriginV3::Readback(_));
        let (intent, lease) = artifacts(&profile, &origin);
        let authorization = profile::authorization_binding(&profile, intent, lease)
            .map_err(|_| Error::WrongScope)?;
        let channel = original_owner_command_channel_v1(
            stream, root, 0, held_root_pidfd, timeout, lifetime,
        ).map_err(|_| Error::Unavailable)?;
        channel.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        let now = now()?;
        require_window(&profile, &origin, now)?;
        if let Some((snapshot, evidence)) = &expected {
            authentication::verify_attestations(&profile, &verifier, snapshot, evidence, now / 1_000)?;
        }
        Ok(Self {
            channel: Arc::new(Mutex::new(Some(ResidentChannelV3 {
                peer: channel, next: 1, execution_requested: readonly, retained: expected,
            }))),
            lane: Arc::new(Semaphore::new(1)),
            profile, verifier, authorization, origin: Arc::new(origin),
        })
    }

    pub async fn readback(&self) -> Result<RootResidentLearningObservationV3, Error> {
        self.exchange(wire::Action::Readback).await
    }

    /// Only the ordinary post-claim source join calls this entry. Recovered
    /// clients translate that local delivery into readback, never fresh work.
    pub(crate) async fn admit_after_original_claim(
        &self,
    ) -> Result<RootResidentLearningObservationV3, Error> {
        let action = match self.origin.as_ref() {
            ClientOriginV3::Fresh => wire::Action::Admit,
            ClientOriginV3::Readback(_) => wire::Action::Readback,
        };
        self.exchange(action).await
    }

    async fn exchange(&self, action: wire::Action) -> Result<RootResidentLearningObservationV3, Error> {
        let permit = Arc::clone(&self.lane).try_acquire_owned().map_err(|_| Error::QueueFull)?;
        let slot = Arc::clone(&self.channel);
        let profile = self.profile.clone();
        let verifier = self.verifier.clone();
        let origin = Arc::clone(&self.origin);
        let authorization = self.authorization;
        let (observed, channel) = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let started = now()?;
            require_window(&profile, &origin, started)?;
            let mut channel = slot.lock().map_err(|_| Error::Unavailable)?
                .take().ok_or(Error::Unavailable)?;
            if matches!(action, wire::Action::Admit) {
                if channel.execution_requested {
                    return Err(Error::CommitUncertain);
                }
                channel.execution_requested = true;
            }
            let id = channel.next;
            channel.next = id.checked_add(1).ok_or(Error::Unavailable)?;
            let request = wire::request(action, id, profile.binding, authorization);
            let bytes = serde_json::to_vec(&request).map_err(|_| Error::Unavailable)?;
            let response = channel.peer.request(&bytes).map_err(|_| Error::CommitUncertain)?;
            if response.len() > wire::BOUND {
                return Err(Error::WrongScope);
            }
            let response: wire::Response = serde_json::from_slice(&response)
                .map_err(|_| Error::CommitUncertain)?;
            if response.schema != 3 || response.operation != wire::OPERATION
                || response.request_id != id || response.profile != profile.binding.to_string()
                || response.authorization != authorization.to_string()
            {
                return Err(Error::WrongScope);
            }
            // Peer lifetime is the last process I/O. Signature and intent
            // windows are rechecked after it, without replacing original times.
            channel.peer.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
            let fresh = now()?;
            if fresh < started {
                return Err(Error::Unavailable);
            }
            require_window(&profile, &origin, fresh)?;
            let observed = wire::decode_current(response.result, &profile, &verifier, fresh / 1_000)?;
            wire::require_original_prefix(&channel.retained, &observed)?;
            if let Some(snapshot) = &observed.snapshot {
                channel.retained = Some((snapshot.clone(), observed.attestations.clone()));
            }
            Ok((observed, channel))
        }).await.map_err(|_| Error::CommitUncertain)??;
        // If this await was cancelled, the returned channel is dropped with
        // the unobserved JoinHandle result. It is never silently restored.
        let fresh = now()?;
        require_window(&self.profile, &self.origin, fresh)?;
        if let Some(snapshot) = &observed.snapshot {
            authentication::verify_attestations(
                &self.profile, &self.verifier, snapshot, &observed.attestations, fresh / 1_000,
            )?;
        }
        *self.channel.lock().map_err(|_| Error::Unavailable)? = Some(channel);
        Ok(observed)
    }
}

impl RootResidentLearningHandleV3 {
    /// Run on the original host's bounded blocking lane. The consumer peer is
    /// the actual A/authorized successor process, independently pinned at this
    /// connection. Role-host peers inside the resident bundle are Root's own
    /// UID/PID and are not copied from this A transport.
    pub fn serve_original_stream(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        held_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<(), Error> {
        if consumer_uid == 0 {
            return Err(Error::WrongScope);
        }
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, held_consumer_pidfd, timeout, lifetime,
        ).map_err(|_| Error::Unavailable)?;
        let mut next = 1_u64;
        while channel.exchange(|bytes| {
            let request: wire::Request = serde_json::from_slice(bytes)
                .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::InvalidRequest)?;
            if bytes.len() > wire::BOUND || request.schema != 3
                || request.operation != wire::OPERATION || request.request_id != next
                || request.profile != self.profile.binding.to_string()
                || request.authorization != self.authorization_binding.to_string()
                || (self.readonly && matches!(request.action, wire::Action::Admit))
            {
                return Err(codex_hepta_contracts::HostIssuerTransportError::InvalidRequest);
            }
            next = next.checked_add(1)
                .ok_or(codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
            let mode = match request.action {
                wire::Action::Admit => ResidentRequestModeV3::Admit,
                wire::Action::Readback => ResidentRequestModeV3::Readback,
            };
            let result = match self.runtime.block_on(self.request(mode)) {
                Ok(observation) => wire::encode_current(observation)
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?,
                Err(Error::CommitUncertain) => wire::Reply::Uncertain,
                Err(_) => wire::Reply::Unavailable,
            };
            let response = serde_json::to_vec(&wire::Response {
                schema: 3, operation: wire::OPERATION.into(), request_id: request.request_id,
                profile: request.profile, authorization: request.authorization, result,
            }).map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)?;
            if response.len() > wire::BOUND {
                return Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable);
            }
            Ok(response)
        }).map_err(|_| Error::Unavailable)? {}
        Ok(())
    }
}

fn artifacts<'a>(
    profile: &'a RootResidentLearningProfileV3,
    origin: &'a ClientOriginV3,
) -> (&'a codex_hepta_contracts::SignedFinalUseGrant,
      &'a codex_hepta_contracts::authority_lease::AuthorityLease)
{
    match origin {
        ClientOriginV3::Fresh => (&profile.intent, &profile.lease),
        ClientOriginV3::Readback(authorization) => (&authorization.intent, &authorization.lease),
    }
}

fn require_window(
    profile: &RootResidentLearningProfileV3,
    origin: &ClientOriginV3,
    now: u64,
) -> Result<(), Error> {
    let (intent, lease) = artifacts(profile, origin);
    if now < intent.grant.not_before_unix_ms || now >= intent.grant.expires_at_unix_ms
        || now < lease.issued_at_unix_ms || now >= lease.expires_at_unix_ms
    {
        return Err(Error::Unavailable);
    }
    Ok(())
}

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Unavailable)?.as_millis().try_into()
        .map_err(|_| Error::Unavailable)
}
