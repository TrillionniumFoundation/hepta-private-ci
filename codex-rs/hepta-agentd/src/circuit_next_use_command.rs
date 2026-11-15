//! Purpose-fixed original C Observer commands for an actual TrainingNoUpdate cut.
//! The original key and journal remain in the Observer host. No request carries
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
use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

#[path = "circuit_next_use_command_stage_binding.rs"]
mod stage_binding;

#[path = "circuit_next_use_command_service.rs"]
mod serving;
#[path = "circuit_next_use_command_wire.rs"]
mod wire;
pub use serving::OriginalCircuitNextUseCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitNextUseCommandErrorV1 {
    #[error("original C Observer command binding: {0}")]
    Binding(&'static str),
    #[error("original C Observer command channel is unavailable")]
    Unavailable,
    #[error("original C Observer completion is uncertain; read the same operation")]
    CommitUncertain,
    #[error("original C Observer execution was already requested; readback only")]
    ReadbackRequired,
    #[error("original C Observer owner is occupied")]
    Busy,
    #[error("original C Observer operation is missing")]
    Missing,
    #[error("original C Observer operation is pending")]
    Pending,
    #[error("original C Observer new work deadline expired")]
    DeadlineExceeded,
    #[error("original C Observer transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original C Observer owner: {0}")]
    Owner(#[from] OriginalCircuitNextUseReceiptErrorV1),
    #[error("original C Observer iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original C Observer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original C Observer snapshot codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original C Observer command encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitNextUseCommandErrorV1;

/// Fresh dispatch is bound to an actual opaque original Selection result.
/// This predecessor is not evidence that C has finished. The ordinary host
/// must wait for actual C completion before requesting the one attestation.
#[derive(Clone)]
pub struct OriginalCircuitNextUseCommandContextV1 {
    selection: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training_evidence: SignedLearningEvidenceV1,
    selection_evidence: SignedLearningEvidenceV1,
}

impl OriginalCircuitNextUseCommandContextV1 {
    pub fn from_original_selection(
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        original: &OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<Self, Error> {
        Self::from_checkpoint(
            original.snapshot().clone(),
            scope,
            verifier,
            original.training_attestation().clone(),
            original.attestation().clone(),
        )
    }

    fn from_checkpoint(
        selection: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training_evidence: SignedLearningEvidenceV1,
        selection_evidence: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let context = Self {
            selection,
            scope,
            verifier,
            training_evidence,
            selection_evidence,
        };
        context.authenticate(now()?)?;
        Ok(context)
    }

    fn authenticate(&self, current: u64) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(self.selection.clone())?;
        self.scope.validate_snapshot(&self.selection)?;
        if self.selection.receipts.len() != 4
            || coordinator.next_stage() != Some(LearningIterationStageV1::NextUse)
            || coordinator.next_task_bundle() != Some(&self.selection.request.selected_bundle)
            || self.selection.owners.evidence_trust_digest != self.verifier.trust_digest()
            || self.selection.request.envelope.objective_digest != self.verifier.objective_digest()
        {
            return Err(Error::Binding("strict original TrainingNoUpdate C profile"));
        }
        let training = &self.selection.receipts[2];
        let selection = &self.selection.receipts[3];
        let baseline = self
            .selection
            .request
            .selected_bundle
            .digest()
            .map_err(LearningIterationError::from)?;
        if !matches!(
            &training.observation,
            LearningIterationObservationV1::TrainingNoUpdateV2(_)
        ) || !matches!(&selection.observation,
                LearningIterationObservationV1::Selection { candidate_bundle, selection_digest }
                if *candidate_bundle == baseline && !selection_digest.is_zero())
            || training.actor_id != self.selection.owners.trainer
            || selection.actor_id != self.selection.owners.selector
            || training.observed_unix_seconds != self.training_evidence.issued_at
            || selection.observed_unix_seconds != self.selection_evidence.issued_at
            || training.observed_unix_seconds > current
            || selection.observed_unix_seconds > current
        {
            return Err(Error::Binding(
                "original completed Training and retained Selection",
            ));
        }
        let trainer = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &self.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(training)?,
            current,
        )?;
        let selector = self.verifier.verify(
            LearningEvidenceRoleV1::Selector,
            &self.selection_evidence,
            &learning_iteration_receipt_signing_bytes_v1(selection)?,
            current,
        )?;
        if trainer.principal().principal_id != self.selection.owners.trainer
            || selector.principal().principal_id != self.selection.owners.selector
        {
            return Err(Error::Binding("original predecessor identities"));
        }
        verify_signed_actor_separation(&trainer, &selector, current)?;
        Ok([trainer, selector])
    }

    fn initial(&self) -> Result<LearningIterationSnapshotV1, Error> {
        Ok(LearningIterationCoordinatorV1::new(
            self.selection.request.clone(),
            self.selection.owners.clone(),
        )?
        .snapshot()
        .clone())
    }

    fn binding(&self, current: u64) -> Result<Digest32, Error> {
        self.authenticate(current)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-next-use-command.v1\0",
            &encode_original_owner_snapshot_v1(&self.selection)?,
            self.scope.binding().as_array(),
            self.verifier.trust_digest().as_array(),
            self.verifier.scope_digest().as_array(),
            self.verifier.objective_digest().as_array(),
            &self.training_evidence.signing_bytes(),
            &self.training_evidence.signature,
            &self.selection_evidence.signing_bytes(),
            &self.selection_evidence.signature,
        ]))
    }
}

