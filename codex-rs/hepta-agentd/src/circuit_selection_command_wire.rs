//! The fixed Selector command wire. Requests carry no observations or cut.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCircuitSelectionCommandContextV1;
use super::OriginalCircuitSelectionCommandReceiptV1;
use super::evidence_wire;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-circuit-selection.command.v1";

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
    pub training_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
}
impl Request {
    pub(super) fn new(
        context: &OriginalCircuitSelectionCommandContextV1,
        binding: Digest32,
        request_id: u64,
        action: Action,
    ) -> Self {
        Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            operation_id: context.training.request.operation_id.to_string(),
            training_head: context.training.head_digest.to_string(),
            scope_binding: context.scope.binding().to_string(),
            actor_id: context.training.owners.selector.to_string(),
            action,
        }
    }

    pub(super) fn require_context(
        &self,
        context: &OriginalCircuitSelectionCommandContextV1,
        binding: Digest32,
        next_request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1
            || self.operation != OPERATION
            || self.request_id != next_request_id
            || !(1..=128).contains(&self.request_id)
            || self.binding != binding.to_string()
            || self.operation_id != context.training.request.operation_id.as_str()
            || self.training_head != context.training.head_digest.to_string()
            || self.scope_binding != context.scope.binding().to_string()
            || self.actor_id != context.training.owners.selector.as_str()
        {
            return Err(Error::Binding("same original Selector command context"));
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
    pub training_head: String,
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
            training_head: request.training_head.clone(),
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
            || self.training_head != request.training_head
            || self.scope_binding != request.scope_binding
            || self.actor_id != request.actor_id
            || self.action != request.action
        {
            return Err(Error::Binding("same original Selector response"));
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
    context: &OriginalCircuitSelectionCommandContextV1,
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
    context: &OriginalCircuitSelectionCommandContextV1,
    snapshot: String,
    evidence: evidence_wire::Evidence,
    current: u64,
) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
    if snapshot.len() > 10_924 {
        return Err(Error::Binding("bounded original Selection cut"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(&snapshot)
        .map_err(|_| Error::Binding("original Selection cut encoding"))?;
    if STANDARD_NO_PAD.encode(&bytes) != snapshot {
        return Err(Error::Binding("canonical original Selection cut"));
    }
    let completed = decode_original_owner_snapshot_v1(&bytes)?;
    let signed = evidence
        .decode()
        .map_err(|_| Error::Binding("original Selector encoding"))?;
    authenticate_completed(context, completed, signed, current)
}

pub(super) fn authenticate_completed(
    context: &OriginalCircuitSelectionCommandContextV1,
    snapshot: LearningIterationSnapshotV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
    if snapshot.request != context.training.request
        || snapshot.owners != context.training.owners
        || snapshot.receipts.len() != context.training.receipts.len() + 1
        || snapshot.receipts[..context.training.receipts.len()] != context.training.receipts
    {
        return Err(Error::Binding("one original Selection extension"));
    }
    let receipt = snapshot
        .receipts
        .last()
        .ok_or(Error::Binding("original Selection receipt"))?
        .clone();
    let original = authenticate_receipt(context, receipt, signed, current)?;
    if original.snapshot != snapshot {
        return Err(Error::Binding("exact original Selection snapshot"));
    }
    Ok(original)
}

pub(super) fn authenticate_receipt(
    context: &OriginalCircuitSelectionCommandContextV1,
    receipt: LearningIterationReceiptV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
    let training = context.authenticate(current)?;
    let baseline = context
        .training
        .request
        .selected_bundle
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    if !matches!(&receipt.observation,
        LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if *candidate_bundle == baseline)
        || receipt.operation_id != context.training.request.operation_id
        || receipt.actor_id != context.training.owners.selector
        || receipt.predecessor != context.training.head_digest
        || receipt.observed_unix_seconds != signed.issued_at
        || receipt.observed_unix_seconds > current
    {
        return Err(Error::Binding(
            "original retained-model Selection actor and time",
        ));
    }
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(context.training.clone())?;
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    context.scope.validate_snapshot(coordinator.snapshot())?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::NextUse) {
        return Err(Error::Binding("original Selection before C"));
    }
    let selector = context.verifier.verify(
        LearningEvidenceRoleV1::Selector,
        &signed,
        &learning_iteration_receipt_signing_bytes_v1(&receipt)?,
        current,
    )?;
    if selector.principal().principal_id != context.training.owners.selector {
        return Err(Error::Binding("original enrolled Selector"));
    }
    verify_signed_actor_separation(&training, &selector, current)?;
    Ok(OriginalCircuitSelectionCommandReceiptV1 {
        snapshot: coordinator.snapshot().clone(),
        receipt,
        attestation: signed,
        training_evidence: context.training_evidence.clone(),
    })
}
