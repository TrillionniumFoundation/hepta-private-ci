//! Original remote S custody becomes a read-only evidence host. It retains
//! the same T/B and original task read clients, with their existing deadlines.
//! There is no Cell writer, replacement stream, execute or signing entry.

use super::*;

use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitLearningReadClientV1;

pub struct OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1<W: AnchorWitnessStore> {
    owner: Mutex<OriginalCircuitSelectionReceiptOwnerV1<W>>,
    live: Arc<OriginalCircuitLearningReadClientV1>,
    trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    initial_head: Digest32,
    binding: Digest32,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static>
    OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1<W>
{
    pub(crate) fn from_original_receipt_owner(
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        live: Arc<OriginalCircuitLearningReadClientV1>,
        trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
        evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    ) -> Result<Self, Error> {
        let (config, _) = owner.original_command_profile();
        let (initial_head, binding) = binding::original_context(config, &selection)?;
        live.require_original_evaluated_selection(selection.original_context())
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            trainer,
            evaluator,
            selection,
            initial_head,
            binding,
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

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
                OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_remote_selection(
                    &mut owner,
                    OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                        snapshot: self.selection.snapshot(),
                        live: &self.live,
                        trainer: &self.trainer,
                        evaluator: &self.evaluator,
                    },
                ),
            )?
        };
        binding.after_read(request, started_at, original)
    }
}

#[cfg(test)]
#[path = "circuit_evaluated_selection_remote_readback_support_tests.rs"]
mod test_support;
