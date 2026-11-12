//! Fixed read-only view of the same original Artifact writer. Every response
//! comes from its complete physical RegistryDurable read; no phase is advanced.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::OriginalArtifactRegistryDurableV1;
use codex_hepta_learning_artifacts::UntrustedArtifactRegistryDurableV1;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

use super::ArtifactHeadSigningConfigV1;
use super::Error;
use super::fresh;
use super::now;
use super::require_peer;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

/// Native host retains the exact writer instance; no path-based reopen API.
pub struct OriginalArtifactRegistrySourceOwnerV1 {
    writer: Arc<Mutex<LearningArtifactOwnerService>>,
    config: ArtifactHeadSigningConfigV1,
    binding: Digest32,
    connections: Arc<Semaphore>,
}

impl OriginalArtifactRegistrySourceOwnerV1 {
    pub fn from_original_writer(
        writer: Arc<Mutex<LearningArtifactOwnerService>>,
        config: ArtifactHeadSigningConfigV1,
    ) -> Result<Self, Error> {
        config.authenticate_current(now()?)?;
        let binding = config.binding()?;
        Ok(Self {
            writer,
            config,
            binding,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub async fn serve_reads(
        self: &Arc<Self>,
        stream: UnixStream,
        consumer: LearningIterationEvidencePeerV1,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        // The original Head identity was selected natively, not by a request.
        require_peer(&consumer, &self.config.signer_id)?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: consumer.pid,
                boot_id: consumer.boot_id,
                process_start_ticks: consumer.process_start_ticks,
            },
            consumer.uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        let original = Arc::clone(self);
        let cancelled = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&cancelled));
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            for nonce in 1..=128 {
                if cancelled.load(Ordering::Acquire) {
                    return Err(Error::Unavailable);
                }
                let mut failure = None;
                let exchanged = channel.exchange(|bytes| {
                    if cancelled.load(Ordering::Acquire) {
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    original.respond(bytes, nonce).map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })
                });
                match exchanged {
                    Ok(true) => {}
                    Ok(false) => return Ok(nonce - 1),
                    Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
                }
            }
            Err(Error::Unavailable)
        })
        .await
        .map_err(|_| Error::Unavailable)?;
        drop(waiting);
        result
    }

    fn respond(&self, bytes: &[u8], nonce: u64) -> Result<Vec<u8>, Error> {
        let started = now()?;
        let request = wire::Request::decode(bytes, wire::Purpose::Registry, nonce, self.binding)?;
        self.config.authenticate_current(started)?;
        let writer = self.writer.try_lock().map_err(|_| Error::Busy)?;
        let observed = LearningArtifactOwnerService::read_original_registry_durable(
            &writer,
            &self.config.publication,
        )?;
        drop(writer);
        // Encoding is pure. The original writer has already reread payload,
        // complete registry/checkpoint/CURRENT and the original writer lease.
        let encoded = OriginalArtifactRegistryDurableV1::encode_for_original_head_source(&observed, &self.config)?;
        let claims = UntrustedArtifactRegistryDurableV1::decode(&encoded, &self.config)?;
        claims.authenticate_current(&self.config, fresh(started)?)?;
        request.response(wire::Status::Completed, &encoded)
    }
}

pub(super) struct QueueFence(pub(super) Arc<AtomicBool>);
impl Drop for QueueFence {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next: u64,
    source_at: u64,
    subject: Option<Digest32>,
}

/// Opaque, purpose-bound native handoff. It cannot sign, advance a publication
/// or expose an untrusted observation as a public original-writer capability.
pub struct OriginalArtifactRegistrySourceClientV1 {
    pub(super) config: ArtifactHeadSigningConfigV1,
    binding: Digest32,
    channel: Mutex<Option<Channel>>,
    initial_at: u64,
}

impl OriginalArtifactRegistrySourceClientV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_writer_pidfd: OwnedFd,
        config: ArtifactHeadSigningConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started = now()?;
        require_peer(&peer, &config.writer_lease.producer_id)?;
        config.authenticate_current(started)?;
        let binding = config.binding()?;
        let channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_writer_pidfd,
            timeout,
            lifetime,
        )?;
        channel.check_peer_lifetime()?;
        let observed = fresh(started)?;
        config.authenticate_current(observed)?;
        Ok(Self {
            config,
            binding,
            initial_at: observed,
            channel: Mutex::new(Some(Channel {
                peer: channel,
                next: 1,
                source_at: 0,
                subject: None,
            })),
        })
    }

    pub(super) async fn read_current(
        self: &Arc<Self>,
    ) -> Result<UntrustedArtifactRegistryDurableV1, Error> {
        let original = Arc::clone(self);
        let cancelled = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&cancelled));
        let result = tokio::task::spawn_blocking(move || original.read_current_in_lane(&cancelled))
            .await
            .map_err(|_| Error::Unavailable)?;
        drop(waiting);
        result
    }

    /// Only native original HEAD code running in its blocking lane may call
    /// this direct exchange. It avoids a nested blocking-pool network wait.
    pub(super) fn read_current_in_lane(
        &self,
        cancelled: &AtomicBool,
    ) -> Result<UntrustedArtifactRegistryDurableV1, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Busy)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started = now()?;
        if started < self.initial_at || cancelled.load(Ordering::Acquire) {
            return Err(Error::Unavailable);
        }
        self.config.authenticate_current(started)?;
        let request = wire::Request::new(
            wire::Purpose::Registry,
            wire::Action::Readback,
            channel.next,
            self.binding,
        )?;
        channel.next = channel.next.checked_add(1).ok_or(Error::Unavailable)?;
        channel.peer.check_peer_lifetime()?;
        if cancelled.load(Ordering::Acquire) {
            return Err(Error::Unavailable);
        }
        let bytes = channel.peer.request(&request.encode())?;
        let payload = request.read_response(&bytes)?;
        let source = UntrustedArtifactRegistryDurableV1::decode(payload, &self.config)?;
        // This check may perform pidfd I/O. Full windows are checked afterward.
        channel.peer.check_peer_lifetime()?;
        let current = fresh(started)?;
        source.authenticate_current(&self.config, current)?;
        let binding = source.subject_binding(&self.config)?;
        if source.observed_unix_millis() < channel.source_at
            || channel.subject.is_some_and(|old| old != binding)
            || cancelled.load(Ordering::Acquire)
        {
            return Err(Error::CommitUncertain);
        }
        channel.source_at = source.observed_unix_millis();
        channel.subject = Some(binding);
        *self.channel.try_lock().map_err(|_| Error::Busy)? = Some(channel);
        Ok(source)
    }
}

#[cfg(test)]
#[path = "artifact_original_head_tests.rs"]
mod tests;
