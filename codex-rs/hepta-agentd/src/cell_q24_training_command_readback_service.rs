//! Read-only Trainer endpoint over the original bounded command transport.
//! It never dispatches Execute or accesses bootstrap custody.

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
use super::OriginalCellQ24TrainingCommandOwnerV1;
use crate::AgentdRootAuthorityPeer;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingCommandOwnerV1<TW, RW>
{
    /// Deliver a separate stream for the fixed original-training.readback
    /// purpose. Transport admission precedes queuing; no deadline restarts.
    pub async fn serve_original_training_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            self.serve_original_training_readback_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(in crate::learning_iteration_evidence_client::training_command) fn serve_original_training_readback_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    pub(in crate::learning_iteration_evidence_client::training_command) fn original_training_readback_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let request: wire::Request = serde_json::from_slice(bytes)?;
        readonly::require_request(&request, &self.context, request_id)?;
        let completed = self
            .runtime
            .block_on(SourceBoundCellQ24TrainingStageV1::readback(
                &self.stage,
                &self.context.dataset,
            ));
        let result = self.completed_response(completed)?;
        Ok(serde_json::to_vec(&wire::Response::from_request(
            &request, result,
        ))?)
    }
}
