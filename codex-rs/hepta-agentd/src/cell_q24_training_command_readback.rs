//! Read the same completed Trainer through a distinct read-only command purpose.
//! The initial peer, pidfd and absolute session end move once; no bootstrap,
//! native writer, Generator key or execution request is exposed by this client.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::learning_iteration_evidence_client::command_evidence::OriginalCommandEvidenceV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

pub(in crate::learning_iteration_evidence_client) const OPERATION: &str =
    "runtime.learning.original-q24-training.readback.v1";

/// A separately delivered read-only Trainer connection, bound before D/T exist.
/// The matching host endpoint only borrows an already Ready original Stage.
pub struct OriginalCellQ24TrainingReadbackConnectionV1 {
    peer: HostAuthorityPeerChannel,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    initial_binding: Digest32,
}

impl OriginalCellQ24TrainingReadbackConnectionV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let (initial_binding, started_at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
                .map_err(|_| Error::Binding("original Training readback initial context"))?;
        if peer.actor_id != material.initial.owners.trainer {
            return Err(Error::Binding("original Training readback actor"));
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
        channel.check_peer_lifetime()?;
        let (after, current) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
                .map_err(|_| Error::Binding("current Training readback initial context"))?;
        if current < started_at || after != initial_binding {
            return Err(Error::Binding("unchanged Training readback initial context"));
        }
        Ok(Self { peer: channel, material, initial_binding })
    }

    /// Consume the original connection only after actual opaque D and T arrive.
    /// This returns the existing evidence-only interface, backed by this exact
    /// read-only purpose. It cannot send old Execute/Readback bootstrap commands.
    pub fn bind_original_training(
        self,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<LearningIterationEvidenceClientV1, Error> {
        let started_at = now()?;
        let context = OriginalCellQ24TrainingCommandContextV1 {
            dataset: dataset.snapshot().clone(),
            scope: self.material.scope.clone(),
            verifier: self.material.verifier.clone(),
        };
        if context.validate()? != self.material.initial {
            return Err(Error::Binding("same original Training readback initial cut"));
        }
        let binding = binding(&context)?;
        self.peer.check_peer_lifetime()?;
        let (original, current) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&self.material)
                .map_err(|_| Error::Binding("current Training readback initial context"))?;
        let verified_at =
            OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
                &dataset, &self.material,
            )
            .map_err(|_| Error::Binding("same original Dataset before Training readback"))?;
        if current < started_at || verified_at < current || original != self.initial_binding {
            return Err(Error::Binding("unchanged Training readback clock and initial context"));
        }
        let verified = wire::authenticate_receipt(
            &context, training.receipt.clone(), training.attestation.clone(), verified_at,
        )?;
        if verified != training {
            return Err(Error::Binding("exact original Training readback signature"));
        }
        let initial = self.material.initial.clone();
        let actor_id = initial.owners.trainer.clone();
        let verifier = self.material.verifier.clone();
        let reader = OriginalTrainingReadbackV1 {
            peer: Some(self.peer),
            next_request_id: 1,
            material: self.material,
            dataset,
            training,
            context,
            binding,
        };
        Ok(LearningIterationEvidenceClientV1 {
            channel: Mutex::new(None),
            command: Some(Mutex::new(Some(OriginalCommandEvidenceV1::Training(reader)))),
            initial,
            actor_id,
            verifier,
        })
    }
}

pub(in crate::learning_iteration_evidence_client) struct OriginalTrainingReadbackV1 {
    peer: Option<HostAuthorityPeerChannel>,
    next_request_id: u64,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    context: OriginalCellQ24TrainingCommandContextV1,
    binding: Digest32,
}

impl OriginalTrainingReadbackV1 {
    pub(in crate::learning_iteration_evidence_client) async fn readback(
        &mut self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<(SignedLearningEvidenceV1, u64), Error> {
        let started_at = now()?;
        let mut peer = self.peer.take().ok_or(Error::Unavailable)?;
        if expected != self.training.receipt() || !(1..=128).contains(&self.next_request_id) {
            return Err(Error::Binding("same original completed Training readback"));
        }
        let request = request(&self.context, self.binding, self.next_request_id);
        self.next_request_id = self.next_request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let encoded = serde_json::to_vec(&request)?;
        let (peer, bytes) = tokio::task::spawn_blocking(move || {
            let bytes = peer.request(&encoded).map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((peer, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        peer.check_peer_lifetime()?;
        let current =
            OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
                &self.dataset, &self.material,
            )
            .map_err(|_| Error::Binding("current original Dataset after Training readback"))?;
        if current < started_at {
            return Err(Error::Binding("Training readback clock moved backwards"));
        }
        let completed = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } =>
                wire::decode_completed(&self.context, snapshot, evidence, current)?,
            // This capability already pins a real completed T. A different
            // current state cannot erase that fact or become a fresh NoUpdate.
            wire::CommandResult::Missing | wire::CommandResult::Pending =>
                return Err(Error::CommitUncertain),
            wire::CommandResult::Busy => return Err(Error::Busy),
            wire::CommandResult::Expired => return Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => return Err(Error::ReadbackRequired),
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
            wire::CommandResult::Unavailable => return Err(Error::Unavailable),
        };
        if completed != self.training {
            return Err(Error::Binding("unchanged complete original Training signature"));
        }
        self.peer = Some(peer);
        Ok((completed.attestation, current))
    }
}

pub(super) fn binding(context: &OriginalCellQ24TrainingCommandContextV1) -> Result<Digest32, Error> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-q24-training-readback.v1\0",
        context.binding()?.as_array(),
    ]))
}

pub(super) fn request(
    context: &OriginalCellQ24TrainingCommandContextV1,
    binding: Digest32,
    request_id: u64,
) -> wire::Request {
    let mut request = wire::Request::new(
        context, binding, request_id, wire::Action::Readback, /*cancelled*/ false,
    );
    request.operation = OPERATION.into();
    request
}

pub(super) fn require_request(
    observed: &wire::Request,
    context: &OriginalCellQ24TrainingCommandContextV1,
    request_id: u64,
) -> Result<(), Error> {
    let expected = request(context, binding(context)?, request_id);
    if observed.schema != expected.schema
        || observed.operation != OPERATION
        || observed.request_id != request_id
        || !(1..=128).contains(&request_id)
        || observed.binding != expected.binding
        || observed.operation_id != expected.operation_id
        || observed.dataset_head != expected.dataset_head
        || observed.scope_binding != expected.scope_binding
        || observed.actor_id != expected.actor_id
        || observed.action != wire::Action::Readback
        || observed.cancelled
    {
        return Err(Error::Binding("same original read-only Training purpose and context"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "cell_q24_training_readback_support_tests.rs"]
pub(super) mod test_support;
