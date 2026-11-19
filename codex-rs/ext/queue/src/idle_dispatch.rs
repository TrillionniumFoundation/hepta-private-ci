//! Queue wake-ups wait outside the lifecycle callback that owns cleanup.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

use codex_core::CodexThread;
use codex_core::IdleWorkPriority;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadResumeInput;
use codex_protocol::ThreadId;

use super::QueuedItemService;

struct DeferredIdleDispatch {
    thread: Weak<CodexThread>,
    generation: u64,
    wake: Weak<()>,
}

#[derive(Default)]
pub(super) struct IdleDispatchRegistry(Mutex<HashMap<ThreadId, Vec<DeferredIdleDispatch>>>);

impl<C> ThreadLifecycleContributor<C> for QueuedItemService
where
    C: Send + Sync + 'static,
{
    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) {
                self.resumed_threads
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .insert(thread_id);
            }
        })
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if input.cause == ThreadIdleCause::Interrupted {
                return;
            }
            let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) else {
                tracing::warn!(
                    level_id = input.thread_store.level_id(),
                    "queue extension received an invalid thread id"
                );
                return;
            };
            let Some(manager) = self.thread_manager.upgrade() else {
                return;
            };
            let Ok(thread) = manager.get_thread(thread_id).await else {
                return;
            };
            let cleanup = thread.pending_turn_cleanup();
            let completion = thread.pending_admission_fence_completion();
            if cleanup.is_some() || completion.is_some() {
                let generation = cleanup.as_ref().map(|(generation, _)| *generation);
                let weak_thread = Arc::downgrade(&thread);
                let mut pending = self
                    .idle_dispatches
                    .0
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                pending.retain(|_, waits| {
                    waits.retain(|wait| wait.wake.strong_count() != 0);
                    !waits.is_empty()
                });
                let waits = pending.entry(thread_id).or_default();
                if generation.is_some_and(|generation| {
                    waits.iter().any(|wait| {
                        wait.generation == generation && wait.thread.ptr_eq(&weak_thread)
                    })
                }) {
                    return;
                }
                let service = self.clone();
                let captured_thread = weak_thread.clone();
                let wake = Arc::new(());
                let pending_wake = Arc::downgrade(&wake);
                // Core owns bounded scheduling and priority. The registry only
                // deduplicates this exact thread/generation; its weak token also
                // expires if Core cancels the callback before it is polled.
                let completion = completion.unwrap_or_else(|| Box::pin(async {}));
                if let Err(error) =
                    thread.defer_idle_work(IdleWorkPriority::QueuedInput, completion, async move {
                        let _wake = wake;
                        // Poll the generation witness after Core's ordering
                        // wait, so a newer queued turn invalidates this wake.
                        if let Some((_, ready)) = cleanup
                            && !ready.await
                        {
                            return;
                        }
                        let Some(thread) = captured_thread.upgrade() else {
                            return;
                        };
                        // This path rechecks the loaded Arc under the dispatch
                        // guard, current status and durable atomic admission.
                        service.dispatch_idle_notification(thread_id, thread).await;
                    })
                {
                    tracing::warn!(%thread_id, %error, "could not defer queued idle work");
                    return;
                }
                if let Some(generation) = generation {
                    waits.push(DeferredIdleDispatch {
                        thread: weak_thread,
                        generation,
                        wake: pending_wake,
                    });
                }
                return;
            }
            self.dispatch_idle_notification(thread_id, thread).await;
        })
    }
}
