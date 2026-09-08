mod compact;
mod lifecycle;
mod regular;
mod review;
mod user_shell;

use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_diagnostics::Gauge;
use codex_extension_api::QualificationTurnAdmissionIdentity;
use codex_extension_api::ThreadIdleCause;
use futures::FutureExt;
use futures::future::BoxFuture;
use tokio::select;
use tokio::sync::Mutex;
use tokio::sync::Notify;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;
use tokio_util::task::AbortOnDropHandle;
use tracing::Instrument;
use tracing::Span;
use tracing::field;
use tracing::info_span;
use tracing::trace;
use tracing::trace_span;
use tracing::warn;

use crate::codex_thread::BackgroundTerminalInfo;
use crate::config::Config;
use crate::context::ContextualUserFragment;
use crate::context_manager::ContextManager;
use crate::session::TurnInput;
use crate::session::session::RecoveryCandidate;
use crate::session::session::Session;
use crate::session::turn::TurnRunOrigin;
use crate::session::turn::run_hooks_and_record_inputs;
use crate::session::turn_context::TurnContext;
use crate::state::ActiveTurn;
use crate::state::DurableRecoveryState;
use crate::state::RunningTask;
use crate::state::StartReservationHandle;
use crate::state::StartTransition;
use crate::state::StartTransitionCompletion;
use crate::state::TaskKind;
use crate::state::TaskTerminalization;
use crate::state::TaskTerminalizationKind;
use crate::state::TaskTerminalizationPhase;
use crate::state::TurnRecoveryAuthority;
use crate::state::TurnState;
use codex_analytics::TurnProfileFact;
use codex_analytics::TurnTokenUsageFact;
use codex_context_fragments::RenderedFragment;
use codex_otel::SessionTelemetry;
use codex_otel::TURN_E2E_DURATION_METRIC;
use codex_otel::TURN_MEMORY_METRIC;
use codex_otel::TURN_NETWORK_PROXY_METRIC;
use codex_otel::TURN_TOKEN_USAGE_METRIC;
use codex_otel::TURN_TOOL_CALL_METRIC;
use codex_otel::TURN_UNIFIED_EXEC_RUNNING_PROCESSES_METRIC;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::TokenUsage;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnAbortedEvent;
use codex_protocol::protocol::TurnCompleteEvent;
use codex_protocol::protocol::WarningEvent;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_thread_store::LiveThread;
use codex_thread_store::PersistContext;

use codex_features::Feature;
use codex_protocol::error::CodexErr;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::error::Result as CodexResult;
pub(crate) use compact::CompactTask;
pub(crate) use regular::RegularTask;
pub(crate) use review::ReviewTask;
pub(crate) use user_shell::UserShellCommandMode;
pub(crate) use user_shell::UserShellCommandTask;
pub(crate) use user_shell::execute_user_shell_command;

pub(crate) const GRACEFULL_INTERRUPTION_TIMEOUT_MS: u64 = 100;
/// Bounds one detached terminalizer owner. A timeout cancels the owner
/// future itself; its Drop implementation returns the exact witness to the
/// registry and leaves the completion fence unresolved.
#[cfg(not(test))]
pub(crate) const TERMINALIZER_WATCHDOG_TIMEOUT: Duration = Duration::from_secs(30);
#[cfg(test)]
pub(crate) const TERMINALIZER_WATCHDOG_TIMEOUT: Duration = Duration::from_secs(2);

const TASK_COMPACT_METRIC: &str = "codex.task.compact";
static ACTIVE_TURNS: Gauge = Gauge::new("core.turns.active");

pub(crate) type SessionTaskResult = CodexResult<Option<String>>;

pub(crate) enum MailboxParentProvenance {
    Ignore,
    Attribute,
}

/// The two history views needed for a recovery start.  The rewound view is
/// installed only after the host-owned start marker exists; the original view
/// is restored if the transition is aborted before `RunningTask` attach.
pub(crate) struct RecoveryHistoryTransition {
    pub(crate) install: ContextManager,
    pub(crate) restore: ContextManager,
}

/// Snapshot of one exact task's recovery authority before it is detached.
///
/// The authority itself remains attached so the terminal publication path can
/// prove that no Ready -> Unready/Ready transition raced with cancellation.
#[derive(Clone)]
struct RecoverySeed {
    turn_id: String,
    authority: Arc<TurnRecoveryAuthority>,
    generation: u64,
    request_fingerprint_sha256: String,
    replay: codex_history::TurnRecoveryReplayV1,
    persistence_failure_generation: u64,
    attach_epoch: u64,
    confirmation_generation: Option<u64>,
}

#[derive(Default)]
struct TaskAbortOutcome {
    task_quiesced: bool,
    terminal_persistence_generation: Option<u64>,
    recovery_seed: Option<RecoverySeed>,
}

/// Progress points for an ordinary task abort handoff.  Only `Claimed` is
/// retryable: every later phase may already have crossed a durable, lifecycle,
/// or task-owned side effect and therefore stays explicitly fail-closed if its
/// runtime disappears.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskAbortHandoffPhase {
    Claimed,
    RecoveryRevoking,
    TaskAborting,
    LifecyclePublishing,
    InputClearing,
    MarkerReleasing,
    RecoveryPublishing,
    PendingWorkStarting,
    Complete,
}

/// Complete witness for one exact abort terminalizer.  The running task and
/// the caller's first-wins reason move into this registry-backed handoff in
/// the same active-turn critical section that installs the typed marker, so a
/// cancelled detached future cannot drop either witness.
pub(crate) struct TaskAbortHandoff {
    task: Option<RunningTask>,
    turn_state: Arc<Mutex<TurnState>>,
    terminalization_identity: Arc<()>,
    completion: Arc<StartTransitionCompletion>,
    recovery_seed: Option<RecoverySeed>,
    recovery_authority: Option<Arc<TurnRecoveryAuthority>>,
    reason: TurnAbortReason,
    deferred_idle_cause: Option<ThreadIdleCause>,
    phase: TaskAbortHandoffPhase,
    failed_closed: bool,
    task_quiesced: bool,
    terminal_persistence_generation: Option<u64>,
}

pub(crate) type TaskAbortHandoffSlot = Arc<std::sync::Mutex<Option<TaskAbortHandoff>>>;

struct DetachedTaskForAbort {
    slot: TaskAbortHandoffSlot,
}

/// Progress points for a normal task-finish handoff.  A finish witness is
/// retryable only before its detached driver has been polled.  Once recovery,
/// rollout, lifecycle, or marker publication begins, cancellation is retained
/// fail-closed rather than replaying any of those side effects.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskFinishHandoffPhase {
    Claimed,
    RecoveryRevoking,
    RolloutFlushing,
    InputClearing,
    PersistencePublishing,
    LifecyclePublishing,
    MarkerReleasing,
    RecoveryPublishing,
    PendingWorkStarting,
    Complete,
}

/// Full witness for one ordinary task finish.  The task is detached from its
/// runner before this value is published, so a scheduler that drops the first
/// continuation poll cannot abort the runner or lose the terminalization
/// fence.  Shutdown can adopt a still-`Claimed` witness from the registry.
pub(crate) struct TaskFinishHandoff {
    task: Option<RunningTask>,
    turn_context: Arc<TurnContext>,
    task_result: Option<SessionTaskResult>,
    turn_state: Arc<Mutex<TurnState>>,
    terminalization_identity: Arc<()>,
    completion: Arc<StartTransitionCompletion>,
    recovery_seed: Option<RecoverySeed>,
    recovery_authority: Option<Arc<TurnRecoveryAuthority>>,
    phase: TaskFinishHandoffPhase,
    failed_closed: bool,
}

pub(crate) type TaskFinishHandoffSlot = Arc<std::sync::Mutex<Option<TaskFinishHandoff>>>;

struct TaskFinishHandoffOwner {
    slot: TaskFinishHandoffSlot,
    handoff: Option<TaskFinishHandoff>,
}

#[expect(
    clippy::expect_used,
    reason = "the finish handoff owner remains armed until explicit disarm or Drop"
)]
impl TaskFinishHandoffOwner {
    fn new(slot: TaskFinishHandoffSlot, handoff: TaskFinishHandoff) -> Self {
        Self {
            slot,
            handoff: Some(handoff),
        }
    }

    fn handoff_mut(&mut self) -> &mut TaskFinishHandoff {
        self.handoff
            .as_mut()
            .expect("finish handoff owner remains armed")
    }

    fn is_complete(&self) -> bool {
        self.handoff
            .as_ref()
            .is_some_and(|handoff| handoff.completion.is_complete())
    }

    fn disarm(&mut self) {
        self.handoff.take();
    }
}

#[expect(
    clippy::expect_used,
    reason = "Drop observes a private fail-stop handoff mutex"
)]
impl Drop for TaskFinishHandoffOwner {
    fn drop(&mut self) {
        let Some(mut handoff) = self.handoff.take() else {
            return;
        };
        if handoff.completion.is_complete() {
            return;
        }
        if handoff.phase != TaskFinishHandoffPhase::Claimed {
            handoff.failed_closed = true;
        }
        let mut slot = self
            .slot
            .lock()
            .expect("task finish handoff slot mutex poisoned");
        if slot.is_none() {
            *slot = Some(handoff);
        } else {
            warn!("task finish handoff witness already reclaimed during owner drop");
        }
    }
}

/// Exact task witness owned by root-turn suspension.  Suspension is not a
/// terminal protocol outcome, but it still has to keep the active slot fenced
/// while cancellation and persistence drain; the typed marker prevents a
/// replacement admission from observing a false idle turn.
pub(crate) struct DetachedTaskForSuspension {
    pub(crate) task: Option<RunningTask>,
    pub(crate) turn_state: Arc<Mutex<TurnState>>,
    pub(crate) terminalization_identity: Arc<()>,
    pub(crate) task_identity: Arc<dyn AnySessionTask>,
    pub(crate) turn_context: Arc<TurnContext>,
    pub(crate) attach_epoch: u64,
}

/// Progress points for the post-claim suspension owner.  The first two
/// phases are safe to retry after a runtime drops the detached future because
/// the task witness is still owned by the guard.  Once shutdown or writer
/// persistence has started, a dropped future is treated as uncertain and is
/// retained fail-closed rather than blindly repeating a non-idempotent close.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SuspensionHandoffPhase {
    Claimed,
    TaskQuiescing,
    InputClearing,
    RuntimeStopping,
    WriterFlushing,
    WriterClosing,
    LifecyclePublishing,
    EventPublishing,
    MarkerReleasing,
    Complete,
}

/// Full witness for the post-claim root-turn suspension handoff.  Once a
/// suspension claim succeeds, the caller may disappear at any await; this
/// witness keeps the detached task, writer, exact identity, and reply alive
/// until the final writer close and marker CAS complete.  A failed handoff is
/// retained in its registry slot rather than being retried or made to look
/// idle.
pub(crate) struct SuspensionHandoff {
    pub(crate) suspended: DetachedTaskForSuspension,
    pub(crate) live_thread: LiveThread,
    pub(crate) submission_id: String,
    pub(crate) reply:
        Option<oneshot::Sender<CodexResult<codex_protocol::turn_input::SuspendTurnOutcome>>>,
    pub(crate) phase: SuspensionHandoffPhase,
    pub(crate) failed_closed: bool,
}

pub(crate) type SuspensionHandoffSlot = Arc<std::sync::Mutex<Option<SuspensionHandoff>>>;

/// Owns an abort witness while its detached driver is being polled.  A
/// runtime teardown returns the witness to the registry cell; once the driver
/// has crossed a non-idempotent phase the returned witness is marked
/// `failed_closed` and can never be replayed by shutdown.
struct TaskAbortHandoffOwner {
    slot: TaskAbortHandoffSlot,
    handoff: Option<TaskAbortHandoff>,
}

#[expect(
    clippy::expect_used,
    reason = "the abort handoff owner remains armed until explicit disarm or Drop"
)]
impl TaskAbortHandoffOwner {
    fn new(slot: TaskAbortHandoffSlot, handoff: TaskAbortHandoff) -> Self {
        Self {
            slot,
            handoff: Some(handoff),
        }
    }

    fn handoff_mut(&mut self) -> &mut TaskAbortHandoff {
        self.handoff
            .as_mut()
            .expect("abort handoff owner remains armed")
    }

    fn is_complete(&self) -> bool {
        self.handoff
            .as_ref()
            .is_some_and(|handoff| handoff.completion.is_complete())
    }

    fn disarm(&mut self) {
        self.handoff.take();
    }
}

#[expect(
    clippy::expect_used,
    reason = "Drop observes a private fail-stop handoff mutex"
)]
impl Drop for TaskAbortHandoffOwner {
    fn drop(&mut self) {
        let Some(mut handoff) = self.handoff.take() else {
            return;
        };
        if handoff.completion.is_complete() {
            return;
        }
        if handoff.phase != TaskAbortHandoffPhase::Claimed {
            handoff.failed_closed = true;
        }
        let mut slot = self
            .slot
            .lock()
            .expect("task abort handoff slot mutex poisoned");
        if slot.is_none() {
            *slot = Some(handoff);
        } else {
            warn!("task abort handoff witness already reclaimed during owner drop");
        }
    }
}

enum ActiveTurnAbortTarget {
    Running(DetachedTaskForAbort),
    Starting { deferred_idle: bool },
    Terminalizing,
}

enum StartTransitionClearOutcome {
    Stale,
    Cleared {
        deferred_idle_cause: Option<ThreadIdleCause>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AbortTurnOutcome {
    NotActive,
    Running,
    Starting,
    DeferredStart,
    Terminalizing,
}

#[derive(Debug)]
pub(crate) enum StartReservationRelease {
    Released,
    #[expect(
        dead_code,
        reason = "the abort reason is retained as an audit witness even when callers only branch on the outcome"
    )]
    AbortRequested(TurnAbortReason),
    Stale,
}

/// Owns a caller-owned start reservation across the asynchronous preparation
/// preamble.  The reservation must not outlive the future that installed it:
/// cancellation can happen at any of the awaits before `start_task_owned`
/// promotes it to a host-owned transition.  Normal callers disarm this guard
/// after the owned start outcome is known; `Drop` supplies the cancellation
/// path and uses the same identity CAS as explicit cleanup.
pub(crate) struct StartReservationOwner {
    session: Arc<Session>,
    handle: Option<StartReservationHandle>,
}

#[expect(
    clippy::expect_used,
    reason = "the start reservation owner remains armed until explicit completion"
)]
impl StartReservationOwner {
    pub(crate) fn new(session: &Arc<Session>, handle: StartReservationHandle) -> Self {
        Self {
            session: Arc::clone(session),
            handle: Some(handle),
        }
    }

    pub(crate) fn handle(&self) -> &StartReservationHandle {
        self.handle
            .as_ref()
            .expect("start reservation owner remains armed until completion")
    }

    pub(crate) fn disarm(&mut self) {
        self.handle = None;
    }
}

impl Drop for StartReservationOwner {
    fn drop(&mut self) {
        let Some(handle) = self.handle.take() else {
            return;
        };
        let session = Arc::clone(&self.session);
        // A construction-time runtime handle is not a liveness witness:
        // Tokio silently shuts down a future submitted through a closed
        // `OwnedTasks` list.  Only use the thread-local current runtime for
        // the asynchronous path.  When Drop runs off-runtime (including
        // after the construction runtime has shut down), perform the exact
        // identity CAS synchronously; this reservation release has no async
        // persistence or lifecycle ordering to preserve.
        let Some(runtime_handle) = tokio::runtime::Handle::try_current().ok() else {
            let mut active = session.active_turn.blocking_lock();
            let release =
                Session::release_start_reservation_if_current_locked(&mut active, &handle);
            if !matches!(release, StartReservationRelease::Stale) {
                session.settle_consumed_recovery_status();
            }
            return;
        };
        runtime_handle.spawn(async move {
            let release = session.release_start_reservation_if_current(&handle).await;
            if !matches!(release, StartReservationRelease::Stale) {
                session.settle_consumed_recovery_status();
            }
        });
    }
}

/// Payload retained by the detached cleanup continuation for one exact
/// host-owned start transition.  The owner future is allowed to disappear at
/// any cancellation point after promotion; this witness gives the cleanup
/// continuation enough identity to terminalize only that transition.
pub(crate) struct StartTransitionCleanup {
    session: Arc<Session>,
    task: Arc<dyn AnySessionTask>,
    turn_context: Arc<TurnContext>,
    turn_state: Arc<Mutex<TurnState>>,
    transition_identity: Arc<()>,
    completion: Arc<StartTransitionCompletion>,
    recovery_history_restore: Option<ContextManager>,
    /// Set once the detached terminalizer has crossed into the non-idempotent
    /// abort path.  A witness with this bit set is never retried: shutdown
    /// keeps it in the registry so the unresolved completion fence remains
    /// fail-closed rather than replaying lifecycle/durable side effects.
    failed_closed: bool,
}

pub(crate) type StartTransitionCleanupSlot = Arc<std::sync::Mutex<Option<StartTransitionCleanup>>>;

impl StartTransitionCleanup {
    pub(crate) fn new(
        session: &Arc<Session>,
        task: Arc<dyn AnySessionTask>,
        turn_context: Arc<TurnContext>,
        turn_state: Arc<Mutex<TurnState>>,
        transition_identity: Arc<()>,
        completion: Arc<StartTransitionCompletion>,
        recovery_history_restore: Option<ContextManager>,
    ) -> Self {
        Self {
            session: Arc::clone(session),
            task,
            turn_context,
            turn_state,
            transition_identity,
            completion,
            recovery_history_restore,
            failed_closed: false,
        }
    }
}

/// Owns one cleanup witness while the detached terminalizer is running.
///
/// The registry cell is the durable handoff point.  If Tokio cancels or
/// unwinds the terminalizer before it begins side effects, this guard returns
/// the witness to the cell for a later shutdown retry.  Once the abort path
/// has crossed its first non-idempotent await, the guard returns a
/// `failed_closed` witness instead; no caller may replay that path or clear
/// the completion fence speculatively.
struct StartTransitionCleanupOwner {
    slot: StartTransitionCleanupSlot,
    cleanup: Option<StartTransitionCleanup>,
    side_effects_started: bool,
}

