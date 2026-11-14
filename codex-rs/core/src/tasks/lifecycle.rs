use std::sync::atomic::Ordering;

use codex_extension_api::ExtensionData;
use codex_extension_api::ThreadIdleCause;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::TokenUsage;
use codex_protocol::protocol::TurnAbortReason;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;

#[cfg(test)]
#[path = "idle_ready_tests.rs"]
mod tests;

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

    pub(crate) async fn emit_thread_idle_lifecycle_if_idle(&self, cause: ThreadIdleCause) {
        if let Some((cause, attach_epoch)) = self
            .emit_thread_idle_lifecycle_if_idle_inner(
                cause, /*terminalization_owner*/ None, /*start_transition_owner*/ None,
                /*allow_shutdown*/ false,
            )
            .await
        {
            self.emit_thread_idle_ready_lifecycle_if_idle(cause, attach_epoch)
                .await;
        }
    }

    /// A detached start-transition terminalizer may be the last owner of the
    /// turn while shutdown is already latched.  Its idle callback is still a
    /// part of the accepted terminal ordering, so shutdown itself is not a
    /// reason to suppress this exact cleanup-owned emission.
    pub(crate) async fn emit_thread_idle_lifecycle_if_idle_after_start_transition(
        &self,
        cause: ThreadIdleCause,
        start_transition_owner: &std::sync::Arc<()>,
    ) {
        let _ = self
            .emit_thread_idle_lifecycle_if_idle_inner(
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
        &self,
        cause: ThreadIdleCause,
        terminalization_owner: Option<&std::sync::Arc<()>>,
    ) {
        let _ = self
            .emit_thread_idle_lifecycle_if_idle_inner(
                cause,
                terminalization_owner,
                /*start_transition_owner*/ None,
                /*allow_shutdown*/ false,
            )
            .await;
    }

    async fn emit_thread_idle_lifecycle_if_idle_inner(
        &self,
        cause: ThreadIdleCause,
        terminalization_owner: Option<&std::sync::Arc<()>>,
        start_transition_owner: Option<&std::sync::Arc<()>>,
        allow_shutdown: bool,
    ) -> Option<(ThreadIdleCause, u64)> {
        if (!allow_shutdown && self.shutdown_started())
            || self.has_pending_task_terminalization_except(terminalization_owner)
            || self.has_pending_start_transition_except(start_transition_owner)
        {
            return None;
        }
        let (cause, attach_epoch) = {
            let active_turn = self.active_turn.lock().await;
            if (!allow_shutdown && self.shutdown_started())
                || self.has_pending_task_terminalization_except(terminalization_owner)
                || self.has_pending_start_transition_except(start_transition_owner)
                || active_turn.is_some()
            {
                return None;
            }
            let cause = if self.is_interrupted() {
                ThreadIdleCause::Interrupted
            } else {
                cause
            };
            (cause, self.turn_epoch.load(Ordering::Acquire))
        };
        if self.input_queue.has_trigger_turn_mailbox_items().await {
            return None;
        }

        if (!allow_shutdown && self.shutdown_started())
            || self.has_pending_task_terminalization_except(terminalization_owner)
            || self.has_pending_start_transition_except(start_transition_owner)
        {
            return None;
        }

        for contributor in self.services.extensions.thread_lifecycle_contributors() {
            contributor
                .on_thread_idle(codex_extension_api::ThreadIdleInput {
                    cause,
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                })
                .await;
        }
        Some((cause, attach_epoch))
    }

    /// Re-evaluate extension work only after the exact finishing generation
    /// has released its fence. Each contributor still uses ordinary atomic
    /// admission; a concurrent input is allowed to win that race.
    pub(super) async fn emit_thread_idle_ready_lifecycle_if_idle(
        &self,
        cause: ThreadIdleCause,
        attach_epoch: u64,
    ) {
        for contributor in self.services.extensions.thread_lifecycle_contributors() {
            if self.input_queue.has_trigger_turn_mailbox_items().await {
                return;
            }
            {
                let active_turn = self.active_turn.lock().await;
                if self.shutdown_started()
                    || self.is_interrupted()
                    || cause == ThreadIdleCause::Interrupted
                    || self.has_pending_admission_fence()
                    || active_turn.is_some()
                    || self.turn_epoch.load(Ordering::Acquire) != attach_epoch
                {
                    return;
                }
            }
            contributor
                .on_thread_idle_ready(codex_extension_api::ThreadIdleInput {
                    cause,
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                })
                .await;
        }
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
