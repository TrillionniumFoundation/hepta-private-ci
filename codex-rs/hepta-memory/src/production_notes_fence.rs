//! A new, exact authorized effect that fences one original Notes request.

use super::*;

pub const NOTES_FENCE_TOPIC_V1: &str = "trill.notes.fence.v1";

pub(crate) fn is_notes_topic(topic: &str) -> bool {
    matches!(topic, NOTES_REPLACE_TOPIC_V1 | NOTES_FENCE_TOPIC_V1)
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NotesFence {
    schema_version: u16,
    action: FenceAction,
    operation_id: String,
    destination_id: String,
    target: NotesTargetIdentity,
    original_operation_id: String,
    original_payload_sha256: String,
    expected_revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum FenceAction { FenceNoteOperation }

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FenceResponse {
    schema_version: u16,
    target: NotesTargetIdentity,
    operation_id: String,
    payload_sha256: String,
    result: FenceResult,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum FenceResult {
    Fenced {
        original_operation_id: String,
        original_payload_sha256: String,
        previous_revision: u64,
        revision: u64,
        text_sha256: String,
    },
    NotFenced { reason: NotAppliedReason, current_revision: u64 },
    Unknown { current_revision: u64 },
}

pub(super) fn fence_intent(
    target: &NotesTargetIdentity,
    raw: &str,
    subject: StableId,
    generation: Generation,
) -> Result<(NotesFence, OperationIntentV1), String> {
    if raw.is_empty() || raw.len() > NOTES_REQUEST_MAX_BYTES {
        return Err("Notes fence request exceeds its bound".into());
    }
    target.validate()?;
    let parsed: NotesFence = serde_json::from_str(raw).map_err(|_| "invalid Notes fence schema")?;
    if parsed.schema_version != 1 || parsed.target != *target
        || parsed.destination_id != target.destination_id()
        || StableId::new(&parsed.original_operation_id).is_err()
        || parsed.operation_id == parsed.original_operation_id
        || !lower_hex(&parsed.original_payload_sha256, 64)
    { return Err("Notes fence original binding mismatch".into()); }
    let intent = OperationIntentV1::new(
        StableId::new(&parsed.operation_id).map_err(|e| e.to_string())?, subject,
        StableId::new(target.destination_id()).map_err(|e| e.to_string())?,
        Digest32::of_bytes(raw.as_bytes()), target.scope_digest(), generation,
        Some(target.predecessor_digest(parsed.expected_revision)),
    ).map_err(|e| e.to_string())?;
    Ok((parsed, intent))
}

fn fence_response(
    target: &NotesTargetIdentity, raw: &[u8], request: &NotesFence, digest: &str,
) -> Result<(FenceResult, String), String> {
    if raw.is_empty() || raw.len() > NOTES_RESPONSE_MAX_BYTES { return Err("Notes fence response bound".into()); }
    let response: FenceResponse = serde_json::from_slice(raw).map_err(|_| "invalid Notes fence response")?;
    if response.schema_version != 1 || response.target != *target
        || response.operation_id != request.operation_id || response.payload_sha256 != digest
    { return Err("Notes fence response identity mismatch".into()); }
    if let FenceResult::Fenced {
        original_operation_id, original_payload_sha256, previous_revision, revision, text_sha256,
    } = &response.result
        && (original_operation_id != &request.original_operation_id
            || original_payload_sha256 != &request.original_payload_sha256
            || *previous_revision != request.expected_revision
            || previous_revision.checked_add(1) != Some(*revision)
            || !lower_hex(text_sha256, 64))
    { return Err("Notes fence does not prove original request exclusion".into()); }
    Ok((response.result, String::from_utf8(raw.to_vec()).map_err(|_| "Notes fence receipt UTF-8")?))
}

pub(super) fn terminal_receipt(payload: &str, evidence: &str) -> Result<NotesTerminalReceipt, String> {
    let target: serde_json::Value = serde_json::from_str(payload).map_err(|_| "invalid fence payload")?;
    let target: NotesTargetIdentity = serde_json::from_value(target["target"].clone()).map_err(|_| "invalid fence target")?;
    let (parsed, _) = fence_intent(&target, payload, StableId::new("receipt-check").map_err(|e| e.to_string())?, Generation::new(1).map_err(|e| e.to_string())?)?;
    let (result, raw) = fence_response(&target, evidence.as_bytes(), &parsed, Sha256Digest::for_bytes(payload.as_bytes()).as_str())?;
    let outcome = match result {
        FenceResult::Fenced { .. } => crate::LocalReconcileOutcome::Committed,
        FenceResult::NotFenced { .. } => crate::LocalReconcileOutcome::Rejected,
        FenceResult::Unknown { .. } => return Err("unknown fence observation is not terminal".into()),
    };
    Ok(NotesTerminalReceipt { raw, outcome })
}

impl NotesTerminalReceipt {
    /// Validated document lower bound from either an applied edit or a fence.
    pub(crate) fn document_state(&self) -> Result<(NotesTargetIdentity, u64, Sha256Digest), String> {
        if let Ok(value) = serde_json::from_str::<NotesResponse>(&self.raw) {
            return match value.result {
                NotesResult::Applied { revision, text_sha256, .. } => Ok((value.target, revision, Sha256Digest::parse(&text_sha256).map_err(|e| e.to_string())?)),
                NotesResult::NotApplied { .. } | NotesResult::Unknown { .. } => Err("receipt has no committed document state".into()),
            };
        }
        let value: FenceResponse = serde_json::from_str(&self.raw).map_err(|_| "invalid fence receipt")?;
        match value.result {
            FenceResult::Fenced { revision, text_sha256, .. } => Ok((value.target, revision, Sha256Digest::parse(&text_sha256).map_err(|e| e.to_string())?)),
            FenceResult::NotFenced { .. } | FenceResult::Unknown { .. } => Err("fence has no committed document state".into()),
        }
    }
}

impl ProductionNotesTarget {
    pub(super) fn decode_fence(&self, request: &ProductionDispatchRequest) -> Result<NotesFence, String> {
        let (parsed, intent) = fence_intent(&self.identity, &request.payload_json,
            StableId::new(&request.operation_subject_id).map_err(|e| e.to_string())?,
            Generation::new(request.operation_policy_generation).map_err(|e| e.to_string())?)?;
        if request.schema_version != crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != crate::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != NOTES_FENCE_TOPIC_V1
            || request.operation_destination_id != self.destination
            || request.occurrence_key != parsed.operation_id || request.idempotency_key != parsed.operation_id
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
            || request.expected_predecessor_sha256.as_ref().map(Sha256Digest::as_str)
                != Some(self.identity.predecessor_digest(parsed.expected_revision).to_string().as_str())
        { return Err("Notes fence differs from original durable operation".into()); }
        Ok(parsed)
    }

    pub(super) fn dispatch_fence(&self, request: ProductionDispatchRequest) -> ProductionTargetOutcome {
        let parsed = match self.decode_fence(&request) { Ok(v) => v, Err(reason) => return ProductionTargetOutcome::Rejected { reason } };
        match self.channel.exchange(request.payload_json.as_bytes()).and_then(|raw| fence_response(&self.identity, &raw, &parsed, request.payload_sha256.as_str())) {
            Ok((FenceResult::Fenced { .. }, receipt)) => ProductionTargetOutcome::Committed { receipt },
            Ok((FenceResult::NotFenced { .. }, reason)) => ProductionTargetOutcome::NotApplied { reason },
            Ok((FenceResult::Unknown { .. }, _)) => { self.channel.invalidate(); ProductionTargetOutcome::Indeterminate { reason: "fence receipt unavailable".into() } },
            Err(reason) => { self.channel.invalidate(); ProductionTargetOutcome::Indeterminate { reason } },
        }
    }

    pub(super) fn observe_fence(&self, request: &ProductionDispatchRequest) -> ProductionTerminalObservation {
        let parsed = match self.decode_fence(request) { Ok(v) => v, Err(reason) => return ProductionTerminalObservation::Unavailable { reason } };
        let query = serde_json::json!({"schema_version":1,"action":"observe_fence","target":self.identity,
            "operation_id":parsed.operation_id,"payload_sha256":request.payload_sha256.as_str()});
        match serde_json::to_vec(&query).map_err(|e| e.to_string()).and_then(|raw| self.channel.recovery_exchange(&raw))
            .and_then(|raw| fence_response(&self.identity, &raw, &parsed, request.payload_sha256.as_str()))
        {
            Ok((FenceResult::Fenced { .. }, receipt)) => ProductionTerminalObservation::Applied { receipt },
            Ok((FenceResult::NotFenced { .. } | FenceResult::Unknown { .. }, _)) => ProductionTerminalObservation::Indeterminate { reason: "no retained fence receipt".into() },
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
        }
    }
}

pub(crate) fn cancellation_payload(original: &crate::ProductionRetainedOperation, cancel_id: &str) -> Result<(String, OperationIntentV1), String> {
    if original.topic != NOTES_REPLACE_TOPIC_V1 { return Err("cancellation requires an original Notes replacement".into()); }
    let value: serde_json::Value = serde_json::from_str(&original.payload_json).map_err(|_| "invalid original Notes payload")?;
    let target: NotesTargetIdentity = serde_json::from_value(value["target"].clone()).map_err(|_| "invalid original Notes target")?;
    let parsed = parse_replace(&target, &original.payload_json)?;
    let exact = notes_operation_intent(&target, &original.payload_json, original.operation.subject_id().clone(), original.operation.policy_generation())?;
    if exact != original.operation { return Err("cancellation original operation mismatch".into()); }
    let raw = serde_json::to_string(&NotesFence { schema_version: 1, action: FenceAction::FenceNoteOperation,
        operation_id: cancel_id.to_owned(), destination_id: target.destination_id(), target: target.clone(),
        original_operation_id: parsed.operation_id, original_payload_sha256: Sha256Digest::for_bytes(original.payload_json.as_bytes()).to_string(), expected_revision: parsed.expected_revision,
    }).map_err(|e| e.to_string())?;
    let (_, intent) = fence_intent(&target, &raw, original.operation.subject_id().clone(), original.operation.policy_generation())?;
    Ok((raw, intent))
}

#[cfg(test)]
#[path = "production_notes_fence_tests.rs"]
mod tests;
