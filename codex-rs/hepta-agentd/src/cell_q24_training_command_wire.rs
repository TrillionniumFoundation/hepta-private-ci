//! Fixed command records. Only responses contain a completed original cut.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::evidence_wire;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-q24-training.command.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action {
    Execute,
    Readback,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub operation_id: String,
    pub dataset_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
    pub cancelled: bool,
}

impl Request {
    pub(super) fn new(
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        request_id: u64,
        action: Action,
        cancelled: bool,
    ) -> Self {
        Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            operation_id: context.dataset.request.operation_id.to_string(),
            dataset_head: context.dataset.head_digest.to_string(),
            scope_binding: context.scope.binding().to_string(),
            actor_id: context.dataset.owners.trainer.to_string(),
            action,
            cancelled,
        }
    }

    pub(super) fn require_context(
        &self,
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        next_request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1
            || self.operation != OPERATION
            || self.request_id != next_request_id
            || self.binding != binding.to_string()
            || self.operation_id != context.dataset.request.operation_id.as_str()
            || self.dataset_head != context.dataset.head_digest.to_string()
            || self.scope_binding != context.scope.binding().to_string()
            || self.actor_id != context.dataset.owners.trainer.as_str()
            || (self.action == Action::Readback && self.cancelled)
        {
            return Err(Error::Binding("same original Trainer command context"));
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
    pub dataset_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
    pub result: CommandResult,
}

impl Response {
    pub(super) fn from_request(request: &Request, result: CommandResult) -> Self {
        Self {
            schema: request.schema,
            operation: request.operation.clone(),
            request_id: request.request_id,
            binding: request.binding.clone(),
            operation_id: request.operation_id.clone(),
            dataset_head: request.dataset_head.clone(),
            scope_binding: request.scope_binding.clone(),
            actor_id: request.actor_id.clone(),
            action: request.action,
            result,
        }
    }

    pub(super) fn require_request(&self, request: &Request) -> Result<(), Error> {
        if self.schema != request.schema
            || self.operation != request.operation
            || self.request_id != request.request_id
            || self.binding != request.binding
            || self.operation_id != request.operation_id
            || self.dataset_head != request.dataset_head
            || self.scope_binding != request.scope_binding
            || self.actor_id != request.actor_id
            || self.action != request.action
        {
            return Err(Error::Binding("same original Trainer response"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum CommandResult {
    Completed {
        snapshot: String,
        evidence: evidence_wire::Evidence,
    },
    Missing,
    Pending,
    Busy,
    Expired,
    ReadbackRequired,
    Uncertain,
    Unavailable,
}

pub(super) fn encode_completed(
    context: &OriginalCellQ24TrainingCommandContextV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    at: u64,
) -> Result<CommandResult, Error> {
    let completed = authenticate_receipt(context, receipt, attestation, at)?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(context.dataset.clone())?;
    coordinator.record(
        completed.receipt.clone(),
        completed.receipt.observed_unix_seconds,
    )?;
    let bytes = encode_original_owner_snapshot_v1(coordinator.snapshot())?;
    Ok(CommandResult::Completed {
        snapshot: STANDARD_NO_PAD.encode(bytes),
        evidence: evidence_wire::Evidence::from_original(&completed.attestation),
    })
}

pub(super) fn decode_completed(
    context: &OriginalCellQ24TrainingCommandContextV1,
    snapshot: String,
    evidence: evidence_wire::Evidence,
    at: u64,
) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
    if snapshot.len() > 10_924 {
        return Err(Error::Binding("bounded original Training cut"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(&snapshot)
        .map_err(|_| Error::Binding("original Training cut encoding"))?;
    if STANDARD_NO_PAD.encode(&bytes) != snapshot {
        return Err(Error::Binding("canonical original Training cut"));
    }
    let completed = decode_original_owner_snapshot_v1(&bytes)?;
    require_exact_extension(context, &completed)?;
    let receipt = completed
        .receipts
        .last()
        .ok_or(Error::Binding("original Training receipt"))?;
    let attestation = evidence
        .decode()
        .map_err(|_| Error::Binding("original Generator encoding"))?;
    authenticate_receipt(context, receipt.clone(), attestation, at)
}

fn require_exact_extension(
    context: &OriginalCellQ24TrainingCommandContextV1,
    completed: &LearningIterationSnapshotV1,
) -> Result<(), Error> {
    if completed.request != context.dataset.request
        || completed.owners != context.dataset.owners
        || completed.receipts.len() != context.dataset.receipts.len() + 1
        || completed.receipts[..context.dataset.receipts.len()] != context.dataset.receipts
    {
        return Err(Error::Binding("one original Training extension"));
    }
    context.scope.validate_snapshot(completed)?;
    Ok(())
}

pub(super) fn authenticate_receipt(
    context: &OriginalCellQ24TrainingCommandContextV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    at: u64,
) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
    context.validate()?;
    if receipt.observation.stage() != LearningIterationStageV1::Training
        || receipt.operation_id != context.dataset.request.operation_id
        || receipt.actor_id != context.dataset.owners.trainer
        || receipt.predecessor != context.dataset.head_digest
        || receipt.observed_unix_seconds != attestation.issued_at
        || receipt.observed_unix_seconds > at
    {
        return Err(Error::Binding("original Training actor and time"));
    }
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(context.dataset.clone())?;
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    context.scope.validate_snapshot(coordinator.snapshot())?;
    let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)?;
    let verified = context.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &attestation,
        &payload,
        at,
    )?;
    if verified.principal().principal_id != context.dataset.owners.trainer {
        return Err(Error::Binding("original enrolled Generator"));
    }
    Ok(OriginalCellQ24TrainingCommandReceiptV1 {
        receipt,
        attestation,
    })
}