#[expect(
    clippy::expect_used,
    reason = "the cleanup owner and slot are identity-fenced lifecycle state"
)]
impl StartTransitionCleanupOwner {
    fn new(slot: StartTransitionCleanupSlot, cleanup: StartTransitionCleanup) -> Self {
        Self {
            slot,
            cleanup: Some(cleanup),
            side_effects_started: false,
        }
    }

    fn cleanup(&self) -> &StartTransitionCleanup {
        self.cleanup
            .as_ref()
            .expect("start transition cleanup owner must retain its witness")
    }

    fn mark_side_effects_started(&mut self) {
        self.side_effects_started = true;
    }

    /// Normal completion has already retired the exact completion fence in
    /// `abort_dropped_start_transition`; dropping the witness here must not
    /// put it back in the registry.
    fn disarm(&mut self) {
        self.cleanup.take();
    }

    fn is_complete(&self) -> bool {
        self.cleanup
            .as_ref()
            .is_some_and(|cleanup| cleanup.completion.is_complete())
    }
}

#[expect(
    clippy::expect_used,
    reason = "Drop observes a private fail-stop cleanup slot"
)]
impl Drop for StartTransitionCleanupOwner {
    fn drop(&mut self) {
        let Some(mut cleanup) = self.cleanup.take() else {
            return;
        };
        // A terminalizer may have completed the exact fence and then been
        // cancelled while doing a post-completion mailbox wake.  Do not
        // resurrect an already-retired witness in that case.
        if cleanup.completion.is_complete() {
            return;
        }
        if self.side_effects_started {
            cleanup.failed_closed = true;
        }
        let mut slot = self
            .slot
            .lock()
            .expect("start transition cleanup slot mutex poisoned");
        if slot.is_none() {
            *slot = Some(cleanup);
        } else {
            // A concurrent shutdown drain or owner can only safely win the
            // cell once.  Keep the already-published witness and leave the
            // completion fence authoritative rather than overwriting it.
            warn!("start transition cleanup witness already reclaimed during owner drop");
        }
    }
}

/// Keeps a host-owned start transition live independently of its caller while
/// retaining a full cleanup witness even if Tokio cannot schedule the first
/// continuation poll.
///
/// A caller-owned reservation is released by [`StartReservationOwner`], but
/// promotion changes the state machine: the transition now owns lifecycle and
/// terminal ordering.  If the owner future is cancelled after that point, a
/// detached placeholder terminalizer finishes the same abort path instead of
/// leaving `active_turn.start_transition` installed forever.  Panic/hang
/// handling in the terminalizer itself remains a separate watchdog slice.  If
/// the runtime has already shut down, the registry cell preserves the marker
/// and full witness for a later session-shutdown drain rather than silently
/// dropping durable/lifecycle state.
pub(crate) struct StartTransitionOwner {
    cleanup: Option<StartTransitionCleanupSlot>,
    cleanup_spawned: bool,
}

impl StartTransitionOwner {
    pub(crate) fn new(cleanup: StartTransitionCleanupSlot) -> Self {
        Self {
            cleanup: Some(cleanup),
            cleanup_spawned: false,
        }
    }

    /// Spawn exactly one detached terminalizer.  The returned handle is only
    /// for callers that want to await normal terminal ordering; dropping the
    /// owner after this method has been called never aborts the cleanup task.
    fn spawn_cleanup(
        &mut self,
        fallback_reason: TurnAbortReason,
    ) -> Option<tokio::task::JoinHandle<()>> {
        if self.cleanup_spawned {
            return None;
        }
        let cleanup_slot = self.cleanup.as_ref()?.clone();
        let Some(runtime_handle) = tokio::runtime::Handle::try_current().ok() else {
            warn!(
                "start transition cleanup cannot be scheduled because no Tokio runtime is available; preserving its full witness"
            );
            // The completion registry retains `cleanup_slot`, so shutdown can
            // recover and execute the full witness once a live runtime owns
            // teardown.  Do not attempt a synchronous transition cleanup:
            // it crosses durable/lifecycle awaits and would violate the
            // writer and recovery ordering fences.
            self.cleanup_spawned = true;
            return None;
        };
        self.cleanup = None;
        self.cleanup_spawned = true;
        Some(runtime_handle.spawn(async move {
            let Some(cleanup) = cleanup_slot
                .lock()
                .expect("start transition cleanup slot mutex poisoned")
                .take()
            else {
                return;
            };
            if cleanup.failed_closed {
                // A shutdown drain may have re-published a witness whose
                // detached owner was already cancelled after side effects
                // began.  Do not let a late scheduler poll replay it.
                cleanup_slot
                    .lock()
                    .expect("start transition cleanup slot mutex poisoned")
                    .replace(cleanup);
                return;
            }
            let turn_id = cleanup.turn_context.sub_id.clone();
            let session = Arc::clone(&cleanup.session);
            let mut cleanup_owner =
                StartTransitionCleanupOwner::new(Arc::clone(&cleanup_slot), cleanup);
            let result = tokio::time::timeout(
                TERMINALIZER_WATCHDOG_TIMEOUT,
                AssertUnwindSafe(
                    session.abort_dropped_start_transition(&mut cleanup_owner, fallback_reason),
                )
                .catch_unwind(),
            )
            .await;
            match result {
                Ok(Err(_)) => warn!(
                    %turn_id,
                    "start-transition terminalizer panicked; retaining its completion fence"
                ),
                Err(_) => warn!(
                    %turn_id,
                    "start-transition terminalizer watchdog expired; retaining its completion fence"
                ),
                Ok(Ok(())) if cleanup_owner.is_complete() => cleanup_owner.disarm(),
                Ok(Ok(())) => {}
            }
        }))
    }

    #[cfg(test)]
    pub(crate) fn spawn_cleanup_for_test(
        &mut self,
        fallback_reason: TurnAbortReason,
    ) -> Option<tokio::task::JoinHandle<()>> {
        self.spawn_cleanup(fallback_reason)
    }

    /// Mark a successfully attached or already-stale transition as complete.
    fn disarm(&mut self) {
        if let Some(cleanup_slot) = self.cleanup.take()
            && let Some(cleanup) = cleanup_slot
                .lock()
                .expect("start transition cleanup slot mutex poisoned")
                .take()
        {
            cleanup
                .session
                .finish_start_transition(&cleanup.transition_identity, &cleanup.completion);
        }
        self.cleanup_spawned = true;
    }
}

impl Drop for StartTransitionOwner {
    fn drop(&mut self) {
        // A dropped owner is an implicit interruption.  The detached task is
        // deliberately not stored in this guard, so dropping the guard cannot
        // abort the terminalizer it just spawned while the runtime is live.
        let _ = self.spawn_cleanup(TurnAbortReason::Interrupted);
    }
}

impl Session {
    /// Registers the completion fence before releasing the active-turn lock.
    /// The registry intentionally outlives `ActiveTurn::start_transition` so
    /// shutdown can wait through post-clear idle/recovery/pending-work side
    /// effects.
    fn register_start_transition(
        &self,
        transition_identity: Arc<()>,
        completion: Arc<StartTransitionCompletion>,
        cleanup: StartTransitionCleanupSlot,
    ) {
        self.pending_start_transition_completions
            .lock()
            .expect("start transition completion registry mutex poisoned")
            .push((transition_identity, completion, cleanup));
    }

    /// Removes one exact fence before signalling it.  Identity and completion
    /// are both checked so a stale continuation cannot retire a later turn's
    /// registry entry.
    fn finish_start_transition(
        &self,
        transition_identity: &Arc<()>,
        completion: &Arc<StartTransitionCompletion>,
    ) {
        let mut pending = self
            .pending_start_transition_completions
            .lock()
            .expect("start transition completion registry mutex poisoned");
        pending.retain(|(identity, current, _cleanup)| {
            !(Arc::ptr_eq(identity, transition_identity) && Arc::ptr_eq(current, completion))
        });
        drop(pending);
        completion.complete();
    }

    fn pending_start_transition_completions(&self) -> Vec<Arc<StartTransitionCompletion>> {
        self.pending_start_transition_completions
            .lock()
            .expect("start transition completion registry mutex poisoned")
            .iter()
            .map(|(_, completion, _cleanup)| Arc::clone(completion))
            .collect()
    }

    fn pending_start_transition_cleanup_slots(&self) -> Vec<StartTransitionCleanupSlot> {
        self.pending_start_transition_completions
            .lock()
            .expect("start transition completion registry mutex poisoned")
            .iter()
            .map(|(_, _, cleanup)| Arc::clone(cleanup))
            .collect()
    }

    /// Registers a task terminalizer before its owner releases the
    /// active-turn lock.  The registry is independent of `ActiveTurn` because
    /// a replacement may be admitted as soon as the old slot CAS succeeds,
    /// while shutdown still has to wait for the old owner's post-CAS recovery
    /// and lifecycle side effects.
    fn register_task_terminalization(
        &self,
        identity: Arc<()>,
        completion: Arc<StartTransitionCompletion>,
        kind: TaskTerminalizationKind,
        suspension_handoff: Option<SuspensionHandoffSlot>,
        abort_handoff: Option<TaskAbortHandoffSlot>,
        finish_handoff: Option<TaskFinishHandoffSlot>,
    ) {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .push((
                identity,
                completion,
                kind,
                suspension_handoff,
                abort_handoff,
                finish_handoff,
            ));
    }

    /// Returns unclaimed suspension witnesses for shutdown recovery.  A
    /// running detached owner has already taken its slot, so shutdown merely
    /// waits on the completion fence; a queued/no-runtime owner leaves the
    /// slot populated and can be adopted by the shutdown drain.
    pub(crate) fn pending_suspension_handoffs_except(
        &self,
        excluded_identity: Option<&Arc<()>>,
    ) -> Vec<(Arc<()>, SuspensionHandoffSlot)> {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .iter()
            .filter_map(
                |(identity, _, kind, handoff, _abort_handoff, _finish_handoff)| {
                    if *kind != TaskTerminalizationKind::Suspend
                        || excluded_identity.is_some_and(|excluded| Arc::ptr_eq(identity, excluded))
                    {
                        return None;
                    }
                    handoff
                        .as_ref()
                        .map(|slot| (Arc::clone(identity), Arc::clone(slot)))
                },
            )
            .collect()
    }

    /// Returns queued ordinary abort witnesses. A live detached owner has
    /// taken its slot; a queued/no-runtime owner leaves it populated for the
    /// shutdown drain to adopt. Non-claimed witnesses are returned too so the
    /// drain can preserve their failed-closed fence without replaying them.
    fn pending_abort_handoffs_except(
        &self,
        excluded_identity: Option<&Arc<()>>,
    ) -> Vec<(
        Arc<()>,
        Arc<StartTransitionCompletion>,
        TaskAbortHandoffSlot,
    )> {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .iter()
            .filter_map(
                |(
                    identity,
                    completion,
                    kind,
                    _suspension_handoff,
                    abort_handoff,
                    _finish_handoff,
                )| {
                    if *kind != TaskTerminalizationKind::Abort
                        || excluded_identity.is_some_and(|excluded| Arc::ptr_eq(identity, excluded))
                    {
                        return None;
                    }
                    abort_handoff.as_ref().map(|slot| {
                        (
                            Arc::clone(identity),
                            // Shutdown adoption must validate the witness fence,
                            // not merely the logical identity.
                            Arc::clone(completion),
                            Arc::clone(slot),
                        )
                    })
                },
            )
            .collect()
    }

    /// Returns queued ordinary finish witnesses. A live detached owner has
    /// taken its slot; a scheduler that drops the first poll leaves the full
    /// witness here for the shutdown drain to adopt.
    fn pending_finish_handoffs_except(
        &self,
        excluded_identity: Option<&Arc<()>>,
    ) -> Vec<(
        Arc<()>,
        Arc<StartTransitionCompletion>,
        TaskFinishHandoffSlot,
    )> {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .iter()
            .filter_map(
                |(
                    identity,
                    completion,
                    kind,
                    _suspension_handoff,
                    _abort_handoff,
                    finish_handoff,
                )| {
                    if *kind != TaskTerminalizationKind::Finish
                        || excluded_identity.is_some_and(|excluded| Arc::ptr_eq(identity, excluded))
                    {
                        return None;
                    }
                    finish_handoff.as_ref().map(|slot| {
                        (
                            Arc::clone(identity),
                            Arc::clone(completion),
                            Arc::clone(slot),
                        )
                    })
                },
            )
            .collect()
    }

    /// Retires and signals one exact task terminalizer after all of its
    /// post-terminal side effects have completed.  A stale owner cannot
    /// retire a later entry because both identity pointers are checked.
    fn finish_task_terminalization(
        &self,
        identity: &Arc<()>,
        completion: &Arc<StartTransitionCompletion>,
    ) {
        let mut pending = self
            .pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned");
        pending.retain(
            |(
                current_identity,
                current_completion,
                _kind,
                _handoff,
                _abort_handoff,
                _finish_handoff,
            )| {
                !(Arc::ptr_eq(current_identity, identity)
                    && Arc::ptr_eq(current_completion, completion))
            },
        );
        drop(pending);
        completion.complete();
    }

    fn pending_task_terminalization_completions_except(
        &self,
        excluded_identity: Option<&Arc<()>>,
    ) -> Vec<Arc<StartTransitionCompletion>> {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .iter()
            .filter(|(identity, _, _, _, _, _)| {
                excluded_identity.is_none_or(|excluded| !Arc::ptr_eq(identity, excluded))
            })
            .map(|(_, completion, _, _, _, _)| Arc::clone(completion))
            .collect()
    }

    /// Shutdown waits for every materialized task terminalizer.  A panic or
    /// hang intentionally leaves its fence unresolved, so teardown remains
    /// fail-closed instead of publishing thread-stop or closing persistence
    /// behind an unfinished terminal path.
    pub(crate) async fn drain_task_terminalizations_for_shutdown_except(
        self: &Arc<Self>,
        excluded_identity: Option<&Arc<()>>,
    ) {
        loop {
            let mut adopted = false;
            for (identity, completion, slot) in
                self.pending_finish_handoffs_except(excluded_identity)
            {
                let Some(handoff) = Self::take_finish_handoff(&slot) else {
                    continue;
                };
                if handoff.failed_closed || handoff.phase != TaskFinishHandoffPhase::Claimed {
                    Self::retain_finish_handoff(&slot, handoff);
                    continue;
                }
                if !Arc::ptr_eq(&handoff.terminalization_identity, &identity)
                    || !Arc::ptr_eq(&handoff.completion, &completion)
                {
                    let mut handoff = handoff;
                    handoff.failed_closed = true;
                    Self::retain_finish_handoff(&slot, handoff);
                    continue;
                }
                adopted = true;
                self.drive_finish_handoff_taken(slot, handoff).await;
            }
            for (identity, completion, slot) in
                self.pending_abort_handoffs_except(excluded_identity)
            {
                let Some(handoff) = Self::take_abort_handoff(&slot) else {
                    continue;
                };
                if handoff.failed_closed || handoff.phase != TaskAbortHandoffPhase::Claimed {
                    Self::retain_abort_handoff(&slot, handoff);
                    continue;
                }
                if !Arc::ptr_eq(&handoff.terminalization_identity, &identity) {
                    let mut handoff = handoff;
                    handoff.failed_closed = true;
                    Self::retain_abort_handoff(&slot, handoff);
                    continue;
                }
                if !Arc::ptr_eq(&handoff.completion, &completion) {
                    let mut handoff = handoff;
                    handoff.failed_closed = true;
                    Self::retain_abort_handoff(&slot, handoff);
                    continue;
                }
                adopted = true;
                let _ = self.drive_abort_handoff_taken(slot, handoff).await;
            }
            let completions =
                self.pending_task_terminalization_completions_except(excluded_identity);
            if completions.is_empty() {
                return;
            }
            if adopted {
                continue;
            }
            for completion in completions {
                completion.wait().await;
            }
        }
    }

    pub(crate) fn has_pending_start_transition(&self) -> bool {
        self.has_pending_start_transition_except(/*ignored_identity*/ None)
    }

    pub(crate) fn has_pending_start_transition_except(
        &self,
        ignored_identity: Option<&Arc<()>>,
    ) -> bool {
        self.pending_start_transition_completions
            .lock()
            .expect("start transition completion registry mutex poisoned")
            .iter()
            .any(|(identity, _, _cleanup)| {
                ignored_identity.is_none_or(|ignored| !Arc::ptr_eq(identity, ignored))
            })
    }

    /// Returns true while any task finish/abort/suspend owner still has
    /// post-terminal work outstanding.  The marker is intentionally kept in
    /// an independent registry after the active slot CAS so idle observers
    /// cannot admit history mutation or a replacement in the clear→publish
    /// window.
    pub(crate) fn has_pending_task_terminalization(&self) -> bool {
        self.has_pending_task_terminalization_except(/*ignored_identity*/ None)
    }

    pub(crate) fn has_pending_task_terminalization_except(
        &self,
        ignored_identity: Option<&Arc<()>>,
    ) -> bool {
        self.pending_task_terminalization_completions
            .lock()
            .expect("task terminalization completion registry mutex poisoned")
            .iter()
            .any(|(identity, _, _, _, _, _)| {
                ignored_identity.is_none_or(|ignored| !Arc::ptr_eq(identity, ignored))
            })
    }

    /// Admission-facing fence for host starts.  Keep the legacy
    /// `has_pending_start_transition` semantics for shutdown's dedicated
    /// transition drain, while all normal starts also respect task
    /// terminalizers that have already cleared the active slot.
    pub(crate) fn has_pending_admission_fence(&self) -> bool {
        self.has_pending_admission_fence_except(/*ignored_terminalization*/ None)
    }

    pub(crate) fn has_pending_admission_fence_except(
        &self,
        ignored_terminalization: Option<&Arc<()>>,
    ) -> bool {
        self.has_pending_start_transition()
            || self.has_pending_task_terminalization_except(ignored_terminalization)
    }

    pub(crate) fn begin_shutdown(&self) {
        let _admission_gate = self
            .start_admission_gate
            .lock()
            .expect("start admission gate mutex poisoned");
        self.shutdown_started.store(true, Ordering::Release);
    }

    pub(crate) fn shutdown_started(&self) -> bool {
        self.shutdown_started.load(Ordering::Acquire)
    }
}

