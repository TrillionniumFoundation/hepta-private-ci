//! A purpose-fixed read-only Selector connection for the original C host.
//! It retains its initial peer and deadline while waiting for opaque D/T/S.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitSelectionCommandContextV1;
use super::OriginalCircuitSelectionCommandReceiptV1;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_evidence_client::command_evidence::OriginalCommandEvidenceV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

pub(in crate::learning_iteration_evidence_client) const OPERATION: &str =
    "runtime.learning.original-circuit-selection.readback.v1";

pub struct OriginalCircuitSelectionReadbackConnectionV1 {
    peer: HostAuthorityPeerChannel,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    initial_binding: Digest32,
}

#[cfg(test)]
#[path = "circuit_selection_readback_support_tests.rs"]
pub(crate) mod test_support;

impl OriginalCircuitSelectionReadbackConnectionV1 {
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
                .map_err(|_| Error::Binding("original Selector readback initial context"))?;
        if peer.actor_id != material.initial.owners.selector {
            return Err(Error::Binding("original Selector readback actor"));
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
                .map_err(|_| Error::Binding("current Selector readback initial context"))?;
        if current < started_at || after != initial_binding {
            return Err(Error::Binding(
                "unchanged Selector readback initial context",
            ));
        }
        Ok(Self {
            peer: channel,
            material,
            initial_binding,
        })
    }

    /// This consumes only a read-only connection. No fresh/cold brand can
    /// promote it to Selection execution, publication or signature creation.
    pub fn bind_original_selection(
        self,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        selection: OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<LearningIterationEvidenceClientV1, Error> {
        let started_at = now()?;
        let context = OriginalCircuitSelectionCommandContextV1::from_original_training(
            dataset.snapshot().clone(),
            self.material.scope.clone(),
            self.material.verifier.clone(),
            training,
        )?;
        if context.initial()? != self.material.initial {
            return Err(Error::Binding(
                "same original Selector readback initial cut",
            ));
        }
        let binding = context_binding(&context, started_at)?;
        self.peer.check_peer_lifetime()?;
        let (original, current) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )
            .map_err(|_| Error::Binding("current Selector readback initial context"))?;
        let verified_at =
            OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
                &dataset,
                &self.material,
            )
            .map_err(|_| Error::Binding("same original Dataset before Selector readback"))?;
        if current < started_at || verified_at < current || original != self.initial_binding {
            return Err(Error::Binding(
                "unchanged Selector readback clock and initial context",
            ));
        }
        let verified = wire::authenticate_completed(
            &context,
            selection.snapshot.clone(),
            selection.attestation.clone(),
            verified_at,
        )?;
        if verified != selection || context_binding(&context, verified_at)? != binding {
            return Err(Error::Binding(
                "exact original Selector readback signatures",
            ));
        }
        let initial = self.material.initial.clone();
        let actor_id = initial.owners.selector.clone();
        let verifier = self.material.verifier.clone();
        let reader = OriginalSelectionReadbackV1 {
            peer: Some(self.peer),
            next_request_id: 1,
            material: self.material,
            dataset,
            selection,
            context,
            binding,
        };
        Ok(LearningIterationEvidenceClientV1 {
            channel: Mutex::new(None),
            command: Some(Mutex::new(Some(OriginalCommandEvidenceV1::Selection(
                reader,
            )))),
            initial,
            actor_id,
            verifier,
        })
    }
}

pub(in crate::learning_iteration_evidence_client) struct OriginalSelectionReadbackV1 {
    peer: Option<HostAuthorityPeerChannel>,
    next_request_id: u64,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    selection: OriginalCircuitSelectionCommandReceiptV1,
    context: OriginalCircuitSelectionCommandContextV1,
    binding: Digest32,
}

impl OriginalSelectionReadbackV1 {
    pub(in crate::learning_iteration_evidence_client) async fn readback(
        &mut self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<(SignedLearningEvidenceV1, u64), Error> {
        let started_at = now()?;
        let mut peer = self.peer.take().ok_or(Error::Unavailable)?;
        if expected != self.selection.receipt() || !(1..=128).contains(&self.next_request_id) {
            return Err(Error::Binding("same original completed Selection readback"));
        }
        let request = request(&self.context, self.binding, self.next_request_id);
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or(Error::Unavailable)?;
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
        let current = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &self.dataset,
            &self.material,
        )
        .map_err(|_| Error::Binding("current original Dataset after Selector readback"))?;
        if current < started_at || context_binding(&self.context, current)? != self.binding {
            return Err(Error::Binding(
                "unchanged Selector readback clock and context",
            ));
        }
        let completed = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                wire::decode_completed(&self.context, snapshot, evidence, current)?
            }
            wire::CommandResult::Missing | wire::CommandResult::Pending => {
                return Err(Error::CommitUncertain);
            }
            wire::CommandResult::Busy => return Err(Error::Busy),
            wire::CommandResult::Expired => return Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => return Err(Error::ReadbackRequired),
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
            wire::CommandResult::Unavailable => return Err(Error::Unavailable),
        };
        if completed != self.selection {
            return Err(Error::Binding(
                "unchanged complete original Selection signatures",
            ));
        }
        self.peer = Some(peer);
        Ok((completed.attestation, current))
    }
}

pub(super) fn context_binding(
    context: &OriginalCircuitSelectionCommandContextV1,
    current: u64,
) -> Result<Digest32, Error> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-circuit-selection-readback.v1\0",
        context.binding(current)?.as_array(),
    ]))
}

pub(super) fn request(
    context: &OriginalCircuitSelectionCommandContextV1,
    binding: Digest32,
    request_id: u64,
) -> wire::Request {
    let mut request = wire::Request::new(context, binding, request_id, wire::Action::Readback);
    request.operation = OPERATION.into();
    request
}

pub(super) fn require_request(
    observed: &wire::Request,
    context: &OriginalCircuitSelectionCommandContextV1,
    request_id: u64,
    current: u64,
) -> Result<(), Error> {
    let expected = request(context, context_binding(context, current)?, request_id);
    if observed.schema != expected.schema
        || observed.operation != OPERATION
        || observed.request_id != request_id
        || !(1..=128).contains(&request_id)
        || observed.binding != expected.binding
        || observed.operation_id != expected.operation_id
        || observed.training_head != expected.training_head
        || observed.scope_binding != expected.scope_binding
        || observed.actor_id != expected.actor_id
        || observed.action != wire::Action::Readback
    {
        return Err(Error::Binding(
            "same original read-only Selector purpose and context",
        ));
    }
    Ok(())
}
