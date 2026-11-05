use super::NetworkApprovalService;
use std::sync::TryLockError;
use tokio::time::Instant;

impl NetworkApprovalService {
    /// Attempts exact-execution cleanup without waiting for the call-state lock.
    /// The existing deadline gates mutation and confirmation; it does not make
    /// synchronous work preemptible. A false result leaves the
    /// caller responsible for retaining its process entry, even if synchronous
    /// removal completed just as the deadline elapsed.
    pub(crate) fn try_unregister_call_until(
        &self,
        registration_id: &str,
        deadline: Instant,
    ) -> bool {
        if Instant::now() >= deadline {
            return false;
        }
        let mut calls = match self.calls.try_lock() {
            Ok(calls) => calls,
            Err(TryLockError::Poisoned(error)) => error.into_inner(),
            Err(TryLockError::WouldBlock) => return false,
        };
        if Instant::now() >= deadline {
            return false;
        }
        calls.active_calls.shift_remove(registration_id);
        calls.call_outcomes.remove(registration_id);
        Instant::now() < deadline
    }
}
