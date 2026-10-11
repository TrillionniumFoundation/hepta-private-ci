//! Turn-scoped state and active turn metadata scaffolding.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use tokio::sync::Mutex;
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;
use tokio_util::task::AbortOnDropHandle;

use codex_diagnostics::GaugeGuard;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::protocol::TurnEnvironmentSelection;
use codex_protocol::request_permissions::RequestPermissionProfile;
use codex_protocol::request_permissions::RequestPermissionsResponse;
use codex_protocol::request_user_input::RequestUserInputResponse;
use codex_rmcp_client::ElicitationResponse;
use codex_sandboxing::policy_transforms::merge_permission_profiles;
use rmcp::model::RequestId;
use tokio::sync::oneshot;

use crate::agent::control::AgentExecutionGuard;
use crate::mcp_tool_call::McpToolApprovalMetadata;
use crate::session::TurnInputQueue;
use crate::session::turn_context::TurnContext;
use crate::tasks::AnySessionTask;
use codex_protocol::models::AdditionalPermissionProfile;
use codex_protocol::protocol::McpInvocation;
use codex_protocol::protocol::ReviewDecision;
use codex_protocol::protocol::TokenUsage;
use codex_protocol::protocol::TurnAbortReason;

/// Metadata about the currently running turn.
pub(crate) struct ActiveTurn {
    pub(crate) task: Option<RunningTask>,
    pub(crate) turn_state: Arc<Mutex<TurnState>>,
    /// Caller-owned reservation made before a turn context exists. It is
    /// abortable, but cannot itself emit terminal events; the owner must
    /// promote it to `start_transition` once a context is materialized.
    pub(crate) start_reservation: Option<StartReservation>,
    /// Host-owned transition after a context exists and before a
    /// `RunningTask` can be attached. This is deliberately distinct from both
    /// a caller reservation and a plain idle/mutation reservation.
    pub(crate) start_transition: Option<StartTransition>,
    /// Exact owner for the recovery/terminalization phase after a running task
    /// has been claimed by finish or abort. The marker remains installed when
    /// `task` is temporarily absent, so stale idle cleanup cannot mistake the
    /// slot for a fresh idle turn.
    pub(crate) task_terminalization: Option<TaskTerminalization>,
}

#[derive(Clone)]
pub(crate) struct StartReservationHandle {
    pub(crate) identity: Arc<()>,
    pub(crate) turn_id: String,
    pub(crate) turn_state: Arc<Mutex<TurnState>>,
}

pub(crate) struct StartReservation {
    pub(crate) identity: Arc<()>,
    pub(crate) turn_id: String,
    pub(crate) abort_reason: Option<TurnAbortReason>,
}

/// Completion fence for one materialized start transition.  Shutdown and
/// other host-owned abort paths may request interruption while the owner is
/// still inside a lifecycle callback; they must not proceed to thread-stop
/// publication until the exact transition's terminalizer has finished (or
/// failed closed without signalling this fence).
pub(crate) struct StartTransitionCompletion {
    done: AtomicBool,
    notify: Notify,
}

impl StartTransitionCompletion {
    pub(crate) fn new() -> Arc<Self> {
        Arc::new(Self {
            done: AtomicBool::new(false),
            notify: Notify::new(),
        })
    }

    pub(crate) fn complete(&self) {
        self.done.store(true, std::sync::atomic::Ordering::Release);
        // Keep a permit as well as waking current waiters so a waiter that is
        // registered just after the completion cannot lose the signal.
        self.notify.notify_one();
        self.notify.notify_waiters();
    }

    pub(crate) fn is_complete(&self) -> bool {
        self.done.load(std::sync::atomic::Ordering::Acquire)
    }

