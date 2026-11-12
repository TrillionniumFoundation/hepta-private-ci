//! The one original Selector owner serves command and existing readback purpose.
//! Every read calls the original owner, full Model/E and actual version peers. No signature
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
use super::OriginalCircuitCandidateLearningReadContextV1;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24ModelCommandClientV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use crate::OriginalCircuitCandidateLearningReadClientV1;
use crate::OriginalCircuitModelSelectionReceiptErrorV1;
use crate::OriginalCircuitModelSelectionReceiptOwnerV1;
use crate::circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionRemoteSourcesV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "circuit_model_selection_command_evidence.rs"]
mod evidence;

pub struct OriginalCircuitModelSelectionCommandOwnerV1<W: AnchorWitnessStore> {
    owner: Mutex<OriginalCircuitModelSelectionReceiptOwnerV1<W>>,
    live: OriginalCircuitCandidateLearningReadClientV1,
    model: OriginalCellQ24ModelCommandClientV1,
    context: OriginalCircuitCandidateLearningReadContextV1,
    initial_head: Digest32,
    binding: Digest32,
    execution_requested: AtomicBool,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitModelSelectionCommandOwnerV1<W> {
    /// Only the original receipt owner's consuming method calls this factory.
    /// Its private creation/recovery brand determines admission; the caller
    /// cannot supply a boolean to promote a recovered owner into execution.
    pub(crate) fn from_original_receipt_owner(
        owner: OriginalCircuitModelSelectionReceiptOwnerV1<W>,
        context: OriginalCircuitCandidateLearningReadContextV1,
        model: OriginalCellQ24ModelCommandClientV1,
        live: OriginalCircuitCandidateLearningReadClientV1,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        wire::require_selection_context(&context, started_at)?;
        let (config, readback_only) =
            OriginalCircuitModelSelectionReceiptOwnerV1::original_command_profile(&owner);
        let publication = context.model_publication_context();
        if &config.decision != context.decision()
            || &config.scope != context.scope()
            || config.verifier.trust_digest() != context.verifier().trust_digest()
            || config.verifier.scope_digest() != context.verifier().scope_digest()
            || config.verifier.objective_digest() != context.verifier().objective_digest()
            || config.training_evidence != publication.signatures()[2]
            || config.evaluation_evidence != publication.signatures()[3]
        {
            return Err(Error::Binding("same original Model Selector owner profile"));
        }
        live.require_original_context(&context)?;
        let initial = LearningIterationCoordinatorV1::new(
            context.decision().request.clone(), context.decision().owners.clone(),
        )?;
        let binding = context.binding(started_at)?;
        let runtime = Handle::try_current().map_err(|_| Error::Unavailable)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            model,
            context,
            initial_head: initial.snapshot().head_digest,
            binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// The original host runs all blocking command work on a bounded lane.
    /// The existing framer keeps a complete command at <=30 seconds and the
    /// original connection at <=300 seconds; no deadline is renewed per frame.
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

    /// C uses the existing evidence purpose and unchanged 500 ms exchange bound.
    /// This endpoint always performs original readback_remote and cannot attest.
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
            return Err(Error::Binding("original Selector evidence exchange limit"));
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
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original positive Selector request"));
        }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        self.context.authenticate(now()?)?;
        let result = match request.action {
            wire::Action::Execute => {
                if self.execution_requested.swap(/*val*/ true, Ordering::AcqRel) {
                    wire::CommandResult::ReadbackRequired
                } else if now()? >= self.context.decision().request.envelope.expiry_unix_seconds {
                    wire::CommandResult::Expired
                } else {
                    self.original_response(/*execute*/ true)?
                }
            }
            wire::Action::Readback => self.original_response(/*execute*/ false)?,
        };
        // Original owner guard is released only after full Model/E closure and
        // both physical Selector journal reads. No retained response is reused.
        self.context.authenticate(now()?)?;
        let encoded = serde_json::to_vec(&wire::Response::from_request(&request, result))?;
        if encoded.is_empty() || encoded.len() > 16_384 {
            return Err(Error::Binding("bounded original positive Selector response"));
        }
        Ok(encoded)
    }

    fn original_response(&self, execute: bool) -> Result<wire::CommandResult, Error> {
        let completed = {
            let mut owner = match self.owner.try_lock() {
                Ok(owner) => owner,
                Err(_) => return Ok(wire::CommandResult::Busy),
            };
            let original: &mut OriginalCircuitModelSelectionReceiptOwnerV1<W> = &mut owner;
            let source = OriginalCircuitModelSelectionRemoteSourcesV1 {
                context: &self.context,
                model: &self.model,
                live: &self.live,
            };
            if execute {
                self.runtime.block_on(
                    OriginalCircuitModelSelectionReceiptOwnerV1::attest_original_remote_selection(
                        original, source,
                    ),
                )
            } else {
                self.runtime
                    .block_on(OriginalCircuitModelSelectionReceiptOwnerV1::readback_remote(
                        original, source,
                    ))
            }
        };
        match completed {
            Ok((receipt, signed)) => wire::encode_completed(&self.context, receipt, signed, now()?),
            Err(error) => Ok(original_state(error)),
        }
    }
}

fn original_state(error: OriginalCircuitModelSelectionReceiptErrorV1) -> wire::CommandResult {
    use LearningOriginalOwnerErrorV1 as Owner;
    use OriginalCircuitModelSelectionReceiptErrorV1 as Selection;
    use ProductEvaluationExecutionStoreErrorV1 as Store;
    match error {
        Selection::Owner(Owner::Pending) => wire::CommandResult::Pending,
        Selection::Owner(Owner::Store(Store::Missing)) => wire::CommandResult::Missing,
        // An observation, signature or CURRENT failure can follow a durable
        // claim. Never infer Missing, a fresh selection, or TrainingNoUpdate.
        _ => wire::CommandResult::Uncertain,
    }
}

