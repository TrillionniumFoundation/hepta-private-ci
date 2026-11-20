//! One protected checkpoint coordinator shared by an original owner pool.

use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use tokio::sync::Semaphore;

use crate::CheckpointDiagnostics;
use crate::CheckpointFailureCause as Cause;
use crate::CheckpointStage as Stage;
use crate::CognitiveRecoveryAnchor;
use crate::ObjectiveSenderCheckpoint;
use crate::ObjectiveSenderCheckpointError;
use crate::ObjectiveSenderWriterFence;
use crate::cognitive_checkpoint_wire::*;
use crate::cognitive_store::CognitiveCommitGate;

/// Fixed-peer, bounded asynchronous transport for the private protected-host
/// protocol. The caller supplies exact UTF-8 JSON bytes. Implementations frame
/// them with a four-byte big-endian length, enforce the 32-KiB response limit,
/// and authenticate the configured server process lifetime. No automatic retry,
/// reconnect, new publisher registration, or alternate endpoint is permitted.
/// A dropped exchange must invalidate its stream, so a late response cannot be
/// consumed as another request's ACK. Every Future poll must be nonblocking.
/// This boundary supplies no issuer or fallback protected-host implementation.
pub trait CognitiveCheckpointTransport: Send + Sync {
    fn exchange<'a>(
        &'a self,
        request_json: &'a [u8],
    ) -> impl Future<Output = Result<Vec<u8>, ObjectiveSenderCheckpointError>> + Send + 'a;

    /// Preserve the same exchange while optionally recording fixed local phases.
    /// Implementations must not use diagnostics to authorize, retry or reconnect.
    fn exchange_diagnosed<'a>(
        &'a self,
        request_json: &'a [u8],
        diagnostics: &'a CheckpointDiagnostics,
    ) -> impl Future<Output = Result<Vec<u8>, ObjectiveSenderCheckpointError>> + Send + 'a {
        async move {
            diagnostics.stage(Stage::TransportExchange);
            self.exchange(request_json).await
        }
    }
}

/// Created only by consuming an exclusively recovered CognitiveStore. Every
/// checkout and commit in that store shares this coordinator and atomic gate.
/// The protected service remains responsible for durable CAS, publisher
/// lifetimes, and independent restart reconciliation.
pub struct ProtectedCognitiveCheckpoint<T: CognitiveCheckpointTransport> {
    transport: Arc<T>,
    receipt: Mutex<CognitiveCheckpointReceipt>,
    // The permit serializes the whole protocol operation. Receipt memory is
    // separately locked only to copy/publish, never across an RPC or await.
    serial: Semaphore,
    sequence: AtomicU64,
    gate: CognitiveCommitGate,
    deadline: Duration,
}

impl<T: CognitiveCheckpointTransport> ProtectedCognitiveCheckpoint<T> {
    pub(crate) fn new(
        transport: Arc<T>,
        receipt: CognitiveCheckpointReceipt,
        gate: CognitiveCommitGate,
        deadline: Duration,
    ) -> Result<Self, ObjectiveSenderCheckpointError> {
        if deadline.is_zero()
            || deadline > Duration::from_secs(5)
            || receipt.head.schema_version != 1
            || receipt.head.phase != CognitiveCheckpointPhase::Current
            || receipt.head.proposal.is_some()
            || receipt.head.publisher_epoch == 0
            || receipt.head.counter == 0
            || receipt.head.counter == u64::MAX
            || receipt.head.last_mutation_sequence == u64::MAX
            || receipt.head.publisher_epoch != receipt.token.publisher_epoch
            || receipt.head.counter != receipt.token.counter
            || receipt.head.last_current.owner_agent_id != receipt.head.owner_agent_id
            || receipt.head.last_current.profile != "hepta:cognitive:exact-current-cut:v1"
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(Self {
            sequence: AtomicU64::new(receipt.head.last_mutation_sequence + 1),
            receipt: Mutex::new(receipt),
            serial: Semaphore::new(1),
            transport,
            gate,
            deadline,
        })
    }

