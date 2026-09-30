//! Host-owned interruption of otherwise deterministic recall.
//!
//! A successful controlled call has exactly the same result as its legacy
//! counterpart. Interruption returns an error, never a successful partial
//! packet. A caller cancelling its wait does not release the worker's capacity.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use crate::RecallErrorV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallInterruptionV1 {
    Cancelled,
    DeadlineExceeded,
    WorkLimitExceeded,
}

#[derive(Debug)]
struct WorkState {
    cancelled: AtomicBool,
    remaining: AtomicU64,
}

/// One request's host-supplied deadline and deterministic work ceiling.
/// Clones share cancellation and the remaining budget; cloning cannot renew it.
#[derive(Clone, Debug)]
pub struct RecallWorkControlV1 {
    state: Arc<WorkState>,
    deadline: Option<Instant>,
}

impl RecallWorkControlV1 {
    #[must_use]
    pub fn bounded(deadline: Instant, maximum_checkpoints: u64) -> Self {
        Self {
            state: Arc::new(WorkState {
                cancelled: AtomicBool::new(false),
                remaining: AtomicU64::new(maximum_checkpoints),
            }),
            deadline: Some(deadline),
        }
    }

    /// Only compatibility entrypoints use this; named product callers supply a
    /// bounded control. Existing result bytes are not changed by this adapter.
    pub(crate) fn compatibility() -> Self {
        Self {
            state: Arc::new(WorkState {
                cancelled: AtomicBool::new(false),
                remaining: AtomicU64::new(u64::MAX),
            }),
            deadline: None,
        }
    }

    pub fn cancel(&self) {
        self.state.cancelled.store(true, Ordering::Release);
    }

    pub fn checkpoint(&self) -> Result<(), RecallErrorV1> {
        let reason = if self.state.cancelled.load(Ordering::Acquire) {
            Some(RecallInterruptionV1::Cancelled)
        } else if self
            .deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            Some(RecallInterruptionV1::DeadlineExceeded)
        } else if self
            .state
            .remaining
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |remaining| {
                remaining.checked_sub(1)
            })
            .is_err()
        {
            Some(RecallInterruptionV1::WorkLimitExceeded)
        } else {
            None
        };
        reason.map_or(Ok(()), |reason| Err(RecallErrorV1::Interrupted(reason)))
    }
}

#[cfg(test)]
#[path = "work_tests.rs"]
mod tests;
