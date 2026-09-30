//! Immutable governed candidate identities; no mutation or acceptance authority.
use crate::AgentdError;
use codex_hepta_agent_components::types::Digest32;
#[path = "self_iteration_contracts.rs"]
mod contracts;
pub use contracts::*;
#[path = "self_iteration_payload.rs"]
mod payload;
pub use payload::self_iteration_canary_payload_v1;
pub use payload::self_iteration_candidate_payload_v1;
pub use payload::self_iteration_stage_payload_v1;

fn invalid(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}
fn control_error(error: crate::AgentdNeuronControlErrorV2) -> AgentdError {
    AgentdError::Protocol(format!("self-iteration runtime: {error}"))
}
