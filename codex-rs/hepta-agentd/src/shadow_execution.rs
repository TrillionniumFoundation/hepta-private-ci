//! Shadow-only canonical execution proposals. No tool or topology dispatch.

use codex_execution_core::Currentness;
use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionIntent;
use codex_execution_core::ExecutionJournal;
use codex_execution_core::ExecutionRecord;
use codex_execution_core::FinalUse;

use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::canonical_codex_intent_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowExecutionCandidateV1 {
    pub intent: ExecutionIntent,
    pub record_digest: String,
}

/// Canonical native entrypoint. No Codex session, thread, protocol or model
/// DTO is required, and this function cannot execute an effect. The caller must
/// bring an exact versioned intent from the appropriate independent owner.
pub fn propose_native_shadow_execution_v1(
    intent: ExecutionIntent,
) -> Result<ShadowExecutionCandidateV1, ExecutionError> {
    if intent.binding.currentness != Currentness::Current
        || !matches!(intent.binding.final_use, FinalUse::NotGranted)
        || intent.binding.predecessor.is_some()
    {
        return Err(ExecutionError::Binding("shadow candidate cannot carry authority"));
    }
    let mut journal = ExecutionJournal::new();
    let record_digest = journal.append(ExecutionRecord::ExecutionIntent(intent.clone()))?;
    Ok(ShadowExecutionCandidateV1 {
        intent,
        record_digest,
    })
}

/// Compatibility bridge only: Codex-specific bindings are translated at this
/// edge, and the native validation path is shared. This does not remove other
/// Codex dependencies or activate an independent Agent Loop.
pub fn propose_shadow_execution_v1(
    binding: ExecutionBinding,
    operation: &CodexOperationIntent,
    class: ExecutionClass,
) -> Result<ShadowExecutionCandidateV1, ExecutionError> {
    let intent = canonical_codex_intent_v1(binding, operation, class)?;
    propose_native_shadow_execution_v1(intent)
}

#[cfg(test)]
#[path = "shadow_execution_tests.rs"]
mod tests;
