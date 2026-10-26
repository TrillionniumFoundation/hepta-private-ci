//! Explicit trusted Notes interaction selection. A model-backed original
//! thread is never represented as the existing no-model literal profile.

use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::text_session::AgentdTextSessionConfig;

#[derive(Default, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum NotesLaunchMode {
    #[default]
    LiteralUiV1,
    OriginalThreadToolV1 {
        route: AgentdTextSessionConfig,
    },
}

impl NotesLaunchMode {
    pub(crate) fn validate_for(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if let Self::OriginalThreadToolV1 { route } = self
            && (route.agent_id != identity.agent_id
                || route.spawn_generation != identity.spawn_generation
                || route.control_socket != identity.control_socket
                || route.codex_home != identity.home_root
                || route.thread_id.is_empty()
                || route.thread_id.len() > 128
                || route.app_server_session_id.is_empty()
                || route.app_server_session_id.len() > 256)
        {
            return Err(AgentdError::Invalid(
                "sealed original Notes thread differs from the registered daemon".into(),
            ));
        }
        Ok(())
    }
}
