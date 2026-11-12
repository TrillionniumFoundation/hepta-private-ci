//! Private fixture access to the actual command and one issuer worker.
//! No fixture constructs a host phase or bypasses its original current reads.
use super::super::super::wire;
use super::*;

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
                    wire::Request::new(cut, 1, action),
                    cut.duplicate_response_pin(),
                )
            };
            let response = self.command_response(&serde_json::to_vec(&request)?, 1)?;
            let response: wire::Response = serde_json::from_slice(&response)?;
            if response.request != request {
                return Err(Error::CommitUncertain);
            }
            response.result.decode(&pin)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(crate) async fn run_original_issuer_fixture(self: Arc<Self>) -> Result<(), Error> {
        Self::serve_original_final_use(self).await
    }
}
