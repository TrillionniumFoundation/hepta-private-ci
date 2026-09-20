//! Explicit translation of reviewed registry state into runtime handoff policy.
//! Unknown spellings/versions must not silently acquire the stateless path.

use codex_hepta_control_plane::RuntimeModuleStateClassV1;

use crate::AgentdError;

pub(super) fn parse(state: &str) -> Result<RuntimeModuleStateClassV1, AgentdError> {
    match state {
        // Ephemeral host state has no persistent migration; declared writer
        // domains/effect scope still retain their separate handoff requirements.
        "stateless" | "ephemeral" => Ok(RuntimeModuleStateClassV1::Stateless),
        "stateful" => Ok(RuntimeModuleStateClassV1::Stateful),
        "stateful_external" => Ok(RuntimeModuleStateClassV1::ExternalStateful),
        _ => Err(AgentdError::Protocol(
            "unknown runtime module state class; explicit compatibility required".to_string(),
        )),
    }
}

#[cfg(test)]
#[path = "runtime_module_state_tests.rs"]
mod tests;
