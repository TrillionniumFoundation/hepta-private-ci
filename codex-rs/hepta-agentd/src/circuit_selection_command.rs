//! Purpose-fixed original Selector commands for an actual TrainingNoUpdate cut.
//! The original key and journal remain in the Selector host. No request carries
//! a selection observation, predecessor snapshot, signature payload or grant.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::LearningIterationEvidencePeerV1;
use super::wire as evidence_wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_selection_command_stage_binding.rs"]
mod stage_binding;

#[path = "circuit_selection_command_service.rs"]
mod serving;
#[path = "circuit_selection_command_wire.rs"]
mod wire;
pub use serving::OriginalCircuitSelectionCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitSelectionCommandErrorV1 {
    #[error("original Selector command binding: {0}")]
    Binding(&'static str),
    #[error("original Selector command channel is unavailable")]
    Unavailable,
    #[error("original Selector completion is uncertain; read the same operation")]
    CommitUncertain,
    #[error("original Selector execution was already requested; readback only")]
    ReadbackRequired,
    #[error("original Selector owner is occupied")]
    Busy,
    #[error("original Selector operation is missing")]
    Missing,
    #[error("original Selector operation is pending")]
    Pending,
    #[error("original Selector new work deadline expired")]
    DeadlineExceeded,
    #[error("original Selector transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Selector owner: {0}")]
    Owner(#[from] OriginalCircuitSelectionReceiptErrorV1),
    #[error("original Selector iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Selector evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Selector snapshot codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original Selector command encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitSelectionCommandErrorV1;

/// Fresh dispatch can only be configured from an actual opaque Trainer result.
/// This is a point-in-time predecessor, not a lease or a prefilled future cut.
#[derive(Clone)]
pub struct OriginalCircuitSelectionCommandContextV1 {
    training: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training_evidence: SignedLearningEvidenceV1,
}

impl OriginalCircuitSelectionCommandContextV1 {
    pub fn from_original_training(
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        original: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Self, Error> {
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
            || coordinator.snapshot().receipts.len() != 2
        {
            return Err(Error::Binding("original Dataset before Trainer completion"));
        }
        coordinator.record(
            original.receipt().clone(),
            original.receipt().observed_unix_seconds,
        )?;
        Self::from_checkpoint(
            coordinator.snapshot().clone(),
            scope,
            verifier,
            original.attestation().clone(),
        )
    }

    fn from_checkpoint(
        training: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training_evidence: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let context = Self {
            training,
            scope,
            verifier,
            training_evidence,
        };
        context.authenticate(now()?)?;
        Ok(context)
    }

    fn authenticate(&self, current: u64) -> Result<VerifiedLearningEvidenceV1, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(self.training.clone())?;
        self.scope.validate_snapshot(&self.training)?;
        let receipt = self
            .training
            .receipts
            .last()
            .ok_or(Error::Binding("original TrainingNoUpdate predecessor"))?;
        if self.training.receipts.len() != 3
            || coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
            || !matches!(
                &receipt.observation,
                LearningIterationObservationV1::TrainingNoUpdateV2(_)
            )
            || self.training.owners.evidence_trust_digest != self.verifier.trust_digest()
            || self.training.request.envelope.objective_digest != self.verifier.objective_digest()
            || receipt.actor_id != self.training.owners.trainer
            || receipt.observed_unix_seconds != self.training_evidence.issued_at
            || receipt.observed_unix_seconds > current
        {
            return Err(Error::Binding(
                "strict original TrainingNoUpdate command profile",
            ));
        }
        let original = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &self.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            current,
        )?;
        if original.principal().principal_id != self.training.owners.trainer {
            return Err(Error::Binding("original Trainer predecessor identity"));
        }
        Ok(original)
    }

    fn initial(&self) -> Result<LearningIterationSnapshotV1, Error> {
        Ok(LearningIterationCoordinatorV1::new(
            self.training.request.clone(),
            self.training.owners.clone(),
        )?
        .snapshot()
        .clone())
    }

    fn binding(&self, current: u64) -> Result<Digest32, Error> {
        self.authenticate(current)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-selection-command.v1\0",
            &encode_original_owner_snapshot_v1(&self.training)?,
            self.scope.binding().as_array(),
            self.verifier.trust_digest().as_array(),
            self.verifier.scope_digest().as_array(),
            self.verifier.objective_digest().as_array(),
            &self.training_evidence.signing_bytes(),
            &self.training_evidence.signature,
        ]))
    }
}

/// Verified actual Selection output. C may use this exact cut and both original
/// signatures; a cached value never substitutes for a subsequent CURRENT read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitSelectionCommandReceiptV1 {
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    training_evidence: SignedLearningEvidenceV1,
}
impl OriginalCircuitSelectionCommandReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
    pub fn training_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.training_evidence
    }
}

// A dropped async caller cannot authorize a still-queued Execute. This flag
// belongs only to one exchange; it never restores the consumed channel or once bit.
struct QueuedExecuteFence {
    abandoned: Arc<AtomicBool>,
}

