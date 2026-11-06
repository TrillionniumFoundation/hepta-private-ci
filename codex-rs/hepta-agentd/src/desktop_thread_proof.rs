//! Opaque callback evidence from the one original connection plus an exact
//! readback of Core's in-progress item. No serialized caller-proof is accepted.
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ThreadItem;
use codex_hepta_types::Digest32;
use serde_json::Value;

use super::*;

#[cfg(test)]
#[path = "desktop_thread_proof_tests.rs"]
mod tests;

pub(super) struct OriginalDesktopThreadItem {
    params: DynamicToolCallParams,
    callback_digest: Digest32,
}

pub(super) struct VerifiedDesktopThreadCall {
    item: OriginalDesktopThreadItem,
}

impl std::ops::Deref for VerifiedDesktopThreadCall {
    type Target = OriginalDesktopThreadItem;
    fn deref(&self) -> &Self::Target {
        &self.item
    }
}

impl VerifiedDesktopThreadCall {
    pub(super) fn recorded_reference(
        &self,
        route: &AgentdTextSessionConfig,
    ) -> codex_hepta_memory::OriginalDesktopThreadReference {
        codex_hepta_memory::OriginalDesktopThreadReference {
            profile: "organ.desktop.thread-tool.v1".into(),
            tool: self.tool().into(),
            app_server_session_id: route.app_server_session_id.clone(),
            thread_id: route.thread_id.clone(),
            turn_id: self.turn_id().into(),
            call_id: self.call_id().into(),
            callback_sha256: self.callback_digest().to_string(),
        }
    }
    pub(super) fn from_original_item(
        route: &AgentdTextSessionConfig,
        params: &DynamicToolCallParams,
        original: &ThreadItem,
    ) -> Result<Self, AgentdError> {
        Self::validate_callback(route, params)?;
        let ThreadItem::DynamicToolCall {
            id,
            namespace,
            tool,
            arguments,
            status,
            ..
        } = original
        else {
            return Err(invalid("original item is not a Core dynamic tool call"));
        };
        if id != &params.call_id
            || namespace != &params.namespace
            || tool != &params.tool
            || arguments != &params.arguments
            || *status != DynamicToolCallStatus::InProgress
        {
            return Err(invalid(
                "callback differs from its original in-progress ThreadItem",
            ));
        }
        Ok(Self {
            item: OriginalDesktopThreadItem {
                params: params.clone(),
                callback_digest: Digest32::of_bytes(&serde_json::to_vec(params)?),
            },
        })
    }

    pub(super) fn validate_callback(
        route: &AgentdTextSessionConfig,
        params: &DynamicToolCallParams,
    ) -> Result<(), AgentdError> {
        if params.thread_id != route.thread_id
            || params.namespace.is_some()
            || !matches!(
                params.tool.as_str(),
                READ_TOOL
                    | REPLACE_TOOL
                    | STATUS_TOOL
                    | CALCULATOR_READ_TOOL
                    | CALCULATOR_EVALUATE_TOOL
                    | CALCULATOR_STATUS_TOOL
            )
            || params.turn_id.is_empty()
            || params.turn_id.len() > 128
            || params.turn_id.contains('\0')
            || params.call_id.is_empty()
            || params.call_id.len() > 128
            || params.call_id.contains('\0')
            || serde_json::to_vec(params)?.len() > 8192
        {
            return Err(invalid("original Desktop callback scope or bound mismatch"));
        }
        match params.tool.as_str() {
            READ_TOOL | CALCULATOR_READ_TOOL if params.arguments == json!({}) => Ok(()),
            STATUS_TOOL | CALCULATOR_STATUS_TOOL => {
                let navigation: StatusArguments = serde_json::from_value(params.arguments.clone())?;
                navigation.validate_for_tool(&params.tool)
            }
            REPLACE_TOOL => {
                let arguments: NotesArguments = serde_json::from_value(params.arguments.clone())?;
                if arguments.text.trim().is_empty() || arguments.text.len() > 4096 {
                    return Err(invalid("original Desktop text bound"));
                }
                Ok(())
            }
            CALCULATOR_EVALUATE_TOOL => {
                let arguments: CalculatorArguments =
                    serde_json::from_value(params.arguments.clone())?;
                arguments.validate()
            }
            _ => Err(invalid(
                "Desktop state tool accepts no model-supplied identity",
            )),
        }
    }
}

impl OriginalDesktopThreadItem {
    pub(super) fn turn_id(&self) -> &str {
        &self.params.turn_id
    }
    pub(super) fn call_id(&self) -> &str {
        &self.params.call_id
    }
    pub(super) fn tool(&self) -> &str {
        &self.params.tool
    }
    pub(super) fn arguments(&self) -> &Value {
        &self.params.arguments
    }
    pub(super) fn callback_digest(&self) -> Digest32 {
        self.callback_digest
    }
}

/// A read-only reference to an actual original replace item, including a
/// completed unknown response. It is never admitted to `execute` or preparation.
pub(super) struct VerifiedDesktopThreadOperation {
    original: OriginalDesktopThreadItem,
}
impl VerifiedDesktopThreadOperation {
    pub(super) fn from_original_item(
        route: &AgentdTextSessionConfig,
        turn_id: &str,
        call_id: &str,
        item: &ThreadItem,
    ) -> Result<Self, AgentdError> {
        let ThreadItem::DynamicToolCall {
            id,
            namespace,
            tool,
            arguments,
            ..
        } = item
        else {
            return Err(invalid("status navigation is not an original dynamic item"));
        };
        if id != call_id || !matches!(tool.as_str(), REPLACE_TOOL | CALCULATOR_EVALUATE_TOOL) {
            return Err(invalid(
                "status navigation is not an original Desktop replace item",
            ));
        }
        let params = DynamicToolCallParams {
            thread_id: route.thread_id.clone(),
            turn_id: turn_id.into(),
            call_id: call_id.into(),
            namespace: namespace.clone(),
            tool: tool.clone(),
            arguments: arguments.clone(),
        };
        VerifiedDesktopThreadCall::validate_callback(route, &params)?;
        Ok(Self {
            original: OriginalDesktopThreadItem {
                callback_digest: Digest32::of_bytes(&serde_json::to_vec(&params)?),
                params,
            },
        })
    }
    pub(super) fn original_item(&self) -> &OriginalDesktopThreadItem {
        &self.original
    }
}
