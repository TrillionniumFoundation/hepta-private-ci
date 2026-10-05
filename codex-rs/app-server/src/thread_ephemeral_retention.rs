//! Bounded residency for an exact ephemeral Core runtime. This is a live-memory
//! hold, not an execution record, terminal observation or cleanup authority.
use super::ConnectionId;
use super::ThreadId;
use super::ThreadStateManager;
use codex_core::CodexThread;
use std::sync::Arc;
use std::sync::Weak;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::sync::watch;

const MAX_RETAINED_EPHEMERAL_RUNTIMES: usize = 32;

#[cfg(test)]
#[path = "thread_ephemeral_retention_tests.rs"]
mod tests;

#[derive(Clone)]
pub(super) struct RetentionCapacity(Arc<Semaphore>);

impl Default for RetentionCapacity {
    fn default() -> Self {
        Self(Arc::new(Semaphore::new(MAX_RETAINED_EPHEMERAL_RUNTIMES)))
    }
}

struct RetainedRuntime {
    runtime: Weak<CodexThread>,
    operation_id: String,
    _capacity: OwnedSemaphorePermit,
}

pub(super) struct EphemeralRetentionState {
    retained: Option<RetainedRuntime>,
    watcher: watch::Sender<Option<Weak<CodexThread>>>,
}

impl Default for EphemeralRetentionState {
    fn default() -> Self {
        Self {
            retained: None,
            watcher: watch::channel(None).0,
        }
    }
}

impl ThreadStateManager {
    /// Install only a residency hold for the same registered runtime. Ordinary
    /// unsubscribe and disconnect leave this independently visible hold intact.
    pub(crate) async fn retain_ephemeral_runtime(
        &self,
        thread_id: ThreadId,
        runtime: &Arc<CodexThread>,
        connection_id: ConnectionId,
        operation_id: String,
    ) -> Result<(), &'static str> {
        let mut state = self.state.lock().await;
        if !state.live_connections.contains_key(&connection_id) {
            return Err("ephemeral retention connection is closed");
        }
        let entry = state
            .threads
            .get_mut(&thread_id)
            .ok_or("ephemeral runtime has no original listener")?;
        if !entry.connection_ids.contains(&connection_id) {
            return Err("ephemeral retention requires its original subscriber");
        }
        let weak = Arc::downgrade(runtime);
        if let Some(retained) = &entry.ephemeral_retention.retained {
            return if retained.runtime.ptr_eq(&weak) && retained.operation_id == operation_id {
                Ok(())
            } else {
                Err("ephemeral retention belongs to another runtime or operation")
            };
        }
        let permit = self
            .ephemeral_retention_capacity
            .0
            .clone()
            .try_acquire_owned()
            .map_err(|_| "ephemeral retention capacity exhausted")?;
        entry.ephemeral_retention.retained = Some(RetainedRuntime {
            runtime: weak.clone(),
            operation_id,
            _capacity: permit,
        });
        entry.ephemeral_retention.watcher.send_replace(Some(weak));
        Ok(())
    }

    pub(crate) async fn subscribe_to_ephemeral_retention(
        &self,
        thread_id: ThreadId,
    ) -> Option<watch::Receiver<Option<Weak<CodexThread>>>> {
        let state = self.state.lock().await;
        Some(
            state
                .threads
                .get(&thread_id)?
                .ephemeral_retention
                .watcher
                .subscribe(),
        )
    }
}
