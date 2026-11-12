//! Read the original Selector without its execution surface or legacy 500-ms
//! evidence budget. The distinct operation cannot enter the command dispatcher.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::readonly;
use super::super::wire;
use super::Error;
use super::OriginalCircuitSelectionCommandOwnerV1;
use super::now;
use super::original_state;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::OriginalCircuitSelectionRemoteSourcesV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionCommandOwnerV1<W> {
    pub async fn serve_original_selection_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            self.serve_original_selection_readback_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(in crate::learning_iteration_evidence_client::selection_command) fn
        serve_original_selection_readback_channel(
            &self,
            channel: &mut HostAuthorityPeerChannel,
        ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.original_selection_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    fn original_selection_readback_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let request: wire::Request = serde_json::from_slice(bytes)?;
        readonly::require_request(&request, &self.context, request_id, now()?)?;
        let completed = {
            let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
            let original: &mut OriginalCircuitSelectionReceiptOwnerV1<W> = &mut owner;
            self.runtime.block_on(OriginalCircuitSelectionReceiptOwnerV1::readback_remote(
                original,
                OriginalCircuitSelectionRemoteSourcesV1 {
                    snapshot: &self.context.training,
                    live: &self.live,
                    trainer: &self.trainer,
                },
            ))
        };
        // All Cell/Trainer/Selector owner locks are released before encoding
        // or writing a response. No branch can attest or publish a selection.
        let result = match completed {
            Ok((receipt, signature)) =>
                wire::encode_completed(&self.context, receipt, signature, now()?)?,
            Err(error) => original_state(error),
        };
        self.context.authenticate(now()?)?;
        Ok(serde_json::to_vec(&wire::Response::from_request(&request, result))?)
    }
}