    pub(crate) async fn verify_initial(&self) -> Result<(), ObjectiveSenderCheckpointError> {
        let _serial = self
            .serial
            .acquire()
            .await
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        let expected = self.receipt_snapshot()?;
        if self
            .read_head(&expected, &CheckpointDiagnostics::default())
            .await?
            != expected
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(())
    }

    /// Called for new and reused connections, before owner code receives them.
    /// A failed transition fences writes but preserves read-only inspection.
    pub(crate) async fn before_checkout(&self) {
        if self.gate.is_fenced() {
            return;
        }
        let Ok(_serial) = self.serial.acquire().await else {
            drop(self.gate.transition_attempt());
            return;
        };
        let Ok(receipt) = self.receipt_snapshot() else {
            drop(self.gate.transition_attempt());
            return;
        };
        if self.gate.is_fenced() {
            return;
        }
        if receipt.head.phase == CognitiveCheckpointPhase::Dirty {
            self.gate.allow_dirty_commits();
            return;
        }
        let attempt = self.gate.transition_attempt();
        if receipt.head.phase != CognitiveCheckpointPhase::Current {
            return;
        }
        if let Ok(next) = self
            .transition(
                &receipt,
                CognitiveCheckpointCommand::BeginWrites,
                None,
                &CheckpointDiagnostics::default(),
            )
            .await
        {
            if self.store_receipt(next).is_err() {
                return;
            }
            self.gate.allow_dirty_commits();
            attempt.acknowledge();
        }
    }

