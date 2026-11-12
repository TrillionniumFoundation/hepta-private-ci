//! A deferred host may serve this purpose before T exists, but it may only
//! borrow Ready. Neither fresh nor cold Awaiting is bootstrapped by readback.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::Error;
use super::super::OriginalCellQ24TrainingBootstrapOwnerV1;
use super::super::OriginalCellQ24TrainingCommandErrorV1;
use super::super::OriginalCellQ24TrainingCommandOwnerV1;
use super::super::super::readonly;
use super::super::super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    /// A distinct purpose-bound stream, admitted while the original initial
    /// context exists. Waiting for T never renews its original session.
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
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            self.serve_original_training_readback_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::Uncertain)?
    }

    pub(in crate::learning_iteration_evidence_client::training_command) fn
        serve_original_training_readback_channel(
            &self,
            channel: &mut HostAuthorityPeerChannel,
        ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Uncertain)
    }

    fn original_training_readback_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let request: wire::Request =
            serde_json::from_slice(bytes).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        let initial = &self.config.material.initial;
        let canonical = |value: &str| -> bool {
            value.parse::<Digest32>()
                .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == value)
        };
        if request.schema != 1
            || request.operation != readonly::OPERATION
            || request.action != wire::Action::Readback
            || request.cancelled
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.operation_id != initial.request.operation_id.as_str()
            || request.actor_id != initial.owners.trainer.as_str()
            || request.scope_binding != self.config.material.scope.binding().to_string()
            || !canonical(&request.binding)
            || !canonical(&request.dataset_head)
        {
            return Err(Error::Binding("same original read-only Trainer bootstrap purpose"));
        }
        let result = match self.ready()? {
            Some(original) => {
                return Ok(OriginalCellQ24TrainingCommandOwnerV1::original_training_readback_response(
                    &original, bytes, request_id,
                )?);
            }
            // This describes the endpoint's admission, not the contents of a
            // file that this read-only request has not opened or recovered.
            None => wire::CommandResult::ReadbackRequired,
        };
        Ok(serde_json::to_vec(&wire::Response::from_request(&request, result))
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?)
    }
}
