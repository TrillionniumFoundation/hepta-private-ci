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
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
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
        selection.original_receipt_predecessors(now()?)?;
        let (config, _) = owner.original_command_profile();
        let (scope, verifier, training) = selection.original_context().receipt_configuration();
        if config.decision != *selection.original_context().snapshot()
            || config.scope.binding() != scope.binding()
            || config.verifier.trust_digest() != verifier.trust_digest()
            || config.verifier.scope_digest() != verifier.scope_digest()
            || config.verifier.objective_digest() != verifier.objective_digest()
            || config.training_evidence != training
            || config.signer.principal.principal_id != selection.receipt().actor_id
        {
            return Err(Error::Binding(
                "same original evaluated Selector readback context",
            ));
        }
        let initial = LearningIterationCoordinatorV1::new(
            selection.snapshot().request.clone(),
            selection.snapshot().owners.clone(),
        )
        .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let binding = selection.original_receipt_binding();
        Ok(Self {
            owner: Mutex::new(owner),
            cell,
            trainer,
            evaluator,
            selection,
            initial_head: initial.snapshot().head_digest,
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
        let request: wire::Request = serde_json::from_slice(bytes)?;
        let snapshot_head: Digest32 = request
            .snapshot_head
            .parse()
            .map_err(|_| Error::Binding("original evaluated Selector correlation head"))?;
        if request.schema != 1
            || request.operation != wire::OPERATION
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.binding != self.initial_head.to_string()
            || request.operation_id != self.selection.snapshot().request.operation_id.as_str()
            || request.actor_id != self.selection.snapshot().owners.selector.as_str()
            || request.predecessor != self.selection.receipt().predecessor.to_string()
            || request.receipt_digest != self.selection.attestation().payload_digest.to_string()
            || snapshot_head.is_zero()
            || request.snapshot_head != snapshot_head.to_string()
        {
            return Err(Error::Binding(
                "same original evaluated Selector evidence request",
            ));
        }
        let started_at = now()?;
        self.selection.original_receipt_predecessors(started_at)?;
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
        let current = now()?;
        original.original_receipt_predecessors(current)?;
        if current < started_at
            || original.snapshot() != self.selection.snapshot()
            || original.receipt() != self.selection.receipt()
            || original.attestation() != self.selection.attestation()
            || original.original_receipt_binding() != self.binding
        {
            return Err(Error::Binding(
                "unchanged original evaluated Selector result",
            ));
        }
        // snapshot_head is correlation only, as in the existing evidence wire.
        // C validates its full same-prefix history before it issues this read.
        Ok(serde_json::to_vec(&wire::Response {
            schema: 1,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: wire::Evidence::from_original(original.attestation()),
        })?)
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
