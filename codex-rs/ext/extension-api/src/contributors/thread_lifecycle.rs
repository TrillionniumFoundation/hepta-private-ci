use std::sync::Arc;
use std::sync::Mutex;

use crate::ExtensionData;
use crate::ExtensionFuture;
use crate::ExtensionMetrics;
use codex_mcp::McpResourceClient;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::TurnEnvironmentSelection;

/// Trusted, host-resolved billing attribution for a thread.
///
/// Extensions may forward this value to first-party APIs. It is seeded by Core
/// after resolving persisted and host-provided originator state, rather than
/// from model- or tool-controlled input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ThreadOriginator(pub String);

/// Input supplied when the host starts a runtime for a thread.
pub struct ThreadStartInput<'a, C> {
    /// Host configuration visible at thread start.
    pub config: &'a C,
    /// Source that created the session for this thread.
    pub session_source: &'a SessionSource,
    /// Host-resolved installation identity for provenance correlation and binding.
    ///
    /// This value is not an authorization capability. Extensions should derive
    /// any required domain-separated digest during this callback instead of
    /// retaining or exposing the raw identity.
    pub installation_id: &'a str,
    /// Whether persistent thread-scoped state is available for this thread.
    pub persistent_thread_state_available: bool,
    /// Execution environments selected for this thread.
    pub environments: &'a [TurnEnvironmentSelection],
    /// MCP resource access supplied by the host for this session.
    pub mcp_resource_client: Option<Arc<McpResourceClient>>,
    /// Session-attributed metrics supplied by the host.
    pub extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
}

/// Input supplied after the host has registered a fully initialized thread.
pub struct ThreadReadyInput<'a, C> {
    /// Host configuration visible after thread registration.
    pub config: &'a C,
    /// Source that created the session for this thread.
    pub session_source: &'a SessionSource,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
}

/// Input supplied when the host resumes an existing thread.
pub struct ThreadResumeInput<'a> {
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
}

/// Why a thread has no immediately pending work.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ThreadIdleCause {
    /// The previous turn completed and automatic follow-up work can run.
    Completed,
    /// The user interrupted the previous turn.
    Interrupted,
    /// The previous turn ended with a terminal error.
    Failed,
}

/// Ordered requests for new work after the current idle cleanup completes.
///
/// Contributors register futures while the host still owns its completion
/// fence. The host first completes every cleanup callback, then waits for the
/// fence and polls these futures in registration order. Once one starts a new
/// turn, the remaining callbacks belong to a stale idle observation and are
/// discarded. These are notifications, not admission capabilities: each
/// continuation must use the normal atomic
/// input API, including its shutdown and permission checks.
#[derive(Default)]
pub struct ThreadIdleContinuations {
    pending: Mutex<Vec<ExtensionFuture<'static, ()>>>,
}

impl ThreadIdleContinuations {
    /// Record new work without polling it inside an owner-fenced callback.
    pub fn push(&self, continuation: ExtensionFuture<'static, ()>) {
        self.pending
            .lock()
            .unwrap_or_else(|error| panic!("idle continuation mutex poisoned: {error:?}"))
            .push(continuation);
    }

    /// Transfer the ordered futures to the host after all callbacks return.
    pub fn take(&self) -> Vec<ExtensionFuture<'static, ()>> {
        std::mem::take(
            &mut *self
                .pending
                .lock()
                .unwrap_or_else(|error| panic!("idle continuation mutex poisoned: {error:?}")),
        )
    }
}

/// Input supplied when the host has no immediately pending thread work.
pub struct ThreadIdleInput<'a> {
    /// Why the thread became idle.
    pub cause: ThreadIdleCause,
    /// New admission attempts must be registered here instead of awaited from
    /// this callback, which may still be owned by the previous terminalizer.
    pub continuations: &'a ThreadIdleContinuations,
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
}

/// Input supplied when the host stops a thread runtime.
pub struct ThreadStopInput<'a> {
    /// Store scoped to the host session runtime.
    pub session_store: &'a ExtensionData,
    /// Store scoped to this thread runtime.
    pub thread_store: &'a ExtensionData,
}
