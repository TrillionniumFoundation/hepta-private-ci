//! Goal wake-ups wait outside the lifecycle callback that owns cleanup.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

use codex_core::CodexThread;
use codex_core::IdleWorkPriority;
use codex_protocol::protocol::AgentStatus;

use super::GoalRuntimeHandle;

struct DeferredContinuation {
    thread: Weak<CodexThread>,
    generation: u64,
    wake: Weak<()>,
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

        let cleanup = thread.pending_turn_cleanup();
        let completion = thread.pending_admission_fence_completion();
        if cleanup.is_some() || completion.is_some() {
            let generation = cleanup.as_ref().map(|(generation, _)| *generation);
            let weak_thread = Arc::downgrade(&thread);
            let mut pending = self
                .inner
                .idle_continuations
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            pending.retain(|wait| wait.wake.strong_count() != 0);
            if generation.is_some_and(|generation| {
                pending
                    .iter()
                    .any(|wait| wait.generation == generation && wait.thread.ptr_eq(&weak_thread))
            }) {
                return Ok(());
            }

            // Core owns the only task and preserves Queue's reserved capacity
            // and priority. Weak runtime/thread references avoid retaining a
            // stopped contributor while its original cleanup owner is pending.
            let runtime = Arc::downgrade(&self.inner);
            let captured_thread = weak_thread.clone();
            let wake = Arc::new(());
            let pending_wake = Arc::downgrade(&wake);
            let completion = completion.unwrap_or_else(|| Box::pin(async {}));
            if let Err(error) = thread.defer_idle_work(
                IdleWorkPriority::AutomaticContinuation,
                completion,
                async move {
                    let _wake = wake;
                    // Queue may have admitted a newer task while Core ordered
                    // this callback. Check the captured generation afterward.
                    if let Some((_, ready)) = cleanup
                        && !ready.await
                    {
                        return;
                    }
                    let (Some(inner), Some(thread)) =
                        (runtime.upgrade(), captured_thread.upgrade())
                    else {
                        return;
                    };
                    if matches!(
                        thread.agent_status().await,
                        AgentStatus::Running
                            | AgentStatus::Interrupted
                            | AgentStatus::Shutdown
                            | AgentStatus::NotFound
                    ) {
                        return;
                    }
                    let runtime = GoalRuntimeHandle { inner };
                    // Continue only this contributor. The normal path retains
                    // the loaded Arc, current goal, permit and admission checks.
                    if let Err(error) = runtime.continue_on_thread(thread).await {
                        tracing::warn!(
                            thread_id = %runtime.thread_id(),
                            %error,
                            "failed to continue active goal after cleanup"
                        );
                    }
                },
            ) {
                tracing::warn!(
                    thread_id = %self.thread_id(),
                    %error,
                    "could not defer idle goal continuation"
                );
                return Ok(());
            }
            if let Some(generation) = generation {
                pending.push(DeferredContinuation {
                    thread: weak_thread,
                    generation,
                    wake: pending_wake,
                });
            }
            return Ok(());
        }

        self.continue_on_thread(thread).await
    }
}
