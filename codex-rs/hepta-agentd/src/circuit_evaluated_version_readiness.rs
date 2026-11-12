//! The original Version host exposes readiness from its own actual C owners.
//! This consumes a prebound server channel; no C owner or PublishedTask escapes.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::super::Error;
use super::super::profile::VersionCut;
use super::super::profile::VersionPurpose;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionHostPhaseV1;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCircuitEvaluatedLearningReadContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

type EvaluatedReadinessOwner =
    OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

/// Original server-side stream and pidfd, bound before the future S result.
/// The caller must transfer the original connected stream; there is no socket
/// discovery, client-side identity inference or extraction/rebinding method.
pub struct OriginalCircuitEvaluatedReadinessChannelV1 {
    channel: HostAuthorityPeerChannel,
}

impl OriginalCircuitEvaluatedReadinessChannelV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(Error::Binding("original evaluated readiness server bounds"));
        }
        let channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        Ok(Self { channel })
    }
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// The actual opaque S is checked against this host's complete T/B cut and
    /// actual installed C. Cold origins stay read-only. The server descriptor
    /// keeps the deadline established when the deployment originally bound it.
    pub async fn serve_original_evaluated_completion_readiness(
        self: Arc<Self>,
        original: OriginalCircuitEvaluatedReadinessChannelV1,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<u64, Error> {
        let permit = self.admit_original_readiness_server(&original)?;
        let queued = QueuedReadinessFence(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original.channel;
            require_not_cancelled(&cancelled)?;
            self.require_lifetime()?;
            channel.check_peer_lifetime()?;
            let reader = self.prepare_evaluated_readiness_reader(selection)?;
            self.serve_evaluated_readiness_frames(&mut channel, &reader, &cancelled)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    fn admit_original_readiness_server(
        &self,
        original: &OriginalCircuitEvaluatedReadinessChannelV1,
    ) -> Result<tokio::sync::OwnedSemaphorePermit, Error> {
        if self.purpose != VersionPurpose::Evaluated {
            return Err(Error::Binding(
                "original evaluated Version readiness purpose",
            ));
        }
        self.require_lifetime()?;
        original.channel.check_peer_lifetime()?;
        Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)
    }

    fn prepare_evaluated_readiness_reader(
        &self,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<EvaluatedReadinessOwner, Error> {
        let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
        self.bind_original_predecessor(&mut state)?;
        self.read_original(&state)?;
        let Some(VersionCut::Evaluated(cut)) = state.cut.as_ref() else {
            return Err(Error::Binding("original evaluated Version four-cut"));
        };
        selection
            .original_receipt_predecessors(super::super::now()?)
            .map_err(|_| Error::Binding("original evaluated readiness T/B/S signatures"))?;
        if selection.original_context().snapshot() != cut.evaluated.snapshot()
            || selection.original_context().receipt_context_binding()
                != cut.evaluated.receipt_context_binding()
        {
            return Err(Error::Binding(
                "same complete original Version T/B and Selection",
            ));
        }
        let original = match state.phase.as_ref() {
            Some(
                RetainedVersionHostPhaseV1::Installed { original, .. }
                | RetainedVersionHostPhaseV1::Recovered(original),
            ) => original,
            _ => return Err(Error::ReadbackRequired),
        };
        let context =
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection)
                .map_err(published_read)?;
        let reader = OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
            original.cell.clone(),
            original.source.as_ref().clone(),
            original.identity.clone(),
            context,
        )
        .map_err(published_read)?;
        // Last awaited T/B reads are followed by actual Source/Cell/CURRENT.
        // Neither the S pins nor a previous physical read substitute for it.
        self.read_original(&state)?;
        Ok(reader)
    }

    fn serve_evaluated_readiness_frames(
        &self,
        channel: &mut HostAuthorityPeerChannel,
        reader: &EvaluatedReadinessOwner,
        cancelled: &AtomicBool,
    ) -> Result<u64, Error> {
        for request_id in 1..=128 {
            require_not_cancelled(cancelled)?;
            self.require_lifetime()?;
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                let result = (|| {
                    require_not_cancelled(cancelled)?;
                    self.require_lifetime()?;
                    let response =
                        OriginalCircuitLearningReadOwnerV1::evaluated_readiness_response(
                            reader, bytes, request_id,
                        )
                        .map_err(published_read)?;
                    self.require_lifetime()?;
                    require_not_cancelled(cancelled)?;
                    Ok(response)
                })();
                result.map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::InvalidRequest
                })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(request_id - 1),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
        Err(Error::Unavailable)
    }
}

fn published_read(error: crate::OriginalCircuitLearningReadErrorV1) -> Error {
    Error::Owner(crate::AgentdError::Invalid(error.to_string()))
}

struct QueuedReadinessFence(Arc<AtomicBool>);
impl Drop for QueuedReadinessFence {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) {
        return Err(Error::Cancelled);
    }
    Ok(())
}

#[cfg(test)]
#[path = "circuit_evaluated_version_readiness_support_tests.rs"]
mod fixture;
