//! Public, raw-content-free diagnostics for the existing prompt pipeline.
use std::fmt;

use super::AgentdPromptRuntimeError;
use crate::exact_context_delivery::ExactContextDeliveryError;

/// Opaque diagnostic from the exact-delivery owner. The internal error and any
/// dynamic details remain private; callers can inspect its stable reason code.
#[derive(Clone, Copy, Eq, PartialEq)]
pub struct AgentdExactContextDeliveryError {
    code: &'static str,
}

impl AgentdExactContextDeliveryError {
    pub const fn reason_code(&self) -> &'static str {
        self.code
    }
}

impl From<ExactContextDeliveryError> for AgentdExactContextDeliveryError {
    fn from(error: ExactContextDeliveryError) -> Self {
        Self {
            code: error.reason_code(),
        }
    }
}

impl fmt::Debug for AgentdExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code)
    }
}

impl fmt::Display for AgentdExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code)
    }
}

impl std::error::Error for AgentdExactContextDeliveryError {}

pub enum AgentdPromptPipelineError {
    RegistryOpen(String),
    RuntimeOpen(AgentdPromptRuntimeError),
    ExactOpen(AgentdExactContextDeliveryError),
    StatePoisoned,
    CandidateSource(String),
    Compilation(String),
    Stage(AgentdPromptRuntimeError),
    ExactStage(AgentdExactContextDeliveryError),
}

impl AgentdPromptPipelineError {
    pub fn reason_code(&self) -> &'static str {
        match self {
            Self::RegistryOpen(_) => "prompt_pipeline_registry_open",
            Self::RuntimeOpen(error) | Self::Stage(error) => error.reason_code(),
            Self::ExactOpen(error) | Self::ExactStage(error) => error.reason_code(),
            Self::StatePoisoned => "prompt_pipeline_state_poisoned",
            Self::CandidateSource(_) => "prompt_pipeline_candidate_source",
            Self::Compilation(_) => "prompt_pipeline_compilation",
        }
    }
}

impl fmt::Debug for AgentdPromptPipelineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl fmt::Display for AgentdPromptPipelineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl std::error::Error for AgentdPromptPipelineError {}

impl From<ExactContextDeliveryError> for AgentdPromptPipelineError {
    fn from(error: ExactContextDeliveryError) -> Self {
        Self::ExactStage(error.into())
    }
}

impl AgentdPromptRuntimeError {
    pub fn reason_code(&self) -> &'static str {
        match self {
            Self::InvalidTurnId => "prompt_runtime_invalid_turn_id",
            Self::InvalidModel => "prompt_runtime_invalid_model",
            Self::InvalidDeadline => "prompt_runtime_invalid_deadline",
            Self::SourceValidationFailed => "prompt_runtime_source_validation_failed",
            Self::EmptySelection => "prompt_runtime_empty_selection",
            Self::UnsupportedPromptRole => "prompt_runtime_unsupported_prompt_role",
            Self::PayloadNotUtf8 => "prompt_runtime_payload_not_utf8",
            Self::CapacityExceeded => "prompt_runtime_capacity_exceeded",
            Self::StageConflict => "prompt_runtime_stage_conflict",
            Self::DispatchConflict => "prompt_runtime_dispatch_conflict",
            Self::TerminalWithoutDispatch => "prompt_runtime_terminal_without_dispatch",
            Self::TerminalBindingMismatch => "prompt_runtime_terminal_binding_mismatch",
            Self::TerminalConflict => "prompt_runtime_terminal_conflict",
            Self::IndeterminatePending => "prompt_runtime_indeterminate_pending",
            Self::StatePoisoned => "prompt_runtime_state_poisoned",
            Self::CorruptState => "prompt_runtime_corrupt_state",
            Self::StateLocked => "prompt_runtime_state_locked",
            Self::Unavailable => "prompt_runtime_unavailable",
            Self::IndeterminateDurability => "prompt_runtime_indeterminate_durability",
            Self::ReopenRequired => "prompt_runtime_reopen_required",
            Self::Adapter(_) => "prompt_runtime_adapter_rejected",
        }
    }
}

impl fmt::Debug for AgentdPromptRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl fmt::Display for AgentdPromptRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl std::error::Error for AgentdPromptRuntimeError {}

#[cfg(test)]
#[path = "prompt_runtime_error_tests.rs"]
mod tests;
