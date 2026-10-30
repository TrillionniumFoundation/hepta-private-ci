use super::QueuedItemService;
use codex_async_utils::CoalescingWake;
use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

#[derive(Default)]
struct Observations {
    wakes: HashMap<ThreadId, Weak<CoalescingWake>>,
    rejected: HashMap<ThreadId, (String, String)>,
}

/// Runtime observations only. The durable row and normal admission retain all
/// queue authority. At most one rejected head is remembered per loaded thread.
#[derive(Default)]
pub(super) struct IdleQueueState {
    observations: Mutex<Observations>,
}

impl IdleQueueState {
    fn wake(&self, thread_id: ThreadId) -> Arc<CoalescingWake> {
        let mut observations = self
            .observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        observations
            .wakes
            .retain(|_, wake| wake.strong_count() != 0);
        if let Some(wake) = observations.wakes.get(&thread_id).and_then(Weak::upgrade) {
            return wake;
        }
        let wake = Arc::new(CoalescingWake::default());
        observations.wakes.insert(thread_id, Arc::downgrade(&wake));
        wake
    }

    pub(super) fn rejected(&self, thread_id: ThreadId, item_id: &str, digest: &str) -> bool {
        let mut observations = self
            .observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if observations
            .rejected
            .get(&thread_id)
            .is_some_and(|(id, hash)| id == item_id && hash == digest)
        {
            return true;
        }
        observations.rejected.remove(&thread_id);
        false
    }

    pub(super) fn record_rejection(&self, thread_id: ThreadId, item_id: &str, digest: &str) {
        self.observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .rejected
            .insert(thread_id, (item_id.to_string(), digest.to_string()));
    }

    pub(super) fn clear(&self, thread_id: ThreadId) {
        let mut observations = self
            .observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        observations.wakes.remove(&thread_id);
        observations.rejected.remove(&thread_id);
    }
}

impl QueuedItemService {
    pub(super) async fn schedule_idle_dispatch(&self, thread_id: ThreadId) {
        let Some(manager) = self.thread_manager.upgrade() else {
            return;
        };
        let Ok(thread) = manager.get_thread(thread_id).await else {
            return;
        };
        let wake = self.idle.wake(thread_id);
        if !wake.register_with(|| thread.current_turn_completion_barrier()) {
            return;
        }
        let service = self.clone();
        tokio::spawn(async move {
            while let Some(completion) = wake.next_barrier() {
                completion.await;
                let _guard = service.dispatch_guard(thread_id).await;
                // Re-read queue and lifecycle state after the fence and use
                // ordinary Core admission. No callback awaits its own owner.
                if let Err(error) = service.dispatch_if_idle(thread_id).await {
                    tracing::warn!(%thread_id, %error, "failed to dispatch queued user input");
                }
            }
        });
    }
}