/// Result of handing a materialized turn context to the host start state
/// machine.  Owned callers use this to avoid reporting `Started` after a
/// caller reservation was fenced by an abort or replacement; legacy direct
/// callers may ignore the value.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum StartTaskOutcome {
    Attached,
    Aborted,
    Stale,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RecoveryReadyForSampling {
    Ready,
    PendingInput,
    Detached,
}

/// One outer sampling generation may authorize the same pre-output physical
/// request across auth retry or HTTP/WS fallback. Once any provider output or
/// terminal error closes the arm, an internal retry can never mint Ready
/// again from the same logical sampling generation.
pub(crate) struct RecoveryDispatchArm {
    closed: AtomicBool,
    recovery_disabled: AtomicBool,
    expected_fingerprint_sha256: Option<String>,
}

impl RecoveryDispatchArm {
    pub(crate) fn new(expected_fingerprint_sha256: Option<String>) -> Self {
        Self {
            closed: AtomicBool::new(false),
            recovery_disabled: AtomicBool::new(false),
            expected_fingerprint_sha256,
        }
    }

    pub(crate) fn close(&self) {
        self.closed.store(true, Ordering::Release);
    }

    pub(crate) fn is_open(&self) -> bool {
        !self.closed.load(Ordering::Acquire)
    }

    pub(crate) fn disable_recovery(&self) {
        self.recovery_disabled.store(true, Ordering::Release);
    }

    pub(crate) fn recovery_disabled(&self) -> bool {
        self.recovery_disabled.load(Ordering::Acquire)
    }

    pub(crate) fn expected_fingerprint_sha256(&self) -> Option<&str> {
        self.expected_fingerprint_sha256.as_deref()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RecoveryProviderOutputGate {
    Attached,
    Detached,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum InterruptedTurnHistoryMarker {
    Disabled,
    ContextualUser,
    Developer,
}

impl InterruptedTurnHistoryMarker {
    pub(crate) fn from_config_and_version(
        config: &Config,
        multi_agent_version: MultiAgentVersion,
    ) -> Self {
        if !config.agent_interrupt_message_enabled {
            return Self::Disabled;
        }
        if multi_agent_version == MultiAgentVersion::V2 {
            Self::Developer
        } else {
            Self::ContextualUser
        }
    }
}

/// Shared model-visible marker used by both the real interrupt path and
/// interrupted fork snapshots.
pub(crate) fn interrupted_turn_history_marker(
    marker: InterruptedTurnHistoryMarker,
) -> Option<ResponseItem> {
    match marker {
        InterruptedTurnHistoryMarker::Disabled => None,
        InterruptedTurnHistoryMarker::ContextualUser => Some(ContextualUserFragment::into(
            crate::context::TurnAborted::new(crate::context::TurnAborted::INTERRUPTED_GUIDANCE),
        )),
        InterruptedTurnHistoryMarker::Developer => {
            let marker = crate::context::TurnAborted::new(
                crate::context::TurnAborted::INTERRUPTED_DEVELOPER_GUIDANCE,
            );
            let (_, content) = marker.render_fragment().into_parts();
            Some(RenderedFragment::new("developer", content).into())
        }
    }
}

fn emit_turn_network_proxy_metric(
    session_telemetry: &SessionTelemetry,
    network_proxy_active: bool,
    tmp_mem: (&str, &str),
) {
    let active = if network_proxy_active {
        "true"
    } else {
        "false"
    };
    session_telemetry.counter(
        TURN_NETWORK_PROXY_METRIC,
        /*inc*/ 1,
        &[("active", active), tmp_mem],
    );
}

fn emit_turn_memory_metric(
    session_telemetry: &SessionTelemetry,
    feature_enabled: bool,
    config_enabled: bool,
    has_citations: bool,
) {
    let read_allowed = feature_enabled && config_enabled;
    session_telemetry.counter(
        TURN_MEMORY_METRIC,
        /*inc*/ 1,
        &[
            ("read_allowed", bool_tag(read_allowed)),
            ("feature_enabled", bool_tag(feature_enabled)),
            ("config_use_memories", bool_tag(config_enabled)),
            ("has_citations", bool_tag(has_citations)),
        ],
    );
}

pub(crate) fn emit_compact_metric(
    session_telemetry: &SessionTelemetry,
    compact_type: &'static str,
    manual: bool,
) {
    session_telemetry.counter(
        TASK_COMPACT_METRIC,
        /*inc*/ 1,
        &[("type", compact_type), ("manual", bool_tag(manual))],
    );
}

fn bool_tag(value: bool) -> &'static str {
    if value { "true" } else { "false" }
}

/// Async task that drives a [`Session`] turn.
///
/// Implementations encapsulate a specific Codex workflow (regular chat,
/// reviews, ghost snapshots, etc.). Each task instance is owned by a
/// [`Session`] and executed on a background Tokio task. The trait is
/// intentionally small: implementers identify themselves via
/// [`SessionTask::kind`], perform their work in [`SessionTask::run`], and may
/// release resources in [`SessionTask::abort`].
pub(crate) trait SessionTask: Send + Sync + 'static {
    /// Describes the type of work the task performs so the session can
    /// surface it in telemetry and UI.
    fn kind(&self) -> TaskKind;

    /// Whether an interrupted instance can resume as the same model turn.
    /// Auxiliary tasks must leave this false even when their UI kind is
    /// `Regular`.
    fn recovery_eligible_model_turn(&self) -> bool {
        false
    }

    /// Shared task-owned authority that becomes Ready only at a strict
    /// provider-dispatch checkpoint.
    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        None
    }

    /// Returns the tracing name for a spawned task span.
    fn span_name(&self) -> &'static str;

    /// Lifecycle origin exposed to extension contributors before the task
    /// reaches the provider boundary.
    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin {
        codex_extension_api::TurnStartOrigin::NewTurn
    }

    /// Executes the task until completion or cancellation.
    ///
    /// Implementations typically stream protocol events using `session` and
    /// `ctx`, returning an optional final agent message when finished. The
    /// provided `cancellation_token` is cancelled when the session requests an
    /// abort; implementers should watch for it and terminate quickly once it
    /// fires. Returning [`Some`] yields a final message that
    /// [`Session::on_task_finished`] will emit to the client. Returning
    /// [`CodexErr::TurnAborted`] completes the task through the aborted-turn
    /// lifecycle instead.
    fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        ctx: Arc<TurnContext>,
        input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> impl std::future::Future<Output = SessionTaskResult> + Send;

    /// Gives the task a chance to perform cleanup after an abort.
    ///
    /// The default implementation is a no-op; override this if additional
    /// teardown or notifications are required once
    /// [`Session::abort_all_tasks`] cancels the task.
    /// An accepted host-owned start transition may invoke this hook before
    /// [`SessionTask::run`] has begun, so implementations must tolerate
    /// pre-run cleanup as well as cancellation of a running task.
    fn abort(
        &self,
        session: Arc<Session>,
        ctx: Arc<TurnContext>,
    ) -> impl std::future::Future<Output = ()> + Send {
        async move {
            let _ = (session, ctx);
        }
    }
}

pub(crate) trait AnySessionTask: Send + Sync + 'static {
    fn kind(&self) -> TaskKind;

    fn recovery_eligible_model_turn(&self) -> bool;

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>>;

    fn span_name(&self) -> &'static str;

    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin;

    fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        ctx: Arc<TurnContext>,
        input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> BoxFuture<'static, SessionTaskResult>;

    fn abort<'a>(&'a self, session: Arc<Session>, ctx: Arc<TurnContext>) -> BoxFuture<'a, ()>;
}

impl<T> AnySessionTask for T
where
    T: SessionTask,
{
    fn kind(&self) -> TaskKind {
        SessionTask::kind(self)
    }

    fn recovery_eligible_model_turn(&self) -> bool {
        SessionTask::recovery_eligible_model_turn(self)
    }

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        SessionTask::recovery_authority(self)
    }

    fn span_name(&self) -> &'static str {
        SessionTask::span_name(self)
    }

    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin {
        SessionTask::turn_start_origin(self)
    }

    fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        ctx: Arc<TurnContext>,
        input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> BoxFuture<'static, SessionTaskResult> {
        Box::pin(SessionTask::run(
            self,
            session,
            ctx,
            input,
            cancellation_token,
        ))
    }

    fn abort<'a>(&'a self, session: Arc<Session>, ctx: Arc<TurnContext>) -> BoxFuture<'a, ()> {
        Box::pin(SessionTask::abort(self, session, ctx))
    }
}

