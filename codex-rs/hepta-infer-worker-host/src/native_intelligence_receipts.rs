//! The process spawn lease and the runtime run generation are distinct domains.
//! Compare a dispatch acknowledgement with the complete owner handoff captured
//! before preparation, never with the worker's process-generation configuration.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;

use super::NativeIntelligenceRunBinding;

pub(super) fn matches_new_dispatch(
    dispatched: &AgentRunReceipt,
    handoff: &AgentRunReceipt,
    binding: &NativeIntelligenceRunBinding,
) -> bool {
    handoff.phase == AgentRunPhase::ContextAttached
        && !handoff.terminal_observed
        && handoff.run_id == binding.run_id
        && handoff.revision == binding.expected_revision
        && handoff.generation != 0
        && dispatched.run_id == handoff.run_id
        && dispatched.phase == AgentRunPhase::Dispatched
        && !dispatched.idempotent
        && !dispatched.terminal_observed
        && Some(dispatched.revision) == handoff.revision.checked_add(1)
        && dispatched.generation == handoff.generation
        && dispatched.fence_digest == handoff.fence_digest
        && dispatched.authority_epoch == handoff.authority_epoch
        && dispatched.deadline_ms == handoff.deadline_ms
        && dispatched.cancel_reason.is_none()
        && dispatched.cancel_ack_deadline_ms.is_none()
        && dispatched.context_digest.as_deref() == Some(binding.context_digest.as_str())
        && dispatched.compilation_receipt_digest.as_deref()
            == Some(binding.envelope_digest.as_str())
}

#[cfg(test)]
#[path = "native_intelligence_receipts_tests.rs"]
mod tests;
