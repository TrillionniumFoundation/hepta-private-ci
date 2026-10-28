//! Goal wake-ups wait outside the lifecycle callback that owns cleanup.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

use codex_core::CodexThread;
use tokio::task::JoinHandle;

use super::GoalRuntimeHandle;

struct DeferredContinuation {
    thread: Weak<CodexThread>,
    generation: u64,
    task: JoinHandle<()>,
}

#[derive(Default)]
pub(super) struct IdleContinuations(Mutex<Vec<DeferredContinuation>>);

impl GoalRuntimeHandle {
    pub(crate) async fn continue_if_idle(&self) -> Result<(), String> {
        if !self.tools_visible() {
            self.inner.accounting_state.clear_active_goal();
            return Ok(());
        }
        let Some(manager) = self.inner.thread_manager.upgrade() else {
            return Ok(());
        };
        let Ok(thread) = manager.get_thread(self.thread_id()).await else {
            return Ok(());
        };

        if let Some((generation, ready)) = thread.pending_turn_cleanup() {
            let weak_thread = Arc::downgrade(&thread);
            let mut pending = self
                .inner
                .idle_continuations
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            pending.retain(|wait| !wait.task.is_finished());
            if pending
                .iter()
                .any(|wait| wait.generation == generation && wait.thread.ptr_eq(&weak_thread))
            {
                return Ok(());
            }

            // Do not retain the runtime while waiting: its registry owns the
            // JoinHandle, and a task owning the runtime would form a cycle.
            let runtime = Arc::downgrade(&self.inner);
            let captured_thread = weak_thread.clone();
            let task = tokio::spawn(async move {
                if !ready.await {
                    return;
                }
                let (Some(inner), Some(thread)) = (runtime.upgrade(), captured_thread.upgrade())
                else {
                    return;
                };
                let runtime = GoalRuntimeHandle { inner };
                // Continue only this contributor. The normal path rechecks
                // the loaded Arc, current goal, deferral and atomic admission.
                if let Err(error) = runtime.continue_on_thread(thread).await {
                    tracing::warn!(
                        thread_id = %runtime.thread_id(),
                        %error,
                        "failed to continue active goal after cleanup"
                    );
                }
            });
            pending.push(DeferredContinuation {
                thread: weak_thread,
                generation,
                task,
            });
            return Ok(());
        }

        self.continue_on_thread(thread).await
    }
}
