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
        seed: crate::NotesThreadSeedReceipt,
    },
}

impl NotesLaunchMode {
    pub(crate) fn validate_for(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if let Self::OriginalThreadToolV1 { route, seed } = self
            && (route.agent_id != identity.agent_id
                || route.spawn_generation != identity.spawn_generation
                || route.control_socket != identity.control_socket
                || route.codex_home != identity.home_root
                || route.thread_id.is_empty()
                || route.thread_id.len() > 128
                || route.app_server_session_id.is_empty()
                || route.app_server_session_id.len() > 256
                || seed.codex_home != route.codex_home
                || seed.thread_id != route.thread_id
                || seed.app_server_session_id != route.app_server_session_id)
        {
            return Err(AgentdError::Invalid(
                "sealed original Notes thread differs from the registered daemon".into(),
            ));
        }
        if let Self::OriginalThreadToolV1 { seed, .. } = self {
            seed.verify_persisted()?;
        }
        Ok(())
    }

    pub(crate) fn validate_model_tuple(
        &self,
        expected: codex_hepta_types::Digest32,
    ) -> Result<(), AgentdError> {
        if let Self::OriginalThreadToolV1 { seed, .. } = self
            && seed.model_tuple_digest()? != expected
        {
            return Err(AgentdError::Invalid(
                "sealed Notes model tuple differs from original seed".into(),
            ));
        }
        Ok(())
    }
}
