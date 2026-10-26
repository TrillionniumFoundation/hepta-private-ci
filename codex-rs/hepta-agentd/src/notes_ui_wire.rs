//! The existing Desktop ObjectiveBridge v1 wire, mirrored without a dependency
//! from Hepta back into Desktop. Source: trillionnium-os-desktop f4872ca,
//! ui/core/src/objective.rs. Only navigation IDs/text enter; no authority does.
//! Changes must remain compatible with that Session decoder.
use serde::Deserialize;
use serde::Serialize;

pub const MAX_INTENT_BYTES: usize = 16 * 1024;
pub const MAX_OBJECTIVE_VIEWS: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveIntent {
    pub client_intent_id: String,
    pub text: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ObjectiveCommand {
    Availability {},
    Submit {
        intent: ObjectiveIntent,
    },
    Status {
        client_intent_id: String,
    },
    Cancel {
        client_intent_id: String,
    },
    ConfirmModelProposal {
        proposal_id: String,
        proposal_sha256: String,
    },
    DeclineModelProposal {
        proposal_id: String,
        proposal_sha256: String,
    },
}

impl ObjectiveCommand {
    pub fn client_intent_id(&self) -> Option<&str> {
        match self {
            Self::Availability {} => None,
            Self::Submit { intent } => Some(&intent.client_intent_id),
            Self::Status { client_intent_id } | Self::Cancel { client_intent_id } => {
                Some(client_intent_id)
            }
            Self::ConfirmModelProposal { proposal_id, .. }
            | Self::DeclineModelProposal { proposal_id, .. } => Some(proposal_id),
        }
    }

    pub fn validate(&self) -> Result<(), ObjectiveHostIssue> {
        if let Some(id) = self.client_intent_id()
            && (id.is_empty()
                || id.len() > 96
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"-_".contains(&c)))
        {
            return Err(ObjectiveHostIssue::InvalidIntent);
        }
        if let Self::Submit { intent } = self
            && (intent.client_intent_id.starts_with("model-")
                || intent.text.trim().is_empty()
                || intent.text.len() > MAX_INTENT_BYTES)
        {
            return Err(ObjectiveHostIssue::InvalidIntent);
        }
        if let Self::ConfirmModelProposal {
            proposal_sha256, ..
        }
        | Self::DeclineModelProposal {
            proposal_sha256, ..
        } = self
            && (proposal_sha256.len() != 64
                || !proposal_sha256
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)))
        {
            return Err(ObjectiveHostIssue::InvalidIntent);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectiveHostIssue {
    Unavailable,
    InvalidIntent,
    Capacity,
    OwnerRefused,
    PersistenceUnknown,
    TransportUnknown,
    IdentityMismatch,
    NoRetainedIntent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectiveStage {
    Unavailable,
    Ready,
    Queued,
    Retained,
    NotSent,
    SubmitUnknown,
    Refused,
    Admitted,
    Abstained,
    Conflict,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectiveRunPhase {
    Admitted,
    ContextAttached,
    Dispatched,
    Cancelling,
    Cancelled,
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveRunObservation {
    pub revision: u64,
    pub phase: ObjectiveRunPhase,
    pub terminal_observed: bool,
}

/// Current application readback, independent of an Objective's outcome. This
/// disposable snapshot cannot admit an effect or retire an original receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NotesDocumentObservation {
    pub target: codex_hepta_memory::NotesTargetIdentity,
    pub observed_unix_ms: u64,
    pub revision: u64,
    pub text_sha256: String,
    pub receipt_pending: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NotesModelPhase {
    ReviewRequired,
    Retained,
    ReplyStarted,
    ReplyObserved,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NotesModelResult {
    Applied,
    Rejected,
    Declined,
    Unknown,
}

/// Exact original owner evidence, which can arrive after the model already
/// received an unknown answer. It does not rewrite that earlier tool reply.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NotesModelTerminalObservation {
    pub operation_id: String,
    pub result: NotesModelResult,
    pub application_receipt_sha256: String,
    pub terminal_event_id: String,
    pub terminal_event_sha256: String,
}

impl NotesModelTerminalObservation {
    pub(crate) fn from_original(
        operation_id: &str,
        terminal: &codex_hepta_memory::ProductionNotesTerminalObservation,
    ) -> Result<Self, crate::AgentdError> {
        use codex_hepta_memory::LocalOutcomeState;
        let result = match terminal.state {
            LocalOutcomeState::Committed => NotesModelResult::Applied,
            LocalOutcomeState::Rejected => NotesModelResult::Rejected,
            _ => {
                return Err(crate::notes_literal_adapter::invalid(
                    "Notes owner observation is not an application terminal",
                ));
            }
        };
        if terminal.operation.operation_id().as_str() != operation_id {
            return Err(crate::notes_literal_adapter::invalid(
                "Notes owner terminal operation identity differs",
            ));
        }
        Ok(Self {
            operation_id: operation_id.to_owned(),
            result,
            application_receipt_sha256: terminal.application_receipt_sha256.as_str().to_owned(),
            terminal_event_id: terminal.terminal_event_id.clone(),
            terminal_event_sha256: terminal.terminal_event_sha256.as_str().to_owned(),
        })
    }
}

/// Bounded presentation of an actual original tool call. Confirmation refers
/// only to this owner-generated digest; the UI cannot replace any payload.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NotesModelProposalObservation {
    pub proposal_id: String,
    pub proposal_sha256: String,
    pub thread_id: String,
    pub turn_id: String,
    pub call_id: String,
    pub text: String,
    pub reviewed_document: Option<NotesDocumentObservation>,
    pub phase: NotesModelPhase,
    pub result: Option<NotesModelResult>,
    pub application_receipt_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner_terminal: Option<NotesModelTerminalObservation>,
}

/// Navigation IDs read from the original owner's retained requests. No signed
/// request, admission, sending permission or effect result is projected here.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveRetainedIntents {
    pub client_intent_ids: Vec<String>,
    pub complete: bool,
}

impl ObjectiveRetainedIntents {
    pub fn validate(&self) -> Result<(), ObjectiveHostIssue> {
        if self.client_intent_ids.len() > MAX_OBJECTIVE_VIEWS {
            return Err(ObjectiveHostIssue::Capacity);
        }
        let mut seen = std::collections::BTreeSet::new();
        for id in &self.client_intent_ids {
            ObjectiveCommand::Status {
                client_intent_id: id.clone(),
            }
            .validate()?;
            if !seen.insert(id) {
                return Err(ObjectiveHostIssue::IdentityMismatch);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectiveCancellation {
    #[default]
    NotRequested,
    Unknown,
    CancelledBeforeDispatch,
    CancellingAfterDispatch,
    AlreadyTerminal,
}

/// Admission, run state and cancellation remain separate. No field establishes
/// device/effect completion. This disposable view is never a recovery ledger.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveObservation {
    /// Local view freshness only; never an authority clock.
    pub observed_unix_ms: u64,
    pub client_intent_id: Option<String>,
    pub stage: ObjectiveStage,
    pub request_retained: bool,
    pub publication_retained: bool,
    pub run: Option<ObjectiveRunObservation>,
    pub cancellation: ObjectiveCancellation,
    pub issue: Option<ObjectiveHostIssue>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retained_intents: Option<ObjectiveRetainedIntents>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes_document: Option<NotesDocumentObservation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_proposal: Option<NotesModelProposalObservation>,
    /// Original writer observation, independently recoverable by the existing
    /// client intent ID even when its model callback is no longer replayed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes_terminal: Option<NotesModelTerminalObservation>,
}

impl ObjectiveObservation {
    pub fn new(client_intent_id: Option<String>, stage: ObjectiveStage) -> Self {
        Self {
            observed_unix_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |duration| {
                    duration.as_millis().min(u128::from(u64::MAX)) as u64
                }),
            client_intent_id,
            stage,
            request_retained: false,
            publication_retained: false,
            run: None,
            cancellation: ObjectiveCancellation::NotRequested,
            issue: None,
            retained_intents: None,
            notes_document: None,
            model_proposal: None,
            notes_terminal: None,
        }
    }
}

#[cfg(test)]
#[path = "notes_ui_wire_tests.rs"]
mod tests;
