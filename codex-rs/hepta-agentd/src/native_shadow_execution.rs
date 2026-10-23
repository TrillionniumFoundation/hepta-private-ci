//! Backend-neutral shadow execution admission for Hepta Agentd.
//!
//! This module deliberately does not depend on Codex, the App Server, a model,
//! tool drivers or any credential provider. It records a proposal, not an
//! authorization to run a process or apply a device effect. The independent
//! runtime owner must verify signed Final-use at the physical entrypoint,
//! commit a durable write-ahead receipt, and reconcile unknown effects.

use codex_execution_core::Currentness;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionIntent;
use codex_execution_core::ExecutionJournal;
use codex_execution_core::ExecutionRecord;
use codex_execution_core::FinalUse;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowExecutionCandidateV1 {
    pub intent: ExecutionIntent,
    pub record_digest: String,
}

/// Produce the exact canonical, non-authorizing candidate without any
/// Codex-specific session, provider, thread or turn DTO.
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

#[cfg(test)]
#[path = "native_shadow_execution_tests.rs"]
mod tests;
