//! Bounded first-failure evidence for the original observation lane. This is
//! diagnostic state only: it cannot authorize, refresh, clear or resume a feed.
//! Static stages and scalar timings exclude authority payloads and secrets.
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) struct ObservationFailure {
    pub stage: &'static str,
    pub now_ns: Option<u64>,
    pub started_ns: Option<u64>,
    pub ended_ns: Option<u64>,
    pub previous_started_ns: Option<u64>,
    pub previous_checked_ns: Option<u64>,
    pub projected_unix_ms: Option<u64>,
    pub anchor_boottime_ns: Option<u64>,
    pub anchor_unix_ms: Option<u64>,
    pub observed_unix_ms: Option<u64>,
    pub ceiling_unix_ms: Option<u64>,
    pub lease_expires_unix_ms: Option<u64>,
    pub duration_ns: Option<u64>,
    pub os_error: Option<i32>,
    pub io_error_kind: Option<std::io::ErrorKind>,
    pub poll_result: Option<i32>,
    pub poll_revents: Option<i16>,
}

#[derive(Default)]
pub(super) struct ObservationDiagnostics {
    first: OnceLock<ObservationFailure>,
    claimed: AtomicBool,
}
impl ObservationDiagnostics {
    pub(super) fn record(&self, failure: ObservationFailure) {
        // Only one publisher may enter OnceLock::set; other failures never
        // wait for it. A preempted publisher can temporarily leave first() None.
        // Recording never waits; authority decisions cannot inspect this state.
        if self
            .claimed
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            let _ = self.first.set(failure);
        }
    }
    pub(super) fn first(&self) -> Option<ObservationFailure> {
        self.first.get().copied()
    }
}
