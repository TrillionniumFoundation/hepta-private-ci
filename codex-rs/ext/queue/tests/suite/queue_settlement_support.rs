use anyhow::Context;
use codex_core::CodexThread;
use codex_extension_api::ExtensionEventSink;
use codex_extension_api::ExtensionWarning;
use codex_protocol::ThreadId;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_queue_extension::QueuedItemService;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;

pub(super) struct QueueSettlementSink {
    thread_id: ThreadId,
    observed_change: AtomicBool,
    changed: Notify,
}

impl QueueSettlementSink {
    pub(super) fn new(thread_id: ThreadId) -> Self {
        Self {
            thread_id,
            observed_change: AtomicBool::new(false),
            changed: Notify::new(),
        }
    }

    pub(super) async fn wait_for_empty(&self, service: &QueuedItemService) -> anyhow::Result<()> {
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                let changed = self.changed.notified();
                tokio::pin!(changed);
                // Register before reading the durable queue so a transition
                // between the read and the await cannot lose its notification.
                changed.as_mut().enable();
                if self.observed_change.load(Ordering::Acquire)
                    && service.list(self.thread_id).await?.is_empty()
                {
                    return anyhow::Ok(());
                }
                changed.await;
            }
        })
        .await
        .context("queue did not become empty after a matching thread queue change")??;
        Ok(())
    }
}

impl ExtensionEventSink for QueueSettlementSink {
    fn emit(&self, event: Event) {
        if matches!(
            event.msg,
            EventMsg::ThreadQueueChanged(change) if change.thread_id == self.thread_id
        ) {
            self.observed_change.store(true, Ordering::Release);
            self.changed.notify_waiters();
        }
    }

    fn emit_warning(&self, _warning: ExtensionWarning) {}
}

pub(super) async fn wait_for_completed_turn(thread: &CodexThread) -> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let (event, completion) = thread.next_event_with_completion().await?;
            if matches!(event.msg, EventMsg::TurnComplete(_)) {
                completion.await;
                return anyhow::Ok(());
            }
        }
    })
    .await
    .context("queued turn did not retire its completion owner")??;
    Ok(())
}
