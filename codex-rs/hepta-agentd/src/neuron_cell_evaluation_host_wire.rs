//! Fixed Evaluation commands. No request carries rows, a plan, an outcome,
//! Product evidence, a signature body or a claimed evaluation receipt.
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::Receipt;
use super::contract::Context;
use super::contract::authenticate_receipt;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_evidence;

const PURPOSE: &str = "runtime.learning.original-cell-evaluation.command.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action {
    Execute,
    Readback,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    schema: u8,
    purpose: String,
    pub request_id: u64,
    binding: String,
    operation_id: String,
    training_head: String,
    scope: String,
    evaluator: String,
    pub action: Action,
}
impl Request {
    pub(super) fn new(
        context: &Context,
        binding: Digest32,
        request_id: u64,
        action: Action,
    ) -> Self {
        Self {
            schema: 1,
            purpose: PURPOSE.into(),
            request_id,
            binding: binding.to_string(),
            operation_id: context.training.request.operation_id.to_string(),
            training_head: context.training.head_digest.to_string(),
            scope: context.scope.binding().to_string(),
            evaluator: context.training.owners.evaluator.to_string(),
            action,
        }
    }
    pub(super) fn require_context(
        &self,
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1
            || self.purpose != PURPOSE
            || self.request_id != request_id
            || !(1..=128).contains(&self.request_id)
            || self.binding != binding.to_string()
            || self.operation_id != context.training.request.operation_id.as_str()
            || self.training_head != context.training.head_digest.to_string()
            || self.scope != context.scope.binding().to_string()
            || self.evaluator != context.training.owners.evaluator.as_str()
        {
            return Err(Error::Binding(
                "exact original Evaluation command purpose and context",
            ));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Outcome {
    Completed {
        snapshot: String,
        original_evidence: String,
    },
    Missing,
    Pending,
    Busy,
    Expired,
    ReadbackRequired,
    PredecessorUnavailable,
    Uncertain,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    request: Request,
    pub outcome: Outcome,
}
impl Response {
    pub(super) fn new(request: Request, outcome: Outcome) -> Self {
        Self { request, outcome }
    }
    pub(super) fn require_request(&self, expected: &Request) -> Result<(), Error> {
        if self.request.schema != expected.schema
            || self.request.purpose != expected.purpose
            || self.request.request_id != expected.request_id
            || self.request.binding != expected.binding
            || self.request.operation_id != expected.operation_id
            || self.request.training_head != expected.training_head
            || self.request.scope != expected.scope
            || self.request.evaluator != expected.evaluator
            || self.request.action != expected.action
        {
            return Err(Error::Binding("same original Evaluation response"));
        }
        Ok(())
    }
}

pub(super) fn encode_completed(
    context: &Context,
    receipt: Receipt,
    current: u64,
) -> Result<Outcome, Error> {
    let checked = authenticate_completed(
        context,
        receipt.snapshot.clone(),
        receipt.attestation.clone(),
        current,
    )?;
    if checked != receipt {
        return Err(Error::Binding("exact original Evaluation result"));
    }
    let snapshot = encode_original_owner_snapshot_v1(&receipt.snapshot)?;
    let payload = learning_iteration_receipt_signing_bytes_v1(&receipt.receipt)?;
    let evidence = learning_owner_evidence::encode(&payload, &receipt.attestation)?;
    // Per-field bounds do not promise that both maxima fit in one frame.
    // The service also checks the complete encoded envelope against the
    // original 16 KiB ceiling; oversized real contexts fail closed.
    if snapshot.len() > 8192 || evidence.len() > 4096 {
        return Err(Error::Binding("bounded original Evaluation response"));
    }
    Ok(Outcome::Completed {
        snapshot: STANDARD_NO_PAD.encode(snapshot),
        original_evidence: STANDARD_NO_PAD.encode(evidence),
    })
}

pub(super) fn decode_completed(
    context: &Context,
    snapshot: String,
    original_evidence: String,
    current: u64,
) -> Result<Receipt, Error> {
    if snapshot.len() > 10_924 || original_evidence.len() > 5464 {
        return Err(Error::Binding("bounded original Evaluation encoding"));
    }
    let snapshot_bytes = STANDARD_NO_PAD
        .decode(&snapshot)
        .map_err(|_| Error::Binding("original Evaluation snapshot encoding"))?;
    let evidence_bytes = STANDARD_NO_PAD
        .decode(&original_evidence)
        .map_err(|_| Error::Binding("original Evaluation evidence encoding"))?;
    if STANDARD_NO_PAD.encode(&snapshot_bytes) != snapshot
        || STANDARD_NO_PAD.encode(&evidence_bytes) != original_evidence
    {
        return Err(Error::Binding("canonical original Evaluation encoding"));
    }
    let snapshot = decode_original_owner_snapshot_v1(&snapshot_bytes)?;
    let (payload, signed) = learning_owner_evidence::decode(&evidence_bytes)?;
    let receipt = snapshot
        .receipts
        .last()
        .ok_or(Error::Binding("original Evaluation receipt"))?;
    if payload != learning_iteration_receipt_signing_bytes_v1(receipt)? {
        return Err(Error::Binding(
            "same original Evaluation payload and full signature",
        ));
    }
    authenticate_completed(context, snapshot, signed, current)
}

pub(super) fn authenticate_completed(
    context: &Context,
    snapshot: LearningIterationSnapshotV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<Receipt, Error> {
    if snapshot.request != context.training.request
        || snapshot.owners != context.training.owners
        || snapshot.receipts.len() != context.training.receipts.len() + 1
        || !snapshot.receipts.starts_with(&context.training.receipts)
    {
        return Err(Error::Binding("one exact original Evaluation extension"));
    }
    let receipt = snapshot
        .receipts
        .last()
        .ok_or(Error::Binding("original Evaluation receipt"))?
        .clone();
    let result = authenticate_receipt(context, receipt, signed, current)?;
    if result.snapshot != snapshot {
        return Err(Error::Binding("exact original Evaluation snapshot"));
    }
    Ok(result)
}
