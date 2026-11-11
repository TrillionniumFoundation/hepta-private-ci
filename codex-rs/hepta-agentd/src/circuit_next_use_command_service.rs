//! The one original C Observer owner serves command and existing readback purpose.
//! Every read calls the original owner and its task/Trainer peers. No signature
//! cache, writer reopen, owner clone, public callback or key extraction exists.

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

use super::Error;
use super::OriginalCircuitNextUseCommandContextV1;
use super::now;
use super::require_clock;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitNextUseRemoteSourcesV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "circuit_next_use_command_evidence.rs"]
mod evidence;

pub struct OriginalCircuitNextUseCommandOwnerV1<W: AnchorWitnessStore> {
    owner: Mutex<OriginalCircuitNextUseReceiptOwnerV1<W>>,
    live: OriginalCircuitLearningReadClientV1,
    trainer: LearningIterationEvidenceClientV1,
    selector: LearningIterationEvidenceClientV1,
    context: OriginalCircuitNextUseCommandContextV1,
    initial_head: Digest32,
    binding: Digest32,
    execution_requested: AtomicBool,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitNextUseCommandOwnerV1<W> {
    /// Only the original receipt owner's consuming method calls this factory.
    /// Its private creation/recovery brand determines admission; the caller
    /// cannot supply a boolean to promote a recovered owner into execution.
    pub(crate) fn from_original_receipt_owner(
        owner: OriginalCircuitNextUseReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        trainer: LearningIterationEvidenceClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<Self, Error> {
        let (config, readback_only) =
            OriginalCircuitNextUseReceiptOwnerV1::original_command_profile(&owner);
        let context = OriginalCircuitNextUseCommandContextV1::from_checkpoint(
            config.selection.clone(), config.scope.clone(), config.verifier.clone(),
            config.training_evidence.clone(), config.selection_evidence.clone(),
        )?;
        OriginalCircuitLearningReadClientV1::require_original_context(
            &live, &context.selection, &context.scope, &context.verifier,
            &context.training_evidence, Some(&context.selection_evidence),
        ).map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        let initial = context.initial()?;
        if trainer.initial != initial || trainer.actor_id != context.selection.owners.trainer
            || trainer.verifier.trust_digest() != context.verifier.trust_digest()
            || trainer.verifier.scope_digest() != context.verifier.scope_digest()
            || trainer.verifier.objective_digest() != context.verifier.objective_digest()
        {
            return Err(Error::Binding("same original Trainer readback capability"));
        }
        if selector.initial != initial || selector.actor_id != context.selection.owners.selector
            || selector.verifier.trust_digest() != context.verifier.trust_digest()
            || selector.verifier.scope_digest() != context.verifier.scope_digest()
            || selector.verifier.objective_digest() != context.verifier.objective_digest()
        {
            return Err(Error::Binding("same original Selector readback capability"));
        }
        let binding = context.binding(now()?)?;
        let runtime = Handle::try_current().map_err(|_| Error::Unavailable)?;
        Ok(Self {
            owner: Mutex::new(owner), live, trainer, selector, context,
            initial_head: initial.head_digest, binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime, connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// The original host runs all blocking command work on a bounded lane.
    /// The existing framer keeps a complete command at <=30 seconds and the
    /// original connection at <=300 seconds; no deadline is renewed per frame.
    pub async fn serve_commands(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
            )?;
            self.serve_command_channel(&mut channel)
        }).await.map_err(|_| Error::CommitUncertain)?
    }

    /// The existing evidence purpose retains its unchanged 500 ms exchange bound.
    /// This endpoint always performs original readback_remote and cannot attest.
    pub async fn serve_evidence_readback(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding("original C Observer evidence exchange limit"));
        }
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
            )?;
            self.serve_evidence_channel(&mut channel)
        }).await.map_err(|_| Error::CommitUncertain)?
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
                } else if now()? >= self.context.selection.request.envelope.expiry_unix_seconds {
                    wire::CommandResult::Expired
                } else {
                    self.original_response(true)?
                }
            }
            wire::Action::Readback => self.original_response(false)?,
        };
        // Original owner guard has been released before encoding and writing.
        let current = now()?;
        require_clock(started_at, current)?;
        self.context.authenticate(current)?;
        Ok(serde_json::to_vec(&wire::Response::from_request(&request, result))?)
    }

    fn original_response(&self, execute: bool) -> Result<wire::CommandResult, Error> {
        let completed = {
            let mut owner = match self.owner.try_lock() {
                Ok(owner) => owner,
                Err(_) => return Ok(wire::CommandResult::Busy),
            };
            let original: &mut OriginalCircuitNextUseReceiptOwnerV1<W> = &mut owner;
            let source = OriginalCircuitNextUseRemoteSourcesV1 {
                snapshot: &self.context.selection, live: &self.live, trainer: &self.trainer,
                selector: &self.selector,
            };
            if execute {
                self.runtime.block_on(
                    OriginalCircuitNextUseReceiptOwnerV1::attest_original_remote_completion(
                        original, source,
                    ),
                )
            } else {
                self.runtime.block_on(
                    OriginalCircuitNextUseReceiptOwnerV1::readback_remote(original, source),
                )
            }
        };
        match completed {
            Ok((receipt, signed)) => {
                wire::encode_completed(&self.context, receipt, signed, now()?)
            }
            Err(error) => Ok(original_state(error)),
        }
    }


}

fn original_state(error: OriginalCircuitNextUseReceiptErrorV1) -> wire::CommandResult {
    use LearningOriginalOwnerErrorV1 as Owner;
    use OriginalCircuitNextUseReceiptErrorV1 as Observer;
    use ProductEvaluationExecutionStoreErrorV1 as Store;
    match error {
        Observer::Owner(Owner::Pending) => wire::CommandResult::Pending,
        Observer::Owner(Owner::Store(Store::Missing)) => wire::CommandResult::Missing,
        // An observation, signature or CURRENT failure can follow a durable
        // claim. Never infer Missing, a fresh selection, or TrainingNoUpdate.
        _ => wire::CommandResult::Uncertain,
    }
}

#[cfg(test)]
#[path = "circuit_next_use_command_support_tests.rs"]
pub(crate) mod command_test_support;
