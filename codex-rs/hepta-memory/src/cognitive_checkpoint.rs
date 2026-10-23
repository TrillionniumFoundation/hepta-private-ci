//! One protected checkpoint coordinator shared by an original owner pool.

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use tokio::sync::Mutex;

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
}

/// Created only by consuming an exclusively recovered CognitiveStore. Every
/// checkout and commit in that store shares this coordinator and atomic gate.
/// The protected service remains responsible for durable CAS, publisher
/// lifetimes, and independent restart reconciliation.
pub struct ProtectedCognitiveCheckpoint<T: CognitiveCheckpointTransport> {
    transport: Arc<T>,
    receipt: Mutex<CognitiveCheckpointReceipt>,
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
            || receipt.head.publisher_epoch != receipt.token.publisher_epoch
            || receipt.head.counter != receipt.token.counter
            || receipt.head.last_current.owner_agent_id != receipt.head.owner_agent_id
            || receipt.head.last_current.profile != "hepta:cognitive:exact-current-cut:v1"
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(Self {
            sequence: AtomicU64::new(receipt.head.counter),
            receipt: Mutex::new(receipt),
            transport,
            gate,
            deadline,
        })
    }

    pub(crate) async fn verify_initial(&self) -> Result<(), ObjectiveSenderCheckpointError> {
        let expected = self.receipt.lock().await;
        if self.read_head(&expected).await? != *expected {
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
        let mut receipt = self.receipt.lock().await;
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
            .transition(&receipt, CognitiveCheckpointCommand::BeginWrites, None)
            .await
        {
            *receipt = next;
            self.gate.allow_dirty_commits();
            attempt.acknowledge();
        }
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
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        let bytes =
            serde_json::to_vec(request).map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        if bytes.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        let response = tokio::time::timeout(self.deadline, self.transport.exchange(&bytes))
            .await
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)??;
        if response.is_empty() || response.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        let response: CognitiveCheckpointResponse = serde_json::from_slice(&response)
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        if response.schema_version != 1 || response.request_id != request.request_id {
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        match response.status {
            CognitiveCheckpointStatus::Refused => Err(ObjectiveSenderCheckpointError::Refused),
            CognitiveCheckpointStatus::Unknown => Err(ObjectiveSenderCheckpointError::Unavailable),
            CognitiveCheckpointStatus::Ack => {
                if response.reason.is_some() {
                    return Err(ObjectiveSenderCheckpointError::Unavailable);
                }
                let receipt = CognitiveCheckpointReceipt {
                    token: response
                        .token
                        .ok_or(ObjectiveSenderCheckpointError::Unavailable)?,
                    head: response
                        .head
                        .ok_or(ObjectiveSenderCheckpointError::Unavailable)?,
                };
                if receipt.head.schema_version != 1
                    || receipt.token.counter != receipt.head.counter
                    || receipt.token.publisher_epoch != receipt.head.publisher_epoch
                {
                    return Err(ObjectiveSenderCheckpointError::Unavailable);
                }
                Ok(receipt)
            }
        }
    }

    async fn read_head(
        &self,
        expected: &CognitiveCheckpointReceipt,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        let request = self.request(expected, CognitiveCheckpointCommand::ReadHead, None)?;
        let receipt = self.exchange(&request).await?;
        if receipt.head.owner_agent_id != expected.head.owner_agent_id
            || receipt.head.publisher_epoch != expected.head.publisher_epoch
            || receipt.head.writer_binding != expected.head.writer_binding
            || receipt.head.peer_lifetime != expected.head.peer_lifetime
            || receipt.head.counter < expected.head.counter
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(receipt)
    }

    async fn transition(
        &self,
        previous: &CognitiveCheckpointReceipt,
        command: CognitiveCheckpointCommand,
        proposal: Option<CognitiveCheckpointProposal>,
    ) -> Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError> {
        let request = self.request(previous, command, proposal)?;
        let mut expected = previous.head.clone();
        expected.counter = expected
            .counter
            .checked_add(1)
            .ok_or(ObjectiveSenderCheckpointError::Unavailable)?;
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
        let observed = self.exchange(&request).await?;
        if observed.head != expected || observed.token.head_sha256 == previous.token.head_sha256 {
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
        let mut receipt = self.receipt.lock().await;
        if committed.owner_agent_id != receipt.head.owner_agent_id
            || writer.owner_agent_id != receipt.head.owner_agent_id
            || !receipt.head.writer_binding.matches(writer)
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        if self.gate.is_fenced() {
            // Independent readback may settle an unchanged cut. It cannot
            // reopen this publisher or mint another Objective send ticket.
            let observed = self.read_head(&receipt).await?;
            if observed.head.phase != CognitiveCheckpointPhase::Current
                || observed.head.proposal.is_some()
                || observed.head.last_current != *committed
            {
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            }
            *receipt = observed;
            return Ok(committed.clone());
        }
        self.gate.close_commits();
        let attempt = self.gate.checkpoint_attempt();
        *receipt = self
            .transition(
                &receipt,
                CognitiveCheckpointCommand::PreparePublication,
                Some(CognitiveCheckpointProposal {
                    cut: committed.clone(),
                    writer_fence: writer.clone(),
                }),
            )
            .await?;
        *receipt = self
            .transition(
                &receipt,
                CognitiveCheckpointCommand::CommitPublication,
                None,
            )
            .await?;
        // Stay closed. The next checkout must independently invalidate Current
        // with a durable Dirty ACK before any original-owner commit is possible.
        attempt.acknowledge();
        Ok(committed.clone())
    }
}
