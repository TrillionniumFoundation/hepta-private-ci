//! Original Chain task settlement observed alongside exact packet membership.

use serde::Deserialize;
use serde::Serialize;

pub const AUTOMATION_TERMINAL_OBSERVATION_CAPABILITY: &str = "automation.effect.observe";

impl crate::AgentdRequest {
    pub fn automation_observe_effect(
        request_id: u64,
        spawn_generation: u64,
        intent: codex_hepta_automation::AuthorizedEffectIntent,
        command_id: String,
    ) -> Self {
        Self {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: crate::AgentdMethod::AutomationObserveEffect { intent, command_id },
        }
    }
}

/// A read-only observation of the existing reserve/receipt/accept transaction
/// path. An accepted task commits bytes; it grants no Hepta installation or
/// execution authority and is not independent evaluation of those bytes.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationAcceptedTaskObservation {
    pub schema_version: u32,
    pub task_id: String,
    pub owner: String,
    pub provider: String,
    pub output_sha256: String,
    pub accept_tx_id: String,
    pub accepted_in_exact_packet: bool,
    pub current_status: String,
}
