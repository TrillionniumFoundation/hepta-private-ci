//! Explicit same-process server transport only; the real Version producer
//! still consumes this channel, checks actual D/T/B/S and reads its own C.
use super::*;
use crate::learning_iteration_evidence_client::command_test_support;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

impl OriginalCircuitEvaluatedReadinessChannelV1 {
    pub(crate) fn fixture_original_stream(stream: UnixStream) -> anyhow::Result<Self> {
        let channel = HostAuthorityPeerChannel::from_stream(
            stream,
            HostAuthorityPeerPolicy {
                // SAFETY: this fixture admits only its own live UID/process.
                peer: HostIssuerPeer {
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_millis(500),
                lifetime: Duration::from_secs(300),
                request_bound: 16_384,
                response_bound: 16_384,
            },
            command_test_support::pidfd()?,
        )?;
        Ok(Self { channel })
    }
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// Only an event tells the test consumer that actual bootstrap completed.
    /// Both paths call the same original preparation and bounded serving loop;
    /// this does not skip a read, wait by sleeping or restart either deadline.
    pub(crate) async fn fixture_synchronized_evaluated_readiness(
        self: Arc<Self>,
        original: OriginalCircuitEvaluatedReadinessChannelV1,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        ready: tokio::sync::oneshot::Sender<()>,
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
            ready.send(()).map_err(|_| Error::Cancelled)?;
            self.serve_evaluated_readiness_frames(&mut channel, &reader, &cancelled)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }
}
