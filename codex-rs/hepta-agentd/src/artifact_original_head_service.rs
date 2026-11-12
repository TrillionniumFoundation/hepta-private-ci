//! Native HEAD command service. Context checks precede the one owner-wide
//! admission. The server never accepts material, private keys or a sign body.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalArtifactHeadOwnerV1;
use super::fresh;
use super::now;
use super::require_peer;
use super::source::QueueFence;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalArtifactHeadOwnerV1<W> {
    pub async fn serve_commands(
        self: &Arc<Self>, stream: UnixStream, consumer: LearningIterationEvidencePeerV1,
        original_consumer_pidfd: OwnedFd, timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        require_peer(&consumer, &self.source.config.writer_lease.producer_id)?;
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        // Construct the original channel and its absolute end before enqueue.
        let mut channel = original_owner_command_channel_v1(
            stream, AgentdRootAuthorityPeer { pid: consumer.pid, boot_id: consumer.boot_id,
                process_start_ticks: consumer.process_start_ticks },
            consumer.uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let binding = self.source.config.binding()?;
        let original = Arc::clone(self);
        let cancelled = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&cancelled));
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            for nonce in 1..=128 {
                if cancelled.load(Ordering::Acquire) { return Err(Error::Unavailable); }
                let mut failure = None;
                let exchanged = channel.exchange(|bytes| {
                    if cancelled.load(Ordering::Acquire) {
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    let result = (|| {
                        let started = now()?;
                        let request = wire::Request::decode(bytes, wire::Purpose::Head, nonce, binding)?;
                        original.source.config.authenticate_current(started)?;
                        let response = match request.action {
                            wire::Action::Sign => original.sign_original(&cancelled),
                            wire::Action::Readback => original.read_original(&cancelled),
                        };
                        original.source.config.authenticate_current(fresh(started)?)?;
                        match response {
                            Ok(signed) => request.response(wire::Status::Completed, &signed),
                            Err(Error::Missing) => request.response(wire::Status::Missing, &[]),
                            Err(Error::Pending) => request.response(wire::Status::Pending, &[]),
                            Err(Error::ReadbackRequired) => request.response(wire::Status::ReadbackRequired, &[]),
                            Err(error) => Err(error),
                        }
                    })();
                    result.map_err(|error| {
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
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(waiting);
        result
    }
}
