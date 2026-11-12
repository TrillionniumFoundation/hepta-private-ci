//! Private fixture access to the actual command and one issuer worker.
//! No fixture constructs a host phase or bypasses its original current reads.
use super::super::super::evaluated_wire::VersionRequest;
use super::super::super::evaluated_wire::decode_result;
use super::super::super::wire;
use super::*;

#[path = "circuit_evaluated_version_progress_support_tests.rs"]
mod evaluated_progress;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(crate) async fn prepare_original_version_fixture(
        self: Arc<Self>,
    ) -> Result<super::super::super::OriginalCircuitRetainedVersionReadbackV1, Error> {
        self.original_version_fixture_request(wire::Action::Prepare)
            .await
    }

    pub(crate) async fn read_original_version_fixture(
        self: Arc<Self>,
    ) -> Result<super::super::super::OriginalCircuitRetainedVersionReadbackV1, Error> {
        self.original_version_fixture_request(wire::Action::Readback)
            .await
    }

    async fn original_version_fixture_request(
        self: Arc<Self>,
        action: wire::Action,
    ) -> Result<super::super::super::OriginalCircuitRetainedVersionReadbackV1, Error> {
        tokio::task::spawn_blocking(move || {
            let (request, pin) = {
                let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
                self.bind_original_predecessor(&mut state)?;
                let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
                (
                    VersionRequest::new(cut, 1, action),
                    cut.duplicate_response_pin(),
                )
            };
            let response = self.command_response(&request.encode()?, 1)?;
            decode_result(request.decode_response(&response)?, &pin)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(crate) async fn run_original_issuer_fixture(self: Arc<Self>) -> Result<(), Error> {
        Self::serve_original_final_use(self).await
    }

    /// Consume only the installed fresh runtime configuration, using the same
    /// once flag/current/FinalUse gates as run_original_c. No new owner opens.
    pub(crate) async fn take_original_installed_c_fixture(
        self: Arc<Self>,
    ) -> Result<
        (
            crate::AgentdConfig,
            crate::PublishedCircuitCellOwnerV1<codex_hepta_neuron::FileAnchorWitnessStore>,
            Arc<crate::CircuitTaskSourceReadbackV1<codex_hepta_neuron::FileAnchorWitnessStore>>,
            crate::PublishedCircuitFeatureTaskV1,
        ),
        Error,
    > {
        use super::super::super::RetainedVersionOriginV1;
        use super::super::RetainedVersionHostPhaseV1;
        if self.origin != RetainedVersionOriginV1::Fresh
            || self.runtime_started.swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        tokio::task::spawn_blocking(move || {
            self.require_lifetime()?;
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            self.read_original(&state)?;
            if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published {
                return Err(Error::CommitUncertain);
            }
            state
                .cut
                .as_ref()
                .ok_or(Error::Unavailable)?
                .require_fresh(super::super::super::now()?, PublicationAccess::NewWork)?;
            let Some(RetainedVersionHostPhaseV1::Installed { original, config }) =
                state.phase.as_mut()
            else {
                return Err(Error::ReadbackRequired);
            };
            Ok((
                config.take().ok_or(Error::ReadbackRequired)?,
                original.cell.clone(),
                Arc::clone(&original.source),
                original.cell.task.clone(),
            ))
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }
}
