//! A sealed, pre-existing App Server route for the original Notes owner.
//! This declaration cannot register a tool, create a thread or grant authority.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::text_session::AgentdTextSessionConfig;

pub(crate) const NOTES_MODEL_NAMESPACE: &str = "trill_notes";
pub(crate) const NOTES_MODEL_TOOL: &str = "propose_replace";
pub(crate) const NOTES_MODEL_MAX_TEXT_BYTES: usize = 4096;

/// Trusted launch data for one already registered model tool and human scope.
/// The live App Server still owns the callback and the original Notes adapter
/// still owns every preparation, signature, sending fence and terminal receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNotesModelRoute {
    pub(crate) thread_id: String,
    pub(crate) app_server_session_id: String,
    pub(crate) principal_scope_digest: Digest32,
    pub(crate) registered_tool_schema_sha256: Digest32,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RegisteredNotesModelRoute {
    thread_id: String,
    app_server_session_id: String,
    principal_scope_digest: String,
    registered_tool_schema_sha256: String,
}

impl RegisteredNotesModelRoute {
    pub(crate) fn into_route(
        self,
        principal_scope_digest: Digest32,
    ) -> Result<AgentdNotesModelRoute, AgentdError> {
        let route = AgentdNotesModelRoute {
            thread_id: self.thread_id,
            app_server_session_id: self.app_server_session_id,
            principal_scope_digest: self
                .principal_scope_digest
                .parse()
                .map_err(|_| invalid("principal scope digest is invalid"))?,
            registered_tool_schema_sha256: self
                .registered_tool_schema_sha256
                .parse()
                .map_err(|_| invalid("registered tool schema digest is invalid"))?,
        };
        route.validate_for(principal_scope_digest)?;
        Ok(route)
    }
}

impl AgentdNotesModelRoute {
    /// Exact UTF-8 definition bytes whose digest the trusted launcher must bind
    /// to its original thread-registration evidence. Reading these bytes does
    /// not install the tool. JSON maxLength counts characters; the host also
    /// enforces the stricter 4096-byte UTF-8 bound before presenting a proposal.
    pub const TOOL_DEFINITION_JSON: &'static str = r#"{"type":"namespace","name":"trill_notes","description":"Propose a human-reviewed change to the one Notes document bound to this original Hepta session.","tools":[{"type":"function","name":"propose_replace","description":"Propose replacing the bound Notes document with exact nonblank text, at most 4096 UTF-8 bytes. The human must review and confirm the proposal. The original owner reports applied, refused or unknown evidence; an unknown result does not authorize a replacement call or another effect.","inputSchema":{"type":"object","properties":{"text":{"type":"string","minLength":1,"maxLength":4096}},"required":["text"],"additionalProperties":false}}]}"#;

    pub(crate) fn validate_for(&self, principal_scope_digest: Digest32) -> Result<(), AgentdError> {
        if !bounded_identity(&self.thread_id, /*maximum*/ 128)
            || !bounded_identity(&self.app_server_session_id, /*maximum*/ 256)
            || self.principal_scope_digest.is_zero()
            || self.principal_scope_digest != principal_scope_digest
            || self.registered_tool_schema_sha256
                != Digest32::of_bytes(Self::TOOL_DEFINITION_JSON.as_bytes())
        {
            return Err(invalid(
                "original thread, human scope or registered tool definition differs",
            ));
        }
        Ok(())
    }

    pub(crate) fn text_session_config(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<AgentdTextSessionConfig, AgentdError> {
        self.validate_for(self.principal_scope_digest)?;
        if identity.spawn_generation == 0
            || !identity.control_socket.is_absolute()
            || !identity.home_root.is_absolute()
        {
            return Err(invalid("original Agentd route is unavailable"));
        }
        Ok(AgentdTextSessionConfig {
            control_socket: identity.control_socket.clone(),
            agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            thread_id: self.thread_id.clone(),
            app_server_session_id: self.app_server_session_id.clone(),
            codex_home: identity.home_root.clone(),
        })
    }
}

fn bounded_identity(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && !value
            .chars()
            .any(|ch| ch.is_control() || ch.is_whitespace())
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("original Notes model route: {message}"))
}

#[cfg(test)]
#[path = "notes_model_route_tests.rs"]
mod tests;
