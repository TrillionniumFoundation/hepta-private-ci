//! Opaque callback evidence from the one original connection plus an exact
//! readback of Core's in-progress item. No serialized caller-proof is accepted.
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ThreadItem;
use codex_hepta_types::Digest32;
use serde_json::Value;

use super::*;

pub(super) struct OriginalNotesThreadItem {
    params: DynamicToolCallParams,
    callback_digest: Digest32,
}

pub(super) struct VerifiedNotesThreadCall {
    item: OriginalNotesThreadItem,
}

impl std::ops::Deref for VerifiedNotesThreadCall {
    type Target = OriginalNotesThreadItem;
    fn deref(&self) -> &Self::Target {
        &self.item
    }
}

impl VerifiedNotesThreadCall {
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
            item: OriginalNotesThreadItem {
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
            || !matches!(params.tool.as_str(), READ_TOOL | REPLACE_TOOL | STATUS_TOOL)
            || params.turn_id.is_empty()
            || params.turn_id.len() > 128
            || params.call_id.is_empty()
            || params.call_id.len() > 128
            || serde_json::to_vec(params)?.len() > 8192
        {
            return Err(invalid("original Notes callback scope or bound mismatch"));
        }
        match params.tool.as_str() {
            READ_TOOL if params.arguments == json!({}) => Ok(()),
            STATUS_TOOL => {
                let navigation: StatusArguments = serde_json::from_value(params.arguments.clone())?;
                if navigation.turn_id.is_empty()
                    || navigation.turn_id.len() > 128
                    || navigation.call_id.is_empty()
                    || navigation.call_id.len() > 128
                {
                    return Err(invalid("original Notes status navigation bound"));
                }
                Ok(())
            }
            REPLACE_TOOL => {
                let arguments: ReplaceArguments = serde_json::from_value(params.arguments.clone())?;
                if arguments.text.trim().is_empty() || arguments.text.len() > 4096 {
                    return Err(invalid("original Notes text bound"));
                }
                Ok(())
            }
            _ => Err(invalid(
                "Notes state tool accepts no model-supplied identity",
            )),
        }
    }
}

impl OriginalNotesThreadItem {
    pub(super) fn intent_id(&self, route: &AgentdTextSessionConfig) -> Result<String, AgentdError> {
        // Arguments are deliberately not part of the operation ID: a repeated
        // callback cannot gain a new effect by changing its text/predecessor.
        Ok(Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.notes.original-thread-call.v1",
            route.agent_id.as_str(),
            &route.app_server_session_id,
            &route.thread_id,
            &self.params.turn_id,
            &self.params.call_id,
        ))?)
        .to_string())
    }
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
pub(super) struct VerifiedNotesThreadOperation {
    original: OriginalNotesThreadItem,
}
impl VerifiedNotesThreadOperation {
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
        if id != call_id || tool != REPLACE_TOOL {
            return Err(invalid(
                "status navigation is not an original Notes replace item",
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
        VerifiedNotesThreadCall::validate_callback(route, &params)?;
        Ok(Self {
            original: OriginalNotesThreadItem {
                callback_digest: Digest32::of_bytes(&serde_json::to_vec(&params)?),
                params,
            },
        })
    }
    pub(super) fn original_item(&self) -> &OriginalNotesThreadItem {
        &self.original
    }
}
