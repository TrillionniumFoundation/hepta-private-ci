//! Agentd-owned source for prompt attachments consumed by the embedded App Server.
//!
//! Staging accepts only the exact `PromptRegistryCompiledContextV2` produced
//! after optimizer exercise validation. The owner is bounded and in-memory at
//! this stage; target-host qualification must still establish durable terminal
//! observation/reconciliation before a production claim.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use codex_hepta_codex_adapter::PromptRuntimeAttachmentV1;
use codex_hepta_codex_adapter::PromptRuntimeDeveloperFragmentV1;
use codex_hepta_codex_adapter::PromptRuntimeHost;
use codex_hepta_codex_adapter::PromptRuntimeHostError;
use codex_hepta_codex_adapter::PromptRuntimePrepareFuture;
use codex_hepta_codex_adapter::PromptRuntimePrepareRequest;
use codex_hepta_codex_adapter::PromptRuntimeRecordFuture;
use codex_hepta_codex_adapter::PromptRuntimeTerminalOutcomeV1;
use codex_hepta_codex_adapter::PromptRuntimeTerminalRecordV1;
use codex_hepta_intelligence::PromptRegistryCompiledContextV2;
use codex_hepta_prompt_registry::PromptRoleV2;

const MAX_STAGED_TURNS: usize = 256;
const MAX_TERMINAL_RECORDS: usize = 1024;
const PROMPT_RUNTIME_CAPABILITY_ID: &str = "agentd.prompt-runtime";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeStageDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdPromptRuntimeError {
    InvalidTurnId,
    InvalidModel,
    InvalidDeadline,
    SourceValidationFailed,
    EmptySelection,
    UnsupportedPromptRole,
    PayloadNotUtf8,
    CapacityExceeded,
    StageConflict,
    TerminalWithoutStage,
    TerminalBindingMismatch,
    TerminalConflict,
    StatePoisoned,
    Adapter(String),
}

impl fmt::Display for AgentdPromptRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdPromptRuntimeError {}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct PromptRuntimeKey {
    thread_id: String,
    turn_id: String,
}

#[derive(Default)]
struct PromptRuntimeState {
    staged: BTreeMap<PromptRuntimeKey, PromptRuntimeAttachmentV1>,
    terminal_records: BTreeMap<String, PromptRuntimeTerminalRecordV1>,
    terminal_order: VecDeque<String>,
}

/// Long-lived Agentd owner shared with the embedded App Server.
#[derive(Default)]
pub struct AgentdPromptRuntimeOwner {
    state: Mutex<PromptRuntimeState>,
}

impl fmt::Debug for AgentdPromptRuntimeOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        formatter
            .debug_struct("AgentdPromptRuntimeOwner")
            .field("staged_turns", &state.staged.len())
            .field("terminal_records", &state.terminal_records.len())
            .finish()
    }
}

