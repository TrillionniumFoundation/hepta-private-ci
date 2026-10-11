use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use codex_protocol::config_types::CollaborationMode;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::TokenUsage;
use codex_protocol::protocol::TurnAbortReason;

use crate::ExtensionData;

/// Schema version for the host-owned pre-provider turn gate.
pub const TURN_START_GATE_SCHEMA_VERSION: u32 = 1;

/// Safety-ordered state of a host-owned turn-start gate.
///
/// `Pending` is fail-closed: a contributor that attaches a gate must
/// explicitly authorize the provider boundary. `Allowed` can only be reached
/// from `Pending`; a later failure may still strengthen it to `Blocked` before
/// the provider boundary is checked. A blocked gate cannot be reopened.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TurnStartGateDisposition {
    Pending,
    Allowed,
    Blocked,
}

/// Whether a turn is a fresh admission or a restart of a persisted request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TurnStartOrigin {
    NewTurn,
    Recovery,
}

#[derive(Debug)]
struct TurnStartGateState {
    disposition: TurnStartGateDisposition,
    reason_code: Option<String>,
}

/// Typed side-channel between a lifecycle contributor and the host's provider
/// boundary. It is intentionally in-memory and turn-scoped; it grants no
/// durable or production authority.
#[derive(Clone, Debug)]
pub struct TurnStartGate {
    state: Arc<Mutex<TurnStartGateState>>,
}

impl Default for TurnStartGate {
    fn default() -> Self {
        Self::new()
    }
}

impl TurnStartGate {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(TurnStartGateState {
                disposition: TurnStartGateDisposition::Pending,
                reason_code: None,
            })),
        }
    }

    /// Authorizes the boundary only if no contributor has blocked it.
    pub fn allow(&self) {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        if state.disposition == TurnStartGateDisposition::Pending {
            state.disposition = TurnStartGateDisposition::Allowed;
        }
    }

    /// Permanently blocks this turn's provider boundary.
    pub fn block(&self, reason_code: impl Into<String>) {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        state.disposition = TurnStartGateDisposition::Blocked;
        if state.reason_code.is_some() {
            return;
        }
        let reason_code = reason_code.into();
        state.reason_code = Some(
            if reason_code.len() <= 128 && !reason_code.as_bytes().contains(&0) {
                reason_code
            } else {
                "turn_start_gate_blocked".to_string()
            },
        );
    }

    pub fn disposition(&self) -> TurnStartGateDisposition {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .disposition
    }

    pub fn is_allowed(&self) -> bool {
        self.disposition() == TurnStartGateDisposition::Allowed
    }

    pub fn reason_code(&self) -> Option<String> {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .reason_code
            .clone()
    }
}

/// Input supplied when the host starts a turn.
pub struct TurnStartInput<'a> {
    /// Stable host-owned turn identifier.
    pub turn_id: &'a str,
    /// Host-owned lifecycle origin for this turn.
    pub origin: TurnStartOrigin,
    /// Effective collaboration mode for this turn.
    pub collaboration_mode: &'a CollaborationMode,
    /// Total token usage snapshot captured when the turn started.
    pub token_usage_at_turn_start: &'a TokenUsage,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
    /// Store scoped to this turn runtime.
    pub turn_store: &'a ExtensionData,
}

/// Input supplied when the host completes a turn.
pub struct TurnStopInput<'a> {
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
    /// Store scoped to this turn runtime.
    pub turn_store: &'a ExtensionData,
}

/// Input supplied when the host aborts a turn.
pub struct TurnAbortInput<'a> {
    /// Reason the host aborted the turn.
    pub reason: TurnAbortReason,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
    /// Store scoped to this turn runtime.
    pub turn_store: &'a ExtensionData,
}

/// Input supplied when the host observes an error for a turn.
pub struct TurnErrorInput<'a> {
    /// Stable host-owned turn identifier.
    pub turn_id: &'a str,
    /// Error surfaced by the host for this turn.
    pub error: CodexErrorInfo,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
    /// Store scoped to this turn runtime.
    pub turn_store: &'a ExtensionData,
}
