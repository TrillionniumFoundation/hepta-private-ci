//! Per-handle clock binding compiled only for tests or explicit test support.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;

use super::LocalLeaseOutbox;

impl LocalLeaseOutbox {
    /// Bind this handle and its future clones to an explicitly controlled clock.
    ///
    /// Call before opening an executor: its stored lease clone then observes
    /// the same Unix seconds. Reopened or separately acquired handles keep the
    /// system clock unless explicitly bound. Journal timestamps are unchanged.
    /// This helper is absent from the default library; the opt-in test feature
    /// is a build convention, not an authority or permission boundary.
    pub fn with_test_clock(mut self, now_unix_seconds: Arc<AtomicU64>) -> Self {
        self.test_clock = Some(now_unix_seconds);
        self
    }
}
