//! Frozen data for the distinct six-tool original Desktop thread.
//! These serializable values contain no effect permission or new authority.
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNotesLiteralBindings;
use crate::DesktopThreadSeedReceipt;
use crate::text_session::AgentdTextSessionConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;
#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum DesktopInteraction {
    OriginalDesktopThreadToolV1 {
        route: AgentdTextSessionConfig,
        seed: DesktopThreadSeedReceipt,
    },
}
impl DesktopInteraction {
    pub(crate) fn validate_for(
        &self,
        identity: &AgentdIdentity,
        model: Digest32,
    ) -> Result<(), AgentdError> {
        let Self::OriginalDesktopThreadToolV1 { route, seed } = self;
        if route.agent_id != identity.agent_id
            || route.spawn_generation != identity.spawn_generation
            || route.control_socket != identity.control_socket
            || route.codex_home != identity.home_root
            || route.thread_id.is_empty()
            || route.thread_id.len() > 128
            || route.app_server_session_id.is_empty()
            || route.app_server_session_id.len() > 256
            || seed.codex_home != route.codex_home
            || seed.thread_id != route.thread_id
            || seed.app_server_session_id != route.app_server_session_id
            || seed.model_tuple_digest()? != model
        {
            return Err(invalid(
                "Desktop seed differs from original daemon, route or model",
            ));
        }
        seed.verify_persisted()
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FrozenBindings {
    pub(crate) principal_scope: String,
    pub(crate) principal_scope_digest: String,
    pub(crate) issuer_id: String,
    pub(crate) policy_generation: u64,
    pub(crate) locale: String,
    pub(crate) runtime_body_digest: String,
    pub(crate) preference_state_digest: String,
    pub(crate) model_tuple_digest: String,
    pub(crate) prompt_registry_digest: String,
    pub(crate) artifact_set_digest: String,
}
impl FrozenBindings {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        if self.principal_scope.is_empty()
            || self.principal_scope.len() > 256
            || self.issuer_id.is_empty()
            || self.issuer_id.len() > 64
            || !matches!(self.locale.as_str(), "en-US" | "zh-CN")
        {
            return Err(invalid("invalid original Desktop frozen bindings"));
        }
        Generation::new(self.policy_generation).map_err(|e| invalid(&e.to_string()))?;
        for value in [
            &self.principal_scope_digest,
            &self.runtime_body_digest,
            &self.preference_state_digest,
            &self.model_tuple_digest,
            &self.prompt_registry_digest,
            &self.artifact_set_digest,
        ] {
            digest(value)?;
        }
        Ok(())
    }
    pub(crate) fn into_original(self) -> Result<AgentdNotesLiteralBindings, AgentdError> {
        self.validate()?;
        Ok(AgentdNotesLiteralBindings {
            principal_scope: self.principal_scope,
            principal_scope_digest: digest(&self.principal_scope_digest)?,
            issuer_id: self.issuer_id,
            policy_generation: Generation::new(self.policy_generation)
                .map_err(|e| invalid(&e.to_string()))?,
            locale: self.locale,
            runtime_body_digest: digest(&self.runtime_body_digest)?,
            preference_state_digest: digest(&self.preference_state_digest)?,
            model_tuple_digest: digest(&self.model_tuple_digest)?,
            prompt_registry_digest: digest(&self.prompt_registry_digest)?,
            artifact_set_digest: digest(&self.artifact_set_digest)?,
        })
    }
}
pub(crate) fn digest(value: &str) -> Result<Digest32, AgentdError> {
    let value: Digest32 = value
        .parse()
        .map_err(|_| invalid("invalid original Desktop digest"))?;
    if value.is_zero() {
        return Err(invalid("absent original Desktop digest"));
    }
    Ok(value)
}
fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(message.into())
}
