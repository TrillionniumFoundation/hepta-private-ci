//! Embedding drain state and cancellation ownership for App Server tasks.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

/// Embedding-owned graceful drain control for one App Server lifetime.
///
/// `drained` observes zero running turns after closing RPC admission. It does
/// not acknowledge task destruction: `completed` additionally requires the
/// non-forced processor exit and successful joins of all outer server tasks.
#[derive(Clone)]
pub struct AppServerDrainHandle {
    request: CancellationToken,
    pub(super) running_turns: Arc<AtomicUsize>,
    pub(super) drained: Arc<AtomicBool>,
    completed: Arc<AtomicBool>,
}

impl AppServerDrainHandle {
    pub fn new() -> Self {
        Self {
            request: CancellationToken::new(),
            running_turns: Arc::new(AtomicUsize::new(0)),
            drained: Arc::new(AtomicBool::new(false)),
            completed: Arc::new(AtomicBool::new(/*v*/ false)),
        }
    }

    pub fn request_drain(&self) {
        // Repeated polls cannot erase completion of this one-shot lifetime.
        self.request.cancel();
    }

    pub fn running_turns(&self) -> usize {
        self.running_turns.load(Ordering::Acquire)
    }

    pub fn drained(&self) -> bool {
        self.drained.load(Ordering::Acquire)
    }

    /// True only after the original server future joined its owned tasks.
    /// Cancellation, a drain acknowledgement, or abort requests are insufficient.
    pub fn completed(&self) -> bool {
        self.completed.load(Ordering::Acquire)
    }

    pub(super) async fn wait_requested(&self) {
        self.request.cancelled().await;
    }

    pub(super) fn observe_running_turns(&self, running_turns: usize) {
        self.running_turns.store(running_turns, Ordering::Release);
    }

    pub(super) fn mark_drained(&self) {
        self.running_turns.store(0, Ordering::Release);
        self.drained.store(true, Ordering::Release);
    }

    pub(super) fn mark_completed(&self) {
        self.completed.store(true, Ordering::Release);
    }
}

impl Default for AppServerDrainHandle {
    fn default() -> Self {
        Self::new()
    }
}

/// Own even handles appended by the existing stdio transport constructor.
/// Drop requests abort; it deliberately issues no completion acknowledgement.
#[derive(Default)]
pub(super) struct OwnedTransportTasks(pub(super) Vec<JoinHandle<()>>);

impl Drop for OwnedTransportTasks {
    fn drop(&mut self) {
        for task in &self.0 {
            task.abort();
        }
    }
}

#[cfg(test)]
#[path = "runtime_lifecycle_tests.rs"]
mod tests;
