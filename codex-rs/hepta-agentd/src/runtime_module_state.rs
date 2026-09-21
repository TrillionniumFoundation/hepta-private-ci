//! Explicit translation of reviewed registry state into runtime handoff policy.
//! Unknown spellings/versions must not silently acquire the stateless path.

use codex_hepta_control_plane::RuntimeModuleStateClassV1;

use crate::AgentdError;

pub(super) fn parse(state: &str) -> Result<RuntimeModuleStateClassV1, AgentdError> {
    match state {
        // These are explicit catalog spellings, not substring matches. Read-only
        // modules own no durable writer; declared domains/effects still retain
        // their separate handoff checks. Remote reads do not imply a remote writer.
        "stateless"
        | "stateless_runtime"
        | "ephemeral"
        | "ephemeral_isolated"
        | "read_only"
        | "read_only_remote" => Ok(RuntimeModuleStateClassV1::Stateless),
        // A rebuildable projection still has state to drain/fence. Neither
        // 'shadow' nor 'create_only' is an exemption from the lifecycle protocol.
        "stateful"
        | "stateful_projection"
        | "stateful_rebuildable"
        | "stateful_append_only"
        | "stateful_shadow"
        | "stateful_create_only"
        | "isolated_stateful" => Ok(RuntimeModuleStateClassV1::Stateful),
        "stateful_external" => Ok(RuntimeModuleStateClassV1::ExternalStateful),
        _ => Err(AgentdError::Protocol(
            "unknown runtime module state class; explicit compatibility required".to_string(),
        )),
    }
}

#[cfg(test)]
#[path = "runtime_module_state_tests.rs"]
mod tests;
