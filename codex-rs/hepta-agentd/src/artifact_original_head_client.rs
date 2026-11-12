//! Keyless original-writer side of HEAD issuance. A Sign request consumes the
//! actual same-writer continuation. Unknown/Drop cannot recover that capability;
//! a separate readonly handoff can only observe the saved original signature.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::OriginalArtifactPreparedPublicationV1;
use codex_hepta_learning_artifacts::OriginalArtifactRegistryDurableV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::UntrustedArtifactRegistryDurableV1;
use codex_hepta_learning_artifacts::decode_artifact_head_bytes_v1;
use codex_hepta_types::Digest32;

use super::ArtifactHeadSigningConfigV1;
use super::Error;
use super::fresh;
use super::now;
use super::require_peer;
use super::source::QueueFence;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

enum Origin {
    Fresh,
    Readonly(Option<SignedCurrentArtifactHeadV1>),
}

/// Consumed at most once. There is no API to extract/reopen the original
/// channel, change its expiry, or derive a writer continuation from a reply.
pub struct OriginalArtifactHeadConnectionV1 {
    channel: HostAuthorityPeerChannel,
    config: ArtifactHeadSigningConfigV1,
    binding: Digest32,
    initial_at: u64,
    origin: Origin,
}

impl OriginalArtifactHeadConnectionV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_head_pidfd: OwnedFd,
        config: ArtifactHeadSigningConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind(
            stream,
            peer,
            original_head_pidfd,
            config,
            timeout,
            lifetime,
            Origin::Fresh,
        )
    }

    pub fn recover_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_head_pidfd: OwnedFd,
        config: ArtifactHeadSigningConfigV1,
        expected: Option<SignedCurrentArtifactHeadV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind(
            stream,
            peer,
            original_head_pidfd,
            config,
            timeout,
            lifetime,
            Origin::Readonly(expected),
        )
    }

    fn bind(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_head_pidfd: OwnedFd,
        config: ArtifactHeadSigningConfigV1,
        timeout: Duration,
        lifetime: Duration,
        origin: Origin,
    ) -> Result<Self, Error> {
        let started = now()?;
        require_peer(&peer, &config.signer_id)?;
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
            original_head_pidfd,
            timeout,
            lifetime,
        )?;
        channel.check_peer_lifetime()?;
        let initial_at = fresh(started)?;
        config.authenticate_current(initial_at)?;
        Ok(Self {
            channel,
            config,
            binding,
            initial_at,
            origin,
        })
    }

    pub async fn sign_original_registry(
        self,
        prepared: OriginalArtifactPreparedPublicationV1,
        cancelled: Arc<AtomicBool>,
    ) -> Result<
        (
            OriginalArtifactPreparedPublicationV1,
            SignedCurrentArtifactHeadV1,
        ),
        Error,
    > {
        if !matches!(&self.origin, Origin::Fresh) {
            return Err(Error::ReadbackRequired);
        }
        let original = prepared
            .registry_durable()
            .encode_for_original_head_source(&self.config)?;
        let claims = UntrustedArtifactRegistryDurableV1::decode(&original, &self.config)?;
        claims.require_unsigned_phase()?;
        // The continuation is moved into this one future, so cancellation or
        // any failed ACK drops it even if the signing host completed its claim.
        let signed = self.exchange(wire::Action::Sign, claims, cancelled).await?;
        Ok((prepared, signed))
    }

    pub async fn read_original_head(
        self,
        observed: &OriginalArtifactRegistryDurableV1,
    ) -> Result<SignedCurrentArtifactHeadV1, Error> {
        let bytes = observed.encode_for_original_head_source(&self.config)?;
        let source = UntrustedArtifactRegistryDurableV1::decode(&bytes, &self.config)?;
        self.exchange(
            wire::Action::Readback,
            source,
            Arc::new(AtomicBool::new(false)),
        )
        .await
    }

    async fn exchange(
        mut self,
        action: wire::Action,
        source: UntrustedArtifactRegistryDurableV1,
        cancelled: Arc<AtomicBool>,
    ) -> Result<SignedCurrentArtifactHeadV1, Error> {
        let started = now()?;
        if started < self.initial_at {
            return Err(Error::CommitUncertain);
        }
        source.authenticate_current(&self.config, started)?;
        let request = wire::Request::new(wire::Purpose::Head, action, 1, self.binding)?;
        let encoded = request.encode();
        let abandoned = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&abandoned));
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            if abandoned.load(Ordering::Acquire) || cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            self.channel.check_peer_lifetime()?;
            if abandoned.load(Ordering::Acquire) || cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            let bytes = self
                .channel
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((self, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        drop(waiting);
        let payload = request.read_response(&bytes).map_err(|error| {
            if action == wire::Action::Sign {
                Error::CommitUncertain
            } else {
                error
            }
        })?;
        let signed = decode_artifact_head_bytes_v1(payload)?;
        channel.channel.check_peer_lifetime()?;
        let current = fresh(started)?;
        channel
            .config
            .verify_original_head(&source, &signed, current)?;
        if let Origin::Readonly(Some(expected)) = channel.origin
            && expected != signed
        {
            return Err(Error::CommitUncertain);
        }
        Ok(signed)
    }
}
