//! Bounded scheduling only: never grants authority or alters operation state.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::AgentdError;

#[derive(Debug, Default)]
pub(super) struct ReconcileSchedule {
    next: AtomicUsize,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct ReconcilePlan {
    pub(super) start: usize,
    pub(super) quotas: Vec<usize>,
}

impl ReconcileSchedule {
    pub(super) fn reserve(
        &self,
        destination_count: usize,
        limit: usize,
    ) -> Result<ReconcilePlan, AgentdError> {
        if !(1..=256).contains(&limit) {
            return Err(AgentdError::Protocol(
                "production operation reconcile limit must be 1..=256".to_string(),
            ));
        }
        if destination_count == 0 {
            return Err(AgentdError::Protocol(
                "production final-use outbox dispatcher is not explicitly attached".to_string(),
            ));
        }
        // Advance before any observer await. Even if the first observer errors
        // or the caller cancels, a later call begins at the next destination.
        // Advance one start position, not the whole reserved batch: an error
        // must not repeatedly skip the same unattempted tail.
        let start = self
            .next
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |next| {
                Some((next % destination_count + 1) % destination_count)
            })
            .expect("reconciliation rotation always advances")
            % destination_count;
        let selected = destination_count.min(limit);
        let per_destination = limit / selected;
        let extra = limit % selected;
        let quotas = (0..selected)
            .map(|position| per_destination + usize::from(position < extra))
            .collect();
        Ok(ReconcilePlan { start, quotas })
    }
}

#[cfg(test)]
#[path = "production_reconcile_schedule_tests.rs"]
mod tests;
