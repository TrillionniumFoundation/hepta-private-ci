//! Typed, authority-neutral host execution seam.
//!
//! It never calls SSH, MCP or the local shell. A production host must implement
//! both independent verifiers and persist accepted events before applying effects.

use codex_execution_core::EffectReceipt;
use codex_execution_core::EffectReceiptVerifier;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionJournal;
use codex_execution_core::ExecutionRecord;
use codex_execution_core::ExecutionStarted;
use codex_execution_core::ExecutionVerifier;

/// The in-process host adapter can inspect a canonical journal without
/// importing Codex agent plans, prompts or TUI types.
#[derive(Debug, Default)]
pub struct RuntimeExecutionPortV1 {
    journal: ExecutionJournal,
}

impl RuntimeExecutionPortV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn events(&self) -> &[ExecutionRecord] {
        self.journal.events()
    }

    /// Non-authorizing events are validated and hash linked, not executed.
    pub fn observe(&mut self, event: ExecutionRecord) -> Result<String, ExecutionError> {
        self.journal.append(event)
    }

    pub fn admit_start(
        &mut self,
        event: ExecutionStarted,
        verifier: &impl ExecutionVerifier,
    ) -> Result<String, ExecutionError> {
        self.journal.append_started(event, verifier)
    }

    pub fn admit_effect_receipt(
        &mut self,
        event: EffectReceipt,
        verifier: &impl EffectReceiptVerifier,
    ) -> Result<String, ExecutionError> {
        self.journal.append_effect_receipt(event, verifier)
    }
}
