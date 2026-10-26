//! Private incomplete terminal observation. Never a completed continuation.

use crate::ResponseCaptureError;
use crate::sse::responses::ResponseCompletedUsage;
use codex_protocol::protocol::TokenUsage;
use serde::Serialize;
use serde_json::Value;
use serde_json::value::RawValue;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IncompleteReason {
    MaxOutputTokens,
    ContentFilter,
    Other,
}

impl IncompleteReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MaxOutputTokens => "max_output_tokens",
            Self::ContentFilter => "content_filter",
            Self::Other => "other",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IncompleteUsageStatus {
    Observed,
    Missing,
    Invalid,
}

impl IncompleteUsageStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Observed => "observed",
            Self::Missing => "missing",
            Self::Invalid => "invalid",
        }
    }
}

/// Private evidence from the same captured stream. No Debug/Serialize and no
/// conversion into OpaqueResponsesContinuation or replayable raw input exist.
pub struct OpaqueResponsesIncomplete {
    events: Vec<Arc<RawValue>>,
    usage: Option<TokenUsage>,
    usage_status: IncompleteUsageStatus,
    reason: IncompleteReason,
    terminal_consistent: bool,
    echoed_max_output_tokens: Option<u64>,
}

impl OpaqueResponsesIncomplete {
    pub(crate) fn from_capture(
        events: Vec<Arc<RawValue>>,
        terminal: &RawValue,
    ) -> Result<Self, ResponseCaptureError> {
        let terminal: Value =
            serde_json::from_str(terminal.get()).map_err(|_| ResponseCaptureError::Invalid)?;
        let reason = match terminal["incomplete_details"]["reason"].as_str() {
            Some("max_output_tokens") => IncompleteReason::MaxOutputTokens,
            Some("content_filter") => IncompleteReason::ContentFilter,
            _ => IncompleteReason::Other,
        };
        let terminal_consistent = terminal["status"] == "incomplete"
            && terminal["id"]
                .as_str()
                .is_some_and(|id| !id.is_empty() && id.len() <= 256)
            && terminal.get("error").is_none_or(Value::is_null)
            && terminal
                .get("max_output_tokens")
                .is_none_or(|value| value.as_u64().is_some());
        let (usage, usage_status) = match terminal.get("usage").filter(|value| !value.is_null()) {
            None => (None, IncompleteUsageStatus::Missing),
            Some(value) => match serde_json::from_value::<ResponseCompletedUsage>(value.clone())
                .map(TokenUsage::from)
            {
                Ok(usage) if valid_usage(&usage) => (Some(usage), IncompleteUsageStatus::Observed),
                _ => (None, IncompleteUsageStatus::Invalid),
            },
        };
        Ok(Self {
            events,
            usage,
            usage_status,
            reason,
            terminal_consistent,
            echoed_max_output_tokens: terminal.get("max_output_tokens").and_then(Value::as_u64),
        })
    }

    pub fn usage(&self) -> Option<&TokenUsage> {
        self.usage.as_ref()
    }
    pub fn usage_status(&self) -> IncompleteUsageStatus {
        self.usage_status
    }
    pub fn reason(&self) -> IncompleteReason {
        self.reason
    }
    pub fn terminal_consistent(&self) -> bool {
        self.terminal_consistent
    }
    pub fn echoed_max_output_tokens(&self) -> Option<u64> {
        self.echoed_max_output_tokens
    }

    /// Original continuation-owner private storage only. Raw usage, opaque
    /// partial output and unknown terminal fields remain intact even if the
    /// normalized usage is missing/invalid. Never log these private bytes.
    pub fn private_evidence_json(&self) -> Result<Vec<u8>, ResponseCaptureError> {
        #[derive(Serialize)]
        struct Evidence<'a> {
            schema: &'static str,
            events: Vec<&'a RawValue>,
        }
        serde_json::to_vec(&Evidence {
            schema: "responses-opaque-incomplete:v1",
            events: self.events.iter().map(AsRef::as_ref).collect(),
        })
        .map_err(|_| ResponseCaptureError::Invalid)
    }
}

fn valid_usage(usage: &TokenUsage) -> bool {
    let (Ok(input), Ok(output), Ok(total)) = (
        u64::try_from(usage.input_tokens),
        u64::try_from(usage.output_tokens),
        u64::try_from(usage.total_tokens),
    ) else {
        return false;
    };
    usage.cached_input_tokens >= 0
        && usage.cached_input_tokens <= usage.input_tokens
        && usage.cache_write_input_tokens >= 0
        && usage.reasoning_output_tokens >= 0
        && usage.reasoning_output_tokens <= usage.output_tokens
        && input.checked_add(output) == Some(total)
}

#[cfg(test)]
#[path = "response_incomplete_tests.rs"]
mod tests;
