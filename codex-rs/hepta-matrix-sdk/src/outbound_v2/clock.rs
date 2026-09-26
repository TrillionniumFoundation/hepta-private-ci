use std::time::Duration;

use tokio::time::Instant;

use super::OutboxDispatchError;

/// One real monotonic clock anchored to the caller's durable wall-clock sample.
///
/// The anchor also permits deterministic fixtures to use a synthetic epoch;
/// elapsed signing, SQLite and transport time is never replaced by row indexes.
/// The protected authority clock remains responsible for grant validity.
pub(super) struct DispatchClock {
    epoch_ms: u64,
    started: Instant,
}

impl DispatchClock {
    pub(super) fn new(epoch_ms: u64) -> Self {
        Self {
            epoch_ms,
            started: Instant::now(),
        }
    }

    pub(super) fn now_ms(&self) -> Result<u64, OutboxDispatchError> {
        let elapsed_ms = u64::try_from(self.started.elapsed().as_millis())
            .map_err(|_| OutboxDispatchError::Invalid)?;
        self.epoch_ms
            .checked_add(elapsed_ms)
            .filter(|value| *value <= i64::MAX as u64)
            .ok_or(OutboxDispatchError::Invalid)
    }

    /// An absolute deadline, not a fresh duration granted after each await.
    /// Reserve one millisecond before the durable lease's exclusive boundary.
    pub(super) fn deadline(&self, lease_until_ms: u64) -> Result<Instant, OutboxDispatchError> {
        let offset = lease_until_ms
            .checked_sub(self.epoch_ms)
            .and_then(|remaining| remaining.checked_sub(1))
            .ok_or(OutboxDispatchError::LeaseExpired)?;
        let deadline = self
            .started
            .checked_add(Duration::from_millis(offset))
            .ok_or(OutboxDispatchError::Invalid)?;
        if deadline <= Instant::now() {
            return Err(OutboxDispatchError::LeaseExpired);
        }
        Ok(deadline)
    }
}

#[cfg(test)]
#[path = "clock_tests.rs"]
mod tests;
