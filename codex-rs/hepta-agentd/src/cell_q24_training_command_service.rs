//! Original Trainer host producer. The same retained SourceBound Stage serves
//! command results and existing evidence readback; no owner or key is reopened.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
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
use super::OriginalCellQ24TrainingCommandContextV1;
use super::evidence_wire;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::OriginalCellQ24TrainingReceiptErrorV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "cell_q24_training_candidate_service.rs"]
mod candidate;

enum Admission {
    OriginalExecution,
    ReadbackOnly,
}

pub struct OriginalCellQ24TrainingCommandOwnerV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    stage: Arc<SourceBoundCellQ24TrainingStageV1<TW, RW>>,
    context: OriginalCellQ24TrainingCommandContextV1,
    initial_head: Digest32,
    binding: Digest32,
    cancellation: Arc<AtomicBool>,
    execution_requested: AtomicBool,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingCommandOwnerV1<TW, RW>
{
    /// Retain the same captured Stage facade and actual host cancellation.
    /// The original host can keep this same Arc for its four narrow Model
    /// handlers. The facade retains one semaphore, mutex and source identity;
    /// no native writer or key is cloned, reopened, exposed or reconstructed.
    /// This local sharing does not transfer custody across a UID boundary.
    pub async fn from_original_stage(
        stage: Arc<SourceBoundCellQ24TrainingStageV1<TW, RW>>,
        context: OriginalCellQ24TrainingCommandContextV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        Self::bind_original_stage(stage, context, cancellation, Admission::OriginalExecution).await
    }

    /// The host has recovered the same native and Generator owners first.
    /// Serving resumes readback only, including Missing and unresolved Pending;
    /// this path never sends execution to the Stage or renews a signature.
    pub async fn recover_original_stage(
        stage: Arc<SourceBoundCellQ24TrainingStageV1<TW, RW>>,
        context: OriginalCellQ24TrainingCommandContextV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        Self::bind_original_stage(stage, context, cancellation, Admission::ReadbackOnly).await
    }

    async fn bind_original_stage(
        stage: Arc<SourceBoundCellQ24TrainingStageV1<TW, RW>>,
        context: OriginalCellQ24TrainingCommandContextV1,
        cancellation: Arc<AtomicBool>,
        admission: Admission,
    ) -> Result<Self, Error> {
        let initial = context.validate()?;
        let binding = context.binding()?;
        SourceBoundCellQ24TrainingStageV1::require_original_command_context(
            &stage,
            &context.dataset,
            &context.scope,
        )
        .await?;
        Ok(Self {
            stage,
            context,
            initial_head: initial.head_digest,
            binding,
            cancellation,
            execution_requested: AtomicBool::new(matches!(admission, Admission::ReadbackOnly)),
            runtime: Handle::current(),
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// Serve only the fixed command purpose on this original connection.
    /// Four held connections bound blocking work; the original Stage still
    /// admits only one native lane. Every stream has one unextended lifetime.
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

    /// Preserve the old readback-only purpose and its 500 ms exchange limit.
    /// Requests identify an existing receipt, never a payload to sign. The
    /// returned bytes come from an actual Stage read every time, not a cache.
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
            return Err(Error::Binding("original evidence exchange limit"));
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
        let mut next_request_id = 1_u64;
        for count in 0..128_u64 {
            let exchanged = channel.exchange(|bytes| {
                self.command_response(bytes, next_request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })?;
            if !exchanged {
                return Ok(count);
            }
            next_request_id = next_request_id
                .checked_add(1)
                .ok_or(Error::Binding("Trainer request id overflow"))?;
        }
        Err(Error::Unavailable)
    }

    pub(super) fn command_response(
        &self,
        bytes: &[u8],
        next_request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, next_request_id)?;
        let result = match request.action {
            wire::Action::Execute => {
                if self.execution_requested.swap(true, Ordering::AcqRel) {
                    wire::CommandResult::ReadbackRequired
                } else if now()? >= self.context.dataset.request.envelope.expiry_unix_seconds {
                    wire::CommandResult::Expired
                } else {
                    if request.cancelled {
                        self.cancellation.store(true, Ordering::Release);
                    }
                    let completed =
                        self.runtime
                            .block_on(SourceBoundCellQ24TrainingStageV1::execute_training(
                                &self.stage,
                                &self.context.dataset,
                                Arc::clone(&self.cancellation),
                            ));
                    self.completed_response(completed)?
                }
            }
            wire::Action::Readback => {
                let completed = self
                    .runtime
                    .block_on(SourceBoundCellQ24TrainingStageV1::readback(
                        &self.stage,
                        &self.context.dataset,
                    ));
                self.completed_response(completed)?
            }
        };
        Ok(serde_json::to_vec(&wire::Response::from_request(
            &request, result,
        ))?)
    }

    fn completed_response(
        &self,
        completed: Result<
            crate::OriginalCellQ24TrainingCompletionV1,
            OriginalCellQ24TrainingStageErrorV1,
        >,
    ) -> Result<wire::CommandResult, Error> {
        match completed {
            Ok(completed) => wire::encode_completed(
                &self.context,
                completed.receipt,
                completed.attestation,
                now()?,
            ),
            Err(error) => Ok(original_state(error)),
        }
    }

    fn serve_evidence_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        let mut next_request_id = 1_u64;
        for count in 0..128_u64 {
            let exchanged = channel.exchange(|bytes| {
                self.evidence_response(bytes, next_request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })?;
            if !exchanged {
                return Ok(count);
            }
            next_request_id = next_request_id
                .checked_add(1)
                .ok_or(Error::Binding("Trainer evidence request id overflow"))?;
        }
        Err(Error::Unavailable)
    }

    fn evidence_response(&self, bytes: &[u8], next_request_id: u64) -> Result<Vec<u8>, Error> {
        let request: evidence_wire::Request = serde_json::from_slice(bytes)?;
        let snapshot_head: Digest32 = request
            .snapshot_head
            .parse()
            .map_err(|_| Error::Binding("original evidence correlation head"))?;
        if request.schema != 1
            || request.operation != evidence_wire::OPERATION
            || request.request_id != next_request_id
            || request.binding != self.initial_head.to_string()
            || request.operation_id != self.context.dataset.request.operation_id.as_str()
            || request.actor_id != self.context.dataset.owners.trainer.as_str()
            || request.predecessor != self.context.dataset.head_digest.to_string()
            || snapshot_head.is_zero()
            || request.snapshot_head != snapshot_head.to_string()
        {
            return Err(Error::Binding("original Trainer evidence request"));
        }
        let completed = self
            .runtime
            .block_on(SourceBoundCellQ24TrainingStageV1::readback(
                &self.stage,
                &self.context.dataset,
            ))?;
        let original = wire::authenticate_receipt(
            &self.context,
            completed.receipt,
            completed.attestation,
            now()?,
        )?;
        if request.receipt_digest != original.attestation.payload_digest.to_string() {
            return Err(Error::Binding("exact original Training receipt digest"));
        }
        // snapshot_head is echoed only for correlation. It never selects work,
        // creates an observation, or authorizes a new signature or checkpoint.
        let response = evidence_wire::Response {
            schema: 1,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: evidence_wire::Evidence::from_original(&original.attestation),
        };
        Ok(serde_json::to_vec(&response)?)
    }
}

fn original_state(error: OriginalCellQ24TrainingStageErrorV1) -> wire::CommandResult {
    use CellQ24TrainingOwnerErrorV1 as Native;
    use LearningOriginalOwnerErrorV1 as Owner;
    use OriginalCellQ24TrainingReceiptErrorV1 as Receipt;
    use OriginalCellQ24TrainingStageErrorV1 as Stage;
    use ProductEvaluationExecutionStoreErrorV1 as Store;
    match error {
        Stage::Busy => wire::CommandResult::Busy,
        Stage::Training(Native::Pending)
        | Stage::Receipt(Receipt::Training(Native::Pending))
        | Stage::Receipt(Receipt::Owner(Owner::Pending)) => wire::CommandResult::Pending,
        Stage::Training(Native::Store(Store::Missing))
        | Stage::Receipt(Receipt::Training(Native::Store(Store::Missing)))
        | Stage::Receipt(Receipt::Owner(Owner::Store(Store::Missing))) => {
            wire::CommandResult::Missing
        }
        // A failure during fit, signature creation or tail CURRENT can follow
        // durable admission. Never call it Missing or infer a fresh NoUpdate.
        _ => wire::CommandResult::Uncertain,
    }
}

#[cfg(test)]
#[path = "cell_q24_training_command_support_tests.rs"]
pub(crate) mod command_test_support;
