//! One immutable, last-published metrics observation. Only an explicit writer
//! metrics barrier refreshes it. It is never authority, a task-state cache, or
//! permission to retry. Observation age is measured with a monotonic clock.

use codex_hepta_infer_core::durable_control::native::NativeControlMetrics;
use serde::Serialize;
use std::sync::Arc;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Clone, Debug, Serialize)]
pub struct NativePublishedMetrics {
    /// Caller-supplied time used to evaluate expiry counters in this observation.
    pub evaluated_at_unix_ms: u64,
    pub observed_unix_ms: Option<u64>,
    pub metrics: NativeControlMetrics,
    #[serde(skip)]
    published_at: Instant,
}

impl NativePublishedMetrics {
    pub(crate) fn new(metrics: NativeControlMetrics, evaluated_at_unix_ms: u64) -> Arc<Self> {
        Arc::new(Self {
            evaluated_at_unix_ms,
            observed_unix_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .ok()
                .and_then(|value| u64::try_from(value.as_millis()).ok()),
            metrics,
            published_at: Instant::now(),
        })
    }

    pub fn age_millis(&self) -> u64 {
        u64::try_from(self.published_at.elapsed().as_millis()).unwrap_or(u64::MAX)
    }
}
