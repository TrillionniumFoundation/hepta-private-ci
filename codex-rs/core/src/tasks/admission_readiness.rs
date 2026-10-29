//! Read-only observation of already materialized admission transitions.
//!
//! A terminal event precedes the owner's final persistence/recovery/lifecycle
//! work. Observing that event does not itself authorize a new turn. These waits
//! retain only completion witnesses; they never adopt a handoff, clear a marker,
//! release a reservation, or bypass the final atomic admission check.

use crate::session::session::Session;
use crate::state::StartTransitionCompletion;
use codex_extension_api::ThreadIdleContinuations;
use std::sync::Arc;
use std::sync::atomic::Ordering;

impl Session {
    /// Waits for the completion fences present when this future is first polled.
    ///
    /// Later transitions are deliberately not followed: a waiter is not an idle
    /// reservation and cannot claim that the thread is still idle when it wakes.
    /// Cancellation simply drops observer references and leaves every owner and
    /// fence untouched. Callers must keep their existing admission/deadline checks.
    ///
    /// Do not await this from an inline lifecycle callback: that callback can be
    /// owned by one of the fences being observed. Schedule the continuation and
    /// return from the callback before awaiting it.
    pub(crate) async fn wait_for_pending_admission_transitions(&self) {
        wait_for_completions(self.admission_transition_snapshot()).await;
    }

    fn admission_transition_snapshot(&self) -> Vec<Arc<StartTransitionCompletion>> {
        let mut completions = self.pending_start_transition_completions();
        completions.extend(
            self.pending_task_terminalization_completions_except(/*excluded_identity*/ None),
        );
        completions
    }

    pub(super) fn run_idle_continuations(
        self: &Arc<Self>,
        continuations: ThreadIdleContinuations,
        idle_epoch: u64,
    ) -> Option<tokio::task::JoinHandle<()>> {
        let continuations = continuations.take();
        if continuations.is_empty() {
            return None;
        }
        // Capture the old owner before returning to its cleanup driver. Do not
        // chase later transitions or admit any new work on a failed-closed fence.
        let completions = self.admission_transition_snapshot();
        let thread_id = self.thread_id;
        let session = Arc::downgrade(self);
        Some(tokio::spawn(async move {
            if tokio::time::timeout(
                super::TERMINALIZER_WATCHDOG_TIMEOUT,
                wait_for_completions(completions),
            )
            .await
            .is_err()
            {
                tracing::warn!(%thread_id, "idle continuations declined because admission fences remain unfinished");
                return;
            }
            // Queue is registered before goal continuation. Independent spawned
            // tasks would lose that priority; await each registered action here.
            let Some(session) = session.upgrade() else {
                return;
            };
            for continuation in continuations {
                if session.shutdown_started()
                    || session.is_interrupted()
                    || session.turn_epoch.load(Ordering::Acquire) != idle_epoch
                {
                    // An accepted queue turn, an intervening user turn, or a
                    // history mutation retires this idle batch. A later idle
                    // notification owns any subsequent lower-priority work.
                    return;
                }
                continuation.await;
            }
        }))
    }
}

async fn wait_for_completions(completions: Vec<Arc<StartTransitionCompletion>>) {
    for completion in completions {
        completion.wait().await;
    }
}

#[cfg(test)]
#[path = "admission_readiness_tests.rs"]
mod tests;
