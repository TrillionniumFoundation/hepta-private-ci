//! Existing shutdown state, independent of a windowing toolkit.
use std::time::Duration;
use std::time::Instant;

const SHUTDOWN_GRACE: Duration = Duration::from_secs(150);

#[derive(Default)]
pub(crate) struct Shutdown {
    requested_at: Option<Instant>,
    pub(crate) close_started: bool,
    pub(crate) runtime_closed: bool,
    pub(crate) update_requested: bool,
    pub(crate) failure: Option<String>,
}

impl Shutdown {
    pub(crate) fn requested(&self) -> bool {
        self.requested_at.is_some()
    }

    pub(crate) fn request(&mut self, now: Instant) {
        // Repeated window-close events do not extend the deadline.
        self.requested_at.get_or_insert(now);
    }

    pub(crate) fn check_deadline(&mut self, now: Instant) {
        if !self.runtime_closed
            && self.failure.is_none()
            && self
                .requested_at
                .is_some_and(|start| now.saturating_duration_since(start) >= SHUTDOWN_GRACE)
        {
            self.failure = Some("Shutdown deadline exceeded. Every worker is still owned; no update will activate. Do not replay unknown operations.".to_owned());
            self.update_requested = false;
        }
    }

    pub(crate) fn activation_allowed(&self) -> bool {
        self.runtime_closed && self.update_requested && self.failure.is_none()
    }
}

#[cfg(test)]
#[path = "shutdown_tests.rs"]
mod tests;
