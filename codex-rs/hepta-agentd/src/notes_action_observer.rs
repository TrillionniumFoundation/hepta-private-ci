//! ACT-2 projection over the original Notes owner and a fresh application read.
//! No process state, input wait, partial write or late-commit exclusion is
//! inferred from a document revision, source outcome or receipt-retirement flag.

use codex_hepta_automation::ActionGoalStateV1;
use codex_hepta_automation::ActionRuntimeStateV1;
use codex_hepta_automation::ActionTerminalOutcomeV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NOTES_REPLACE_TOPIC_V1;
use codex_hepta_memory::NOTES_REQUEST_MAX_BYTES;
use codex_hepta_memory::NOTES_RESPONSE_MAX_BYTES;
use codex_hepta_memory::NotesDocumentState;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionRetainedOperation;
use codex_hepta_memory::notes_operation_intent;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct NotesActionDocumentV1 {
    target: NotesTargetIdentity,
    revision: u64,
    text_sha256: Sha256Digest,
    receipt_pending: bool,
}

impl From<&NotesDocumentState> for NotesActionDocumentV1 {
    fn from(state: &NotesDocumentState) -> Self {
        Self {
            target: state.target.clone(),
            revision: state.revision,
            text_sha256: state.text_sha256.clone(),
            receipt_pending: state.receipt_pending,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum HistoricalNotesEffectV1 {
    Applied,
    NotApplied,
    Unknown,
}

#[derive(Debug, Eq, PartialEq, Serialize)]
pub(crate) struct NotesActionObservationV1 {
    schema_version: u16,
    operation_id: String,
    payload_sha256: Sha256Digest,
    original_target: NotesTargetIdentity,
    expected_revision: u64,
    goal_revision: Option<u64>,
    expected_text_sha256: Sha256Digest,
    historical_effect: HistoricalNotesEffectV1,
    terminal_receipt_sha256: Option<Sha256Digest>,
    current_document: Option<NotesActionDocumentV1>,
    current_goal: ActionGoalStateV1,
    runtime_state: ActionRuntimeStateV1,
}

// The existing Notes parser validates the complete original payload first.
#[derive(Deserialize)]
struct Goal {
    target: NotesTargetIdentity,
    expected_revision: u64,
    text: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    schema_version: u16,
    target: NotesTargetIdentity,
    operation_id: String,
    payload_sha256: Sha256Digest,
    result: ReceiptResult,
}

#[derive(Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum ReceiptResult {
    Applied {
        previous_revision: u64,
        revision: u64,
        text_sha256: Sha256Digest,
    },
    NotApplied {
        reason: String,
        current_revision: u64,
    },
}

/// Shared result assembly for the product status/replace return path. The
/// owner reads its retained operation and receipt; the current document comes
/// from this call's fresh application observation, never a retained result.
pub(crate) fn original_notes_status(
    original: &ProductionRetainedOperation,
    receipt: Option<&str>,
    current: Option<&NotesDocumentState>,
    request_sha256: Option<&str>,
    provenance: Value,
    sender_observation_retained: Option<bool>,
) -> Result<Value, AgentdError> {
    let action = observe_notes_action(original, receipt, current)?;
    Ok(json!({
        "source_domain":provenance["kind"], "provenance":provenance,
        "operation_id":original.operation.operation_id().as_str(),
        "semantic_sha256":original.operation.semantic_digest().to_string(),
        "exact_request_sha256":request_sha256,
        "sender_observation_retained":sender_observation_retained,
        "state":format!("{:?}",original.state), "receipt_utf8":receipt,
        "original_target":action.original_target,
        "current_document_readback_available":current.is_some(),
        "current_document":current.map(NotesActionDocumentV1::from),
        "action_observation":action,
    }))
}

/// Project the original model-facing tool success bit from this call's trusted
/// result assembly. Reading a document is separate from confirming a write's
/// current goal; a historical committed receipt alone cannot confirm that goal.
pub(crate) fn original_notes_tool_succeeded(tool: &str, value: &Value) -> bool {
    if value["write_admission"] == "refused_later_replace_in_original_turn"
        || value["status"] == "unknown"
    {
        return false;
    }
    match tool {
        crate::notes_thread_tool::READ_TOOL => true,
        crate::notes_thread_tool::REPLACE_TOOL | crate::notes_thread_tool::STATUS_TOOL => {
            value["state"] == "Committed"
                && value["receipt_utf8"].is_string()
                && value["action_observation"]["current_goal"]
                    == json!(ActionGoalStateV1::Satisfied)
                && value["action_observation"]["runtime_state"]
                    == json!(ActionRuntimeStateV1::Terminal {
                        outcome: ActionTerminalOutcomeV1::Succeeded
                    })
        }
        _ => false,
    }
}

/// `current` is queried on the existing nonce-correlated application lane in
/// the same status call, never restored from a checkpoint. A retained receipt
/// proves a historical effect; only matching current target/revision/content
/// also confirms this exact goal now. This projection cannot settle or retry.
pub(crate) fn observe_notes_action(
    original: &ProductionRetainedOperation,
    receipt: Option<&str>,
    current: Option<&NotesDocumentState>,
) -> Result<NotesActionObservationV1, AgentdError> {
    if original.payload_json.len() > NOTES_REQUEST_MAX_BYTES {
        return Err(invalid("ACT Notes original request exceeds its bound"));
    }
    let goal: Goal = serde_json::from_str(&original.payload_json)?;
    let operation = notes_operation_intent(
        &goal.target,
        &original.payload_json,
        original.operation.subject_id().clone(),
        original.operation.policy_generation(),
    )
    .map_err(|error| invalid(&error))?;
    if original.topic != NOTES_REPLACE_TOPIC_V1 || operation != original.operation {
        return Err(invalid(
            "ACT Notes observation differs from the original operation",
        ));
    }
    let operation_id = operation.operation_id().as_str();
    let payload_sha256 = Sha256Digest::for_bytes(original.payload_json.as_bytes());
    let expected_text_sha256 = Sha256Digest::for_bytes(goal.text.as_bytes());
    let goal_revision = goal.expected_revision.checked_add(1);
    let historical_effect = if let Some(raw) = receipt {
        if raw.len() > NOTES_RESPONSE_MAX_BYTES {
            return Err(invalid("ACT Notes retained receipt exceeds its bound"));
        }
        let receipt: Receipt = serde_json::from_str(raw)?;
        if receipt.schema_version != 1
            || receipt.target != goal.target
            || receipt.operation_id != operation_id
            || receipt.payload_sha256 != payload_sha256
        {
            return Err(invalid("ACT Notes receipt identity mismatch"));
        }
        match receipt.result {
            ReceiptResult::Applied {
                previous_revision,
                revision,
                text_sha256,
            } => {
                if previous_revision != goal.expected_revision
                    || Some(revision) != goal_revision
                    || text_sha256 != expected_text_sha256
                {
                    return Err(invalid(
                        "ACT Notes receipt does not prove the original goal",
                    ));
                }
                HistoricalNotesEffectV1::Applied
            }
            ReceiptResult::NotApplied {
                reason,
                current_revision,
            } => {
                if !matches!(
                    reason.as_str(),
                    "revision_conflict"
                        | "operation_conflict"
                        | "revision_exhausted"
                        | "target_mismatch"
                        | "ui_deadline_elapsed"
                        | "receipt_pending"
                ) {
                    return Err(invalid("ACT Notes non-application reason is invalid"));
                }
                let _ = current_revision;
                // This old response is not a durable destination tombstone.
                HistoricalNotesEffectV1::NotApplied
            }
        }
    } else {
        HistoricalNotesEffectV1::Unknown
    };
    let current_goal = match current {
        Some(state) => {
            state.target.validate().map_err(|error| invalid(&error))?;
            Sha256Digest::parse(state.text_sha256.as_str()).map_err(|error| invalid(&error))?;
            if state.target != goal.target
                || (historical_effect == HistoricalNotesEffectV1::Applied
                    && goal_revision.is_some_and(|revision| state.revision < revision))
            {
                ActionGoalStateV1::Unknown
            } else if Some(state.revision) == goal_revision
                && state.text_sha256 == expected_text_sha256
            {
                ActionGoalStateV1::Satisfied
            } else {
                ActionGoalStateV1::Unsatisfied
            }
        }
        None => ActionGoalStateV1::Unknown,
    };
    let runtime_state = if historical_effect == HistoricalNotesEffectV1::Applied
        && current_goal == ActionGoalStateV1::Satisfied
        // Earlier nonterminal source reads can precede receipt settlement;
        // Rejected/RolledBack cannot transition to Committed in this owner.
        && matches!(original.state, LocalOutcomeState::Queued
            | LocalOutcomeState::Indeterminate | LocalOutcomeState::Committed)
    {
        ActionRuntimeStateV1::Terminal {
            outcome: ActionTerminalOutcomeV1::Succeeded,
        }
    } else {
        ActionRuntimeStateV1::Unknown
    };
    Ok(NotesActionObservationV1 {
        schema_version: 1,
        operation_id: operation_id.to_owned(),
        payload_sha256,
        original_target: goal.target,
        expected_revision: goal.expected_revision,
        goal_revision,
        expected_text_sha256,
        historical_effect,
        terminal_receipt_sha256: receipt.map(|raw| Sha256Digest::for_bytes(raw.as_bytes())),
        current_document: current.map(NotesActionDocumentV1::from),
        current_goal,
        runtime_state,
    })
}

#[cfg(test)]
#[path = "notes_action_observer_tests.rs"]
mod tests;
