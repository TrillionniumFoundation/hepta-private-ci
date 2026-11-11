//! Typed original Trainer commands over an already held external role channel.
//! No command contains a dataset, label, observation, signing payload or key.
//! Native work and Generator custody remain in the same SourceBound owner lane.

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
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::LearningIterationEvidencePeerV1;
use super::wire as evidence_wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "cell_q24_training_command_connection.rs"]
mod connection;
pub use connection::OriginalCellQ24TrainingCommandConnectionErrorV1;
pub use connection::OriginalCellQ24TrainingCommandConnectionV1;

#[path = "cell_q24_training_bootstrap.rs"]
mod bootstrap;
pub use bootstrap::OriginalCellQ24TrainingBootstrapConfigV1;
pub use bootstrap::OriginalCellQ24TrainingBootstrapCustodyV1;
pub use bootstrap::OriginalCellQ24TrainingBootstrapErrorV1;
pub use bootstrap::OriginalCellQ24TrainingBootstrapOwnerV1;

#[path = "cell_q24_training_command_service.rs"]
mod serving;
#[path = "cell_q24_training_command_wire.rs"]
mod wire;
pub use serving::OriginalCellQ24TrainingCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingCommandErrorV1 {
    #[error("original Trainer command binding: {0}")]
    Binding(&'static str),
    #[error("original Trainer command channel is unavailable")]
    Unavailable,
    #[error("original Trainer command completion is uncertain; read the same job")]
    CommitUncertain,
    #[error("original Trainer execution was already requested; readback only")]
    ReadbackRequired,
    #[error("original Trainer lane is occupied")]
    Busy,
    #[error("original Trainer operation is missing")]
    Missing,
    #[error("original Trainer operation is pending")]
    Pending,
    #[error("original Trainer new work deadline expired")]
    DeadlineExceeded,
    #[error("original Trainer dispatch was cancelled")]
    Cancelled,
    #[error("original Trainer transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Trainer stage: {0}")]
    Stage(#[from] OriginalCellQ24TrainingStageErrorV1),
    #[error("original Trainer iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Trainer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Trainer receipt codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original Trainer command encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}

type Error = OriginalCellQ24TrainingCommandErrorV1;

/// Fixed before descriptor transfer. This unsigned context cannot create a
/// SourceBound stage or replace its live Material predecessors.
#[derive(Clone)]
pub struct OriginalCellQ24TrainingCommandContextV1 {
    pub dataset: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub verifier: LearningEvidenceVerifierV1,
}

impl OriginalCellQ24TrainingCommandContextV1 {
    fn validate(&self) -> Result<LearningIterationSnapshotV1, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(self.dataset.clone())?;
        self.scope.validate_snapshot(&self.dataset)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
            || self.dataset.receipts.len() != 2
            || self.dataset.owners.evidence_trust_digest != self.verifier.trust_digest()
            || self.dataset.request.envelope.objective_digest != self.verifier.objective_digest()
        {
            return Err(Error::Binding("exact original Dataset context"));
        }
        Ok(LearningIterationCoordinatorV1::new(
            self.dataset.request.clone(),
            self.dataset.owners.clone(),
        )?
        .snapshot()
        .clone())
    }

    fn binding(&self) -> Result<Digest32, Error> {
        let initial = self.validate()?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-q24-training-command.v1\0",
            initial.head_digest.as_array(),
            self.dataset.head_digest.as_array(),
            self.scope.binding().as_array(),
            self.verifier.trust_digest().as_array(),
            self.dataset.owners.trainer.as_str().as_bytes(),
        ]))
    }
}

/// A verified original response, not a local native owner or publication grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellQ24TrainingCommandReceiptV1 {
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
}

impl OriginalCellQ24TrainingCommandReceiptV1 {
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}

pub struct OriginalCellQ24TrainingCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: OriginalCellQ24TrainingCommandContextV1,
    binding: Digest32,
    retained: Mutex<Option<OriginalCellQ24TrainingCommandReceiptV1>>,
}

