//! Cancellation and time bounds for read-only current-owner checks.
//!
//! This must never wrap an unjoined subprocess or a durable write: dropping a
//! read releases its locks, but dropping an effect is not proof of terminality.
use std::future::Future;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::SharedMemoryTrainingError;

pub(super) const OWNER_READ_LIMIT: Duration = Duration::from_secs(10);

pub(super) async fn read_owner_phase<T>(
    stop: &CancellationToken,
    limit: Duration,
    read: impl Future<Output = Result<T, SharedMemoryTrainingError>>,
) -> Result<T, SharedMemoryTrainingError> {
    tokio::select! {
        biased;
        _ = stop.cancelled() => Err(SharedMemoryTrainingError::Invalid("memory owner read cancelled")),
        _ = tokio::time::sleep(limit) => Err(SharedMemoryTrainingError::Invalid("memory owner read timed out")),
        result = read => result,
    }
}

#[cfg(test)]
#[path = "memory_serving_owner_wait_tests.rs"]
mod tests;