/// The original Observer's verified receipt for actually completed ordinary C.
/// A subsequent read always calls the original owner again. Keeping this value
/// neither starts C nor supplies a replacement for physical CURRENT.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitNextUseCommandReceiptV1 {
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    training_evidence: SignedLearningEvidenceV1,
    selection_evidence: SignedLearningEvidenceV1,
}
impl OriginalCircuitNextUseCommandReceiptV1 {
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
    pub fn selection_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.selection_evidence
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
pub struct OriginalCircuitNextUseCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: OriginalCircuitNextUseCommandContextV1,
    binding: Digest32,
    retained: Mutex<Option<OriginalCircuitNextUseCommandReceiptV1>>,
}

impl OriginalCircuitNextUseCommandClientV1 {
    /// Original-host supplied connected stream and held pidfd only. Bootstrap
    /// is synchronous bounded I/O and belongs on the host's blocking lane.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitNextUseCommandContextV1,
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

    /// Cold Root supplies its exact original Selection cut and complete original
    /// signatures. This constructor can only restore readback, including when
    /// Root has no confirmed NextUse ACK. It cannot manufacture a fresh context.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        selection: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training_evidence: SignedLearningEvidenceV1,
        selection_evidence: SignedLearningEvidenceV1,
        expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let context = OriginalCircuitNextUseCommandContextV1::from_checkpoint(
            selection,
            scope,
            verifier,
            training_evidence,
            selection_evidence,
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
        context: OriginalCircuitNextUseCommandContextV1,
        timeout: Duration,
        lifetime: Duration,
        execution_requested: bool,
        retained: Option<OriginalCircuitNextUseCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if peer.actor_id != context.selection.owners.next_use_observer {
            return Err(Error::Binding("original C Observer process"));
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
        if let Some(expected) = &retained
            && wire::authenticate_completed(
                &context,
                expected.snapshot.clone(),
                expected.attestation.clone(),
                current,
            )? != *expected
        {
            return Err(Error::Binding("exact cold original NextUse"));
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

    /// Ask the original Observer once to attest C that has already completed.
    /// This does not publish, start, run, retry or wait for C. An early request,
    /// timeout, cancellation, Busy or unknown ACK cannot reset the dispatch.
    pub async fn attest_completed_task(
        &self,
    ) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
        if now()? >= self.context.selection.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCircuitNextUseCommandClientV1::readback(self).await?;
        if &original.receipt != expected {
            return Err(Error::Binding("exact original NextUse receipt"));
        }
        Ok(original.attestation)
    }

    async fn exchange(
        &self,
        action: wire::Action,
    ) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
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
                    return Err(Error::Binding("unchanged original NextUse attestation"));
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
            "original C Observer command clock moved backwards",
        ));
    }
    Ok(())
}
fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original C Observer system clock"))
}

#[cfg(test)]
pub(crate) use serving::command_test_support;
