//! Typed, authority-neutral host execution seam.
//!
//! It never calls SSH, MCP or the local shell. A production host must implement
//! both independent verifiers and persist accepted events before applying effects.

use codex_execution_core::EffectReceipt;
use codex_execution_core::EffectReceiptVerifier;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionJournal;
use codex_execution_core::ExecutionRecord;
use codex_execution_core::ExecutionStarted;
use codex_execution_core::ExecutionVerifier;

/// Strictly increasing capability rollout. Default Shadow admits no starts.
#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub enum RuntimeCutoverStageV1 {
    #[default]
    ShadowOnly,
    ReadOnlyInspection,
    FileRead,
    NonDestructiveBuild,
    RestrictedFileWrite,
    DurableProcess,
    PrivilegedAction,
    CrossHostDevice,
}

impl RuntimeCutoverStageV1 {
    pub const fn permits(self, class: ExecutionClass) -> bool {
        let stage = self as u8;
        let required = match class {
            ExecutionClass::ReadOnlyInspection => Self::ReadOnlyInspection as u8,
            ExecutionClass::FileRead => Self::FileRead as u8,
            ExecutionClass::NonDestructiveBuild => Self::NonDestructiveBuild as u8,
            ExecutionClass::RestrictedFileWrite => Self::RestrictedFileWrite as u8,
            ExecutionClass::DurableProcess => Self::DurableProcess as u8,
            ExecutionClass::PrivilegedAction => Self::PrivilegedAction as u8,
            ExecutionClass::CrossHostDevice => Self::CrossHostDevice as u8,
        };
        stage >= required
    }
}

/// The in-process host adapter can inspect a canonical journal without
/// importing Codex agent plans, prompts or TUI types.
#[derive(Debug, Default)]
pub struct RuntimeExecutionPortV1 {
    journal: ExecutionJournal,
    cutover: RuntimeCutoverStageV1,
}

impl RuntimeExecutionPortV1 {
    pub fn new() -> Self {
        Self::default()
    }

    // Only the runtime-owning crate may opt in after host policy admission.
    // External callers cannot elevate a fresh shadow port by supplying a tag.
    pub(crate) fn with_cutover(cutover: RuntimeCutoverStageV1) -> Self {
        Self {
            journal: ExecutionJournal::new(),
            cutover,
        }
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
        let class = self.journal.events().first().and_then(|record| match record {
            ExecutionRecord::ExecutionIntent(intent) => Some(intent.class),
            _ => None,
        });
        if !class.is_some_and(|class| self.cutover.permits(class)) {
            return Err(ExecutionError::AuthorizationDenied);
        }
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
