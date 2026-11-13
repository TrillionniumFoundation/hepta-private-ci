//! Same-process transport only, forwarding to the production Version admission
//! and serving path. These helpers create no C owner, S or T/E response.

use super::*;
use std::sync::atomic::AtomicBool;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(crate) async fn fixture_serve_original_evaluated_next_use(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        channel: HostAuthorityPeerChannel,
        readiness: bool,
    ) -> Result<u64, Error> {
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned().map_err(|_| Error::Busy)?;
        self.serve_original_evaluated_next_use_channel(
            selection,
            channel,
            permit,
            if readiness { NextUseReadPurpose::CompletionReadiness }
            else { NextUseReadPurpose::Readback },
        ).await
    }

    pub(crate) async fn fixture_require_original_evaluated_next_use(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        tokio::task::spawn_blocking(move || {
            self.build_original_evaluated_next_use_reader(selection).map(|_| ())
        }).await.map_err(|_| Error::CommitUncertain)?
    }

    /// The deadline probe only narrows the original Version's end. It invokes
    /// the same response/128-loop with real owners and an unchanged channel.
    /// Its extra test observation never supplies a successful wire response.
    pub(crate) async fn fixture_evaluated_next_use_deadline_probe(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        mut channel: HostAuthorityPeerChannel,
        already_expired: bool,
        response_observed: Arc<AtomicBool>,
    ) -> Result<u64, Error> {
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned().map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            channel.check_peer_lifetime()?;
            let reader = self.build_original_evaluated_next_use_reader(selection)?;
            let end = if already_expired {
                Instant::now()
            } else {
                Instant::now().checked_add(Duration::from_millis(250)).ok_or(Error::Clock)?
            }.min(self.end);
            reader.fixture_evaluated_next_use_deadline_channel(
                &mut channel, end, !already_expired, response_observed,
            ).map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))
        }).await.map_err(|_| Error::CommitUncertain)?
    }
}
