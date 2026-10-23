//! Codex-specific compatibility bridge to the canonical native shadow gate.
//!
//! The actual mutation boundary remains the independently authorized runtime.
//! This adapter cannot execute a tool or grant Final-use.

use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;

use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::canonical_codex_intent_v1;

use crate::native_shadow_execution::ShadowExecutionCandidateV1;
use crate::native_shadow_execution::propose_native_shadow_execution_v1;

/// Legacy Codex App Server entrypoint. Translate the DTO once at the boundary,
/// then share exactly the same validation and digest with the native caller.
pub fn propose_shadow_execution_v1(
    binding: ExecutionBinding,
    operation: &CodexOperationIntent,
    class: ExecutionClass,
) -> Result<ShadowExecutionCandidateV1, ExecutionError> {
    let intent = canonical_codex_intent_v1(binding, operation, class)?;
    propose_native_shadow_execution_v1(intent)
}
