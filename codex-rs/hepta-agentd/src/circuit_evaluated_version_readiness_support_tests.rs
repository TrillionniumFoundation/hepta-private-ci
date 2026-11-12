//! Test transport access to the actual Version selection-serving loop.
//! No phase, reader, outcome, grant or original-owner result is constructed.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(crate) fn fixture_original_final_use_uncertain(&self) -> bool {
        self.original_final_use_outcome() == RetainedVersionFinalUseOutcomeV1::Uncertain
    }

    /// The caller has already completed a real cold read. Construct its next
    /// original wire request from that held pin, without a fixture-side current
    /// read that could hide the production command's failure branch.
    pub(crate) async fn fixture_read_bound_original_version(
        self: Arc<Self>,
    ) -> Result<super::super::super::OriginalCircuitRetainedVersionReadbackV1, Error> {
        tokio::task::spawn_blocking(move || {
            let (request, pin) = {
                let state = self.state.try_lock().map_err(|_| Error::Busy)?;
                let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
                (wire::Request::new(cut, 1, wire::Action::Readback), cut.duplicate_response_pin())
            };
            let response = self.command_response(&serde_json::to_vec(&request)?, 1)?;
            let response: wire::Response = serde_json::from_slice(&response)?;
            if response.request != request {
                return Err(Error::CommitUncertain);
            }
            response.result.decode(&pin)
        }).await.map_err(|_| Error::CommitUncertain)?
    }

    pub(crate) fn fixture_original_selection_reader_installed(&self) -> Result<bool, Error> {
        let state = self.state.try_lock().map_err(|_| Error::Busy)?;
        Ok(state.selection_reader.is_some())
    }

    pub(crate) async fn fixture_serve_original_selection_channel(
        self: Arc<Self>,
        channel: HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned().map_err(|_| Error::Busy)?;
        self.serve_original_selection_channel(channel, permit).await
    }
}
