//! A disposable preview of one actual original model call. Stable IDs exclude
//! arguments and connection generations: changed arguments conflict at the
//! original writer instead of acquiring another execution identity.

use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallResponse;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NotesDocumentState;
use codex_hepta_memory::ProductionNotesTerminalObservation;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::json;

use crate::AgentdError;
use crate::AgentdNotesModelRoute;
use crate::notes_literal_adapter::invalid;
use crate::notes_model_route::NOTES_MODEL_MAX_TEXT_BYTES;
use crate::notes_model_route::NOTES_MODEL_NAMESPACE;
use crate::notes_model_route::NOTES_MODEL_TOOL;
use crate::notes_ui_wire::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProposedText {
    text: String,
}

pub(super) fn proposed_text(params: &DynamicToolCallParams) -> Result<String, AgentdError> {
    let proposed: ProposedText = serde_json::from_value(params.arguments.clone())?;
    if proposed.text.trim().is_empty() || proposed.text.len() > NOTES_MODEL_MAX_TEXT_BYTES {
        return Err(invalid(
            "Notes model proposal exceeds the original text bound",
        ));
    }
    Ok(proposed.text)
}

pub(super) fn proposal_id(
    agent_id: &str,
    route: &AgentdNotesModelRoute,
    params: &DynamicToolCallParams,
) -> Result<String, AgentdError> {
    if params.thread_id != route.thread_id
        || params.namespace.as_deref() != Some(NOTES_MODEL_NAMESPACE)
        || params.tool != NOTES_MODEL_TOOL
        || params.turn_id.is_empty()
        || params.turn_id.len() > 128
        || params.call_id.is_empty()
        || params.call_id.len() > 256
    {
        return Err(invalid(
            "Notes proposal differs from its sealed original route",
        ));
    }
    let identity = serde_json::to_vec(&(
        "organ.notes.model.intent.v1",
        agent_id,
        route.principal_scope_digest.to_string(),
        &route.app_server_session_id,
        &params.thread_id,
        &params.turn_id,
        &params.call_id,
    ))?;
    Ok(format!("model-{}", Digest32::of_bytes(&identity)))
}

pub(super) fn proposal_view(
    id: String,
    params: &DynamicToolCallParams,
    reviewed: Option<&NotesDocumentState>,
) -> Result<NotesModelProposalObservation, AgentdError> {
    let text = proposed_text(params)?;
    let predecessor = reviewed.map(|state| {
        json!({
            "target": state.target, "revision": state.revision,
            "text_sha256": state.text_sha256.as_str(), "receipt_pending": state.receipt_pending,
        })
    });
    let exact_preview =
        serde_json::to_vec(&("organ.notes.model.preview.v1", &id, &text, predecessor))?;
    let reviewed_document = reviewed.map(|state| NotesDocumentObservation {
        target: state.target.clone(),
        observed_unix_ms: ObjectiveObservation::new(None, ObjectiveStage::Unavailable)
            .observed_unix_ms,
        revision: state.revision,
        text_sha256: state.text_sha256.as_str().to_owned(),
        receipt_pending: state.receipt_pending,
    });
    Ok(NotesModelProposalObservation {
        proposal_id: id,
        proposal_sha256: Digest32::of_bytes(&exact_preview).to_string(),
        thread_id: params.thread_id.clone(),
        turn_id: params.turn_id.clone(),
        call_id: params.call_id.clone(),
        text,
        reviewed_document,
        phase: if reviewed.is_some() {
            NotesModelPhase::ReviewRequired
        } else {
            NotesModelPhase::Retained
        },
        result: None,
        application_receipt_sha256: None,
        owner_terminal: None,
    })
}

