//! Original Chain task settlement observed alongside exact packet membership.

use serde::Deserialize;
use serde::Serialize;

pub const AUTOMATION_TERMINAL_OBSERVATION_CAPABILITY: &str = "automation.effect.observe";
pub const AUTOMATION_EFFECT_RESUME_CAPABILITY: &str = "automation.effect.resume";
pub const AUTOMATION_PON_PACKET_FILE_CAPABILITY: &str = "automation.effect.pon_packet_file";

/// Transport reference to exact provider bytes in an explicitly configured
/// host-owned PoN directory. This is neither a grant nor a new payload digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationPonPacketFile {
    pub path: std::path::PathBuf,
    pub byte_length: u64,
    pub payload_sha256: codex_hepta_contracts::Sha256Digest,
}

impl crate::AgentdMethod {
    /// Two provider operations, each bounded by the host's 30-second maximum,
    /// plus five seconds for the original durable owners. Frame I/O has its
    /// separate existing bound. This is a cooperative operation budget, not an
    /// OS preemption guarantee. Queued dispatch must retain the configured
    /// provider duration before contact. Expiry never proves provider absence.
    pub fn effect_control_timeout_ms(&self) -> Option<u64> {
        matches!(
            self,
            Self::AutomationResumeEffect { .. }
                | Self::AutomationResumePonPacket { .. }
                | Self::AutomationObserveEffect { .. }
        )
        .then_some(2 * 30_000 + 5_000)
    }
}

impl crate::AgentdRequest {
    pub fn automation_resume_pon_packet(
        request_id: u64,
        spawn_generation: u64,
        intent: codex_hepta_automation::AuthorizedEffectIntent,
        packet: AutomationPonPacketFile,
        signed_grant: codex_hepta_contracts::SignedFinalUseGrant,
        command_id: String,
    ) -> Self {
        Self {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: crate::AgentdMethod::AutomationResumePonPacket {
                intent,
                packet,
                signed_grant: Box::new(signed_grant),
                command_id,
            },
        }
    }

    pub fn automation_resume_effect(
        request_id: u64,
        spawn_generation: u64,
        intent: codex_hepta_automation::AuthorizedEffectIntent,
        wire_payload_hex: String,
        signed_grant: codex_hepta_contracts::SignedFinalUseGrant,
        command_id: String,
    ) -> Self {
        Self {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: crate::AgentdMethod::AutomationResumeEffect {
                intent,
                wire_payload_hex,
                signed_grant: Box::new(signed_grant),
                command_id,
            },
        }
    }

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
