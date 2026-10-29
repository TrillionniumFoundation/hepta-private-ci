use super::QueuedItemService;
use codex_protocol::ThreadId;

impl QueuedItemService {
    pub(super) async fn dispatch_after_pending_admission(&self, thread_id: ThreadId) {
        // This is only a deferred wake. No process lock, dispatch lease, or
        // durable queue mutation is acquired before the read-only barrier.
        // The ordinary dispatch path still owns and settles every admission.
        let Some(manager) = self.thread_manager.upgrade() else {
            return;
        };
        let Ok(thread) = manager.get_thread(thread_id).await else {
            return;
        };
        if let Err(error) = thread.wait_for_pending_admission_transitions().await {
            tracing::warn!(%thread_id, %error, "queue wake could not observe completed admission transitions");
            return;
        }
        let _guard = self.dispatch_guard(thread_id).await;
        if let Err(error) = self.dispatch_if_idle(thread_id).await {
            tracing::warn!(%thread_id, %error, "failed to dispatch queued user input");
        }
    }
}
