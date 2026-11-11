//! The fixed Observer command wire. No request can carry a C task, execution,
//! observation, predecessor cut, signature payload or replacement publication.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCircuitNextUseCommandContextV1;
use super::OriginalCircuitNextUseCommandReceiptV1;
use super::evidence_wire;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-circuit-next-use.command.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action { Execute, Readback }

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub operation_id: String,
    pub selection_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
}
impl Request {
    pub(super) fn new(
        context: &OriginalCircuitNextUseCommandContextV1,
        binding: Digest32,
        request_id: u64,
        action: Action,
    ) -> Self {
        Self {
            schema: 1, operation: OPERATION.into(), request_id, binding: binding.to_string(),
            operation_id: context.selection.request.operation_id.to_string(),
            selection_head: context.selection.head_digest.to_string(),
            scope_binding: context.scope.binding().to_string(),
            actor_id: context.selection.owners.next_use_observer.to_string(), action,
        }
    }

    pub(super) fn require_context(
        &self, context: &OriginalCircuitNextUseCommandContextV1,
        binding: Digest32, next_request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1 || self.operation != OPERATION
            || self.request_id != next_request_id || !(1..=128).contains(&self.request_id)
            || self.binding != binding.to_string()
            || self.operation_id != context.selection.request.operation_id.as_str()
            || self.selection_head != context.selection.head_digest.to_string()
            || self.scope_binding != context.scope.binding().to_string()
            || self.actor_id != context.selection.owners.next_use_observer.as_str()
        {
            return Err(Error::Binding("same original C Observer command context"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub operation_id: String,
    pub selection_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
    pub result: CommandResult,
}
impl Response {
    pub(super) fn from_request(request: &Request, result: CommandResult) -> Self {
        Self {
            schema: request.schema, operation: request.operation.clone(),
            request_id: request.request_id, binding: request.binding.clone(),
            operation_id: request.operation_id.clone(), selection_head: request.selection_head.clone(),
            scope_binding: request.scope_binding.clone(), actor_id: request.actor_id.clone(),
            action: request.action, result,
        }
    }
    pub(super) fn require_request(&self, request: &Request) -> Result<(), Error> {
        if self.schema != request.schema || self.operation != request.operation
            || self.request_id != request.request_id || self.binding != request.binding
            || self.operation_id != request.operation_id || self.selection_head != request.selection_head
            || self.scope_binding != request.scope_binding || self.actor_id != request.actor_id
            || self.action != request.action
        {
            return Err(Error::Binding("same original C Observer response"));
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum CommandResult {
    Completed { snapshot: String, evidence: evidence_wire::Evidence },
    Missing, Pending, Busy, Expired, ReadbackRequired, Uncertain, Unavailable,
}

pub(super) fn encode_completed(
    context: &OriginalCircuitNextUseCommandContextV1,
    receipt: LearningIterationReceiptV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<CommandResult, Error> {
    let original = authenticate_receipt(context, receipt, signed, current)?;
    let encoded = encode_original_owner_snapshot_v1(&original.snapshot)?;
    Ok(CommandResult::Completed {
        snapshot: STANDARD_NO_PAD.encode(encoded),
        evidence: evidence_wire::Evidence::from_original(&original.attestation),
    })
}

pub(super) fn decode_completed(
    context: &OriginalCircuitNextUseCommandContextV1,
    snapshot: String,
    evidence: evidence_wire::Evidence,
    current: u64,
) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
    if snapshot.len() > 10_924 {
        return Err(Error::Binding("bounded original NextUse cut"));
    }
    let bytes = STANDARD_NO_PAD.decode(&snapshot)
        .map_err(|_| Error::Binding("original NextUse cut encoding"))?;
    if STANDARD_NO_PAD.encode(&bytes) != snapshot {
        return Err(Error::Binding("canonical original NextUse cut"));
    }
    let completed = decode_original_owner_snapshot_v1(&bytes)?;
    let signed = evidence.decode().map_err(|_| Error::Binding("original C Observer encoding"))?;
    authenticate_completed(context, completed, signed, current)
}

pub(super) fn authenticate_completed(
    context: &OriginalCircuitNextUseCommandContextV1,
    snapshot: LearningIterationSnapshotV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
    if snapshot.request != context.selection.request
        || snapshot.owners != context.selection.owners
        || snapshot.receipts.len() != context.selection.receipts.len() + 1
        || snapshot.receipts[..context.selection.receipts.len()] != context.selection.receipts
    {
        return Err(Error::Binding("one original NextUse extension"));
    }
    let receipt = snapshot.receipts.last()
        .ok_or(Error::Binding("original NextUse receipt"))?.clone();
    let original = authenticate_receipt(context, receipt, signed, current)?;
    if original.snapshot != snapshot {
        return Err(Error::Binding("exact original NextUse snapshot"));
    }
    Ok(original)
}

pub(super) fn authenticate_receipt(
    context: &OriginalCircuitNextUseCommandContextV1,
    receipt: LearningIterationReceiptV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
    let predecessors = context.authenticate(current)?;
    let baseline = context.selection.request.selected_bundle.digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let selected = &context.selection.receipts[3].observation;
    if !matches!(&receipt.observation,
        LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle, state_partition, checkpoint_digest, selection_digest,
            committed_step_receipt, task_owner_publication,
        } if *retained_bundle == baseline
            && state_partition.principal_id == context.selection.request.principal_id
            && state_partition.agent_id == context.selection.request.agent_id
            && state_partition.cell_id == context.selection.request.cell_id
            && state_partition.run_id != context.selection.request.source_run_id
            && !checkpoint_digest.is_zero()
            && !committed_step_receipt.is_zero()
            && !task_owner_publication.is_zero()
            && matches!(selected, LearningIterationObservationV1::Selection {
                candidate_bundle, selection_digest: original_selection,
            } if *candidate_bundle == baseline && original_selection == selection_digest))
        || receipt.operation_id != context.selection.request.operation_id
        || receipt.actor_id != context.selection.owners.next_use_observer
        || receipt.predecessor != context.selection.head_digest
        || receipt.observed_unix_seconds != signed.issued_at
        || receipt.observed_unix_seconds > current
    {
        return Err(Error::Binding("actual retained C completion, actor and time"));
    }
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(context.selection.clone())?;
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    context.scope.validate_snapshot(coordinator.snapshot())?;
    if coordinator.next_stage().is_some()
        || coordinator.next_task_bundle() != Some(&context.selection.request.selected_bundle)
    {
        return Err(Error::Binding("completed original retained C"));
    }
    let observer = context.verifier.verify(
        LearningEvidenceRoleV1::Observer, &signed,
        &learning_iteration_receipt_signing_bytes_v1(&receipt)?, current,
    )?;
    if observer.principal().principal_id != context.selection.owners.next_use_observer {
        return Err(Error::Binding("original enrolled C Observer"));
    }
    for predecessor in &predecessors {
        verify_signed_actor_separation(predecessor, &observer, current)?;
    }
    Ok(OriginalCircuitNextUseCommandReceiptV1 {
        snapshot: coordinator.snapshot().clone(), receipt, attestation: signed,
        training_evidence: context.training_evidence.clone(),
        selection_evidence: context.selection_evidence.clone(),
    })
}
