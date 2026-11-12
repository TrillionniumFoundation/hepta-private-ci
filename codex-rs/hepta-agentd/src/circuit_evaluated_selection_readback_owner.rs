//! Read-only evidence serving by the same evaluated Selector custody.
//! PublishedCircuitCellOwnerV1::clone shares its original Arc<Mutex<Journal>>
//! and sealed task; it supplies no CellStateOwner or reopened writer. The T/B
//! Arcs likewise share the publication's original connected clients.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptSourcesV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitEvaluatedSelectionReadbackErrorV1 {
    #[error("original evaluated Selector readback binding: {0}")]
    Binding(&'static str),
    #[error("original evaluated Selector readback unavailable")]
    Unavailable,
    #[error("original evaluated Selector readback occupied")]
    Busy,
    #[error("original evaluated Selector receipt: {0}")]
    Receipt(#[from] OriginalCircuitSelectionReceiptErrorV1),
    #[error("original evaluated Selector readback transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original evaluated Selector readback encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitEvaluatedSelectionReadbackErrorV1;

#[path = "circuit_evaluated_selection_readback_binding.rs"]
mod binding;
#[path = "circuit_evaluated_selection_remote_readback.rs"]
mod remote;
pub use remote::OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1;

#[path = "circuit_evaluated_selection_command.rs"]
mod command;
pub use command::OriginalCircuitEvaluatedSelectionCommandClientV1;
pub use command::OriginalCircuitEvaluatedSelectionCommandErrorV1;
pub use command::OriginalCircuitEvaluatedSelectionCommandOwnerV1;

#[cfg(test)]
pub(crate) use command::command_test_support;

pub struct OriginalCircuitEvaluatedSelectionReadbackOwnerV1<
    W: AnchorWitnessStore,
    C: AnchorWitnessStore,
> {
    owner: Mutex<OriginalCircuitSelectionReceiptOwnerV1<W>>,
    cell: PublishedCircuitCellOwnerV1<C>,
    trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    initial_head: Digest32,
    binding: Digest32,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static, C: AnchorWitnessStore + Send + 'static>
    OriginalCircuitEvaluatedSelectionReadbackOwnerV1<W, C>
{
    // Called only by the original Selector's consuming factory. There is no
    // fresh/cold flag, callback, new key or replacement journal in this API.
    pub(crate) fn from_original_receipt_owner(
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        cell: PublishedCircuitCellOwnerV1<C>,
        trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
        evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    ) -> Result<Self, Error> {
        let (config, _) = owner.original_command_profile();
        let (initial_head, binding) = binding::original_context(config, &selection)?;
        Ok(Self {
            owner: Mutex::new(owner),
            cell,
            trainer,
            evaluator,
            selection,
            initial_head,
            binding,
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// Only the established read-only evidence purpose is served. Each call
    /// resolves the original journal and its current T/B/Cell readbacks.
    pub async fn serve_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding(
                "original evaluated Selector evidence exchange limit",
            ));
        }
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            )?;
            self.serve_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::Unavailable)?
    }

    fn serve_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.evidence_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    fn evidence_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let binding = binding::ReadbackBinding::from_original_pins(
            &self.selection,
            self.initial_head,
            self.binding,
        );
        let (request, started_at) = binding.before_read(bytes, request_id)?;
        let original = {
            let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
            self.runtime.block_on(
                OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_selection(
                    &mut owner,
                    OriginalCircuitEvaluatedSelectionReceiptSourcesV1 {
                        snapshot: self.selection.snapshot(),
                        cell: &self.cell,
                        trainer: &self.trainer,
                        evaluator: &self.evaluator,
                    },
                ),
            )?
        };
        binding.after_read(request, started_at, original)
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|at| at.as_secs())
        .map_err(|_| Error::Binding("original evaluated Selector readback clock"))
}

#[cfg(test)]
#[path = "circuit_evaluated_selection_readback_support_tests.rs"]
mod test_support;
