//! A separate evaluated S command purpose. No request supplies an observation,
//! future cut, signing payload, Model selection or FinalUse capability.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Context;
use super::Error;
use super::evidence_wire;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str =
    "runtime.learning.original-circuit.evaluated-selection.command.v1";

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
    pub evaluation_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub action: Action,
}

impl Request {
    pub(super) fn new(
        context: &Context,
        binding: Digest32,
        request_id: u64,
        action: Action,
    ) -> Self {
        let snapshot = context.original.snapshot();
        let (scope, _, _) = context.original.receipt_configuration();
        Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            operation_id: snapshot.request.operation_id.to_string(),
            evaluation_head: snapshot.head_digest.to_string(),
            scope_binding: scope.binding().to_string(),
            actor_id: snapshot.owners.selector.to_string(),
            action,
        }
    }

    pub(super) fn require_context(
        &self,
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        let actual = Self::new(context, binding, request_id, self.action);
        if self.schema != actual.schema
            || self.operation != actual.operation
            || self.request_id != request_id
            || !(1..=128).contains(&request_id)
            || self.binding != actual.binding
            || self.operation_id != actual.operation_id
            || self.evaluation_head != actual.evaluation_head
            || self.scope_binding != actual.scope_binding
            || self.actor_id != actual.actor_id
        {
            return Err(Error::Binding(
                "same original evaluated Selector command context",
            ));
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
    pub evaluation_head: String,
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
            evaluation_head: request.evaluation_head.clone(),
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
            || self.evaluation_head != request.evaluation_head
            || self.scope_binding != request.scope_binding
            || self.actor_id != request.actor_id
            || self.action != request.action
        {
            return Err(Error::Binding("same original evaluated Selector response"));
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
    context: &Context,
    original: &OriginalCircuitEvaluatedSelectionReceiptV1,
    current: u64,
) -> Result<CommandResult, Error> {
    let checked = authenticate_completed(
        context,
        original.snapshot().clone(),
        original.attestation().clone(),
        current,
    )?;
    if !same_original(original, &checked) {
        return Err(Error::Binding("same original evaluated Selector output"));
    }
    Ok(CommandResult::Completed {
        snapshot: STANDARD_NO_PAD.encode(encode_original_owner_snapshot_v1(original.snapshot())?),
        evidence: evidence_wire::Evidence::from_original(original.attestation()),
    })
}

pub(super) fn decode_completed(
    context: &Context,
    snapshot: String,
    evidence: evidence_wire::Evidence,
    current: u64,
) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
    if snapshot.len() > 10_924 {
        return Err(Error::Binding("bounded original evaluated Selection cut"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(&snapshot)
        .map_err(|_| Error::Binding("original evaluated Selection cut encoding"))?;
    if STANDARD_NO_PAD.encode(&bytes) != snapshot {
        return Err(Error::Binding("canonical original evaluated Selection cut"));
    }
    let completed = decode_original_owner_snapshot_v1(&bytes)?;
    let signed = evidence
        .decode()
        .map_err(|_| Error::Binding("original evaluated Selector signature encoding"))?;
    authenticate_completed(context, completed, signed, current)
}

pub(super) fn authenticate_completed(
    context: &Context,
    snapshot: LearningIterationSnapshotV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
    context.authenticate(current)?;
    Ok(
        OriginalCircuitEvaluatedSelectionReceiptV1::authenticate_original_command_response(
            context.original.clone_for_original_receipt(),
            snapshot,
            signed,
            current,
        )?,
    )
}

pub(super) fn same_original(
    left: &OriginalCircuitEvaluatedSelectionReceiptV1,
    right: &OriginalCircuitEvaluatedSelectionReceiptV1,
) -> bool {
    left.snapshot() == right.snapshot()
        && left.receipt() == right.receipt()
        && left.attestation() == right.attestation()
        && left.original_receipt_binding() == right.original_receipt_binding()
}
