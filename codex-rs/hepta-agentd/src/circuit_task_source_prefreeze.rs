//! One fixed Root Source lane from pre-freeze observation through the original
//! Material pair. Private aliases share its one channel, counter and deadline.
//! No raw payload constructor or Source-view getter is public.

use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::net::UnixStream;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_ledger::{LearningEvidenceVerifierV1, SignedLearningEvidenceV1};
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::{Digest32, StableId};
use crate::{AgentdIdentity, AgentdRootAuthorityPeer};
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use super::{CircuitTaskSourceReadbackV1, OriginalReadback};
use super::super::{CircuitTaskSourcePublicationV1, Error};
use super::material::{decode_current_root_payload, wire};

#[path = "circuit_task_source_prefreeze_context.rs"]
mod context;
pub use context::OriginalCircuitPrefreezeSourceRequestV1;

#[path = "circuit_task_source_prefreeze_client.rs"]
mod client;
pub use client::OriginalCircuitPrefreezeSourceV1;

#[path = "circuit_task_source_prefreeze_ready.rs"]
pub(crate) mod ready;

struct Channel {
    original: HostAuthorityPeerChannel,
    next: u64,
}

pub(super) struct Client {
    slot: Mutex<Option<Channel>>,
    request: Arc<OriginalCircuitPrefreezeSourceRequestV1>,
    evidence: SignedLearningEvidenceV1,
    verifier: LearningEvidenceVerifierV1,
    identity: AgentdIdentity,
    binding: Digest32,
    timeout: Duration,
    end: Instant,
}

impl CircuitTaskSourceReadbackV1<FileAnchorWitnessStore> {
    fn require_original_prefreeze_current(&self) -> Result<(), Error> {
        let OriginalReadback::RootPrefreeze(original) = &self.original else {
            return Err(Error::InvalidBinding);
        };
        original.require_current()
    }

    fn from_original_prefreeze_root_stream(
        stream: UnixStream, root: AgentdRootAuthorityPeer, root_pidfd: OwnedFd,
        request: Arc<OriginalCircuitPrefreezeSourceRequestV1>, evidence: SignedLearningEvidenceV1,
        verifier: LearningEvidenceVerifierV1, identity: AgentdIdentity,
        timeout: Duration, lifetime: Duration, startup_end: Instant,
    ) -> Result<Self, Error> {
        if timeout.is_zero() || timeout > wire::TIMEOUT
            || lifetime.is_zero() || lifetime > Duration::from_secs(300)
            || request.consumer.pid != std::process::id()
            || request.consumer_uid != rustix::process::getuid().as_raw()
            || request.consumer_uid != rustix::process::geteuid().as_raw()
            || request.source.scope.agent_id.as_str() != identity.agent_id.as_str()
        { return Err(Error::InvalidBinding); }
        let end = Instant::now() + lifetime;
        let startup_end = startup_end.min(end);
        if startup_end.checked_duration_since(Instant::now())
            .is_none_or(|remaining| remaining.is_zero() || remaining > Duration::from_secs(30))
        { return Err(Error::InvalidBinding); }
        let binding = request.require_evidence(&verifier, request.trust_distribution_digest,
            request.trust_generation, &evidence, now()?)?;
        let socket = stream.as_raw_fd();
        let mut original = original_owner_command_channel_v1(stream, root, /*uid*/ 0,
            root_pidfd, timeout, lifetime).map_err(|_| Error::Unavailable)?;
        // The authenticated original channel owns this fd throughout the wait.
        // Waiting sends no request and does not consume a new Source slot.
        ready::wait_original_source_first_frame(socket, startup_end)?;
        original.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        let expected = ready::frame(binding, request.nonce).map_err(|_| Error::InvalidBinding)?;
        let acknowledged = original.exchange(|bytes| {
            if bytes != expected { return Err(codex_hepta_contracts::HostIssuerTransportError::InvalidRequest); }
            Ok(expected.clone())
        }).map_err(|_| Error::CommitUncertain)?;
        if !acknowledged { return Err(Error::Unavailable); }
        wire::before(startup_end)?;
        original.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        if request.require_evidence(&verifier, request.trust_distribution_digest,
            request.trust_generation, &evidence, now()?)? != binding
        { return Err(Error::InvalidBinding); }
        wire::before(end)?;
        Ok(Self { original: OriginalReadback::RootPrefreeze(Arc::new(Client {
            slot: Mutex::new(Some(Channel { original, next: 2 })), request, evidence,
            verifier, identity, binding, timeout, end,
        })) })
    }
}

impl Client {
    pub(super) fn read_prefreeze(&self, identity: &AgentdIdentity, run: &StableId)
        -> Result<CircuitTaskSourcePublicationV1, Error>
    {
        if identity != &self.identity || run != &self.request.source.scope.run_id {
            return Err(Error::InvalidBinding);
        }
        let mut channel = self.slot.try_lock().map_err(|_| Error::Unavailable)?
            .take().ok_or(Error::Unavailable)?;
        let deadline = (Instant::now() + self.timeout).min(self.end);
        wire::before(deadline)?;
        self.require_current()?;
        let request = read_request(self.binding, self.request.nonce, channel.next)?;
        channel.next = channel.next.checked_add(1).ok_or(Error::Unavailable)?;
        let response = channel.original.request(&request).map_err(|_| Error::CommitUncertain)?;
        wire::before(deadline)?;
        let payload = wire::read_response(&request, &response)?;
        // The original decoder is reachable only after the fixed authenticated
        // exchange. It never constructs a Driver receipt or ledger authority.
        let observed = decode_current_root_payload(payload)?;
        self.request.require_publication(&observed)?;
        channel.original.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        self.require_current()?;
        let mut slot = self.slot.try_lock().map_err(|_| Error::Unavailable)?;
        wire::before(deadline)?;
        *slot = Some(channel);
        Ok(observed)
    }

    fn require_current(&self) -> Result<(), Error> {
        if self.request.require_evidence(&self.verifier, self.request.trust_distribution_digest,
            self.request.trust_generation, &self.evidence, now()?)? != self.binding
        { return Err(Error::InvalidBinding); }
        wire::before(self.end)
    }
}

pub(crate) fn read_request(binding: Digest32, nonce: [u8; 16], id: u64) -> Result<Vec<u8>, Error> {
    if binding.is_zero() || nonce == [0; 16] || !(1..=wire::LIMIT).contains(&id) {
        return Err(Error::InvalidBinding);
    }
    let mut bytes = b"HCPRERD1".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&nonce);
    bytes.extend_from_slice(&id.to_be_bytes());
    Ok(bytes)
}

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_secs())
        .map_err(|_| Error::Unavailable)
}

#[cfg(test)]
#[path = "circuit_task_source_prefreeze_support_tests.rs"]
pub(crate) mod test_support;
