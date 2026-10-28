//! Queue wake-ups wait outside the lifecycle callback that owns cleanup.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

use codex_core::CodexThread;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadResumeInput;
use codex_protocol::ThreadId;
use tokio::task::JoinHandle;

use super::QueuedItemService;

struct DeferredIdleDispatch {
    thread: Weak<CodexThread>,
    generation: u64,
    task: JoinHandle<()>,
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
            if let Some((generation, ready)) = thread.pending_turn_cleanup() {
                let weak_thread = Arc::downgrade(&thread);
                let mut pending = self
                    .idle_dispatches
                    .0
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                pending.retain(|_, waits| {
                    waits.retain(|wait| !wait.task.is_finished());
                    !waits.is_empty()
                });
                let waits = pending.entry(thread_id).or_default();
                if waits
                    .iter()
                    .any(|wait| wait.generation == generation && wait.thread.ptr_eq(&weak_thread))
                {
                    return;
                }
                let service = self.clone();
                let captured_thread = weak_thread.clone();
                let task = tokio::spawn(async move {
                    if !ready.await {
                        return;
                    }
                    let Some(thread) = captured_thread.upgrade() else {
                        return;
                    };
                    let Some(manager) = service.thread_manager.upgrade() else {
                        return;
                    };
                    let Ok(loaded_thread) = manager.get_thread(thread_id).await else {
                        return;
                    };
                    if !Arc::ptr_eq(&thread, &loaded_thread) {
                        return;
                    }
                    // Continue only this queue contributor. Replaying the
                    // global idle lifecycle would repeat other contributors'
                    // side effects. The normal dispatch path still checks
                    // all current ownership and durable admission conditions.
                    let _guard = service.dispatch_guard(thread_id).await;
                    if let Err(error) = service.dispatch_if_idle(thread_id).await {
                        tracing::warn!(%thread_id, %error, "failed to dispatch queued user input after cleanup");
                    }
                });
                waits.push(DeferredIdleDispatch {
                    thread: weak_thread,
                    generation,
                    task,
                });
                return;
            }
            let _guard = self.dispatch_guard(thread_id).await;
            if let Err(error) = self.dispatch_if_idle(thread_id).await {
                tracing::warn!(%thread_id, %error, "failed to dispatch queued user input");
            }
        })
    }
}