pub(super) fn observe_owner_terminal(
    run_id: &str,
    proposal: &mut NotesModelProposalObservation,
    terminal: &ProductionNotesTerminalObservation,
) -> Result<(NotesModelResult, DynamicToolCallResponse), AgentdError> {
    let response = terminal_response(run_id, proposal, terminal)?;
    let observed = NotesModelTerminalObservation::from_original(run_id, terminal)?;
    if proposal
        .owner_terminal
        .as_ref()
        .is_some_and(|previous| previous != &observed)
    {
        return Err(invalid("original Notes terminal observation changed"));
    }
    proposal.owner_terminal = Some(observed);
    Ok(response)
}

impl NotesModelProposalObservation {
    /// A completed callback with an unknown effect still needs its original
    /// read-only lookup. Capacity cannot silently discard that correlation.
    pub(super) fn can_release_tracking(&self) -> bool {
        matches!(
            self.phase,
            NotesModelPhase::ReplyObserved | NotesModelPhase::Closed
        ) && (self.owner_terminal.is_some() || self.result == Some(NotesModelResult::Declined))
    }
}

pub(super) fn terminal_response(
    run_id: &str,
    proposal: &NotesModelProposalObservation,
    terminal: &ProductionNotesTerminalObservation,
) -> Result<(NotesModelResult, DynamicToolCallResponse), AgentdError> {
    let payload: serde_json::Value = serde_json::from_str(&terminal.payload_json)?;
    if terminal.operation.operation_id().as_str() != run_id
        || payload["text"].as_str() != Some(proposal.text.as_str())
    {
        return Err(invalid(
            "original Notes terminal differs from the model proposal",
        ));
    }
    let (result, status, success) = match terminal.state {
        LocalOutcomeState::Committed => (NotesModelResult::Applied, "applied", true),
        LocalOutcomeState::Rejected => (NotesModelResult::Rejected, "rejected", false),
        _ => {
            return Err(invalid(
                "Notes terminal projection is not an application outcome",
            ));
        }
    };
    let response = json!({
        "schema":"hepta.notes.model_result.v1", "status":status,
        "proposal_id":proposal.proposal_id, "operation_id":run_id,
        "thread_id":proposal.thread_id, "turn_id":proposal.turn_id, "call_id":proposal.call_id,
        "payload_sha256":terminal.operation.payload_digest().to_string(),
        "application_receipt_json":terminal.application_receipt_json,
        "application_receipt_sha256":terminal.application_receipt_sha256.as_str(),
        "terminal_event_id":terminal.terminal_event_id,
        "terminal_event_sha256":terminal.terminal_event_sha256.as_str(),
        "terminal_generation":terminal.terminal_generation,
        "repeat_authorized":false,
    });
    Ok((
        result,
        DynamicToolCallResponse {
            content_items: vec![DynamicToolCallOutputContentItem::InputText {
                text: serde_json::to_string(&response)?,
            }],
            success,
        },
    ))
}

pub(super) fn unresolved_response(
    proposal: &NotesModelProposalObservation,
    run_id: &str,
    result: NotesModelResult,
) -> Result<DynamicToolCallResponse, AgentdError> {
    let status = match result {
        NotesModelResult::Declined => "human_declined",
        NotesModelResult::Unknown => "unknown",
        NotesModelResult::Applied | NotesModelResult::Rejected => {
            return Err(invalid(
                "application outcome requires an original terminal receipt",
            ));
        }
    };
    Ok(DynamicToolCallResponse {
        content_items: vec![DynamicToolCallOutputContentItem::InputText {
            text: serde_json::to_string(&json!({
                "schema":"hepta.notes.model_result.v1", "status":status,
                "proposal_id":proposal.proposal_id, "operation_id":run_id,
                "thread_id":proposal.thread_id, "turn_id":proposal.turn_id, "call_id":proposal.call_id,
                "application_receipt":null, "repeat_authorized":false,
                "instruction":"Use the original operation identity for read-only reconciliation; do not repeat the effect or infer no effect from missing evidence.",
            }))?,
        }],
        success: false,
    })
}

#[cfg(test)]
#[path = "notes_model_proposal_tests.rs"]
mod tests;