impl AgentdPromptRuntimeOwner {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Stage one exact optimizer-exercised/registry-dereferenced context for a
    /// real Codex turn. Only DeveloperInstruction is activated in this profile.
    pub fn stage_compiled_prompt_context(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        compiled: &PromptRegistryCompiledContextV2,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        validate_model(model)?;
        if requested_deadline_ms == 0 {
            return Err(AgentdPromptRuntimeError::InvalidDeadline);
        }
        compiled
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if compiled.selected_deliveries.is_empty() {
            return Err(AgentdPromptRuntimeError::EmptySelection);
        }

        let mut effective_deadline_ms = requested_deadline_ms;
        let mut fragments = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(AgentdPromptRuntimeError::UnsupportedPromptRole);
            }
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                if expires_unix_ms == 0 {
                    return Err(AgentdPromptRuntimeError::InvalidDeadline);
                }
                effective_deadline_ms = effective_deadline_ms.min(expires_unix_ms);
            }
            let text = std::str::from_utf8(&delivery.payload)
                .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
            fragments.push(
                PromptRuntimeDeveloperFragmentV1::new(text.to_owned())
                    .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
            );
        }

        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt.compilation_id.clone(),
            compiled.attachment.attachment_digest,
            compiled.attachment.payload_digest,
            model.to_owned(),
            effective_deadline_ms,
            fragments,
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?;

        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?;
        if let Some(existing) = state.staged.get(&key) {
            return if existing == &attachment {
                Ok(PromptRuntimeStageDisposition::Unchanged)
            } else {
                Err(AgentdPromptRuntimeError::StageConflict)
            };
        }
        if state.staged.len() >= MAX_STAGED_TURNS {
            return Err(AgentdPromptRuntimeError::CapacityExceeded);
        }
        state.staged.insert(key, attachment);
        Ok(PromptRuntimeStageDisposition::Inserted)
    }

    /// Explicit cleanup for aborted turns or owners that know no further
    /// physical provider attempt can occur.
    pub fn clear_turn(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<bool, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .remove(&key)
            .is_some())
    }

    pub fn terminal_record(
        &self,
        attempt_id: &str,
    ) -> Result<Option<PromptRuntimeTerminalRecordV1>, AgentdPromptRuntimeError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .terminal_records
            .get(attempt_id)
            .cloned())
    }

    pub fn staged_count(&self) -> Result<usize, AgentdPromptRuntimeError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .len())
    }

    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHost, AgentdPromptRuntimeError> {
        let prepare_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new(
            PROMPT_RUNTIME_CAPABILITY_ID,
            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {
                let owner = Arc::clone(&prepare_owner);
                Box::pin(async move { owner.prepare(request) })
            },
            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {
                let owner = Arc::clone(&record_owner);
                Box::pin(async move { owner.record(record) })
            },
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))
    }

    fn prepare(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {
        validate_thread_id(&request.thread_id).map_err(host_error)?;
        validate_turn_id(&request.turn_id).map_err(host_error)?;
        let key = PromptRuntimeKey {
            thread_id: request.thread_id,
            turn_id: request.turn_id,
        };
        self.state
            .lock()
            .map_err(|_| {
                PromptRuntimeHostError::new(
                    "agentd_prompt_runtime_state_poisoned",
                    "Agentd prompt runtime state lock is poisoned",
                )
            })
            .map(|state| state.staged.get(&key).cloned())
    }

    fn record(&self, record: PromptRuntimeTerminalRecordV1) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_terminal_invalid", error.to_string())
        })?;
        let mut state = self.state.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_runtime_state_poisoned",
                "Agentd prompt runtime state lock is poisoned",
            )
        })?;

        if let Some(existing) = state.terminal_records.get(&record.attempt_id) {
            return if existing == &record {
                Ok(())
            } else {
                Err(host_error(AgentdPromptRuntimeError::TerminalConflict))
            };
        }

        let key = PromptRuntimeKey {
            thread_id: record.thread_id.clone(),
            turn_id: record.turn_id.clone(),
        };
        let Some(staged) = state.staged.get(&key) else {
            return Err(host_error(AgentdPromptRuntimeError::TerminalWithoutStage));
        };
        if staged.compilation_id != record.compilation_id
            || staged.context_attachment_digest != record.context_attachment_digest
            || staged.context_payload_digest != record.context_payload_digest
            || staged.source_binding_digest != record.source_binding_digest
        {
            return Err(host_error(
                AgentdPromptRuntimeError::TerminalBindingMismatch,
            ));
        }

        if state.terminal_records.len() >= MAX_TERMINAL_RECORDS {
            let Some(oldest) = state.terminal_order.pop_front() else {
                return Err(host_error(AgentdPromptRuntimeError::StatePoisoned));
            };
            state.terminal_records.remove(&oldest);
        }

        let should_clear = matches!(record.outcome, PromptRuntimeTerminalOutcomeV1::Rejected)
            || (record.outcome == PromptRuntimeTerminalOutcomeV1::Delivered
                && record.end_turn == Some(true));
        let attempt_id = record.attempt_id.clone();
        state.terminal_records.insert(attempt_id.clone(), record);
        state.terminal_order.push_back(attempt_id);
        if should_clear {
            state.staged.remove(&key);
        }
        Ok(())
    }
}

fn validate_thread_id(thread_id: &str) -> Result<(), AgentdPromptRuntimeError> {
    if thread_id.is_empty() || thread_id.len() > 256 || thread_id.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidTurnId);
    }
    Ok(())
}

fn validate_turn_id(turn_id: &str) -> Result<(), AgentdPromptRuntimeError> {
    if turn_id.is_empty() || turn_id.len() > 256 || turn_id.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidTurnId);
    }
    Ok(())
}

fn validate_model(model: &str) -> Result<(), AgentdPromptRuntimeError> {
    if model.is_empty() || model.len() > 256 || model.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidModel);
    }
    Ok(())
}

fn host_error(error: AgentdPromptRuntimeError) -> PromptRuntimeHostError {
    PromptRuntimeHostError::new("agentd_prompt_runtime_error", error.to_string())
}

#[cfg(test)]
#[path = "prompt_runtime_tests.rs"]
mod tests;