impl Drop for QueuedExecuteFence {
    fn drop(&mut self) {
        self.abandoned.store(/*val*/ true, Ordering::Release);
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}
pub struct OriginalCircuitSelectionCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: OriginalCircuitSelectionCommandContextV1,
    binding: Digest32,
    retained: Mutex<Option<OriginalCircuitSelectionCommandReceiptV1>>,
}

impl OriginalCircuitSelectionCommandClientV1 {
    /// Original-host supplied connected stream and held pidfd only. Bootstrap
    /// is synchronous bounded I/O and belongs on the host's blocking lane.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitSelectionCommandContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            context,
            timeout,
            lifetime,
            false,
            None,
        )
    }

    /// Cold Root supplies its exact original Training cut and complete original
    /// signatures. This constructor can only restore readback, including when
    /// Root has no confirmed Selection ACK. It cannot manufacture a fresh context.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        training: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training_evidence: SignedLearningEvidenceV1,
        expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let context = OriginalCircuitSelectionCommandContextV1::from_checkpoint(
            training,
            scope,
            verifier,
            training_evidence,
        )?;
        let retained = expected
            .map(|(snapshot, signed)| {
                wire::authenticate_completed(&context, snapshot, signed, now()?)
            })
            .transpose()?;
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            context,
            timeout,
            lifetime,
            true,
            retained,
        )
    }

    fn bind_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitSelectionCommandContextV1,
        timeout: Duration,
        lifetime: Duration,
        execution_requested: bool,
        retained: Option<OriginalCircuitSelectionCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if peer.actor_id != context.training.owners.selector {
            return Err(Error::Binding("original Selector process"));
        }
        let channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_owner_pidfd,
            timeout,
            lifetime,
        )?;
        let current = now()?;
        require_clock(started_at, current)?;
        context.authenticate(current)?;
        if let Some(expected) = &retained {
            if wire::authenticate_completed(
                &context,
                expected.snapshot.clone(),
                expected.attestation.clone(),
                current,
            )? != *expected
            {
                return Err(Error::Binding("exact cold original Selection"));
            }
        }
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer: channel,
                next_request_id: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
        })
    }

    /// One dispatch only. Timeout, cancellation of this future, Busy or an
    /// unknown ACK never causes automatic execution replay or a new operation.
    pub async fn execute_selection(
        &self,
    ) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
        if now()? >= self.context.training.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCircuitSelectionCommandClientV1::readback(self).await?;
        if &original.receipt != expected {
            return Err(Error::Binding("exact original Selection receipt"));
        }
        Ok(original.attestation)
    }

    async fn exchange(
        &self,
        action: wire::Action,
    ) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
        let started_at = now()?;
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            if action == wire::Action::Execute
                && slot
                    .as_ref()
                    .is_some_and(|channel| channel.execution_requested)
            {
                return Err(Error::ReadbackRequired);
            }
            let mut channel = slot.take().ok_or(Error::Unavailable)?;
            if action == wire::Action::Execute {
                channel.execution_requested = true;
            }
            channel
        };
        self.context.authenticate(started_at)?;
        let request_id = channel.next_request_id;
        if !(1..=128).contains(&request_id) {
            return Err(Error::Unavailable);
        }
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request = wire::Request::new(&self.context, self.binding, request_id, action);
        let encoded = serde_json::to_vec(&request)?;
        let abandoned = Arc::new(AtomicBool::new(/*v*/ false));
        let queued_execute_fence = QueuedExecuteFence {
            abandoned: Arc::clone(&abandoned),
        };
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            // The original peer remains moved into this one task. Once the
            // request has started, a cancelled waiter still has an unknown ACK.
            if action == wire::Action::Execute && abandoned.load(Ordering::Acquire) {
                return Err(Error::Unavailable);
            }
            let bytes = channel
                .peer
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        drop(queued_execute_fence);
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        channel.peer.check_peer_lifetime()?;
        let current = now()?;
        require_clock(started_at, current)?;
        self.context.authenticate(current)?;
        let result = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                let original = wire::decode_completed(&self.context, snapshot, evidence, current)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained
                    .as_ref()
                    .is_some_and(|previous| previous != &original)
                {
                    return Err(Error::Binding("unchanged original Selection attestation"));
                }
                *retained = Some(original.clone());
                Ok(original)
            }
            wire::CommandResult::Missing => Err(Error::Missing),
            wire::CommandResult::Pending => Err(Error::Pending),
            wire::CommandResult::Busy => Err(Error::Busy),
            wire::CommandResult::Expired => Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => Err(Error::ReadbackRequired),
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
            wire::CommandResult::Unavailable => return Err(Error::Unavailable),
        };
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        result
    }
}

fn require_clock(started_at: u64, current: u64) -> Result<(), Error> {
    if current < started_at {
        return Err(Error::Binding(
            "original Selector command clock moved backwards",
        ));
    }
    Ok(())
}
fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original Selector system clock"))
}

#[cfg(test)]
pub(crate) use serving::command_test_support;