    pub(crate) async fn wait(&self) {
        while !self.done.load(std::sync::atomic::Ordering::Acquire) {
            // Register the waiter before the second state check. Without
            // `enable`, completion can land after `notified()` is created but
            // before that future is first polled; `notify_one` then spends its
            // permit on one waiter and a second concurrent waiter can sleep
            // forever even though the fence is already complete.
            let notified = self.notify.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if self.done.load(std::sync::atomic::Ordering::Acquire) {
                break;
            }
            notified.await;
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskTerminalizationKind {
    Finish,
    Abort,
    Suspend,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskTerminalizationPhase {
    Claimed,
    Terminalizing,
}

/// Identity-fenced owner for one running task's terminal path. This remains
/// in `ActiveTurn` even after the `RunningTask` is moved into the owner so
/// every stale cleanup path stays fail-closed.
pub(crate) struct TaskTerminalization {
    pub(crate) identity: Arc<()>,
    pub(crate) task_identity: Arc<dyn AnySessionTask>,
    pub(crate) turn_context: Arc<TurnContext>,
    pub(crate) turn_state: Arc<Mutex<TurnState>>,
    pub(crate) attach_epoch: u64,
    pub(crate) kind: TaskTerminalizationKind,
    pub(crate) phase: TaskTerminalizationPhase,
    pub(crate) completion: Arc<StartTransitionCompletion>,
}

pub(crate) struct StartTransition {
    /// Unique identity for one start continuation.  The continuation keeps
    /// this Arc and uses pointer equality at the attach CAS, so a stale
    /// future cannot consume a later transition that happens to reuse a turn
    /// id or turn state.
    pub(crate) identity: Arc<()>,
    pub(crate) turn_id: String,
    pub(crate) abort_reason: Option<TurnAbortReason>,
    /// Signals once the owner or detached terminalizer has finished this
    /// exact transition.  Shutdown waits on this fence before thread-stop
    /// lifecycle publication.
    pub(crate) completion: Arc<StartTransitionCompletion>,
    /// A guardian abort accepted while this transition is still materializing
    /// needs one deferred idle callback.  It lives on the exact transition so
    /// a stale owner cannot transfer the request to a later attempt.
    pub(crate) deferred_idle_cause: Option<codex_extension_api::ThreadIdleCause>,
}

impl StartTransition {
    pub(crate) fn new(turn_id: String, identity: Arc<()>) -> Self {
        Self {
            identity,
            turn_id,
            abort_reason: None,
            completion: StartTransitionCompletion::new(),
            deferred_idle_cause: None,
        }
    }

    fn from_reservation(reservation: StartReservation) -> Self {
        Self {
            identity: reservation.identity,
            turn_id: reservation.turn_id,
            abort_reason: reservation.abort_reason,
            completion: StartTransitionCompletion::new(),
            deferred_idle_cause: None,
        }
    }

    /// Records only the first abort reason.  The active-turn mutex provides
    /// the serialization boundary for concurrent abort callers.
    pub(crate) fn request_abort(&mut self, reason: TurnAbortReason) -> bool {
        if self.abort_reason.is_some() {
            return false;
        }
        self.abort_reason = Some(reason);
        true
    }

    /// Records one deferred idle callback, with an interrupted cause taking
    /// precedence over weaker causes. The active-turn mutex is the CAS fence.
    pub(crate) fn request_deferred_idle(&mut self, cause: codex_extension_api::ThreadIdleCause) {
        self.deferred_idle_cause = Some(match (self.deferred_idle_cause, cause) {
            (Some(codex_extension_api::ThreadIdleCause::Interrupted), _)
            | (_, codex_extension_api::ThreadIdleCause::Interrupted) => {
                codex_extension_api::ThreadIdleCause::Interrupted
            }
            (Some(existing), _) => existing,
            (None, incoming) => incoming,
        });
    }

    pub(crate) fn take_deferred_idle(&mut self) -> Option<codex_extension_api::ThreadIdleCause> {
        self.deferred_idle_cause.take()
    }
}

impl StartReservation {
    pub(crate) fn request_abort(&mut self, reason: TurnAbortReason) -> bool {
        if self.abort_reason.is_some() {
            return false;
        }
        self.abort_reason = Some(reason);
        true
    }
}

impl ActiveTurn {
    /// Reserves an idle slot for one host-owned start caller. The returned
    /// handle is the only authority allowed to promote or release it.
    pub(crate) fn reserve_start(&mut self, turn_id: String) -> Option<StartReservationHandle> {
        if self.task.is_some()
            || self.start_reservation.is_some()
            || self.start_transition.is_some()
            || self.task_terminalization.is_some()
        {
            return None;
        }
        let identity = Arc::new(());
        let handle = StartReservationHandle {
            identity: Arc::clone(&identity),
            turn_id: turn_id.clone(),
            turn_state: Arc::clone(&self.turn_state),
        };
        self.start_reservation = Some(StartReservation {
            identity,
            turn_id,
            abort_reason: None,
        });
        Some(handle)
    }

    /// Promotes a caller reservation to the host-owned transition under the
    /// same active-turn lock. A stale handle cannot consume a later attempt.
    pub(crate) fn promote_start(&mut self, handle: &StartReservationHandle) -> bool {
        if self.task.is_some()
            || self.start_transition.is_some()
            || self.task_terminalization.is_some()
        {
            return false;
        }
        let Some(reservation) = self.start_reservation.take() else {
            return false;
        };
        let matches = reservation.turn_id == handle.turn_id
            && Arc::ptr_eq(&reservation.identity, &handle.identity)
            && Arc::ptr_eq(&self.turn_state, &handle.turn_state);
        if !matches {
            self.start_reservation = Some(reservation);
            return false;
        }
        self.start_transition = Some(StartTransition::from_reservation(reservation));
        true
    }
}

/// Whether mailbox deliveries should still be folded into the current turn.
///
/// State machine:
/// - A turn starts in `CurrentTurn`, so queued child mail can join the next
///   model request for that turn.
/// - After user-visible terminal output is recorded, we switch to `NextTurn`
///   to leave late child mail queued instead of extending an already shown
///   answer.
/// - If the same task later gets explicit same-turn work again (a steered user
///   prompt or a tool call after an untagged preamble), we reopen `CurrentTurn`
///   so that pending child mail is drained into that follow-up request.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) enum MailboxDeliveryPhase {
    /// Incoming mailbox messages can still be consumed by the current turn.
    #[default]
    CurrentTurn,
    /// The current turn already emitted visible final answer text; mailbox
    /// messages should remain queued for a later turn.
    NextTurn,
}

impl Default for ActiveTurn {
    fn default() -> Self {
        Self {
            task: None,
            turn_state: Arc::new(Mutex::new(TurnState::default())),
            start_reservation: None,
            start_transition: None,
            task_terminalization: None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskKind {
    Regular,
    Review,
    Compact,
}

pub(crate) struct RunningTask {
    pub(crate) done: Arc<Notify>,
    pub(crate) kind: TaskKind,
    /// True only for a model turn that may be resumed under the same durable
    /// turn identity. `TaskKind::Regular` is intentionally insufficient here:
    /// standalone shell tasks also use that UI kind.
    pub(crate) recovery_eligible_model_turn: bool,
    /// Task-owned durable recovery state. The atomic bit is the abort-path
    /// authority; the mutex serializes persisted Ready/Unready transitions.
    pub(crate) recovery_authority: Option<Arc<TurnRecoveryAuthority>>,
    /// Epoch minted while this exact task was attached under `active_turn`.
    pub(crate) attach_epoch: u64,
    pub(crate) task: Arc<dyn AnySessionTask>,
    pub(crate) cancellation_token: CancellationToken,
    pub(crate) handle: AbortOnDropHandle<()>,
    pub(crate) turn_context: Arc<TurnContext>,
    pub(crate) _agent_execution_guard: Option<AgentExecutionGuard>,
    pub(crate) _diagnostics_guard: GaugeGuard,
    // Timer recorded when the task drops to capture the full turn duration.
    pub(crate) _timer: Option<codex_otel::Timer>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum DurableRecoveryState {
    Unknown,
    Ready,
    Unready,
    InterruptedConfirmed,
}

#[derive(Debug)]
pub(crate) struct RecoveryAuthorityState {
    pub(crate) generation: u64,
    pub(crate) durable_state: DurableRecoveryState,
    /// Exact best-effort persistence failure generation under which the
    /// current Ready marker became durable. Terminal publication must still
    /// observe this generation; any later swallowed append/flush failure
    /// permanently invalidates that Ready authority.
    pub(crate) ready_persistence_failure_generation: Option<u64>,
    /// Canonical semantic provider request bound to Ready or
    /// InterruptedConfirmed for this exact generation.
    pub(crate) request_fingerprint_sha256: Option<String>,
    /// Exact replay-critical state used to build the bound provider request.
    pub(crate) replay: Option<codex_history::TurnRecoveryReplayV1>,
    pub(crate) poisoned: bool,
}

#[derive(Debug)]
pub(crate) struct TurnRecoveryAuthority {
    pub(crate) ready: AtomicBool,
    pub(crate) state: Mutex<RecoveryAuthorityState>,
}

impl Default for TurnRecoveryAuthority {
    fn default() -> Self {
        Self {
            ready: AtomicBool::new(false),
            state: Mutex::new(RecoveryAuthorityState {
                generation: 0,
                durable_state: DurableRecoveryState::Unknown,
                ready_persistence_failure_generation: None,
                request_fingerprint_sha256: None,
                replay: None,
                poisoned: false,
            }),
        }
    }
}

impl TurnRecoveryAuthority {
    pub(crate) fn resumed_at_unready_generation(generation: u64) -> Self {
        Self {
            ready: AtomicBool::new(false),
            state: Mutex::new(RecoveryAuthorityState {
                generation,
                durable_state: DurableRecoveryState::Unready,
                ready_persistence_failure_generation: None,
                request_fingerprint_sha256: None,
                replay: None,
                poisoned: false,
            }),
        }
    }
}

/// Mutable state for a single turn.
#[derive(Default)]
pub(crate) struct TurnState {
    pending_approvals: HashMap<String, oneshot::Sender<ReviewDecision>>,
    pending_request_permissions: HashMap<String, PendingRequestPermissions>,
    pending_user_input: HashMap<String, oneshot::Sender<RequestUserInputResponse>>,
    pending_elicitations: HashMap<(String, RequestId), oneshot::Sender<ElicitationResponse>>,
    mcp_tool_approval_metadata: HashMap<String, (Option<McpInvocation>, McpToolApprovalMetadata)>,
    pending_dynamic_tools: HashMap<String, oneshot::Sender<DynamicToolResponse>>,
    pub(crate) pending_input: TurnInputQueue,
    mailbox_delivery_phase: MailboxDeliveryPhase,
    granted_permissions_by_environment_id: HashMap<String, AdditionalPermissionProfile>,
    strict_auto_review_enabled: bool,
    pub(crate) tool_calls: u64,
    pub(crate) has_memory_citation: bool,
    pub(crate) token_usage_at_turn_start: TokenUsage,
}

pub(crate) struct PendingRequestPermissions {
    pub(crate) tx_response: oneshot::Sender<RequestPermissionsResponse>,
    pub(crate) requested_permissions: RequestPermissionProfile,
    pub(crate) environment: TurnEnvironmentSelection,
}

impl TurnState {
    pub(crate) fn insert_pending_approval(
        &mut self,
        key: String,
        tx: oneshot::Sender<ReviewDecision>,
    ) -> Option<oneshot::Sender<ReviewDecision>> {
        self.pending_approvals.insert(key, tx)
    }

    pub(crate) fn remove_pending_approval(
        &mut self,
        key: &str,
    ) -> Option<oneshot::Sender<ReviewDecision>> {
        self.pending_approvals.remove(key)
    }

    pub(crate) fn clear_pending_waiters(&mut self) {
        self.pending_approvals.clear();
        self.pending_request_permissions.clear();
        self.pending_user_input.clear();
        self.pending_elicitations.clear();
        self.mcp_tool_approval_metadata.clear();
        self.pending_dynamic_tools.clear();
    }

    pub(crate) fn insert_pending_request_permissions(
        &mut self,
        key: String,
        pending_request_permissions: PendingRequestPermissions,
    ) -> Option<PendingRequestPermissions> {
        self.pending_request_permissions
            .insert(key, pending_request_permissions)
    }

    pub(crate) fn remove_pending_request_permissions(
        &mut self,
        key: &str,
    ) -> Option<PendingRequestPermissions> {
        self.pending_request_permissions.remove(key)
    }

    pub(crate) fn insert_pending_user_input(
        &mut self,
        key: String,
        tx: oneshot::Sender<RequestUserInputResponse>,
    ) -> Option<oneshot::Sender<RequestUserInputResponse>> {
        self.pending_user_input.insert(key, tx)
    }

    pub(crate) fn remove_pending_user_input(
        &mut self,
        key: &str,
    ) -> Option<oneshot::Sender<RequestUserInputResponse>> {
        self.pending_user_input.remove(key)
    }

    pub(crate) fn insert_pending_elicitation(
        &mut self,
        server_name: String,
        request_id: RequestId,
        tx: oneshot::Sender<ElicitationResponse>,
    ) -> Option<oneshot::Sender<ElicitationResponse>> {
        self.pending_elicitations
            .insert((server_name, request_id), tx)
    }

    pub(crate) fn remove_pending_elicitation(
        &mut self,
        server_name: &str,
        request_id: &RequestId,
    ) -> Option<oneshot::Sender<ElicitationResponse>> {
        self.pending_elicitations
            .remove(&(server_name.to_string(), request_id.clone()))
    }

    pub(crate) fn insert_mcp_tool_approval_metadata(
        &mut self,
        call_id: String,
        invocation: Option<McpInvocation>,
        metadata: McpToolApprovalMetadata,
    ) {
        self.mcp_tool_approval_metadata
            .insert(call_id, (invocation, metadata));
    }

    pub(crate) fn mcp_tool_approval_metadata(
        &self,
        call_id: &str,
    ) -> Option<(Option<McpInvocation>, McpToolApprovalMetadata)> {
        self.mcp_tool_approval_metadata.get(call_id).cloned()
    }

    pub(crate) fn insert_pending_dynamic_tool(
        &mut self,
        key: String,
        tx: oneshot::Sender<DynamicToolResponse>,
    ) -> Option<oneshot::Sender<DynamicToolResponse>> {
        self.pending_dynamic_tools.insert(key, tx)
    }

    pub(crate) fn remove_pending_dynamic_tool(
        &mut self,
        key: &str,
    ) -> Option<oneshot::Sender<DynamicToolResponse>> {
        self.pending_dynamic_tools.remove(key)
    }

    pub(crate) fn accept_mailbox_delivery_for_current_turn(&mut self) {
        self.set_mailbox_delivery_phase(MailboxDeliveryPhase::CurrentTurn);
    }

    pub(crate) fn accepts_mailbox_delivery_for_current_turn(&self) -> bool {
        self.mailbox_delivery_phase == MailboxDeliveryPhase::CurrentTurn
    }

    pub(crate) fn set_mailbox_delivery_phase(&mut self, phase: MailboxDeliveryPhase) {
        self.mailbox_delivery_phase = phase;
    }

    pub(crate) fn record_granted_permissions(
        &mut self,
        environment_id: &str,
        permissions: AdditionalPermissionProfile,
    ) {
        let granted_permissions = merge_permission_profiles(
            self.granted_permissions_by_environment_id
                .get(environment_id),
            Some(&permissions),
        );
        if let Some(granted_permissions) = granted_permissions {
            self.granted_permissions_by_environment_id
                .insert(environment_id.to_string(), granted_permissions);
        }
    }

    pub(crate) fn granted_permissions(
        &self,
        environment_id: &str,
    ) -> Option<AdditionalPermissionProfile> {
        self.granted_permissions_by_environment_id
            .get(environment_id)
            .cloned()
    }

    pub(crate) fn enable_strict_auto_review(&mut self) {
        self.strict_auto_review_enabled = true;
    }

    pub(crate) fn strict_auto_review_enabled(&self) -> bool {
        self.strict_auto_review_enabled
    }
}

#[cfg(test)]
mod tests {
    use super::ActiveTurn;
    use super::StartTransition;
    use super::StartTransitionCompletion;
    use codex_extension_api::ThreadIdleCause;
    use codex_protocol::protocol::TurnAbortReason;
    use std::sync::Arc;
    use std::time::Duration;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn start_transition_completion_wakes_all_waiters() {
        let completion = StartTransitionCompletion::new();
        let first = {
            let completion = Arc::clone(&completion);
            tokio::spawn(async move { completion.wait().await })
        };
        let second = {
            let completion = Arc::clone(&completion);
            tokio::spawn(async move { completion.wait().await })
        };

        // Give both waiters a chance to register with Notify before the
        // completion transition. The `enable` call in `wait` also closes the
        // create-but-not-yet-polled race.
        tokio::task::yield_now().await;
        tokio::task::yield_now().await;
        completion.complete();

        tokio::time::timeout(Duration::from_secs(1), async {
            first.await.expect("first completion waiter should finish");
            second
                .await
                .expect("second completion waiter should finish");
        })
        .await
        .expect("all completion waiters must observe the fence");
    }

    #[test]
    fn start_transition_keeps_first_abort_reason() {
        let identity = Arc::new(());
        let mut transition = StartTransition::new("turn-1".to_string(), identity);

        assert!(transition.request_abort(TurnAbortReason::Replaced));
        assert!(!transition.request_abort(TurnAbortReason::Interrupted));
        assert_eq!(transition.abort_reason, Some(TurnAbortReason::Replaced));
    }

    #[test]
    fn start_reservation_promotes_with_first_abort_reason() {
        let mut active = ActiveTurn::default();
        let handle = active
            .reserve_start("turn-1".to_string())
            .expect("idle slot should reserve");
        assert!(
            active
                .start_reservation
                .as_mut()
                .expect("reservation installed")
                .request_abort(TurnAbortReason::Replaced)
        );
        assert!(
            !active
                .start_reservation
                .as_mut()
                .expect("reservation installed")
                .request_abort(TurnAbortReason::Interrupted)
        );

        assert!(active.promote_start(&handle));
        let transition = active
            .start_transition
            .as_ref()
            .expect("promotion installs transition");
        assert_eq!(transition.abort_reason, Some(TurnAbortReason::Replaced));
        assert!(active.start_reservation.is_none());
    }

    #[test]
    fn stale_start_reservation_cannot_promote_a_later_owner() {
        let mut active = ActiveTurn::default();
        let stale = active
            .reserve_start("turn-1".to_string())
            .expect("first reservation");
        active.start_reservation = None;
        let current = active
            .reserve_start("turn-1".to_string())
            .expect("second reservation");

        assert!(!active.promote_start(&stale));
        assert!(active.start_transition.is_none());
        assert!(active.promote_start(&current));
    }

    #[test]
    fn deferred_idle_cause_is_fenced_and_interrupted_wins() {
        let identity = Arc::new(());
        let mut transition = StartTransition::new("turn-1".to_string(), identity);

        transition.request_deferred_idle(ThreadIdleCause::Failed);
        transition.request_deferred_idle(ThreadIdleCause::Completed);
        assert_eq!(
            transition.take_deferred_idle(),
            Some(ThreadIdleCause::Failed)
        );
        assert_eq!(transition.take_deferred_idle(), None);

        transition.request_deferred_idle(ThreadIdleCause::Completed);
        transition.request_deferred_idle(ThreadIdleCause::Interrupted);
        assert_eq!(
            transition.take_deferred_idle(),
            Some(ThreadIdleCause::Interrupted)
        );
    }
}
