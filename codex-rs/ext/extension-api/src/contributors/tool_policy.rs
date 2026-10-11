use std::future::Future;
use std::pin::Pin;

use codex_tools::ToolName;
use codex_tools::ToolPayload;

use crate::ExtensionData;

use super::ToolCallOutcome;
use super::ToolCallSource;

pub type ToolPolicyFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, ToolPolicyError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolPolicyError {
    reason_code: String,
    detail: String,
}

impl ToolPolicyError {
    pub fn new(reason_code: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            reason_code: reason_code.into(),
            detail: detail.into(),
        }
    }

    pub fn reason_code(&self) -> &str {
        &self.reason_code
    }

    pub fn detail(&self) -> &str {
        &self.detail
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ToolPolicyDecision {
    Allow,
    Block {
        reason_code: String,
        message: String,
    },
}

pub struct ToolPolicyInput<'a> {
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub turn_id: &'a str,
    pub call_id: &'a str,
    /// Opaque identity for this host dispatch attempt. Retries of the same
    /// action receive distinct attempt IDs.
    pub attempt_id: &'a str,
    pub tool_name: &'a ToolName,
    pub source: ToolCallSource,
    pub payload: &'a ToolPayload,
}

pub struct ToolPolicyTerminalInput<'a> {
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub turn_id: &'a str,
    pub call_id: &'a str,
    /// The same opaque attempt ID supplied to admission and authorization for
    /// this dispatch.
    pub attempt_id: &'a str,
    pub tool_name: &'a ToolName,
    pub source: ToolCallSource,
    pub outcome: ToolCallOutcome,
    pub host_accepted: bool,
}
