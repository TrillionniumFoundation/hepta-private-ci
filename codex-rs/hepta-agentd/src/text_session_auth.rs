//! Public identity projected only after a live, kernel-authenticated Root lane.
//! This DTO is not a grant. The original issuer and Agentd recheck every send.
use super::AgentdTextSessionConfig;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct TextOwnerReceipt {
    pub schema_version: u32,
    pub protocol: String,
    pub principal_id: String,
    pub session_id: String,
    pub permission_revision: u64,
    pub expires_at_ms: u64,
    pub route: AgentdTextSessionConfig,
    pub can_interrupt: bool,
    #[serde(default)]
    pub can_resolve_approvals: bool,
    pub intent_namespace: String,
    pub next_intent_sequence: u64,
}

impl TextOwnerReceipt {
    pub(crate) fn validate(&self) -> bool {
        self.schema_version == 1
            && self.protocol == "hepta.ui-chat-owner.v1"
            && [&self.principal_id, &self.session_id]
                .into_iter()
                .all(|value| {
                    !value.is_empty()
                        && value.len() <= 128
                        && value
                            .bytes()
                            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
                })
            && self.permission_revision > 0
            && self.expires_at_ms > 0
            && self.route.spawn_generation > 0
            && !self.route.thread_id.is_empty()
            && !self.route.app_server_session_id.is_empty()
            && self.route.control_socket.is_absolute()
            && self.route.codex_home.is_absolute()
            && self.next_intent_sequence > 0
            && !self.intent_namespace.is_empty()
            && self.intent_namespace.len() <= 96
            && self
                .intent_namespace
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    }

    pub(crate) fn same_authorization(&self, other: &Self) -> bool {
        let mut compare = other.clone();
        compare.next_intent_sequence = self.next_intent_sequence;
        self == &compare
    }
}