impl OriginalCellQ24TrainingCommandClientV1 {
    /// Consume the original host-selected connected stream and pre-held pidfd.
    /// Bootstrap is bounded synchronous I/O; use the host's blocking lane.
    /// The existing framer bounds the whole exchange to at most 30 seconds and
    /// the original session to 300 seconds. No existing transport is widened.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCellQ24TrainingCommandContextV1,
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

    /// Rebind only readback on a newly supplied connection to the same job.
    /// Existing receipt and complete attestation bytes, when retained by Root,
    /// are verified and pinned; no issued time, native job or key is replaced.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCellQ24TrainingCommandContextV1,
        expected: Option<(LearningIterationReceiptV1, SignedLearningEvidenceV1)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let retained = expected
            .map(|(receipt, attestation)| {
                wire::authenticate_receipt(&context, receipt, attestation, now()?)
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
        context: OriginalCellQ24TrainingCommandContextV1,
        timeout: Duration,
        lifetime: Duration,
        execution_requested: bool,
        retained: Option<OriginalCellQ24TrainingCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let binding = context.binding()?;
        if peer.actor_id != context.dataset.owners.trainer {
            return Err(Error::Binding("original Trainer process"));
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

    /// Request execution once. No retry occurs after Busy, cancellation, a lost
    /// ACK or an unknown result. Dropping this future consumes its connection;
    /// already admitted native work retains the original Stage's semantics.
    /// The dispatch flag is sampled here and immediately before the queued
    /// socket request. The original host retains the live cancellation token
    /// used during the fit; no cross-process Arc is claimed.
    pub async fn execute_training(
        &self,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
        if cancellation.load(Ordering::Acquire) {
            return Err(Error::Cancelled);
        }
        if now()? >= self.context.dataset.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(
            wire::Action::Execute,
            /*cancelled*/ false,
            Some(cancellation),
        )
        .await
    }

    pub async fn readback(&self) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
        self.exchange(
            wire::Action::Readback,
            /*cancelled*/ false,
            /*cancellation*/ None,
        )
        .await
    }

    /// Equality with the expected receipt is checked only after an actual
    /// original readback. This method cannot request a new signature.
    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let completed = OriginalCellQ24TrainingCommandClientV1::readback(self).await?;
        if &completed.receipt != expected {
            return Err(Error::Binding("exact original Training receipt"));
        }
        Ok(completed.attestation)
    }

    async fn exchange(
        &self,
        action: wire::Action,
        cancelled: bool,
        cancellation: Option<Arc<AtomicBool>>,
    ) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
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
        let request_id = channel.next_request_id;
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request =
            wire::Request::new(&self.context, self.binding, request_id, action, cancelled);
        let encoded = serde_json::to_vec(&request)?;
        // Restoring the original channel happens only in this caller after
        // complete validation. Cancellation of the await drops the task result,
        // including its channel, and cannot consume a delayed reply later.
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            if cancellation
                .as_ref()
                .is_some_and(|flag| flag.load(Ordering::Acquire))
            {
                return Err(Error::Cancelled);
            }
            let bytes = channel
                .peer
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        // Peer liveness can perform I/O; verify original signatures afterward.
        channel.peer.check_peer_lifetime()?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("Trainer command clock moved backwards"));
        }
        let result = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                let completed =
                    wire::decode_completed(&self.context, snapshot, evidence, fresh_now)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained
                    .as_ref()
                    .is_some_and(|original| original != &completed)
                {
                    return Err(Error::Binding("unchanged original Training attestation"));
                }
                *retained = Some(completed.clone());
                Ok(completed)
            }
            wire::CommandResult::Missing => Err(Error::Missing),
            wire::CommandResult::Pending => Err(Error::Pending),
            wire::CommandResult::Busy => Err(Error::Busy),
            wire::CommandResult::Expired => Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => Err(Error::ReadbackRequired),
            // The original operation may have committed. Consume the channel
            // and require the host to supply readback on this same job.
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
            wire::CommandResult::Unavailable => return Err(Error::Unavailable),
        };
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        result
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("Trainer command clock before Unix epoch"))
}

#[cfg(test)]
pub(crate) use serving::command_test_support;
