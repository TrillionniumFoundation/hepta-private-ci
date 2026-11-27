use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const MAX_DURATION_MILLIS: u64 = 24 * 60 * 60 * 1_000;
const MAX_OPERATIONS: u64 = 2_000_000_000;

/// Host-owned cancellation handle. Cancellation is monotonic and cannot be reset.
#[derive(Clone, Debug)]
pub struct WorkCancellationV1 {
    cancelled: Arc<AtomicBool>,
}

impl WorkCancellationV1 {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

/// Bounded final-use control carried inside a verified training capability.
///
/// The deadline starts when the capability is created, so queueing or retaining
/// a capability consumes its budget rather than silently extending authority.
#[derive(Clone, Debug)]
pub struct WorkControlV1 {
    deadline: Instant,
    max_operations: u64,
    cancelled: Arc<AtomicBool>,
}

impl WorkControlV1 {
    pub fn new(
        max_duration_millis: u64,
        max_operations: u64,
    ) -> Result<(Self, WorkCancellationV1), WorkControlError> {
        if max_duration_millis == 0
            || max_duration_millis > MAX_DURATION_MILLIS
            || max_operations == 0
            || max_operations > MAX_OPERATIONS
        {
            return Err(WorkControlError::InvalidLimits);
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(max_duration_millis))
            .ok_or(WorkControlError::InvalidLimits)?;
        Ok((
            Self {
                deadline,
                max_operations,
                cancelled: Arc::clone(&cancelled),
            },
            WorkCancellationV1 { cancelled },
        ))
    }

    pub fn checkpoint(&self, completed_operations: u64) -> Result<(), WorkControlError> {
        if self.cancelled.load(Ordering::Acquire) {
            return Err(WorkControlError::Cancelled);
        }
        if Instant::now() > self.deadline {
            return Err(WorkControlError::DeadlineExceeded);
        }
        if completed_operations > self.max_operations {
            return Err(WorkControlError::OperationBudgetExceeded);
        }
        Ok(())
    }

    #[must_use]
    pub fn max_operations(&self) -> u64 {
        self.max_operations
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkControlError {
    InvalidLimits,
    Cancelled,
    DeadlineExceeded,
    OperationBudgetExceeded,
}

impl fmt::Display for WorkControlError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WorkControlError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancellation_is_monotonic() {
        let (control, cancellation) = WorkControlV1::new(1_000, 10).unwrap();
        control.checkpoint(10).unwrap();
        cancellation.cancel();
        assert_eq!(control.checkpoint(0), Err(WorkControlError::Cancelled));
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn operation_budget_is_enforced() {
        let (control, _) = WorkControlV1::new(1_000, 10).unwrap();
        assert_eq!(
            control.checkpoint(11),
            Err(WorkControlError::OperationBudgetExceeded)
        );
    }
}