    fn receipt_snapshot(
        &self,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        self.receipt
            .lock()
            .map(|value| value.clone())
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)
    }
    fn store_receipt(
        &self,
        next: CognitiveCheckpointReceipt,
    ) -> Result<(), ObjectiveSenderCheckpointError> {
        *self
            .receipt
            .lock()
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)? = next;
        Ok(())
    }

    fn request(
        &self,
        receipt: &CognitiveCheckpointReceipt,
        command: CognitiveCheckpointCommand,
        proposal: Option<CognitiveCheckpointProposal>,
    ) -> Result<CognitiveCheckpointRequest, ObjectiveSenderCheckpointError> {
        let sequence = self
            .sequence
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |value| {
                value.checked_add(1)
            })
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        Ok(CognitiveCheckpointRequest {
            schema_version: 1,
            operation: "runtime.cognitive.checkpoint.v1".to_string(),
            request_id: format!("{:016x}{:016x}", receipt.token.publisher_epoch, sequence),
            command,
            expected: (command != CognitiveCheckpointCommand::ReadHead)
                .then(|| receipt.token.clone()),
            proposal,
        })
    }

    async fn exchange(
        &self,
        request: &CognitiveCheckpointRequest,
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        diagnostics.request(request);
        diagnostics.stage(Stage::Serialize);
        let bytes = serde_json::to_vec(request).map_err(|_| {
            diagnostics.fail(Cause::Encode);
            ObjectiveSenderCheckpointError::Unavailable
        })?;
        if bytes.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            diagnostics.fail(Cause::Size);
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        let response = tokio::time::timeout(
            self.deadline,
            self.transport.exchange_diagnosed(&bytes, diagnostics),
        )
        .await
        .map_err(|_| {
            diagnostics.fail(Cause::Timeout);
            ObjectiveSenderCheckpointError::Unavailable
        })?
        .inspect_err(|error| {
            diagnostics.fail(match error {
                ObjectiveSenderCheckpointError::Refused => Cause::PublisherRefused,
                ObjectiveSenderCheckpointError::Unavailable => Cause::PublisherUnavailable,
            })
        })?;
        diagnostics.stage(Stage::ValidateResponse);
        if response.is_empty() || response.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            diagnostics.fail(Cause::Size);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        let response: CognitiveCheckpointResponse =
            serde_json::from_slice(&response).map_err(|_| {
                diagnostics.fail(Cause::Decode);
                ObjectiveSenderCheckpointError::Unavailable
            })?;
        if response.schema_version != 1 || response.request_id != request.request_id {
            diagnostics.fail(Cause::Identity);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        match response.status {
            CognitiveCheckpointStatus::Refused => {
                diagnostics.fail(Cause::Refused(response.reason));
                Err(ObjectiveSenderCheckpointError::Refused)
            }
            CognitiveCheckpointStatus::Unknown => {
                diagnostics.fail(Cause::Unknown(response.reason));
                Err(ObjectiveSenderCheckpointError::Unavailable)
            }
            CognitiveCheckpointStatus::Ack => {
                if response.reason.is_some() {
                    diagnostics.fail(Cause::MissingFields);
                    return Err(ObjectiveSenderCheckpointError::Unavailable);
                }
                let receipt = CognitiveCheckpointReceipt {
                    token: response.token.ok_or_else(|| {
                        diagnostics.fail(Cause::MissingFields);
                        ObjectiveSenderCheckpointError::Unavailable
                    })?,
                    head: response.head.ok_or_else(|| {
                        diagnostics.fail(Cause::MissingFields);
                        ObjectiveSenderCheckpointError::Unavailable
                    })?,
                };
                if receipt.head.schema_version != 1
                    || receipt.token.counter != receipt.head.counter
                    || receipt.token.publisher_epoch != receipt.head.publisher_epoch
                {
                    diagnostics.fail(Cause::HeadMismatch);
                    return Err(ObjectiveSenderCheckpointError::Unavailable);
                }
                Ok(receipt)
            }
        }
    }

    async fn read_head(
        &self,
        expected: &CognitiveCheckpointReceipt,
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        let request = self.request(expected, CognitiveCheckpointCommand::ReadHead, None)?;
        let receipt = self.exchange(&request, diagnostics).await?;
        diagnostics.stage(Stage::ValidateHead);
        if receipt.head.owner_agent_id != expected.head.owner_agent_id
            || receipt.head.publisher_epoch != expected.head.publisher_epoch
            || receipt.head.writer_binding != expected.head.writer_binding
            || receipt.head.peer_lifetime != expected.head.peer_lifetime
            || receipt.head.counter < expected.head.counter
            || receipt.head.last_mutation_sequence < expected.head.last_mutation_sequence
        {
            diagnostics.fail(Cause::HeadMismatch);
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(receipt)
    }

    async fn transition(
        &self,
        previous: &CognitiveCheckpointReceipt,
        command: CognitiveCheckpointCommand,
        proposal: Option<CognitiveCheckpointProposal>,
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        let request = self.request(previous, command, proposal)?;
        let mut expected = previous.head.clone();
        expected.counter = expected
            .counter
            .checked_add(1)
            .ok_or(ObjectiveSenderCheckpointError::Unavailable)?;
        expected.last_mutation_sequence = u64::from_str_radix(&request.request_id[16..], 16)
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        expected.last_request = Some(CognitiveCheckpointRetainedRequest {
            request_id: request.request_id.clone(),
            request_sha256: Sha256Digest::from_sha256_output(Sha256::digest(
                serde_json::to_vec(&request)
                    .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?,
            )),
            command,
            predecessor_token: previous.token.clone(),
        });
        match (command, previous.head.phase) {
            (CognitiveCheckpointCommand::BeginWrites, CognitiveCheckpointPhase::Current) => {
                expected.phase = CognitiveCheckpointPhase::Dirty;
                expected.proposal = None;
            }
            (CognitiveCheckpointCommand::PreparePublication, CognitiveCheckpointPhase::Dirty) => {
                let proposal = request
                    .proposal
                    .as_ref()
                    .ok_or(ObjectiveSenderCheckpointError::Refused)?;
                expected.phase = CognitiveCheckpointPhase::Publishing;
                expected.proposal = Some(CognitiveCheckpointRetainedProposal {
                    request_id: request.request_id.clone(),
                    cut: proposal.cut.clone(),
                    writer_fence: proposal.writer_fence.clone(),
                });
            }
            (
                CognitiveCheckpointCommand::CommitPublication,
                CognitiveCheckpointPhase::Publishing,
            ) => {
                expected.last_current = previous
                    .head
                    .proposal
                    .as_ref()
                    .ok_or(ObjectiveSenderCheckpointError::Refused)?
                    .cut
                    .clone();
                expected.phase = CognitiveCheckpointPhase::Current;
                expected.proposal = None;
            }
            _ => return Err(ObjectiveSenderCheckpointError::Refused),
        }
        let observed = self.exchange(&request, diagnostics).await?;
        diagnostics.stage(Stage::ValidateTransition);
        if observed.head != expected || observed.token.head_sha256 == previous.token.head_sha256 {
            diagnostics.fail(Cause::TransitionMismatch);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        Ok(observed)
    }
}

impl<T: CognitiveCheckpointTransport> ObjectiveSenderCheckpoint
    for ProtectedCognitiveCheckpoint<T>
{
    async fn acknowledge_current(
        &self,
        committed: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        self.acknowledge_diagnosed(committed, writer, &CheckpointDiagnostics::default())
            .await
    }
}
impl<T: CognitiveCheckpointTransport> ProtectedCognitiveCheckpoint<T> {
    pub(crate) async fn acknowledge_diagnosed(
        &self,
        committed: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        diagnostics.stage(Stage::WaitingCoordinator);
        let _serial = self
            .serial
            .acquire()
            .await
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        let mut receipt = self.receipt_snapshot()?;
        if committed.owner_agent_id != receipt.head.owner_agent_id
            || writer.owner_agent_id != receipt.head.owner_agent_id
            || !receipt.head.writer_binding.matches(writer)
        {
            diagnostics.fail(Cause::HeadMismatch);
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        if self.gate.is_fenced() {
            // Independent readback may settle an unchanged cut. It cannot
            // reopen this publisher or mint another Objective send ticket.
            let observed = self.read_head(&receipt, diagnostics).await?;
            if observed.head.phase != CognitiveCheckpointPhase::Current
                || observed.head.proposal.is_some()
                || observed.head.last_current != *committed
            {
                diagnostics.fail(Cause::CutMismatch);
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            }
            self.store_receipt(observed)?;
            return Ok(committed.clone());
        }
        if receipt.head.phase == CognitiveCheckpointPhase::Current {
            // The original sender holds BEGIN IMMEDIATE on a physically
            // READONLY connection. A fresh, identical protected head confirms
            // this cut without invalidating it or incrementing any counter.
            if receipt.head.last_current != *committed
                || self.read_head(&receipt, diagnostics).await? != receipt
            {
                diagnostics.fail(Cause::CutMismatch);
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            }
            return Ok(committed.clone());
        }
        self.gate.close_commits();
        let attempt = self.gate.checkpoint_attempt();
        receipt = self
            .transition(
                &receipt,
                CognitiveCheckpointCommand::PreparePublication,
                Some(CognitiveCheckpointProposal {
                    cut: committed.clone(),
                    writer_fence: writer.clone(),
                }),
                diagnostics,
            )
            .await?;
        self.store_receipt(receipt.clone())?;
        receipt = self
            .transition(
                &receipt,
                CognitiveCheckpointCommand::CommitPublication,
                None,
                diagnostics,
            )
            .await?;
        self.store_receipt(receipt)?;
        // Stay closed. The next checkout must independently invalidate Current
        // with a durable Dirty ACK before any original-owner commit is possible.
        attempt.acknowledge();
        diagnostics.stage(Stage::Finished);
        Ok(committed.clone())
    }
}
