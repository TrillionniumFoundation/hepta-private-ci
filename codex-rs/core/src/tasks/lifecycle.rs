use codex_extension_api::ExtensionData;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleContinuations;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::TokenUsage;
use codex_protocol::protocol::TurnAbortReason;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use std::sync::Arc;
use std::sync::atomic::Ordering;

impl Session {
    pub(super) async fn emit_turn_start_lifecycle(
        &self,
        turn_context: &TurnContext,
        token_usage_at_turn_start: &TokenUsage,
        origin: codex_extension_api::TurnStartOrigin,
    ) {
        let collaboration_mode = turn_context.collaboration_mode();
        for contributor in self.services.extensions.turn_lifecycle_contributors() {
            contributor
                .on_turn_start(codex_extension_api::TurnStartInput {
                    turn_id: turn_context.sub_id.as_str(),
                    origin,
                    collaboration_mode: &collaboration_mode,
                    token_usage_at_turn_start,
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                    turn_store: turn_context.extension_data.as_ref(),
                })
                .await;
        }
    }

    pub(super) async fn emit_turn_stop_lifecycle(&self, turn_store: &ExtensionData) {
        for contributor in self.services.extensions.turn_lifecycle_contributors() {
            contributor
                .on_turn_stop(codex_extension_api::TurnStopInput {
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                    turn_store,
                })
                .await;
        }
    }

    pub(crate) async fn emit_thread_idle_lifecycle_if_idle(
        self: &Arc<Self>,
        cause: ThreadIdleCause,
    ) {
        self.emit_thread_idle_lifecycle_if_idle_inner(
            cause, /*terminalization_owner*/ None, /*start_transition_owner*/ None,
            /*allow_shutdown*/ false,
        )
        .await;
    }

    /// A detached start-transition terminalizer may be the last owner of the
    /// turn while shutdown is already latched.  Its idle callback is still a
    /// part of the accepted terminal ordering, so shutdown itself is not a
    /// reason to suppress this exact cleanup-owned emission.
    pub(crate) async fn emit_thread_idle_lifecycle_if_idle_after_start_transition(
        self: &Arc<Self>,
        cause: ThreadIdleCause,
        start_transition_owner: &std::sync::Arc<()>,
    ) {
        self.emit_thread_idle_lifecycle_if_idle_inner(
            cause,
            /*terminalization_owner*/ None,
            Some(start_transition_owner),
            /*allow_shutdown*/ true,
        )
        .await;
    }

    /// Emits idle lifecycle while retaining the caller's own terminalization
    /// completion fence.  External admissions remain fenced; only the exact
    /// owner may progress to the idle callback and subsequent mailbox wake.
    pub(crate) async fn emit_thread_idle_lifecycle_if_idle_for_terminalization(
        self: &Arc<Self>,
        cause: ThreadIdleCause,
        terminalization_owner: Option<&std::sync::Arc<()>>,
    ) {
        self.emit_thread_idle_lifecycle_if_idle_inner(
            cause,
            terminalization_owner,
            /*start_transition_owner*/ None,
            /*allow_shutdown*/ false,
        )
        .await;
    }

    async fn emit_thread_idle_lifecycle_if_idle_inner(
        self: &Arc<Self>,
        cause: ThreadIdleCause,
        terminalization_owner: Option<&std::sync::Arc<()>>,
        start_transition_owner: Option<&std::sync::Arc<()>>,
        allow_shutdown: bool,
    ) {
        if (!allow_shutdown && self.shutdown_started())
            || self.has_pending_task_terminalization_except(terminalization_owner)
            || self.has_pending_start_transition_except(start_transition_owner)
        {
            return;
        }
        let (cause, idle_epoch) = {
            let active_turn = self.active_turn.lock().await;
            if (!allow_shutdown && self.shutdown_started())
                || self.has_pending_task_terminalization_except(terminalization_owner)
                || self.has_pending_start_transition_except(start_transition_owner)
                || active_turn.is_some()
            {
                return;
            }
            let cause = if self.is_interrupted() {
                ThreadIdleCause::Interrupted
            } else {
                cause
            };
            (cause, self.turn_epoch.load(Ordering::Acquire))
        };
        if self.input_queue.has_trigger_turn_mailbox_items().await {
            return;
        }

        if (!allow_shutdown && self.shutdown_started())
            || self.has_pending_task_terminalization_except(terminalization_owner)
            || self.has_pending_start_transition_except(start_transition_owner)
        {
            return;
        }

        let continuations = ThreadIdleContinuations::default();
        for contributor in self.services.extensions.thread_lifecycle_contributors() {
            contributor
                .on_thread_idle(codex_extension_api::ThreadIdleInput {
                    cause,
                    continuations: &continuations,
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                })
                .await;
        }
        // Dropping the handle detaches this future-work notification. It owns no
        // admission capability and cannot outlive the shutdown/epoch checks.
        let _ = self.run_idle_continuations(continuations, idle_epoch);
    }

    pub(super) async fn emit_turn_abort_lifecycle(
        &self,
        reason: TurnAbortReason,
        turn_store: &ExtensionData,
    ) {
        for contributor in self.services.extensions.turn_lifecycle_contributors() {
            contributor
                .on_turn_abort(codex_extension_api::TurnAbortInput {
                    reason: reason.clone(),
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                    turn_store,
                })
                .await;
        }
    }

    pub(crate) async fn emit_turn_error_lifecycle(
        &self,
        turn_context: &TurnContext,
        error: CodexErrorInfo,
    ) {
        for contributor in self.services.extensions.turn_lifecycle_contributors() {
            contributor
                .on_turn_error(codex_extension_api::TurnErrorInput {
                    turn_id: turn_context.sub_id.as_str(),
                    error: error.clone(),
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                    turn_store: turn_context.extension_data.as_ref(),
                })
                .await;
        }
    }
}
