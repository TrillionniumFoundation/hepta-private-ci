//! Cancellation provenance for one prepared execution, independent of turn lifetime.

use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

const CANCELLED: u8 = 1;
const CLASSIFIED: u8 = 2;

#[derive(Debug)]
pub(crate) struct ExecApprovalTerminal {
    launch_turn_id: String,
    parent_call_id: String,
    state: AtomicU8,
}

impl ExecApprovalTerminal {
    #[cfg(any(unix, test))]
    pub(crate) fn new(launch_turn_id: String, parent_call_id: String) -> Self {
        Self {
            launch_turn_id,
            parent_call_id,
            state: AtomicU8::new(0),
        }
    }

    /// Freeze only the cancellation classification. The existing immediate or
    /// background owner must still emit its completion, even after a prior call.
    /// CLASSIFIED is not a delivered-event flag.
    pub(crate) fn cancelled_at_completion(&self, turn_id: &str, call_id: &str) -> bool {
        if self.launch_turn_id != turn_id || self.parent_call_id != call_id {
            return false;
        }
        self.state.fetch_or(CLASSIFIED, Ordering::AcqRel) & CANCELLED != 0
    }
}

/// Bound to the actual pending approval entry, which can belong to a later turn
/// than the process that requested it. Dropping the entry never marks a cancel.
pub(crate) struct PendingExecApprovalCancellation {
    approval_turn_id: String,
    terminal: Arc<ExecApprovalTerminal>,
}

impl PendingExecApprovalCancellation {
    pub(crate) fn new(
        approval_turn_id: String,
        parent_call_id: &str,
        terminal: Arc<ExecApprovalTerminal>,
    ) -> Option<Self> {
        (terminal.parent_call_id == parent_call_id).then_some(Self {
            approval_turn_id,
            terminal,
        })
    }

    pub(crate) fn mark_explicit_abort(&self, supplied_turn_id: Option<&str>) {
        if supplied_turn_id.is_some_and(|turn_id| turn_id != self.approval_turn_id) {
            return;
        }
        // A terminal classification that won first cannot be rewritten by a
        // late approval response. Repeated Abort is also a no-op.
        let _ =
            self.terminal
                .state
                .compare_exchange(0, CANCELLED, Ordering::AcqRel, Ordering::Acquire);
    }
}

#[cfg(test)]
#[path = "approval_terminal_tests.rs"]
mod tests;
