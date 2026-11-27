//! Admission-only translation of a Codex operation into the canonical ABI.
//!
//! The caller must supply independently trusted turn, principal, objective,
//! policy and host bindings. Translation does not grant execution authority.

use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionIntent;
use codex_execution_core::ExecutionRecord;

use crate::CodexOperationIntent;

pub fn canonical_codex_intent_v1(
    binding: ExecutionBinding,
    operation: &CodexOperationIntent,
    class: ExecutionClass,
) -> Result<ExecutionIntent, ExecutionError> {
    if binding.operation_id != operation.operation_id.as_str()
        || operation.payload_digest != operation.lease_payload_digest
        || operation.deadline_ms == 0
        || operation
            .app_server_binding
            .as_ref()
            .is_some_and(|source| source.agent_generation.get() != binding.generation)
    {
        return Err(ExecutionError::Binding(
            "Codex operation requires exact external admission",
        ));
    }
    let intent = ExecutionIntent {
        binding,
        class,
        payload_digest: operation.payload_digest.to_string(),
    };
    ExecutionRecord::ExecutionIntent(intent.clone()).validate()?;
    Ok(intent)
}

#[cfg(test)]
#[path = "execution_core_tests.rs"]
mod tests;
