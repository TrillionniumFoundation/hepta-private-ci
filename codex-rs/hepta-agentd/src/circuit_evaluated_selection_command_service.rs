//! The one original evaluated Selector serves separate command and evidence
//! purposes. Custody, actual task peer, T/B clients and their deadlines stay put.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

use super::Context;
use super::Error;
use super::now;
use super::require_clock;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "circuit_evaluated_selection_command_evidence.rs"]
mod evidence;

pub struct OriginalCircuitEvaluatedSelectionCommandOwnerV1<W: AnchorWitnessStore> {
    owner: Mutex<OriginalCircuitSelectionReceiptOwnerV1<W>>,
    live: OriginalCircuitLearningReadClientV1,
    trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    context: Context,
    initial_head: Digest32,
    binding: Digest32,
    retained: Mutex<Option<OriginalCircuitEvaluatedSelectionReceiptV1>>,
    execution_requested: AtomicBool,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitEvaluatedSelectionCommandOwnerV1<W> {
    /// Only the original receipt owner's consuming factory calls this. Its
    /// private brand determines whether Execute is possible, never a caller tag.
    pub(crate) fn from_original_receipt_owner(
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
        evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    ) -> Result<Self, Error> {
        let context = Context::from_original(
            OriginalCircuitSelectionReceiptOwnerV1::original_evaluated_command_context(&owner)?,
        )?;
        let (_, readback_only) =
            OriginalCircuitSelectionReceiptOwnerV1::original_command_profile(&owner);
        OriginalCircuitLearningReadClientV1::require_original_evaluated_selection(
            &live,
            &context.original,
        )
        .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let initial_head = context.initial()?.head_digest;
        let binding = context.binding(now()?)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            trainer,
            evaluator,
            context,
            initial_head,
            binding,
            retained: Mutex::new(None),
            execution_requested: AtomicBool::new(readback_only),
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// Original process-pinned framing retains the 30s command and 300s
    /// connection bounds. Every connection shares the same once bit and owner.
    pub async fn serve_commands(
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
            self.serve_command_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    /// The existing evidence purpose remains bounded to 500ms and has no
    /// Execute route. A prior actual command result supplies only immutable pins.
    pub async fn serve_evidence_readback(
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
            self.serve_evidence_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    fn serve_command_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.command_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    fn command_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        self.context.authenticate(started_at)?;
        let result = match request.action {
            wire::Action::Execute => {
                if self.execution_requested.swap(true, Ordering::AcqRel) {
                    wire::CommandResult::ReadbackRequired
                } else if now()?
                    >= self
                        .context
                        .original
                        .snapshot()
                        .request
                        .envelope
                        .expiry_unix_seconds
                {
                    wire::CommandResult::Expired
                } else {
                    self.original_response(wire::Action::Execute)?
                }
            }
            wire::Action::Readback => self.original_response(wire::Action::Readback)?,
        };
        let current = now()?;
        require_clock(started_at, current)?;
        self.context.authenticate(current)?;
        Ok(serde_json::to_vec(&wire::Response::from_request(
            &request, result,
        ))?)
    }

    fn original_response(&self, action: wire::Action) -> Result<wire::CommandResult, Error> {
        let completed = {
            let mut owner = match self.owner.try_lock() {
                Ok(owner) => owner,
                Err(_) => return Ok(wire::CommandResult::Busy),
            };
            let source = OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                snapshot: self.context.original.snapshot(),
                live: &self.live,
                trainer: &self.trainer,
                evaluator: &self.evaluator,
            };
            match action {
                wire::Action::Execute => self.runtime.block_on(
                    OriginalCircuitSelectionReceiptOwnerV1::attest_original_evaluated_remote_selection(
                        &mut owner, source,
                    ),
                ),
                wire::Action::Readback => self.runtime.block_on(
                    OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_remote_selection(
                        &mut owner, source,
                    ),
                ),
            }
        };
        match completed {
            Ok(original) => {
                let result = wire::encode_completed(&self.context, &original, now()?)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained
                    .as_ref()
                    .is_some_and(|saved| !wire::same_original(saved, &original))
                {
                    return Err(Error::CommitUncertain);
                }
                *retained = Some(original);
                Ok(result)
            }
            Err(error) => Ok(original_state(error)),
        }
    }
}

fn original_state(error: OriginalCircuitSelectionReceiptErrorV1) -> wire::CommandResult {
    use LearningOriginalOwnerErrorV1 as Owner;
    use OriginalCircuitSelectionReceiptErrorV1 as Selection;
    use ProductEvaluationExecutionStoreErrorV1 as Store;
    match error {
        Selection::Owner(Owner::Pending) => wire::CommandResult::Pending,
        Selection::Owner(Owner::Store(Store::Missing)) => wire::CommandResult::Missing,
        // Signature/current failures can follow a durable claim. Never
        // reinterpret them as Missing, a fresh effect or TrainingNoUpdate.
        _ => wire::CommandResult::Uncertain,
    }
}

#[cfg(test)]
#[path = "circuit_evaluated_selection_command_support_tests.rs"]
pub(crate) mod command_test_support;
