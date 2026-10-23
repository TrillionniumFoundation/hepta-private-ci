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

/// This entrypoint is side-effect free. Only the independent runtime owner may
/// turn a shadow proposal into a reservation, start or final effect receipt.
pub fn propose_shadow_execution_v1(
    binding: ExecutionBinding,
    operation: &CodexOperationIntent,
    class: ExecutionClass,
) -> Result<ShadowExecutionCandidateV1, ExecutionError> {
    if binding.currentness != Currentness::Current
        || !matches!(binding.final_use, FinalUse::NotGranted)
        || binding.predecessor.is_some()
    {
        return Err(ExecutionError::Binding("shadow candidate cannot carry authority"));
    }
    let intent = canonical_codex_intent_v1(binding, operation, class)?;
    let mut journal = ExecutionJournal::new();
    let record_digest = journal.append(ExecutionRecord::ExecutionIntent(intent.clone()))?;
    Ok(ShadowExecutionCandidateV1 {
        intent,
        record_digest,
    })
}
