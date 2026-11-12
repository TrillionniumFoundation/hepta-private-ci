//! An unbound read-only connection to the same actual original E host.
//! Only same-process transport admission is a fixture; binding later consumes
//! the production Connection and its original monotonic channel lifetime.

use super::*;
use super::super::OriginalCellEvaluationCommandConnectionV1;
use super::super::Origin;

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_original_readback_connection(
        self: &Arc<Self>,
    ) -> anyhow::Result<(OriginalCellEvaluationCommandConnectionV1, Thread)> {
        self.fixture_original_readback_connection_before_response(|| Ok(()))
    }

    /// Fault scheduling only: the hook receives no wire payload and cannot
    /// return a receipt. Every response is still the actual original dispatch.
    pub(crate) fn fixture_original_readback_connection_before_response(
        self: &Arc<Self>,
        mut before_response: impl FnMut() -> anyhow::Result<()> + Send + 'static,
    ) -> anyhow::Result<(OriginalCellEvaluationCommandConnectionV1, Thread)> {
        let (client, server) = UnixStream::pair()?;
        let connection = OriginalCellEvaluationCommandConnectionV1 {
            channel: channel(client)?,
            initial: self.context.initial()?,
            scope: self.context.scope.clone(),
            registration: self.context.registration.clone(),
            verifier: self.context.verifier.clone(),
            origin: Origin::ReadbackOnly,
            observed_at: now()?,
        };
        let owner = Arc::clone(self);
        let mut peer = channel(server)?;
        let thread = std::thread::spawn(move || -> anyhow::Result<u64> {
            for request_id in 1..=128_u64 {
                let mut original_error = None;
                let exchanged = peer.exchange(|bytes| {
                    before_response().map_err(|error| {
                        original_error = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })?;
                    owner.fixture_command_response(bytes, request_id).map_err(|error| {
                        original_error = Some(error.into());
                        HostIssuerTransportError::InvalidRequest
                    })
                });
                match exchanged {
                    Ok(true) => {},
                    Ok(false) => return Ok(request_id - 1),
                    Err(error) => return Err(original_error.unwrap_or_else(|| error.into())),
                }
            }
            anyhow::bail!("bounded original E fixture");
        });
        Ok((connection, thread))
    }
}