impl Session {
    /// Installs one exact terminalization owner while the active-turn lock is
    /// held. The running task stays attached until the owner has revoked its
    /// recovery authority, so every admission path continues to see a busy
    /// slot during the lock-free await phase.
    #[expect(
        clippy::too_many_arguments,
        reason = "terminalization claims bind independent task, turn, epoch, kind, and handoff witnesses"
    )]
    fn claim_task_terminalization_locked(
        &self,
        active_turn: &mut ActiveTurn,
        task_identity: &Arc<dyn AnySessionTask>,
        turn_context: &Arc<TurnContext>,
        attach_epoch: u64,
        kind: TaskTerminalizationKind,
        suspension_handoff: Option<SuspensionHandoffSlot>,
        abort_handoff: Option<TaskAbortHandoffSlot>,
        finish_handoff: Option<TaskFinishHandoffSlot>,
    ) -> Option<(Arc<()>, Arc<StartTransitionCompletion>)> {
        if active_turn.task_terminalization.is_some() {
            return None;
        }
        let identity = Arc::new(());
        let completion = StartTransitionCompletion::new();
        active_turn.task_terminalization = Some(TaskTerminalization {
            identity: Arc::clone(&identity),
            task_identity: Arc::clone(task_identity),
            turn_context: Arc::clone(turn_context),
            turn_state: Arc::clone(&active_turn.turn_state),
            attach_epoch,
            kind,
            phase: TaskTerminalizationPhase::Claimed,
            completion: Arc::clone(&completion),
        });
        // Register while the active-turn lock is still held.  A shutdown
        // drain must never observe the marker before its independent fence is
        // visible, otherwise abort_all_tasks can return for Terminalizing and
        // shutdown can race past this owner's terminal event/flush.
        self.register_task_terminalization(
            Arc::clone(&identity),
            Arc::clone(&completion),
            kind,
            suspension_handoff,
            abort_handoff,
            finish_handoff,
        );
        Some((identity, completion))
    }

    fn task_terminalization_matches_locked(
        active_turn: &ActiveTurn,
        identity: &Arc<()>,
        task: &RunningTask,
        kind: TaskTerminalizationKind,
    ) -> bool {
        active_turn
            .task_terminalization
            .as_ref()
            .is_some_and(|marker| {
                marker.kind == kind
                    && Arc::ptr_eq(&marker.identity, identity)
                    && Arc::ptr_eq(&marker.task_identity, &task.task)
                    && Arc::ptr_eq(&marker.turn_context, &task.turn_context)
                    && Arc::ptr_eq(&marker.turn_state, &active_turn.turn_state)
                    && marker.attach_epoch == task.attach_epoch
            })
    }

    /// Moves the exact task into its terminal owner while retaining the marker
    /// in the active slot. A stale owner can never consume a replacement task.
    #[expect(
        clippy::expect_used,
        reason = "the task remains attached after the exact terminalization marker identity check"
    )]
    fn take_task_for_terminalization_locked(
        active_turn: &mut ActiveTurn,
        identity: &Arc<()>,
        kind: TaskTerminalizationKind,
    ) -> Option<RunningTask> {
        let task = active_turn.task.as_ref()?;
        if !Self::task_terminalization_matches_locked(active_turn, identity, task, kind) {
            return None;
        }
        active_turn
            .task_terminalization
            .as_mut()
            .expect("terminalization marker matched")
            .phase = TaskTerminalizationPhase::Terminalizing;
        active_turn.task.take()
    }

    /// Clears only a terminalization marker that still owns the exact turn
    /// state and task identity. The completion fence is signalled after the
    /// slot CAS, never before it.
    fn clear_task_terminalization_if_current_locked(
        active: &mut Option<ActiveTurn>,
        identity: &Arc<()>,
        kind: TaskTerminalizationKind,
        turn_state: &Arc<Mutex<TurnState>>,
        task_identity: &Arc<dyn AnySessionTask>,
        turn_context: &Arc<TurnContext>,
        attach_epoch: u64,
    ) -> Option<Arc<StartTransitionCompletion>> {
        let active_turn = active.as_mut()?;
        let marker = active_turn.task_terminalization.as_ref()?;
        if active_turn.task.is_some()
            || active_turn.start_reservation.is_some()
            || active_turn.start_transition.is_some()
            || marker.kind != kind
            || marker.phase != TaskTerminalizationPhase::Terminalizing
            || !Arc::ptr_eq(&marker.identity, identity)
            || !Arc::ptr_eq(&marker.task_identity, task_identity)
            || !Arc::ptr_eq(&marker.turn_context, turn_context)
            || !Arc::ptr_eq(&marker.turn_state, turn_state)
            || marker.attach_epoch != attach_epoch
        {
            return None;
        }
        let completion = Arc::clone(&marker.completion);
        active_turn.task_terminalization = None;
        *active = None;
        Some(completion)
    }

    /// Claims the exact regular task for root-turn suspension and publishes
    /// its complete handoff witness before sealing shutdown.  The caller may
    /// disappear immediately after this future returns; the registry already
    /// owns the task, writer, reply, and exact terminalization identity.
    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "the terminalization claim lock and handoff identity fence the complete suspension detach"
    )]
    pub(crate) async fn take_task_for_suspension(
        &self,
        handoff_slot: SuspensionHandoffSlot,
        live_thread: LiveThread,
        submission_id: String,
        reply: oneshot::Sender<CodexResult<codex_protocol::turn_input::SuspendTurnOutcome>>,
    ) -> Option<(Arc<()>, SuspensionHandoffSlot)> {
        if self.shutdown_started() {
            return None;
        }
        let _claim_lock = self.terminalization_claim_lock.lock().await;
        let mut active = self.active_turn.lock().await;
        if self.shutdown_started() {
            return None;
        }
        let active_turn = active.as_mut()?;
        if active_turn.task_terminalization.is_some()
            || active_turn.start_reservation.is_some()
            || active_turn.start_transition.is_some()
        {
            return None;
        }
        let task_ref = active_turn.task.as_ref()?;
        if task_ref.kind != TaskKind::Regular {
            return None;
        }
        let task_identity = Arc::clone(&task_ref.task);
        let task_context = Arc::clone(&task_ref.turn_context);
        let attach_epoch = task_ref.attach_epoch;
        let turn_state = Arc::clone(&active_turn.turn_state);
        let (terminalization_identity, _terminalization_completion) = self
            .claim_task_terminalization_locked(
                active_turn,
                &task_identity,
                &task_context,
                attach_epoch,
                TaskTerminalizationKind::Suspend,
                Some(Arc::clone(&handoff_slot)),
                /*abort_handoff*/ None,
                /*finish_handoff*/ None,
            )?;
        let task = Self::take_task_for_terminalization_locked(
            active_turn,
            &terminalization_identity,
            TaskTerminalizationKind::Suspend,
        )?;
        let suspended = DetachedTaskForSuspension {
            task: Some(task),
            turn_state,
            terminalization_identity: Arc::clone(&terminalization_identity),
            task_identity,
            turn_context: task_context,
            attach_epoch,
        };
        // The slot was registered together with the terminalization marker.
        // Fill it while `active_turn` is still held, before shutdown is sealed
        // or this method can return.  A shutdown drain can therefore never
        // observe a claimed Suspend marker without its full witness.
        {
            let mut slot = handoff_slot
                .lock()
                .expect("suspension handoff slot mutex poisoned");
            debug_assert!(
                slot.is_none(),
                "new suspension handoff slot was pre-populated"
            );
            *slot = Some(SuspensionHandoff {
                suspended,
                live_thread,
                submission_id,
                reply: Some(reply),
                phase: SuspensionHandoffPhase::Claimed,
                failed_closed: false,
            });
        }
        // Suspension owns the shutdown handoff from this point.  Seal it
        // before releasing the active-turn lock so a concurrent shutdown or
        // idle mutation cannot observe the detached slot as admissible.
        self.begin_shutdown();
        drop(active);
        Some((terminalization_identity, handoff_slot))
    }

    /// Releases the suspension marker only after the caller has closed the
    /// writer and completed every shutdown-side persistence step.
    pub(crate) async fn finish_task_suspension(
        &self,
        suspended: &DetachedTaskForSuspension,
    ) -> bool {
        let completion = {
            let mut active = self.active_turn.lock().await;
            Self::clear_task_terminalization_if_current_locked(
                &mut active,
                &suspended.terminalization_identity,
                TaskTerminalizationKind::Suspend,
                &suspended.turn_state,
                &suspended.task_identity,
                &suspended.turn_context,
                suspended.attach_epoch,
            )
        };
        if let Some(completion) = completion.as_ref() {
            self.finish_task_terminalization(&suspended.terminalization_identity, completion);
            true
        } else {
            false
        }
    }

    fn recovery_seed_for_task(
        task: &RunningTask,
        abort_reason: Option<&TurnAbortReason>,
    ) -> Option<RecoverySeed> {
        if !task.recovery_eligible_model_turn
            || !matches!(
                abort_reason,
                Some(TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited)
            )
        {
            return None;
        }
        let authority = task.recovery_authority.as_ref()?.clone();
        // A transition in flight is intentionally not recoverable. Waiting on
        // this mutex could delay cancellation behind a blocked rollout flush;
        // fail closed instead and let the abort path quiesce the task.
        let state = authority.state.try_lock().ok()?;
        if state.poisoned
            || state.durable_state != DurableRecoveryState::Ready
            || !authority.ready.load(Ordering::Acquire)
        {
            return None;
        }
        let generation = state.generation;
        let request_fingerprint_sha256 = state.request_fingerprint_sha256.clone()?;
        let replay = state.replay.clone()?;
        let persistence_failure_generation = state.ready_persistence_failure_generation?;
        drop(state);
        Some(RecoverySeed {
            turn_id: task.turn_context.sub_id.clone(),
            authority,
            generation,
            request_fingerprint_sha256,
            replay,
            persistence_failure_generation,
            attach_epoch: task.attach_epoch,
            confirmation_generation: None,
        })
    }

    /// Emits one terminal event exactly once and proves that both its append
    /// and the following durability barrier completed without any swallowed
    /// persistence failure. The returned generation is later matched against
    /// the exact generation bound into the task's durable Ready authority.
    async fn send_terminal_event_and_flush(
        &self,
        turn_context: &TurnContext,
        event: EventMsg,
    ) -> Option<u64> {
        let before = self.rollout_persistence_failure_generation();
        self.send_event(turn_context, event).await;
        let after_append = self.rollout_persistence_failure_generation();
        let flush_succeeded = match self.flush_rollout().await {
            Ok(()) => true,
            Err(err) => {
                warn!("failed to flush rollout after emitting terminal turn event: {err}");
                false
            }
        };
        let after_flush = self.rollout_persistence_failure_generation();
        (flush_succeeded && before == after_append && after_append == after_flush)
            .then_some(after_flush)
    }

    /// Revokes any task-owned Ready marker before controlled detach. Only an
    /// exact, quiescent, failure-free seed survives to the post-terminal
    /// InterruptedConfirmed phase; every other path remains durably Unready.
    async fn prepare_recovery_seed_for_controlled_detach(
        &self,
        turn_id: &str,
        authority: Option<&Arc<TurnRecoveryAuthority>>,
        mut recovery_seed: Option<RecoverySeed>,
    ) -> Option<RecoverySeed> {
        let authority = authority?;
        let seed_interval_is_valid = recovery_seed.as_ref().is_some_and(|seed| {
            seed.persistence_failure_generation == self.rollout_persistence_failure_generation()
        });
        let confirmation_generation = match self
            .prepare_turn_recovery_for_controlled_detach(turn_id, authority.as_ref())
            .await
        {
            Ok(generation) => generation,
            Err(err) => {
                warn!("failed to revoke turn recovery before controlled detach: {err}");
                if !self
                    .persist_turn_recovery_failure_tombstone(turn_id, authority.as_ref())
                    .await
                {
                    warn!(
                        "failed to persist the recovery tombstone after a revoke failure; \
                         recovery provenance is fail-stop/unknown"
                    );
                }
                return None;
            }
        };
        let seed = recovery_seed.as_mut()?;
        if !seed_interval_is_valid
            || confirmation_generation != seed.generation.saturating_add(1)
            || self.rollout_persistence_failure_generation() != seed.persistence_failure_generation
        {
            let mut state = authority.state.lock().await;
            authority.ready.store(false, Ordering::Release);
            state.ready_persistence_failure_generation = None;
            state.poisoned = true;
            return None;
        }
        seed.confirmation_generation = Some(confirmation_generation);
        recovery_seed
    }

    /// Publishes one live recovery candidate only after the task is quiescent
    /// and its terminal event is durable. All detach paths converge here so a
    /// stale atomic Ready bit can never outlive a generation/state transition.
    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "active-turn and recovery-authority locks intentionally serialize terminal recovery publication"
    )]
    async fn publish_recovery_seed_after_terminal(
        &self,
        recovery_seed: Option<RecoverySeed>,
        task_quiesced: bool,
        terminal_persistence_generation: Option<u64>,
    ) -> bool {
        let Some(seed) = recovery_seed else {
            return false;
        };
        let Some(confirmation_generation) = seed.confirmation_generation else {
            return false;
        };
        let persistence_proven = terminal_persistence_generation.is_some_and(|generation| {
            generation == seed.persistence_failure_generation
                && self.rollout_persistence_failure_generation()
                    == seed.persistence_failure_generation
        });
        if !task_quiesced || !persistence_proven {
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }

        // Keep the same lock order as provider-boundary publication: active
        // turn first, then recovery authority state.
        let active_turn = self.active_turn.lock().await;
        if active_turn.is_some() || self.turn_epoch.load(Ordering::Acquire) != seed.attach_epoch {
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        if self.shutdown_started() {
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        if let Err(err) = self
            .confirm_interrupted_turn_recovery(
                &seed.turn_id,
                seed.authority.as_ref(),
                confirmation_generation,
                seed.persistence_failure_generation,
                &seed.request_fingerprint_sha256,
                &seed.replay,
            )
            .await
        {
            warn!("failed to confirm interrupted turn recovery: {err}");
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        if self.shutdown_started() {
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        let state = seed.authority.state.lock().await;
        let authority_invalid = state.poisoned
            || state.durable_state != DurableRecoveryState::InterruptedConfirmed
            || state.generation != confirmation_generation
            || state.ready_persistence_failure_generation.is_some()
            || state.request_fingerprint_sha256.as_deref()
                != Some(seed.request_fingerprint_sha256.as_str())
            || state.replay.as_ref() != Some(&seed.replay)
            || seed.authority.ready.load(Ordering::Acquire)
            || self.rollout_persistence_failure_generation() != seed.persistence_failure_generation;
        if authority_invalid {
            drop(state);
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        if self.shutdown_started() {
            drop(state);
            drop(active_turn);
            self.persist_turn_recovery_failure_tombstone(&seed.turn_id, seed.authority.as_ref())
                .await;
            return false;
        }
        *self
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned") = Some(RecoveryCandidate {
            turn_id: seed.turn_id,
            marker_generation: confirmation_generation,
            request_fingerprint_sha256: seed.request_fingerprint_sha256,
            replay: seed.replay,
            epoch: seed.attach_epoch,
            persistence_failure_generation: seed.persistence_failure_generation,
        });
        drop(state);
        drop(active_turn);
        true
    }

    /// Serializes the provider Ready boundary with active-turn steer
    /// acceptance. If a steer is already pending, sampling may continue but
    /// recovery remains fail-closed until that input is consumed and durable.
    #[cfg(test)]
    pub(crate) async fn mark_recovery_ready_for_sampling(
        &self,
        turn_id: &str,
        authority: &Arc<TurnRecoveryAuthority>,
        persistence_failure_baseline: u64,
        request_fingerprint_sha256: &str,
    ) -> CodexResult<RecoveryReadyForSampling> {
        let replay = codex_history::TurnRecoveryReplayV1 {
            history_boundary: self.current_recovery_history_boundary().await?,
            turn_context_sha256: "test-turn-context".to_string(),
            start: codex_history::TurnRecoveryStartState {
                final_output_json_schema: None,
                parent_turn_id: None,
                root_turn_id: Some(turn_id.to_string()),
                responses_metadata_extra: Default::default(),
            },
            environments: Vec::new(),
        };
        self.mark_recovery_ready_for_sampling_with_replay(
            turn_id,
            authority,
            persistence_failure_baseline,
            request_fingerprint_sha256,
            &replay,
        )
        .await
    }

    #[expect(
        clippy::await_holding_invalid_type,
        reason = "the active-turn identity fence spans durable Ready publication"
    )]
    pub(crate) async fn mark_recovery_ready_for_sampling_with_replay(
        &self,
        turn_id: &str,
        authority: &Arc<TurnRecoveryAuthority>,
        persistence_failure_baseline: u64,
        request_fingerprint_sha256: &str,
        replay: &codex_history::TurnRecoveryReplayV1,
    ) -> CodexResult<RecoveryReadyForSampling> {
        if !self.enabled(Feature::HeptaTurnRecovery) {
            return Ok(RecoveryReadyForSampling::Ready);
        }
        let active = self.active_turn.lock().await;
        let Some(active_turn) = active.as_ref() else {
            return Ok(RecoveryReadyForSampling::Detached);
        };
        if active_turn.task_terminalization.is_some() {
            return Ok(RecoveryReadyForSampling::Detached);
        }
        let Some(task) = active_turn.task.as_ref() else {
            return Ok(RecoveryReadyForSampling::Detached);
        };
        if task.turn_context.sub_id != turn_id
            || !task
                .recovery_authority
                .as_ref()
                .is_some_and(|current| Arc::ptr_eq(current, authority))
        {
            return Ok(RecoveryReadyForSampling::Detached);
        }
        let has_pending_steer = {
            let turn_state = active_turn.turn_state.lock().await;
            !turn_state.pending_input.is_empty()
        };
        // Mailbox input is session-scoped rather than turn-state scoped. It is
        // still accepted model-visible input, so it must suppress Ready when
        // it arrives after the run loop's last drain but before dispatch.
        let has_pending_mailbox = self.input_queue.has_pending_mailbox_items().await;
        if has_pending_steer || has_pending_mailbox {
            return Ok(RecoveryReadyForSampling::PendingInput);
        }
        self.mark_turn_recovery_ready(
            turn_id,
            authority.as_ref(),
            persistence_failure_baseline,
            request_fingerprint_sha256,
            replay,
        )
        .await?;
        Ok(RecoveryReadyForSampling::Ready)
    }

    /// Revalidates attachment for a sampling generation whose provider setup
    /// is intentionally not recoverable. This path must not mint Ready, but it
    /// still must not authorize provider retry/fallback after the owning task
    /// has detached.
    pub(crate) async fn gate_unrecoverable_provider_dispatch(
        &self,
        turn_id: &str,
        authority: &Arc<TurnRecoveryAuthority>,
    ) -> RecoveryProviderOutputGate {
        let active = self.active_turn.lock().await;
        if self.shutdown_started() {
            return RecoveryProviderOutputGate::Detached;
        }
        let recovery_enabled = self.enabled(Feature::HeptaTurnRecovery);
        if active
            .as_ref()
            .is_some_and(|active_turn| active_turn.task_terminalization.is_some())
        {
            return RecoveryProviderOutputGate::Detached;
        }
        let Some(task) = active
            .as_ref()
            .and_then(|active_turn| active_turn.task.as_ref())
        else {
            return RecoveryProviderOutputGate::Detached;
        };
        if task.turn_context.sub_id != turn_id
            || (recovery_enabled
                && !task
                    .recovery_authority
                    .as_ref()
                    .is_some_and(|current| Arc::ptr_eq(current, authority)))
        {
            return RecoveryProviderOutputGate::Detached;
        }
        if !recovery_enabled {
            return RecoveryProviderOutputGate::Attached;
        }
        RecoveryProviderOutputGate::Attached
    }

    /// Serializes the first provider event consumed by the outer turn executor
    /// with controlled detach. The event may close the recovery window only
    /// while the exact task and authority are still attached; an event that
    /// lost the race to abort must not reach model-visible output persistence,
    /// tool dispatch, hooks, commands, or other product effects. Provider-policy
    /// evidence, tracing, and diagnostic telemetry belong to the transport
    /// mapper and are explicitly outside this bounded gate.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "the active-turn identity fence spans the first-provider-output recovery transition"
    )]
    pub(crate) async fn gate_first_provider_output(
        &self,
        turn_id: &str,
        authority: &Arc<TurnRecoveryAuthority>,
    ) -> CodexResult<RecoveryProviderOutputGate> {
        let active = self.active_turn.lock().await;
        if self.shutdown_started() {
            return Ok(RecoveryProviderOutputGate::Detached);
        }
        if active
            .as_ref()
            .is_some_and(|active_turn| active_turn.task_terminalization.is_some())
        {
            return Ok(RecoveryProviderOutputGate::Detached);
        }
        let recovery_enabled = self.enabled(Feature::HeptaTurnRecovery);
        let Some(task) = active
            .as_ref()
            .and_then(|active_turn| active_turn.task.as_ref())
        else {
            return Ok(RecoveryProviderOutputGate::Detached);
        };
        if task.turn_context.sub_id != turn_id
            || (recovery_enabled
                && !task
                    .recovery_authority
                    .as_ref()
                    .is_some_and(|current| Arc::ptr_eq(current, authority)))
        {
            return Ok(RecoveryProviderOutputGate::Detached);
        }
        if recovery_enabled {
            self.ensure_turn_recovery_unready(turn_id, authority.as_ref())
                .await?;
        }
        Ok(RecoveryProviderOutputGate::Attached)
    }

    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "the active-turn guard owns the single start reservation while task startup is admitted"
    )]
    pub async fn spawn_task<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
    ) -> CodexResult<()> {
        if self.shutdown_started() {
            return Err(CodexErr::InvalidRequest(
                "cannot start a task while the session is shutting down".to_string(),
            ));
        }
        if self.has_pending_admission_fence() {
            return Err(CodexErr::InvalidRequest(
                "cannot start a task while the previous turn is terminalizing".to_string(),
            ));
        }
        self.abort_all_tasks(TurnAbortReason::Replaced).await;
        let start_reservation = {
            let mut active_turn = self.active_turn.lock().await;
            if self.shutdown_started()
                || self.has_pending_admission_fence()
                || active_turn.is_some()
            {
                return Err(CodexErr::InvalidRequest(
                    "cannot start replacement task while the previous turn is transitioning"
                        .to_string(),
                ));
            }
            self.consume_recovery_candidate_for_mutation().await?;
            let active = active_turn.get_or_insert_with(ActiveTurn::default);
            active
                .reserve_start(turn_context.sub_id.clone())
                .expect("idle slot should accept one start reservation")
        };
        let mut start_reservation_owner = StartReservationOwner::new(self, start_reservation);
        self.clear_connector_selection().await;
        let start_outcome = self
            .start_task_owned(
                turn_context,
                input,
                task,
                MailboxParentProvenance::Ignore,
                start_reservation_owner.handle().clone(),
            )
            .await;
        match start_outcome {
            StartTaskOutcome::Attached | StartTaskOutcome::Aborted => {
                start_reservation_owner.disarm();
                Ok(())
            }
            StartTaskOutcome::Stale => Err(CodexErr::InvalidRequest(
                "start reservation became stale before task attachment".to_string(),
            )),
        }
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "retained compatibility entry point with explicit lifecycle witnesses"
    )]
    #[cfg_attr(
        not(test),
        expect(dead_code, reason = "used by focused lifecycle qualification tests")
    )]
    pub(crate) async fn start_task<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
        mailbox_parent_provenance: MailboxParentProvenance,
    ) {
        self.start_task_with_options(
            turn_context,
            input,
            task,
            mailbox_parent_provenance,
            /*recovery_history*/ None,
            /*start_reservation*/ None,
            /*terminalization_owner*/ None,
        )
        .await;
    }

    #[expect(
        dead_code,
        reason = "retained compatibility entry point for qualified recovery starts"
    )]
    pub(crate) async fn start_task_with_recovery<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
        mailbox_parent_provenance: MailboxParentProvenance,
        recovery_history: Option<RecoveryHistoryTransition>,
    ) {
        self.start_task_with_options(
            turn_context,
            input,
            task,
            mailbox_parent_provenance,
            recovery_history,
            /*start_reservation*/ None,
            /*terminalization_owner*/ None,
        )
        .await;
    }

    pub(crate) async fn start_task_owned<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
        mailbox_parent_provenance: MailboxParentProvenance,
        start_reservation: StartReservationHandle,
    ) -> StartTaskOutcome {
        self.start_task_with_options(
            turn_context,
            input,
            task,
            mailbox_parent_provenance,
            /*recovery_history*/ None,
            Some(start_reservation),
            /*terminalization_owner*/ None,
        )
        .await
    }

    pub(crate) async fn start_task_with_recovery_owned<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
        mailbox_parent_provenance: MailboxParentProvenance,
        recovery_history: Option<RecoveryHistoryTransition>,
        start_reservation: StartReservationHandle,
    ) -> StartTaskOutcome {
        self.start_task_with_options(
            turn_context,
            input,
            task,
            mailbox_parent_provenance,
            recovery_history,
            Some(start_reservation),
            /*terminalization_owner*/ None,
        )
        .await
    }

    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        clippy::too_many_arguments,
        reason = "the start transaction explicitly carries identity witnesses and retains its admission locks across durable transitions"
    )]
    async fn start_task_with_options<T: SessionTask>(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        task: T,
        mailbox_parent_provenance: MailboxParentProvenance,
        recovery_history: Option<RecoveryHistoryTransition>,
        start_reservation: Option<StartReservationHandle>,
        terminalization_owner: Option<Arc<()>>,
    ) -> StartTaskOutcome {
        let task: Arc<dyn AnySessionTask> = Arc::new(task);
        let task_kind = task.kind();
        // Mark the host-owned async start transition before any subsequent
        // await owned by this function.  While lifecycle contributors, input
        // preparation, or prewarm work are running there is intentionally no
        // `RunningTask` yet, so abort must target this exact continuation
        // instead of silently returning as if the session were idle.  The
        // caller-owned reservation preamble before entering `start_task`
        // remains a separate, inert reservation by design.
        let recovery_history_restore_witness = recovery_history
            .as_ref()
            .map(|history| history.restore.clone());
        let start_transition_identity;
        let transition_turn_state;
        let transition_completion;
        let cleanup_slot;
        {
            let mut active = self.active_turn.lock().await;
            let _admission_gate = self
                .start_admission_gate
                .lock()
                .expect("start admission gate mutex poisoned");
            if self.shutdown_started()
                || self.has_pending_admission_fence_except(terminalization_owner.as_ref())
            {
                return StartTaskOutcome::Stale;
            }
            if let Some(start_reservation) = start_reservation.as_ref() {
                let Some(turn) = active.as_mut() else {
                    warn!(turn_id = %turn_context.sub_id, "start reservation lost before promotion");
                    return StartTaskOutcome::Stale;
                };
                if start_reservation.turn_id != turn_context.sub_id
                    || !turn.promote_start(start_reservation)
                {
                    warn!(turn_id = %turn_context.sub_id, "start reservation failed identity promotion");
                    return StartTaskOutcome::Stale;
                }
                start_transition_identity = Arc::clone(
                    &turn
                        .start_transition
                        .as_ref()
                        .expect("promotion installs start transition")
                        .identity,
                );
                transition_turn_state = Arc::clone(&turn.turn_state);
                transition_completion = Arc::clone(
                    &turn
                        .start_transition
                        .as_ref()
                        .expect("promotion installs start transition")
                        .completion,
                );
            } else {
                if active.is_some() {
                    warn!(
                        turn_id = %turn_context.sub_id,
                        "refusing to steal an existing idle or caller reservation"
                    );
                    return StartTaskOutcome::Stale;
                }
                let turn = active.get_or_insert_with(ActiveTurn::default);
                start_transition_identity = Arc::new(());
                turn.start_transition = Some(StartTransition::new(
                    turn_context.sub_id.clone(),
                    Arc::clone(&start_transition_identity),
                ));
                transition_turn_state = Arc::clone(&turn.turn_state);
                transition_completion = Arc::clone(
                    &turn
                        .start_transition
                        .as_ref()
                        .expect("direct start installs start transition")
                        .completion,
                );
            }
            // Keep the complete terminal witness in a cell shared by the
            // owner and the registry.  The cell is installed before the
            // active-turn lock is released, so a concurrent shutdown drain
            // can never observe a completion fence without its payload.
            cleanup_slot = Arc::new(std::sync::Mutex::new(Some(StartTransitionCleanup::new(
                self,
                Arc::clone(&task),
                Arc::clone(&turn_context),
                Arc::clone(&transition_turn_state),
                Arc::clone(&start_transition_identity),
                Arc::clone(&transition_completion),
                recovery_history_restore_witness,
            ))));
            // Register while the active-turn lock is still held.  Shutdown
            // can begin concurrently, so publishing the marker and its
            // completion fence must be one serialization unit.
            self.register_start_transition(
                Arc::clone(&start_transition_identity),
                Arc::clone(&transition_completion),
                Arc::clone(&cleanup_slot),
            );
        }
        let mut start_transition_owner = StartTransitionOwner::new(cleanup_slot);
        let mut recovery_history_restore = if let Some(recovery_history) = recovery_history {
            self.install_recovery_history_snapshot(recovery_history.install)
                .await;
            Some(recovery_history.restore)
        } else {
            None
        };
        let hepta_turn_recovery_enabled = turn_context
            .config
            .features
            .enabled(Feature::HeptaTurnRecovery);
        let recovery_eligible_model_turn =
            hepta_turn_recovery_enabled && task.recovery_eligible_model_turn();
        let recovery_authority = hepta_turn_recovery_enabled
            .then(|| task.recovery_authority())
            .flatten();
        let span_name = task.span_name();
        let started_at = Instant::now();
        let turn_started_at_unix_ms = turn_context
            .turn_timing_state
            .mark_turn_started(started_at)
            .await;
        turn_context
            .turn_metadata_state
            .set_turn_started_at_unix_ms(turn_started_at_unix_ms);
        let token_usage_at_turn_start = self.total_token_usage().await.unwrap_or_default();

        let cancellation_token = CancellationToken::new();
        let done = Arc::new(Notify::new());

        self.services
            .guardian_rejection_circuit_breaker
            .lock()
            .await
            .clear_turn(&turn_context.sub_id);

        let (pending_items, parent_turn_id, root_turn_id) =
            self.input_queue.get_pending_input(&self.active_turn).await;
        // Preserve the durable client/input identity in the turn scope before
        // any qualification contributor runs.  The extension API remains
        // inert for mailbox/automatic turns and for direct inputs that lack a
        // client message id; those paths cannot honestly claim cross-spawn
        // replay.
        if let Some(identity) =
            qualification_admission_identity(self.thread_id.to_string().as_str(), &input)
        {
            // A host may have supplied an identity through the turn scope.
            // Preserve that authority instead of replacing it with a
            // newly-derived value after the scope was initialized.
            let attached = turn_context
                .extension_data
                .insert_if(identity.clone(), |existing| existing.is_none());
            if !attached
                && turn_context
                    .extension_data
                    .get::<QualificationTurnAdmissionIdentity>()
                    .is_some_and(|existing| *existing != identity)
            {
                // A mismatched pre-seeded value is not allowed to become a
                // qualification authority for this accepted input.  Remove
                // it so the extension remains inert rather than binding the
                // wrong logical turn.
                turn_context
                    .extension_data
                    .remove::<QualificationTurnAdmissionIdentity>();
            }
        } else {
            // Do not let a reused turn context carry a prior user's durable
            // identity into an automatic/mailbox/direct turn.
            turn_context
                .extension_data
                .remove::<QualificationTurnAdmissionIdentity>();
        }
        if let MailboxParentProvenance::Attribute = mailbox_parent_provenance {
            if let Some(id) = parent_turn_id {
                if let Some(initiating_agent_path) = pending_items.iter().find_map(|item| {
                    let TurnInput::InterAgentCommunication(communication) = item else {
                        return None;
                    };
                    communication
                        .trigger_turn
                        .then(|| communication.author.clone())
                }) {
                    turn_context
                        .turn_metadata_state
                        .set_initiating_agent_path(initiating_agent_path);
                }
                turn_context.turn_metadata_state.set_parent_turn_id(id);
            }
            if let Some(id) = root_turn_id {
                turn_context.turn_metadata_state.set_root_turn_id(id);
            }
        } else if pending_items.iter().any(|item| {
            matches!(
                item,
                TurnInput::InterAgentCommunication(communication) if communication.trigger_turn
            )
        }) && turn_context.turn_metadata_state.root_turn_id() != root_turn_id
        {
            turn_context.turn_metadata_state.mark_root_turn_ambiguous();
        }
        let turn_state = {
            let active = self.active_turn.lock().await;
            let Some(turn) = active.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if turn.task.is_some() || turn.task_terminalization.is_some() {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
            let Some(transition) = turn.start_transition.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if !Arc::ptr_eq(&transition.identity, &start_transition_identity) {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
            Arc::clone(&turn.turn_state)
        };
        turn_state.lock().await.token_usage_at_turn_start = token_usage_at_turn_start.clone();
        self.input_queue
            .extend_pending_input_for_turn_state(turn_state.as_ref(), pending_items)
            .await;
        self.emit_turn_start_lifecycle(
            turn_context.as_ref(),
            &token_usage_at_turn_start,
            task.turn_start_origin(),
        )
        .await;

        let mut active = self.active_turn.lock().await;
        let Some(turn) = active.as_mut() else {
            drop(active);
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        };
        if turn.task.is_some() || turn.task_terminalization.is_some() {
            drop(active);
            self.restore_recovery_history_if_current(
                /*turn_state*/ None,
                &start_transition_identity,
                &mut recovery_history_restore,
            )
            .await;
            start_transition_owner.disarm();
            return StartTaskOutcome::Stale;
        }
        {
            let Some(transition) = turn.start_transition.as_ref() else {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            };
            if !Arc::ptr_eq(&transition.identity, &start_transition_identity) {
                drop(active);
                self.restore_recovery_history_if_current(
                    /*turn_state*/ None,
                    &start_transition_identity,
                    &mut recovery_history_restore,
                )
                .await;
                start_transition_owner.disarm();
                return StartTaskOutcome::Stale;
            }
        }

        // Linearize the final attach against the shutdown seal.  The earlier
        // identity checks only prove that this is still our transition; a
        // concurrent `begin_shutdown` could otherwise set the atomic between
        // that check and publication of `turn.task`.  Both sides use the
        // short admission gate while the active-turn lock is held, so the
        // resulting order is unambiguous: either shutdown wins and this
        // transition is aborted, or this attach wins and shutdown observes a
        // fully published running task.
        let admission_gate = self
            .start_admission_gate
            .lock()
            .expect("start admission gate mutex poisoned");
        if self.shutdown_started()
            && let Some(transition) = turn.start_transition.as_mut()
            && transition.abort_reason.is_none()
            && transition.request_abort(TurnAbortReason::Interrupted)
        {
            self.mark_interrupted();
        }
        let abort_reason = turn
            .start_transition
            .as_ref()
            .and_then(|transition| transition.abort_reason.clone());
        if let Some(reason) = abort_reason {
            // Keep the marker installed while terminalization awaits.  The
            // abort side records the reason but never emits lifecycle or
            // terminal events concurrently with an in-flight on_turn_start;
            // retaining the marker also prevents a concurrent reservation
            // clearer or replacement start from stealing this turn state.
            drop(active);
            drop(admission_gate);
            if let Some(cleanup) = start_transition_owner.spawn_cleanup(reason)
                && let Err(error) = cleanup.await
            {
                // A panic or runtime teardown in the detached path must
                // remain observable.  The cleanup CAS is intentionally
                // fail-closed, so an errored join cannot make this turn
                // look idle or permit a replacement start.
                warn!(
                    turn_id = %turn_context.sub_id,
                    ?error,
                    "start transition terminalizer did not complete"
                );
            }
            return StartTaskOutcome::Aborted;
        }
        let agent_execution_guard = self.services.agent_control.execution_guard(
            turn_context.multi_agent_version,
            &turn_context.session_source,
        );
        let done_clone = Arc::clone(&done);
        let session = Arc::clone(self);
        let ctx = Arc::clone(&turn_context);
        let task_for_run = Arc::clone(&task);
        let task_input = input;
        let task_cancellation_token = cancellation_token.child_token();
        // Task-owned turn spans keep a core-owned span open for the
        // full task lifecycle after the submission dispatch span ends.
        let reasoning_effort = turn_context.effective_reasoning_effort_for_tracing();
        let task_span = info_span!(
            "turn",
            otel.name = span_name,
            thread.id = %self.thread_id,
            turn.id = %turn_context.sub_id,
            model = %turn_context.model_info.slug,
            codex.turn.reasoning_effort = %reasoning_effort,
            codex.turn.token_usage.input_tokens = field::Empty,
            codex.turn.token_usage.cached_input_tokens = field::Empty,
            codex.turn.token_usage.cache_write_input_tokens = field::Empty,
            codex.turn.token_usage.non_cached_input_tokens = field::Empty,
            codex.turn.token_usage.output_tokens = field::Empty,
            codex.turn.token_usage.reasoning_output_tokens = field::Empty,
            codex.turn.token_usage.total_tokens = field::Empty,
        );
        let handle = tokio::spawn(
            async move {
                let ctx_for_finish = Arc::clone(&ctx);
                // Enforce the host-owned gate for every task kind at the
                // common spawn boundary.  RegularTask repeats the check
                // before TurnStarted; this common check also protects review,
                // compact, and shell tasks if a gate is ever attached there.
                let task_result = AssertUnwindSafe(
                    async {
                        if let Some(gate) = ctx
                            .extension_data
                            .get::<codex_extension_api::TurnStartGate>()
                            && !gate.is_allowed()
                        {
                            return Err(CodexErr::TurnAborted);
                        }
                        task_for_run
                            .run(
                                Arc::clone(&session),
                                ctx,
                                task_input,
                                task_cancellation_token.child_token(),
                            )
                            .await
                    }
                    .instrument(trace_span!("session_task.run")),
                )
                .catch_unwind()
                .await;
                let task_result = match task_result {
                    Ok(result) => result,
                    Err(_) => {
                        // A panic in a SessionTask must still pass through the
                        // ordinary terminalization path. The RunningTask is
                        // already attached to `active_turn`; letting the
                        // JoinHandle unwind would otherwise strand that task,
                        // its recovery authority, and every later admission.
                        warn!(
                            turn_id = %ctx_for_finish.sub_id,
                            "session task panicked; converting panic to a terminal error"
                        );
                        Err(CodexErr::Fatal("session task panicked".to_string()))
                    }
                };
                let sess = Arc::clone(&session);
                if !task_cancellation_token.is_cancelled() {
                    // Finish uniformly from the spawn site so all tasks share the same lifecycle.
                    sess.on_task_finished(Arc::clone(&ctx_for_finish), task_result)
                        .await;
                }
                done_clone.notify_waiters();
            }
            .instrument(task_span),
        );
        let timer = turn_context
            .session_telemetry
            .start_timer(TURN_E2E_DURATION_METRIC, &[])
            .ok();
        // Attaching any task invalidates an older recovery token and mints the
        // epoch while the active-turn critical section is still held.
        *self
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned") = None;
        let attach_epoch = self.turn_epoch.fetch_add(1, Ordering::AcqRel) + 1;
        let running_task = RunningTask {
            done,
            handle: AbortOnDropHandle::new(handle),
            kind: task_kind,
            recovery_eligible_model_turn,
            recovery_authority,
            attach_epoch,
            task,
            cancellation_token,
            turn_context: Arc::clone(&turn_context),
            _agent_execution_guard: agent_execution_guard,
            _diagnostics_guard: ACTIVE_TURNS.track(),
            _timer: timer,
        };
        turn.task = Some(running_task);
        turn.start_transition = None;
        drop(admission_gate);
        start_transition_owner.disarm();
        StartTaskOutcome::Attached
    }

    /// Returns whether an extension has marked this thread as durably asleep.
    pub(crate) fn has_outstanding_durable_sleep(&self) -> bool {
        self.services
            .thread_extension_data
            .get::<codex_extension_items::sleep::SleepItem>()
            .is_some()
    }

    /// Starts a regular turn when the session is idle and pending work is waiting.
    ///
    /// Pending work includes mailbox mail marked with `trigger_turn`, or any mailbox mail while
    /// an outstanding durable sleep is attached to the thread.
    ///
    /// This helper generates a fresh sub-id for the synthetic turn before delegating to the
    /// explicit-sub-id variant.
    pub(crate) fn maybe_start_turn_for_pending_work(self: &Arc<Self>) -> BoxFuture<'static, ()> {
        let session = Arc::clone(self);
        Box::pin(async move {
            session
                .maybe_start_turn_for_pending_work_with_sub_id_and_owner(
                    uuid::Uuid::new_v4().to_string(),
                    /*terminalization_owner*/ None,
                )
                .await;
        })
    }

    pub(crate) fn maybe_start_turn_for_pending_work_after_terminalization(
        self: &Arc<Self>,
        terminalization_owner: Arc<()>,
    ) -> BoxFuture<'static, ()> {
        let session = Arc::clone(self);
        Box::pin(async move {
            session
                .maybe_start_turn_for_pending_work_with_sub_id_and_owner(
                    uuid::Uuid::new_v4().to_string(),
                    Some(terminalization_owner),
                )
                .await;
        })
    }

    /// Starts a regular turn with the provided sub-id when pending work should wake an idle
    /// session.
    ///
    /// The turn is created only when the session is idle and mailbox mail either requests a turn
    /// or can wake an outstanding durable sleep.
    pub(crate) async fn maybe_start_turn_for_pending_work_with_sub_id(
        self: &Arc<Self>,
        sub_id: String,
    ) {
        self.maybe_start_turn_for_pending_work_with_sub_id_and_owner(
            sub_id, /*terminalization_owner*/ None,
        )
        .await;
    }

    #[expect(
        clippy::expect_used,
        reason = "the pending-work start reservation is created only after the exact idle-state check"
    )]
    async fn maybe_start_turn_for_pending_work_with_sub_id_and_owner(
        self: &Arc<Self>,
        sub_id: String,
        terminalization_owner: Option<Arc<()>>,
    ) {
        if self.shutdown_started()
            || self.has_pending_admission_fence_except(terminalization_owner.as_ref())
        {
            return;
        }
        if !self.input_queue.has_pending_mailbox_items().await
            || (!self.input_queue.has_trigger_turn_mailbox_items().await
                && !self.has_outstanding_durable_sleep())
        {
            return;
        }

        let start_reservation = {
            let mut active_turn = self.active_turn.lock().await;
            if self.shutdown_started()
                || self.has_pending_admission_fence_except(terminalization_owner.as_ref())
                || active_turn.is_some()
            {
                return;
            }
            if self.enabled(Feature::HeptaTurnRecovery)
                && self
                    .recovery_candidate
                    .lock()
                    .expect("recovery candidate mutex poisoned")
                    .is_some()
            {
                // Durable queued work must wait for explicit recovery or an
                // explicit user action that consumes the interrupted tail.
                return;
            }
            let active = active_turn.get_or_insert_with(ActiveTurn::default);
            active
                .reserve_start(sub_id.clone())
                .expect("idle slot should accept one start reservation")
        };

        let mut start_reservation_owner = StartReservationOwner::new(self, start_reservation);
        let turn_context = self.new_default_turn_with_sub_id(sub_id).await;
        self.maybe_emit_model_warnings_for_turn(turn_context.as_ref())
            .await;
        let start_outcome = self
            .start_task_with_options(
                turn_context,
                Vec::new(),
                RegularTask::new(TurnRunOrigin::NewTurn),
                MailboxParentProvenance::Attribute,
                /*recovery_history*/ None,
                Some(start_reservation_owner.handle().clone()),
                terminalization_owner,
            )
            .await;
        if start_outcome != StartTaskOutcome::Stale {
            start_reservation_owner.disarm();
        }
    }

    /// Runs abort terminalization in a detached job. Dropping the caller's
    /// future after the task-terminalization claim must not drop the owner
    /// body; Tokio JoinHandle drop detaches the job and the registry fence
    /// remains the teardown backstop if the job itself fails.
    pub async fn abort_all_tasks(self: &Arc<Self>, reason: TurnAbortReason) {
        let target = AssertUnwindSafe(self.detach_active_task_for_abort(
            &reason, /*expected_turn_id*/ None, /*expected_turn_state*/ None,
            /*deferred_idle_cause*/ None,
        ))
        .catch_unwind()
        .await;
        let Some(target) = (match target {
            Ok(target) => target,
            Err(_) => {
                warn!("abort-all claim panicked; retaining any published completion fence");
                return;
            }
        }) else {
            return;
        };
        let detached = match target {
            ActiveTurnAbortTarget::Running(detached) => detached,
            ActiveTurnAbortTarget::Terminalizing | ActiveTurnAbortTarget::Starting { .. } => {
                // A finish/abort owner or an in-flight start already owns the
                // exact state. The ordinary abort path remains non-blocking;
                // shutdown's dedicated drain adopts queued witnesses.
                return;
            }
        };
        // Claim and publish the full witness before scheduling any detached
        // continuation.  The construction-time Session handle is not a
        // liveness witness: if that runtime has already shut down, Tokio
        // accepts the spawn but drops the future before its first poll.  A
        // current caller runtime may still be alive (for example a guardian
        // callback running on a replacement runtime), so schedule there;
        // either way the registry-backed slot remains the shutdown fallback.
        let Some(runtime_handle) = tokio::runtime::Handle::try_current().ok() else {
            warn!(
                "abort-all terminalizer cannot be scheduled without a live Tokio runtime; retaining its completion fence"
            );
            return;
        };
        let session = Arc::clone(self);
        let join = runtime_handle.spawn(
            async move {
                let result = AssertUnwindSafe(session.drive_abort_handoff(detached.slot))
                    .catch_unwind()
                    .await;
                if result.is_err() {
                    warn!("abort-all terminalizer panicked; retaining its completion fence");
                }
            }
            .in_current_span(),
        );
        if let Err(error) = join.await {
            warn!(?error, "abort-all terminalizer did not complete");
        }
    }

    /// Drain caller reservations and materialized start transitions during
    /// session teardown.
    ///
    /// Ordinary `abort_all_tasks` callers intentionally return immediately for
    /// `Starting`: a lifecycle contributor may be waiting on the caller that
    /// requested replacement/steer.  Teardown has a stronger ordering
    /// obligation, so its handler calls this dedicated drain before emitting
    /// thread-stop lifecycle.  A terminalizer that panics, hangs, or cannot be
    /// scheduled leaves the completion fence unresolved and therefore keeps
    /// teardown fail-closed instead of publishing thread-stop out of order.
    #[expect(
        clippy::expect_used,
        reason = "shutdown drains a transition only after matching its exact cleanup identity"
    )]
    pub(crate) async fn drain_start_transition_for_shutdown(self: &Arc<Self>) {
        loop {
            // Start-transition publication is serialized by the active-turn
            // lock: start_task_with_options checks shutdown and installs the
            // marker, cleanup cell, and registry entry before releasing it.
            // Acquire/release that same lock before taking the registry
            // snapshot so a concurrent shutdown cannot observe an empty
            // registry in the check-to-register window.  begin_shutdown must
            // remain lock-free because suspension can call it while holding
            // the active-turn lock.
            // `abort_all_tasks` records an abort reason on a caller-owned
            // reservation, but there is no materialized turn context yet and
            // therefore no transition completion fence for the ordinary
            // drain to observe.  Once shutdown is sealed, release that exact
            // reservation here so a caller that remains in its preparation
            // preamble cannot keep the session busy indefinitely.  The owner
            // continuation will later fail the same identity check at
            // promotion; no terminal event is valid before a context exists.
            let release = {
                // This acquisition is also the publication barrier described
                // above: a start either publishes its transition before this
                // lock is acquired, or observes shutdown before publishing.
                let mut active = self.active_turn.lock().await;
                if !self.shutdown_started() {
                    None
                } else {
                    let handle = active.as_ref().and_then(|active_turn| {
                        active_turn.start_reservation.as_ref().map(|reservation| {
                            StartReservationHandle {
                                identity: Arc::clone(&reservation.identity),
                                turn_id: reservation.turn_id.clone(),
                                turn_state: Arc::clone(&active_turn.turn_state),
                            }
                        })
                    });
                    let abort_requested = active
                        .as_mut()
                        .and_then(|active_turn| active_turn.start_reservation.as_mut())
                        .is_some_and(|reservation| {
                            reservation.request_abort(TurnAbortReason::Interrupted)
                        });
                    if abort_requested {
                        self.mark_interrupted();
                    }
                    handle.map(|handle| {
                        Self::release_start_reservation_if_current_locked(&mut active, &handle)
                    })
                }
            };
            if let Some(release) = release
                && !matches!(release, StartReservationRelease::Stale)
            {
                self.settle_consumed_recovery_status();
            }
            // A detached owner may have been dropped after its construction
            // runtime closed, or its first spawn may have been accepted by a
            // scheduler that was already shutting down.  In both cases the
            // full witness remains in its registry cell.  Claiming the cell
            // here is the only safe retry: if a live detached owner already
            // took it, the completion fence below remains the authority.
            for cleanup_slot in self.pending_start_transition_cleanup_slots() {
                let Some(cleanup) = cleanup_slot
                    .lock()
                    .expect("start transition cleanup slot mutex poisoned")
                    .take()
                else {
                    continue;
                };
                if cleanup.failed_closed {
                    // The detached owner crossed into non-idempotent abort
                    // work before it was cancelled.  Replaying the witness
                    // could duplicate lifecycle/durable effects, while
                    // clearing the fence would publish teardown out of
                    // order.  Keep it registered and fail closed.
                    cleanup_slot
                        .lock()
                        .expect("start transition cleanup slot mutex poisoned")
                        .replace(cleanup);
                    continue;
                }
                let turn_id = cleanup.turn_context.sub_id.clone();
                let session = Arc::clone(self);
                let mut cleanup_owner =
                    StartTransitionCleanupOwner::new(Arc::clone(&cleanup_slot), cleanup);
                let result = tokio::time::timeout(
                    TERMINALIZER_WATCHDOG_TIMEOUT,
                    AssertUnwindSafe(session.abort_dropped_start_transition(
                        &mut cleanup_owner,
                        TurnAbortReason::Interrupted,
                    ))
                    .catch_unwind(),
                )
                .await;
                match result {
                    Ok(Err(_)) => warn!(
                        %turn_id,
                        "shutdown start-transition terminalizer panicked; retaining its completion fence"
                    ),
                    Err(_) => warn!(
                        %turn_id,
                        "shutdown start-transition terminalizer watchdog expired; retaining its completion fence"
                    ),
                    Ok(Ok(())) if cleanup_owner.is_complete() => cleanup_owner.disarm(),
                    Ok(Ok(())) => {}
                }
            }
            let completions = self.pending_start_transition_completions();
            if completions.is_empty() {
                return;
            }
            for completion in completions {
                completion.wait().await;
            }
        }
    }

    #[cfg_attr(
        not(test),
        expect(dead_code, reason = "used by focused lifecycle qualification tests")
    )]
    pub(crate) async fn abort_turn_if_active(
        self: &Arc<Self>,
        turn_id: &str,
        reason: TurnAbortReason,
    ) -> bool {
        !matches!(
            self.abort_turn_if_active_impl(
                turn_id, /*expected_turn_state*/ None, reason,
                /*deferred_idle_cause*/ None,
            )
            .await,
            AbortTurnOutcome::NotActive
        )
    }

    /// Guardian-specific abort binding. The state identity is captured with
    /// the review request, so a delayed callback cannot target a later attempt
    /// that happens to reuse the same protocol turn id. A start transition
    /// owns the deferred idle callback; the guardian caller must not emit one
    /// for `DeferredStart` or it could race and double-publish.
    pub(crate) async fn abort_turn_if_active_for_guardian(
        self: &Arc<Self>,
        turn_id: &str,
        expected_turn_state: &Arc<Mutex<TurnState>>,
        reason: TurnAbortReason,
    ) -> AbortTurnOutcome {
        self.abort_turn_if_active_impl(
            turn_id,
            Some(expected_turn_state),
            reason,
            Some(ThreadIdleCause::Interrupted),
        )
        .await
    }

    async fn abort_turn_if_active_impl(
        self: &Arc<Self>,
        turn_id: &str,
        expected_turn_state: Option<&Arc<Mutex<TurnState>>>,
        reason: TurnAbortReason,
        deferred_idle_cause: Option<ThreadIdleCause>,
    ) -> AbortTurnOutcome {
        let turn_id = turn_id.to_string();
        let expected_turn_state = expected_turn_state.cloned();
        let target = AssertUnwindSafe(self.detach_active_task_for_abort(
            &reason,
            Some(&turn_id),
            expected_turn_state.as_ref(),
            deferred_idle_cause,
        ))
        .catch_unwind()
        .await;
        let Some(target) = (match target {
            Ok(target) => target,
            Err(_) => {
                warn!(
                    %turn_id,
                    "abort claim panicked; retaining any published completion fence"
                );
                return AbortTurnOutcome::Terminalizing;
            }
        }) else {
            return AbortTurnOutcome::NotActive;
        };
        let detached = match target {
            ActiveTurnAbortTarget::Running(detached) => detached,
            ActiveTurnAbortTarget::Terminalizing => {
                return AbortTurnOutcome::Terminalizing;
            }
            ActiveTurnAbortTarget::Starting { deferred_idle, .. } => {
                return if deferred_idle {
                    AbortTurnOutcome::DeferredStart
                } else {
                    AbortTurnOutcome::Starting
                };
            }
        };
        let Some(runtime_handle) = tokio::runtime::Handle::try_current().ok() else {
            warn!(
                %turn_id,
                "abort terminalizer cannot be scheduled without a live Tokio runtime; retaining its completion fence"
            );
            return AbortTurnOutcome::Terminalizing;
        };
        let session = Arc::clone(self);
        let join = runtime_handle.spawn(
            async move {
                let result =
                    AssertUnwindSafe(async { session.drive_abort_handoff(detached.slot).await })
                        .catch_unwind()
                        .await;
                match result {
                    Ok(outcome) => outcome,
                    Err(_) => {
                        warn!(
                            %turn_id,
                            "abort terminalizer panicked; retaining its completion fence"
                        );
                        AbortTurnOutcome::Terminalizing
                    }
                }
            }
            .in_current_span(),
        );
        match join.await {
            Ok(outcome) => outcome,
            Err(error) => {
                warn!(?error, "abort terminalizer did not complete");
                // The detached job may have claimed the marker before
                // panicking. Keep callers fail-closed rather than reporting a
                // false idle/not-active result.
                AbortTurnOutcome::Terminalizing
            }
        }
    }

    /// Claims a normal task finish before scheduling any detached work.  The
    /// exact task, result, recovery witness, and completion fence are moved
    /// into the registry while the active-turn lock is held.  This closes the
    /// construction-runtime race where a stored Tokio handle accepts a spawn
    /// after its runtime has already stopped polling it.
    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "the terminalization claim lock and handoff identity fence the complete finish detach"
    )]
    async fn claim_task_for_finish(
        &self,
        turn_context: &Arc<TurnContext>,
        task_result: SessionTaskResult,
    ) -> Option<TaskFinishHandoffSlot> {
        // The witness keeps the task's `RunningTask` alive while its original
        // abort handle is replaced with an inert completed handle.  Creating
        // that replacement requires a live Tokio scheduler; fail closed
        // before publishing the marker if this callback is ever polled by a
        // non-Tokio caller.  Otherwise a `tokio::spawn` panic could leave an
        // empty registry slot and an unrecoverable active-turn fence.
        if tokio::runtime::Handle::try_current().is_err() {
            warn!(
                turn_id = %turn_context.sub_id,
                "finish terminalizer cannot claim a task without a live Tokio runtime; retaining the active-turn fence"
            );
            return None;
        }
        let abort_reason_hint = match &task_result {
            Err(err) if matches!(err.details(), CodexErrorDetails::TurnAborted) => {
                Some(TurnAbortReason::Interrupted)
            }
            Ok(_) | Err(_) => None,
        };
        let _claim_lock = self.terminalization_claim_lock.lock().await;
        let mut active = self.active_turn.lock().await;
        let active_turn = active.as_mut()?;
        let task_ref = active_turn.task.as_ref()?;
        if !Arc::ptr_eq(&task_ref.turn_context, turn_context)
            || active_turn.task_terminalization.is_some()
        {
            return None;
        }
        let task_identity = Arc::clone(&task_ref.task);
        let task_context = Arc::clone(&task_ref.turn_context);
        let attach_epoch = task_ref.attach_epoch;
        let turn_state = Arc::clone(&active_turn.turn_state);
        let recovery_seed = Self::recovery_seed_for_task(task_ref, abort_reason_hint.as_ref());
        let recovery_authority = task_ref.recovery_authority.clone();
        let slot: TaskFinishHandoffSlot = Arc::new(std::sync::Mutex::new(None));
        // Keep the cell locked across registry publication, task take, and
        // witness fill.  Shutdown snapshots the registry without holding its
        // lock while it takes the slot, so it cannot observe an empty witness.
        let mut slot_guard = slot
            .lock()
            .expect("task finish handoff slot mutex poisoned");
        let (terminalization_identity, completion) = self
            .claim_task_terminalization_locked(
                active_turn,
                &task_identity,
                &task_context,
                attach_epoch,
                TaskTerminalizationKind::Finish,
                /*suspension_handoff*/ None,
                /*abort_handoff*/ None,
                Some(Arc::clone(&slot)),
            )
            .expect("task terminalization claim should be unique");
        let mut task = Self::take_task_for_terminalization_locked(
            active_turn,
            &terminalization_identity,
            TaskTerminalizationKind::Finish,
        )
        .expect("claimed finish task should remain attached");
        // The callback is running from this very task's future.  Detach its
        // AbortOnDropHandle before publishing the witness so dropping the
        // caller/runtime cannot abort the task that owns the terminalizer.
        // `AbortOnDropHandle::detach` consumes the field. Keep the rest of
        // `RunningTask` (guards/timing metadata) alive through the finish
        // body by replacing it with an already-complete inert handle.
        let detached_handle = std::mem::replace(
            &mut task.handle,
            AbortOnDropHandle::new(tokio::spawn(std::future::ready(()))),
        );
        detached_handle.detach();
        *slot_guard = Some(TaskFinishHandoff {
            task: Some(task),
            turn_context: task_context,
            task_result: Some(task_result),
            turn_state,
            terminalization_identity,
            completion,
            recovery_seed,
            recovery_authority,
            phase: TaskFinishHandoffPhase::Claimed,
            failed_closed: false,
        });
        drop(slot_guard);
        Some(slot)
    }

    #[cfg(test)]
    pub(crate) async fn claim_finish_handoff_for_test(
        &self,
        turn_context: Arc<TurnContext>,
        task_result: SessionTaskResult,
    ) -> Option<TaskFinishHandoffSlot> {
        self.claim_task_for_finish(&turn_context, task_result).await
    }

    /// Keeps the task's terminal owner alive if the task runner/caller is
    /// cancelled while recovery, persistence, or lifecycle callbacks await.
    /// The detached driver is scheduled on the current runtime, never on the
    /// runtime captured when the Session was constructed.
    pub async fn on_task_finished(
        self: &Arc<Self>,
        turn_context: Arc<TurnContext>,
        task_result: SessionTaskResult,
    ) {
        let Ok(Some(slot)) =
            AssertUnwindSafe(self.claim_task_for_finish(&turn_context, task_result))
                .catch_unwind()
                .await
        else {
            return;
        };
        let Some(runtime_handle) = tokio::runtime::Handle::try_current().ok() else {
            warn!(
                turn_id = %turn_context.sub_id,
                "finish terminalizer cannot be scheduled without a live Tokio runtime; retaining its completion fence"
            );
            return;
        };
        let session = Arc::clone(self);
        let join = runtime_handle.spawn(
            async move {
                let result = AssertUnwindSafe(session.drive_finish_handoff(slot))
                    .catch_unwind()
                    .await;
                if result.is_err() {
                    warn!("finish terminalizer panicked; retaining its completion fence");
                }
            }
            .in_current_span(),
        );
        if let Err(error) = join.await {
            warn!(?error, "task-finish terminalizer did not complete");
        }
    }

    #[expect(
        clippy::expect_used,
        reason = "a claimed finish handoff necessarily owns its task result"
    )]
    async fn run_finish_handoff(self: &Arc<Self>, handoff: &mut TaskFinishHandoff) {
        let (task_identity, task_epoch) = {
            let Some(task) = handoff.task.as_ref() else {
                handoff.failed_closed = true;
                return;
            };
            (Arc::clone(&task.task), task.attach_epoch)
        };
        let turn_context = Arc::clone(&handoff.turn_context);
        let turn_state = Arc::clone(&handoff.turn_state);
        handoff.phase = TaskFinishHandoffPhase::RecoveryRevoking;
        let recovery_seed = self
            .prepare_recovery_seed_for_controlled_detach(
                &turn_context.sub_id,
                handoff.recovery_authority.as_ref(),
                handoff.recovery_seed.clone(),
            )
            .await;
        handoff.recovery_seed = recovery_seed;
        turn_context
            .turn_metadata_state
            .cancel_git_enrichment_task();
        handoff.phase = TaskFinishHandoffPhase::RolloutFlushing;
        if let Err(err) = self.flush_rollout().await {
            warn!("failed to flush rollout before completing turn: {err}");
            self.send_event(
                turn_context.as_ref(),
                EventMsg::Warning(WarningEvent {
                    message: format!(
                        "Failed to save the conversation transcript; Codex will continue retrying. Error: {err}"
                    ),
                }),
            )
            .await;
        }
        // Taking the result is the first irreversible interpretation of the
        // task outcome; mark the witness advanced before doing so.
        handoff.phase = TaskFinishHandoffPhase::PersistencePublishing;
        let task_result = handoff
            .task_result
            .take()
            .expect("claimed finish handoff has task result");
        let (last_agent_message, abort_reason) = match task_result {
            Ok(last_agent_message) => (last_agent_message, None),
            Err(err) if matches!(err.details(), CodexErrorDetails::TurnAborted) => {
                (None, Some(TurnAbortReason::Interrupted))
            }
            Err(err) => {
                warn!(%err, "session task returned an unexpected error");
                handoff.phase = TaskFinishHandoffPhase::LifecyclePublishing;
                self.emit_turn_error_lifecycle(
                    turn_context.as_ref(),
                    err.to_codex_protocol_error(),
                )
                .await;
                self.track_turn_codex_error(turn_context.as_ref(), &err);
                self.send_event(
                    turn_context.as_ref(),
                    EventMsg::Error(err.to_error_event(/*message_prefix*/ None)),
                )
                .await;
                (None, None)
            }
        };
        handoff.phase = TaskFinishHandoffPhase::InputClearing;
        let pending_input = self
            .input_queue
            .take_pending_input_for_turn_state(turn_state.as_ref())
            .await;
        let (turn_had_memory_citation, turn_tool_calls, token_usage_at_turn_start) = {
            let ts = turn_state.lock().await;
            (
                ts.has_memory_citation,
                ts.tool_calls,
                ts.token_usage_at_turn_start.clone(),
            )
        };
        run_hooks_and_record_inputs(
            self,
            &turn_context,
            &pending_input,
            PersistContext::Standard,
        )
        .await;
        let task_ended_before_persistence = self
            .pending_user_message_admissions
            .complete_task_end(&turn_context.sub_id);
        // Emit token usage metrics.
        {
            // TODO(jif): drop this
            let tmp_mem = (
                "tmp_mem_enabled",
                if self.enabled(Feature::MemoryTool) {
                    "true"
                } else {
                    "false"
                },
            );
            let network_proxy = self.services.network_proxy.load_full();
            let network_proxy_active = match network_proxy.as_ref() {
                Some(started_network_proxy) => {
                    match started_network_proxy.proxy().current_cfg().await {
                        Ok(config) => config.enabled,
                        Err(err) => {
                            warn!(
                                "failed to read managed network proxy state for turn metrics: {err:#}"
                            );
                            false
                        }
                    }
                }
                None => false,
            };
            emit_turn_network_proxy_metric(
                &self.services.session_telemetry,
                network_proxy_active,
                tmp_mem,
            );
            self.services.session_telemetry.histogram(
                TURN_TOOL_CALL_METRIC,
                i64::try_from(turn_tool_calls).unwrap_or(i64::MAX),
                &[tmp_mem],
            );
            let total_token_usage = self.total_token_usage().await.unwrap_or_default();
            let turn_token_usage = TokenUsage {
                input_tokens: (total_token_usage.input_tokens
                    - token_usage_at_turn_start.input_tokens)
                    .max(0),
                cached_input_tokens: (total_token_usage.cached_input_tokens
                    - token_usage_at_turn_start.cached_input_tokens)
                    .max(0),
                cache_write_input_tokens: (total_token_usage.cache_write_input_tokens
                    - token_usage_at_turn_start.cache_write_input_tokens)
                    .max(0),
                output_tokens: (total_token_usage.output_tokens
                    - token_usage_at_turn_start.output_tokens)
                    .max(0),
                reasoning_output_tokens: (total_token_usage.reasoning_output_tokens
                    - token_usage_at_turn_start.reasoning_output_tokens)
                    .max(0),
                total_tokens: (total_token_usage.total_tokens
                    - token_usage_at_turn_start.total_tokens)
                    .max(0),
                codex_rollout_budget_units: None,
            };
            let current_span = Span::current();
            current_span.record(
                "codex.turn.token_usage.input_tokens",
                turn_token_usage.input_tokens,
            );
            current_span.record(
                "codex.turn.token_usage.cached_input_tokens",
                turn_token_usage.cached_input(),
            );
            current_span.record(
                "codex.turn.token_usage.cache_write_input_tokens",
                turn_token_usage.cache_write_input_tokens,
            );
            current_span.record(
                "codex.turn.token_usage.non_cached_input_tokens",
                turn_token_usage.non_cached_input(),
            );
            current_span.record(
                "codex.turn.token_usage.output_tokens",
                turn_token_usage.output_tokens,
            );
            current_span.record(
                "codex.turn.token_usage.reasoning_output_tokens",
                turn_token_usage.reasoning_output_tokens,
            );
            current_span.record(
                "codex.turn.token_usage.total_tokens",
                turn_token_usage.total_tokens,
            );
            self.services
                .analytics_events_client
                .track_turn_token_usage(TurnTokenUsageFact {
                    turn_id: turn_context.sub_id.clone(),
                    thread_id: self.thread_id.to_string(),
                    token_usage: turn_token_usage.clone(),
                });
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.total_tokens,
                &[("token_type", "total"), tmp_mem],
            );
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.input_tokens,
                &[("token_type", "input"), tmp_mem],
            );
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.cached_input(),
                &[("token_type", "cached_input"), tmp_mem],
            );
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.cache_write_input_tokens,
                &[("token_type", "cache_write_input"), tmp_mem],
            );
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.output_tokens,
                &[("token_type", "output"), tmp_mem],
            );
            self.services.session_telemetry.histogram(
                TURN_TOKEN_USAGE_METRIC,
                turn_token_usage.reasoning_output_tokens,
                &[("token_type", "reasoning_output"), tmp_mem],
            );
        }
        emit_turn_memory_metric(
            &self.services.session_telemetry,
            turn_context.config.features.enabled(Feature::MemoryTool),
            turn_context.config.memories.use_memories,
            turn_had_memory_citation,
        );
        self.services.session_telemetry.counter(
            TURN_UNIFIED_EXEC_RUNNING_PROCESSES_METRIC,
            i64::try_from(self.list_background_terminals().await.len()).unwrap_or(i64::MAX),
            &[],
        );
        let started_at = turn_context.turn_timing_state.started_at_unix_secs().await;
        let (completed_at, duration_ms, profile) = turn_context
            .turn_timing_state
            .complete_profile_and_duration_ms()
            .await;
        self.services
            .analytics_events_client
            .track_turn_profile(TurnProfileFact {
                turn_id: turn_context.sub_id.clone(),
                profile,
            });
        let idle_cause = if matches!(
            abort_reason.as_ref(),
            Some(TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited)
        ) {
            ThreadIdleCause::Interrupted
        } else if task_ended_before_persistence
            || (abort_reason.is_none() && turn_context.terminal_error.lock().await.is_some())
        {
            ThreadIdleCause::Failed
        } else {
            ThreadIdleCause::Completed
        };
        handoff.phase = TaskFinishHandoffPhase::LifecyclePublishing;
        let event = if let Some(reason) = abort_reason {
            self.emit_turn_abort_lifecycle(reason.clone(), turn_context.extension_data.as_ref())
                .await;
            EventMsg::TurnAborted(TurnAbortedEvent {
                turn_id: Some(turn_context.sub_id.clone()),
                reason,
                started_at,
                completed_at,
                duration_ms,
            })
        } else {
            let time_to_first_token_ms = turn_context
                .turn_timing_state
                .time_to_first_token_ms()
                .await;
            let error = turn_context.terminal_error.lock().await.clone();
            self.emit_turn_stop_lifecycle(turn_context.extension_data.as_ref())
                .await;
            EventMsg::TurnComplete(TurnCompleteEvent {
                turn_id: turn_context.sub_id.clone(),
                last_agent_message,
                error,
                started_at,
                completed_at,
                duration_ms,
                time_to_first_token_ms,
            })
        };
        handoff.phase = TaskFinishHandoffPhase::PersistencePublishing;
        let terminal_persistence_generation = self
            .send_terminal_event_and_flush(turn_context.as_ref(), event)
            .await;
        self.services
            .guardian_rejection_circuit_breaker
            .lock()
            .await
            .clear_turn(&turn_context.sub_id);

        handoff.phase = TaskFinishHandoffPhase::MarkerReleasing;
        let cleared_completion = {
            let mut active = self.active_turn.lock().await;
            Self::clear_task_terminalization_if_current_locked(
                &mut active,
                &handoff.terminalization_identity,
                TaskTerminalizationKind::Finish,
                &turn_state,
                &task_identity,
                &turn_context,
                task_epoch,
            )
        };
        if cleared_completion.is_none() {
            handoff.failed_closed = true;
            return;
        }
        handoff.phase = TaskFinishHandoffPhase::RecoveryPublishing;
        self.publish_recovery_seed_after_terminal(
            handoff.recovery_seed.take(),
            /*task_quiesced*/ true,
            terminal_persistence_generation,
        )
        .await;
        handoff.phase = TaskFinishHandoffPhase::PendingWorkStarting;
        if let Some(completion) = cleared_completion.as_ref() {
            self.emit_thread_idle_lifecycle_if_idle_for_terminalization(
                idle_cause,
                Some(&handoff.terminalization_identity),
            )
            .await;
            self.maybe_start_turn_for_pending_work_after_terminalization(Arc::clone(
                &handoff.terminalization_identity,
            ))
            .await;
            self.finish_task_terminalization(&handoff.terminalization_identity, completion);
            handoff.phase = TaskFinishHandoffPhase::Complete;
            handoff.task.take();
        }
    }

    #[expect(
        clippy::expect_used,
        reason = "poisoning this private handoff mutex is an unrecoverable lifecycle invariant breach"
    )]
    fn take_finish_handoff(slot: &TaskFinishHandoffSlot) -> Option<TaskFinishHandoff> {
        slot.lock()
            .expect("task finish handoff slot mutex poisoned")
            .take()
    }

    fn retain_finish_handoff(slot: &TaskFinishHandoffSlot, handoff: TaskFinishHandoff) {
        let mut current = slot
            .lock()
            .expect("task finish handoff slot mutex poisoned");
        if current.is_none() {
            *current = Some(handoff);
        } else {
            warn!("task finish handoff slot already contains a witness");
        }
    }

    /// Drives one complete finish witness. The owner keeps the detached task,
    /// result, and exact identity alive across every await; cancellation after
    /// the first phase retains the fence and never replays side effects.
    async fn drive_finish_handoff(self: &Arc<Self>, slot: TaskFinishHandoffSlot) {
        let Some(handoff) = Self::take_finish_handoff(&slot) else {
            return;
        };
        self.drive_finish_handoff_taken(slot, handoff).await;
    }

    async fn drive_finish_handoff_taken(
        self: &Arc<Self>,
        slot: TaskFinishHandoffSlot,
        handoff: TaskFinishHandoff,
    ) {
        if handoff.failed_closed || handoff.phase != TaskFinishHandoffPhase::Claimed {
            Self::retain_finish_handoff(&slot, handoff);
            return;
        }
        let mut owner = TaskFinishHandoffOwner::new(Arc::clone(&slot), handoff);
        let result = tokio::time::timeout(
            TERMINALIZER_WATCHDOG_TIMEOUT,
            AssertUnwindSafe(self.run_finish_handoff(owner.handoff_mut())).catch_unwind(),
        )
        .await;
        match result {
            Ok(Ok(())) => {
                if owner.is_complete() {
                    owner.disarm();
                }
            }
            Ok(Err(_)) => {
                warn!("finish handoff panicked; retaining its completion fence");
                owner.handoff_mut().failed_closed = true;
            }
            Err(_) => {
                warn!("finish handoff watchdog expired; retaining its completion fence");
            }
        }
    }

    #[expect(
        clippy::expect_used,
        reason = "poisoning this private handoff mutex is an unrecoverable lifecycle invariant breach"
    )]
    fn take_abort_handoff(slot: &TaskAbortHandoffSlot) -> Option<TaskAbortHandoff> {
        slot.lock()
            .expect("task abort handoff slot mutex poisoned")
            .take()
    }

    fn retain_abort_handoff(slot: &TaskAbortHandoffSlot, handoff: TaskAbortHandoff) {
        let mut current = slot.lock().expect("task abort handoff slot mutex poisoned");
        if current.is_none() {
            *current = Some(handoff);
        } else {
            warn!("task abort handoff slot already contains a witness");
        }
    }

    /// Drives one complete abort witness.  The owner keeps the task and all
    /// exact identity/recovery fields alive across every await; if the Tokio
    /// runtime disappears, its Drop implementation re-publishes the witness
    /// and leaves the completion fence authoritative.
    async fn drive_abort_handoff(self: &Arc<Self>, slot: TaskAbortHandoffSlot) -> AbortTurnOutcome {
        let Some(handoff) = Self::take_abort_handoff(&slot) else {
            return AbortTurnOutcome::Terminalizing;
        };
        self.drive_abort_handoff_taken(slot, handoff).await
    }

    async fn drive_abort_handoff_taken(
        self: &Arc<Self>,
        slot: TaskAbortHandoffSlot,
        handoff: TaskAbortHandoff,
    ) -> AbortTurnOutcome {
        if handoff.failed_closed || handoff.phase != TaskAbortHandoffPhase::Claimed {
            Self::retain_abort_handoff(&slot, handoff);
            return AbortTurnOutcome::Terminalizing;
        }
        let mut owner = TaskAbortHandoffOwner::new(Arc::clone(&slot), handoff);
        let result = tokio::time::timeout(
            TERMINALIZER_WATCHDOG_TIMEOUT,
            AssertUnwindSafe(self.run_abort_handoff(owner.handoff_mut())).catch_unwind(),
        )
        .await;
        match result {
            Ok(Ok(outcome)) => {
                if owner.is_complete() {
                    owner.disarm();
                }
                outcome
            }
            Ok(Err(_)) => {
                warn!("abort handoff panicked; retaining its completion fence");
                owner.handoff_mut().failed_closed = true;
                AbortTurnOutcome::Terminalizing
            }
            Err(_) => {
                warn!("abort handoff watchdog expired; retaining its completion fence");
                AbortTurnOutcome::Terminalizing
            }
        }
    }

    async fn run_abort_handoff(
        self: &Arc<Self>,
        handoff: &mut TaskAbortHandoff,
    ) -> AbortTurnOutcome {
        let Some(task) = handoff.task.as_mut() else {
            handoff.failed_closed = true;
            return AbortTurnOutcome::Terminalizing;
        };
        let turn_context = Arc::clone(&task.turn_context);
        let task_identity = Arc::clone(&task.task);
        let task_epoch = task.attach_epoch;

        handoff.phase = TaskAbortHandoffPhase::RecoveryRevoking;
        handoff.recovery_seed = self
            .prepare_recovery_seed_for_controlled_detach(
                &turn_context.sub_id,
                handoff.recovery_authority.as_ref(),
                handoff.recovery_seed.clone(),
            )
            .await;

        handoff.phase = TaskAbortHandoffPhase::TaskAborting;
        let outcome = self
            .handle_task_abort(
                task,
                handoff.reason.clone(),
                handoff.recovery_seed.clone(),
                handoff.recovery_authority.clone(),
            )
            .await;
        handoff.task_quiesced = outcome.task_quiesced;
        handoff.terminal_persistence_generation = outcome.terminal_persistence_generation;
        handoff.recovery_seed = outcome.recovery_seed;
        // The task-specific abort hook and handle have completed. Release the
        // execution/residency guards before lifecycle publication and pending
        // work admission, matching the old consuming terminalizer while the
        // handoff keeps all identity/recovery witnesses alive.
        handoff.task.take();

        handoff.phase = TaskAbortHandoffPhase::LifecyclePublishing;
        self.emit_turn_abort_lifecycle(
            handoff.reason.clone(),
            turn_context.extension_data.as_ref(),
        )
        .await;

        handoff.phase = TaskAbortHandoffPhase::InputClearing;
        self.input_queue
            .clear_pending_for_turn_state(&handoff.turn_state)
            .await;

        handoff.phase = TaskAbortHandoffPhase::MarkerReleasing;
        let cleared_completion = {
            let mut active = self.active_turn.lock().await;
            Self::clear_task_terminalization_if_current_locked(
                &mut active,
                &handoff.terminalization_identity,
                TaskTerminalizationKind::Abort,
                &handoff.turn_state,
                &task_identity,
                &turn_context,
                task_epoch,
            )
        };
        let Some(completion) = cleared_completion else {
            return AbortTurnOutcome::Terminalizing;
        };

        handoff.phase = TaskAbortHandoffPhase::RecoveryPublishing;
        self.publish_recovery_seed_after_terminal(
            handoff.recovery_seed.take(),
            handoff.task_quiesced,
            handoff.terminal_persistence_generation,
        )
        .await;

        handoff.phase = TaskAbortHandoffPhase::PendingWorkStarting;
        if handoff.reason == TurnAbortReason::Interrupted {
            self.maybe_start_turn_for_pending_work_after_terminalization(Arc::clone(
                &handoff.terminalization_identity,
            ))
            .await;
        }
        if let Some(cause) = handoff.deferred_idle_cause {
            // This callback belongs to the exact abort owner. Ignore that
            // owner's still-pending registry entry, but retain every other
            // terminalization fence and the normal shutdown suppression.
            self.emit_thread_idle_lifecycle_if_idle_for_terminalization(
                cause,
                Some(&handoff.terminalization_identity),
            )
            .await;
        }
        self.finish_task_terminalization(&handoff.terminalization_identity, &completion);
        handoff.phase = TaskAbortHandoffPhase::Complete;
        AbortTurnOutcome::Running
    }

    /// Revokes task-owned recovery authority while the active slot is locked,
    /// then either detaches a running task or fences a caller reservation / the
    /// host-owned start transition. Starts and injections therefore cannot
    /// observe an idle session until the old task is quiescent and its terminal
    /// is durable (or the start owner has completed its deferred handoff).
    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "the terminalization claim lock and handoff identity fence the complete abort detach"
    )]
    async fn detach_active_task_for_abort(
        &self,
        reason: &TurnAbortReason,
        expected_turn_id: Option<&str>,
        expected_turn_state: Option<&Arc<Mutex<TurnState>>>,
        deferred_idle_cause: Option<ThreadIdleCause>,
    ) -> Option<ActiveTurnAbortTarget> {
        let _claim_lock = self.terminalization_claim_lock.lock().await;
        let mut active = self.active_turn.lock().await;
        let active_turn = active.as_mut()?;
        if expected_turn_state
            .is_some_and(|expected| !Arc::ptr_eq(&active_turn.turn_state, expected))
        {
            return None;
        }
        if let Some(marker) = active_turn.task_terminalization.as_ref() {
            if expected_turn_id.is_some_and(|expected| marker.turn_context.sub_id != expected) {
                return None;
            }
            return Some(ActiveTurnAbortTarget::Terminalizing);
        }
        let Some(task) = active_turn.task.as_ref() else {
            if let Some(transition) = active_turn.start_transition.as_mut() {
                if expected_turn_id.is_some_and(|expected| transition.turn_id != expected) {
                    return None;
                }
                let accepted = transition.request_abort(reason.clone());
                if accepted {
                    if matches!(
                        reason,
                        TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
                    ) {
                        self.mark_interrupted();
                    }
                    if let Some(cause) = deferred_idle_cause {
                        transition.request_deferred_idle(cause);
                    }
                }
                return Some(ActiveTurnAbortTarget::Starting {
                    deferred_idle: accepted && deferred_idle_cause.is_some(),
                });
            }
            if let Some(reservation) = active_turn.start_reservation.as_mut() {
                if expected_turn_id.is_some_and(|expected| reservation.turn_id != expected) {
                    return None;
                }
                if reservation.request_abort(reason.clone())
                    && matches!(
                        reason,
                        TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
                    )
                {
                    self.mark_interrupted();
                }
                return Some(ActiveTurnAbortTarget::Starting {
                    deferred_idle: false,
                });
            }
            return None;
        };
        if expected_turn_id.is_some_and(|expected| task.turn_context.sub_id != expected) {
            return None;
        }
        if matches!(
            reason,
            TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
        ) {
            self.mark_interrupted();
        }
        let recovery_seed = Self::recovery_seed_for_task(task, Some(reason));
        let recovery_authority = task.recovery_authority.clone();
        let task_context = Arc::clone(&task.turn_context);
        let task_identity = Arc::clone(&task.task);
        let turn_state = Arc::clone(&active_turn.turn_state);
        let attach_epoch = task.attach_epoch;
        let slot: TaskAbortHandoffSlot = Arc::new(std::sync::Mutex::new(None));
        // Keep the cell locked across registry publication, task take, and
        // witness fill. Shutdown may snapshot the registry concurrently, but
        // it cannot observe an empty slot and miss a Claimed witness.
        let mut slot_guard = slot.lock().expect("task abort handoff slot mutex poisoned");
        let (terminalization_identity, completion) = self
            .claim_task_terminalization_locked(
                active_turn,
                &task_identity,
                &task_context,
                attach_epoch,
                TaskTerminalizationKind::Abort,
                /*suspension_handoff*/ None,
                Some(Arc::clone(&slot)),
                /*finish_handoff*/ None,
            )
            .expect("task terminalization claim should be unique");
        let task = Self::take_task_for_terminalization_locked(
            active_turn,
            &terminalization_identity,
            TaskTerminalizationKind::Abort,
        )
        .expect("claimed abort task should remain attached");
        *slot_guard = Some(TaskAbortHandoff {
            task: Some(task),
            turn_state,
            terminalization_identity,
            completion,
            recovery_seed,
            recovery_authority,
            reason: reason.clone(),
            deferred_idle_cause,
            phase: TaskAbortHandoffPhase::Claimed,
            failed_closed: false,
            task_quiesced: false,
            terminal_persistence_generation: None,
        });
        drop(slot_guard);
        Some(ActiveTurnAbortTarget::Running(DetachedTaskForAbort {
            slot,
        }))
    }

    pub(crate) async fn close_unified_exec_processes(&self) {
        self.services
            .unified_exec_manager
            .terminate_all_processes()
            .await;
    }

    pub(crate) async fn list_background_terminals(&self) -> Vec<BackgroundTerminalInfo> {
        self.services.unified_exec_manager.list_processes().await
    }

    pub(crate) async fn terminate_background_terminal(&self, process_id: i32) -> bool {
        self.services
            .unified_exec_manager
            .terminate_process(process_id)
            .await
    }

    /// Completes an abort accepted during the host-owned start transition.
    ///
    /// There is no physical `RunningTask` to detach yet, but the normal abort
    /// path still owns important terminal semantics (admission completion,
    /// interrupted history marker, TurnAborted rollout/event, profile and
    /// guardian cleanup).  A pre-signalled placeholder lets that path run
    /// without ever invoking the real task's provider-facing `run` method.
    async fn abort_unstarted_turn(
        self: &Arc<Self>,
        task: Arc<dyn AnySessionTask>,
        turn_context: Arc<TurnContext>,
        turn_state: Arc<Mutex<TurnState>>,
        transition_identity: Arc<()>,
        mut recovery_history_restore: Option<ContextManager>,
        reason: TurnAbortReason,
    ) -> bool {
        if !self
            .restore_recovery_history_if_current(
                Some(&turn_state),
                &transition_identity,
                &mut recovery_history_restore,
            )
            .await
        {
            return false;
        }
        let done = Arc::new(Notify::new());
        // `handle_task_abort` waits for the task's completion notification;
        // pre-signal it because this placeholder never entered `run`.
        done.notify_one();
        let mut placeholder = RunningTask {
            done,
            kind: task.kind(),
            recovery_eligible_model_turn: false,
            recovery_authority: None,
            attach_epoch: self.turn_epoch.load(Ordering::Acquire),
            task,
            cancellation_token: CancellationToken::new(),
            handle: AbortOnDropHandle::new(tokio::spawn(std::future::pending::<()>())),
            turn_context: Arc::clone(&turn_context),
            _agent_execution_guard: None,
            _diagnostics_guard: ACTIVE_TURNS.track(),
            _timer: None,
        };
        let abort_outcome = self
            .handle_task_abort(
                &mut placeholder,
                reason.clone(),
                /*recovery_seed*/ None,
                /*recovery_authority*/ None,
            )
            .await;
        self.emit_turn_abort_lifecycle(reason.clone(), turn_context.extension_data.as_ref())
            .await;
        // Let the same terminal ordering as a running task clear queued input
        // only after the durable TurnAborted event has been emitted.
        self.input_queue
            .clear_pending_for_turn_state(turn_state.as_ref())
            .await;
        let clear_outcome = self
            .clear_start_transition_after_abort(&turn_state, &transition_identity)
            .await;
        let StartTransitionClearOutcome::Cleared {
            deferred_idle_cause,
        } = clear_outcome
        else {
            // A stale start future must not publish recovery or wake another
            // turn after its reservation has been replaced or fenced.
            return false;
        };
        if let Some(cause) = deferred_idle_cause {
            self.emit_thread_idle_lifecycle_if_idle_after_start_transition(
                cause,
                &transition_identity,
            )
            .await;
        }
        self.publish_recovery_seed_after_terminal(
            abort_outcome.recovery_seed,
            abort_outcome.task_quiesced,
            abort_outcome.terminal_persistence_generation,
        )
        .await;
        true
    }

    /// Claims an exact host-owned transition for detached cleanup after its
    /// owner future disappeared.  An external abort may already have stored a
    /// stronger reason; otherwise cancellation is represented as Interrupted.
    #[expect(
        clippy::expect_used,
        reason = "the dropped transition identity is checked before its retained abort reason is consumed"
    )]
    async fn abort_dropped_start_transition(
        self: &Arc<Self>,
        cleanup_owner: &mut StartTransitionCleanupOwner,
        fallback_reason: TurnAbortReason,
    ) {
        // Clone every witness field before the first await.  The owner guard
        // must retain the original payload so cancellation can put it back in
        // the registry cell without borrowing across an await.
        let cleanup = cleanup_owner.cleanup();
        let completion = Arc::clone(&cleanup.completion);
        let turn_state = Arc::clone(&cleanup.turn_state);
        let transition_identity = Arc::clone(&cleanup.transition_identity);
        let task = Arc::clone(&cleanup.task);
        let turn_context = Arc::clone(&cleanup.turn_context);
        let recovery_history_restore = cleanup.recovery_history_restore.clone();
        let reason = {
            let mut active = self.active_turn.lock().await;
            let Some(active_turn) = active.as_mut() else {
                self.finish_start_transition(&transition_identity, &completion);
                return;
            };
            if active_turn.task.is_some()
                || active_turn.start_reservation.is_some()
                || active_turn.task_terminalization.is_some()
                || !Arc::ptr_eq(&active_turn.turn_state, &turn_state)
                || !active_turn
                    .start_transition
                    .as_ref()
                    .is_some_and(|transition| {
                        Arc::ptr_eq(&transition.identity, &transition_identity)
                    })
            {
                self.finish_start_transition(&transition_identity, &completion);
                return;
            }
            let transition = active_turn
                .start_transition
                .as_mut()
                .expect("transition identity was checked above");
            if transition.abort_reason.is_none()
                && transition.request_abort(fallback_reason.clone())
                && matches!(
                    fallback_reason,
                    TurnAbortReason::Interrupted | TurnAbortReason::BudgetLimited
                )
            {
                self.mark_interrupted();
            }
            transition
                .abort_reason
                .clone()
                .expect("dropped transition cleanup stores an abort reason")
        };

        // `abort_unstarted_turn` performs durable/lifecycle writes and awaits
        // several non-idempotent contributors.  Once entered, cancellation
        // may only leave a failed-closed witness for shutdown; it must never
        // replay the path or clear the completion fence speculatively.
        cleanup_owner.mark_side_effects_started();
        let terminalized = self
            .abort_unstarted_turn(
                task,
                turn_context,
                Arc::clone(&turn_state),
                Arc::clone(&transition_identity),
                recovery_history_restore,
                reason.clone(),
            )
            .await;
        if terminalized {
            // Release the exact phase fence before allowing a pending mailbox
            // wakeup to reserve a replacement turn.  Shutdown admission is
            // already closed, so teardown will not self-wake here.
            self.finish_start_transition(&transition_identity, &completion);
            if reason == TurnAbortReason::Interrupted && !self.shutdown_started() {
                self.maybe_start_turn_for_pending_work().await;
            }
        } else {
            self.complete_start_transition_if_not_current(
                &completion,
                &turn_state,
                &transition_identity,
            )
            .await;
        }
    }

    async fn complete_start_transition_if_not_current(
        &self,
        completion: &Arc<StartTransitionCompletion>,
        turn_state: &Arc<Mutex<TurnState>>,
        transition_identity: &Arc<()>,
    ) {
        let active = self.active_turn.lock().await;
        let still_current = active.as_ref().is_some_and(|active_turn| {
            active_turn.task.is_none()
                && active_turn.start_reservation.is_none()
                && active_turn.task_terminalization.is_none()
                && Arc::ptr_eq(&active_turn.turn_state, turn_state)
                && active_turn
                    .start_transition
                    .as_ref()
                    .is_some_and(|transition| {
                        Arc::ptr_eq(&transition.identity, transition_identity)
                    })
        });
        drop(active);
        if !still_current {
            self.finish_start_transition(transition_identity, completion);
        }
    }

    /// Restores a recovery caller's pre-rewind history only while the exact
    /// host-owned start transition still owns the active slot.  The marker is
    /// retained across the history lock await, so a replacement cannot race
    /// the restore; a stale continuation simply abandons its witness.
    #[expect(
        clippy::expect_used,
        clippy::await_holding_invalid_type,
        reason = "the active-turn identity fence spans restoration of the exact recovery history witness"
    )]
    async fn restore_recovery_history_if_current(
        &self,
        turn_state: Option<&Arc<Mutex<TurnState>>>,
        transition_identity: &Arc<()>,
        recovery_history_restore: &mut Option<ContextManager>,
    ) -> bool {
        if recovery_history_restore.is_none() {
            return true;
        }
        let active = self.active_turn.lock().await;
        let Some(active_turn) = active.as_ref() else {
            return false;
        };
        let current = active_turn.task.is_none()
            && active_turn.start_reservation.is_none()
            && active_turn.task_terminalization.is_none()
            && turn_state.is_none_or(|expected| Arc::ptr_eq(&active_turn.turn_state, expected))
            && active_turn
                .start_transition
                .as_ref()
                .is_some_and(|transition| Arc::ptr_eq(&transition.identity, transition_identity));
        if !current {
            return false;
        }
        drop(active);
        let history = recovery_history_restore
            .take()
            .expect("recovery history witness remained present");
        // The witness is intentionally consumed only after the identity check;
        // the actual install is performed below without the active lock.
        self.install_recovery_history_snapshot(history).await;
        true
    }

    /// Clears the host-owned start-transition reservation after its deferred
    /// terminalization has completed.  This is an identity-fenced CAS: a
    /// stale start future must never clear a later reservation, even if the
    /// logical turn id or turn state happens to be reused.
    async fn clear_start_transition_after_abort(
        &self,
        turn_state: &Arc<Mutex<TurnState>>,
        transition_identity: &Arc<()>,
    ) -> StartTransitionClearOutcome {
        let mut active = self.active_turn.lock().await;
        let Some(active_turn) = active.as_mut() else {
            return StartTransitionClearOutcome::Stale;
        };
        if active_turn.task.is_some()
            || active_turn.start_reservation.is_some()
            || active_turn.task_terminalization.is_some()
            || !Arc::ptr_eq(&active_turn.turn_state, turn_state)
            || !active_turn
                .start_transition
                .as_ref()
                .is_some_and(|transition| Arc::ptr_eq(&transition.identity, transition_identity))
        {
            return StartTransitionClearOutcome::Stale;
        }
        let deferred_idle_cause = active_turn
            .start_transition
            .as_mut()
            .and_then(super::state::turn::StartTransition::take_deferred_idle);
        // Keep the marker installed until all terminal side effects above
        // have completed; only this final identity check may release it.
        *active = None;
        StartTransitionClearOutcome::Cleared {
            deferred_idle_cause,
        }
    }

    /// Releases a caller-owned reservation only through its exact handle. An
    /// accepted abort is returned to the owner instead of being silently
    /// dropped; there is no valid turn context yet, so the owner must take the
    /// explicit cancelled-before-context branch.
    pub(crate) async fn release_start_reservation_if_current(
        &self,
        handle: &StartReservationHandle,
    ) -> StartReservationRelease {
        let mut active = self.active_turn.lock().await;
        Self::release_start_reservation_if_current_locked(&mut active, handle)
    }

    #[expect(
        clippy::expect_used,
        reason = "the reservation is consumed only after its exact identity and turn-state checks"
    )]
    fn release_start_reservation_if_current_locked(
        active: &mut Option<ActiveTurn>,
        handle: &StartReservationHandle,
    ) -> StartReservationRelease {
        let Some(active_turn) = active.as_mut() else {
            return StartReservationRelease::Stale;
        };
        if active_turn.task.is_some()
            || active_turn.start_transition.is_some()
            || active_turn.task_terminalization.is_some()
        {
            return StartReservationRelease::Stale;
        }
        let Some(reservation) = active_turn.start_reservation.as_ref() else {
            return StartReservationRelease::Stale;
        };
        if reservation.turn_id != handle.turn_id
            || !Arc::ptr_eq(&reservation.identity, &handle.identity)
            || !Arc::ptr_eq(&active_turn.turn_state, &handle.turn_state)
        {
            return StartReservationRelease::Stale;
        }
        let reservation = active_turn
            .start_reservation
            .take()
            .expect("reservation remained present after identity check");
        *active = None;
        match reservation.abort_reason {
            Some(reason) => StartReservationRelease::AbortRequested(reason),
            None => StartReservationRelease::Released,
        }
    }

    async fn handle_task_abort(
        self: &Arc<Self>,
        task: &mut RunningTask,
        reason: TurnAbortReason,
        recovery_seed: Option<RecoverySeed>,
        recovery_authority: Option<Arc<TurnRecoveryAuthority>>,
    ) -> TaskAbortOutcome {
        let sub_id = task.turn_context.sub_id.clone();
        // The caller already persisted Unready while holding the active-turn
        // lock and left a reservation installed. Every controlled side effect
        // below therefore happens after durable revocation and before the
        // session can be observed as idle.
        if task.cancellation_token.is_cancelled() {
            if let Some(authority) = recovery_authority.as_ref() {
                let mut state = authority.state.lock().await;
                authority.ready.store(false, Ordering::Release);
                state.ready_persistence_failure_generation = None;
                state.poisoned = true;
            }
            return TaskAbortOutcome::default();
        }

        self.pending_user_message_admissions
            .complete_task_end(&sub_id);
        trace!(task_kind = ?task.kind, sub_id, "aborting running task");
        task.cancellation_token.cancel();
        if reason == TurnAbortReason::Interrupted
            && task
                .turn_context
                .config
                .features
                .enabled(Feature::CodeModeInterrupt)
        {
            self.services
                .code_mode_service
                .interrupt_active_cells()
                .await;
        }
        task.turn_context
            .turn_metadata_state
            .cancel_git_enrichment_task();
        let session_task = Arc::clone(&task.task);

        let mut task_quiesced = select! {
            _ = task.done.notified() => {
                true
            },
            _ = tokio::time::sleep(Duration::from_millis(GRACEFULL_INTERRUPTION_TIMEOUT_MS)) => {
                warn!("task {sub_id} didn't complete gracefully after {}ms", GRACEFULL_INTERRUPTION_TIMEOUT_MS);
                false
            }
        };

        task.handle.abort();
        if !task_quiesced {
            task_quiesced = tokio::time::timeout(
                Duration::from_millis(GRACEFULL_INTERRUPTION_TIMEOUT_MS),
                async {
                    while !task.handle.is_finished() {
                        tokio::task::yield_now().await;
                    }
                },
            )
            .await
            .is_ok();
        }

        session_task
            .abort(Arc::clone(self), Arc::clone(&task.turn_context))
            .await;

        // The task runner deliberately skips `on_task_finished` after the
        // cancellation token is set.  That is the right ownership boundary
        // for an abort, but it also means the runner's ordinary pre-terminal
        // rollout barrier is no longer available to persist output produced
        // immediately before cancellation.  Recovery authority has already
        // been revoked by the caller before entering this method, so this
        // barrier is now safe and preserves the normal abort durability
        // ordering: task output, interrupted marker, then TurnAborted.
        if let Err(err) = self.flush_rollout().await {
            warn!("failed to flush rollout before terminalizing aborted turn: {err}");
        }

        if reason == TurnAbortReason::Interrupted
            && let Some(marker) = interrupted_turn_history_marker(
                InterruptedTurnHistoryMarker::from_config_and_version(
                    task.turn_context.config.as_ref(),
                    task.turn_context.multi_agent_version,
                ),
            )
        {
            self.record_conversation_items(
                task.turn_context.as_ref(),
                std::slice::from_ref(&marker),
            )
            .await;
            // Ensure the marker is durably visible before emitting TurnAborted: some clients
            // synchronously re-read the rollout on receipt of the abort event.
            if let Err(err) = self.flush_rollout().await {
                warn!("failed to flush interrupted-turn marker before emitting TurnAborted: {err}");
            }
        }

        let started_at = task
            .turn_context
            .turn_timing_state
            .started_at_unix_secs()
            .await;
        let (completed_at, duration_ms, profile) = task
            .turn_context
            .turn_timing_state
            .complete_profile_and_duration_ms()
            .await;
        self.services
            .analytics_events_client
            .track_turn_profile(TurnProfileFact {
                turn_id: task.turn_context.sub_id.clone(),
                profile,
            });
        let event = EventMsg::TurnAborted(TurnAbortedEvent {
            turn_id: Some(task.turn_context.sub_id.clone()),
            reason,
            started_at,
            completed_at,
            duration_ms,
        });
        let terminal_persistence_generation = self
            .send_terminal_event_and_flush(task.turn_context.as_ref(), event)
            .await;
        self.services
            .guardian_rejection_circuit_breaker
            .lock()
            .await
            .clear_turn(&task.turn_context.sub_id);
        TaskAbortOutcome {
            task_quiesced,
            terminal_persistence_generation,
            recovery_seed,
        }
    }
}

fn qualification_admission_identity(
    thread_scope_key: &str,
    input: &[TurnInput],
) -> Option<QualificationTurnAdmissionIdentity> {
    let mut user_input = None;
    for item in input {
        if matches!(item, TurnInput::InterAgentCommunication(_)) {
            // A user message mixed with mailbox/inter-agent input is not a
            // single client admission.  Keep qualification identity inert
            // rather than binding the wrong source to the provider turn.
            return None;
        }
        let TurnInput::UserInput { content, client_id } = item else {
            continue;
        };
        if content.is_empty() || client_id.is_none() || user_input.is_some() {
            return None;
        }
        user_input = Some((content.as_slice(), client_id.as_deref()?));
    }
    let (content, client_id) = user_input?;
    let payload_sha256 = user_input_payload_sha256(content).ok()?;
    QualificationTurnAdmissionIdentity::new(
        thread_scope_key.to_string(),
        client_id.to_string(),
        payload_sha256,
    )
}

#[cfg(test)]
#[path = "mod_tests.rs"]
mod tests;
