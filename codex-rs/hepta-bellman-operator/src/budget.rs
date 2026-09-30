//! Shared absolute resource budget and cooperative cancellation for bounded
//! operator construction.
//!
//! `FitContextV1` is the explicit cloneable propagation object for worker
//! threads and blocking pools. Installing the same context in each worker shares
//! one monotonic cancellation token and one elapsed-time origin. The legacy
//! `with_work_control_v1` helper remains for synchronous callers and creates a
//! fresh context for that one call; it is not cross-thread propagation.

use std::cell::RefCell;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorResourceBudgetV1 {
    pub max_operations: u64,
    pub max_estimated_bytes: u64,
    pub max_elapsed_micros: u64,
}

impl OperatorResourceBudgetV1 {
    #[must_use]
    pub const fn qualification_default() -> Self {
        Self {
            max_operations: 50_000_000,
            max_estimated_bytes: 256 * 1024 * 1024,
            max_elapsed_micros: 30_000_000,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct WorkControlV1 {
    cancelled: Arc<AtomicBool>,
}

impl WorkControlV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    /// Create an explicit context before dispatching work. Clone and install the
    /// returned value in every worker that participates in the same fit.
    #[must_use]
    pub fn fit_context(&self) -> FitContextV1 {
        FitContextV1::new(self.clone())
    }
}

/// Explicit propagation proof for one bounded fit.
///
/// Clones share cancellation and the same monotonic start instant. A caller
/// moving work to another thread must move a clone and invoke
/// `with_fit_context_v1` there; thread-local state is never assumed to follow a
/// task automatically.
#[derive(Clone, Debug)]
pub struct FitContextV1 {
    control: WorkControlV1,
    started: Instant,
}

impl FitContextV1 {
    #[must_use]
    pub fn new(control: WorkControlV1) -> Self {
        Self {
            control,
            started: Instant::now(),
        }
    }

    #[must_use]
    pub fn control(&self) -> &WorkControlV1 {
        &self.control
    }

    #[must_use]
    pub fn elapsed_micros(&self) -> u64 {
        u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX)
    }

    pub fn run<T>(&self, operation: impl FnOnce() -> T) -> T {
        with_fit_context_v1(self, operation)
    }
}

thread_local! {
    static ACTIVE_FIT_CONTEXT: RefCell<Option<FitContextV1>> = const { RefCell::new(None) };
}

struct FitContextScope {
    previous: Option<FitContextV1>,
}

impl Drop for FitContextScope {
    fn drop(&mut self) {
        let previous = self.previous.take();
        ACTIVE_FIT_CONTEXT.with(|slot| {
            let _ = slot.replace(previous);
        });
    }
}

/// Install an explicit context around one synchronous portion of a fit.
/// Nested scopes restore the previous context even on unwind.
pub fn with_fit_context_v1<T>(context: &FitContextV1, operation: impl FnOnce() -> T) -> T {
    let previous = ACTIVE_FIT_CONTEXT.with(|slot| slot.replace(Some(context.clone())));
    let _scope = FitContextScope { previous };
    operation()
}

/// Execute a composite operation under its caller's active context, or create
/// one context around the entire composite operation when there is no caller
/// context. This keeps build, validation and receipt emission on one absolute
/// elapsed-time origin without overriding explicit cancellation supplied by a
/// parent final-use capability.
pub(crate) fn with_inherited_fit_context_v1<T>(operation: impl FnOnce() -> T) -> T {
    let inherited = ACTIVE_FIT_CONTEXT.with(|slot| slot.borrow().clone());
    if inherited.is_some() {
        operation()
    } else {
        let context = WorkControlV1::new().fit_context();
        with_fit_context_v1(&context, operation)
    }
}

/// Compatibility helper for existing synchronous fitters.
///
/// This creates a new elapsed-time origin at the call boundary. Parallel or
/// deferred callers must instead construct one `FitContextV1` before dispatch
/// and explicitly install a clone in every worker.
pub fn with_work_control_v1<T>(
    control: &WorkControlV1,
    operation: impl FnOnce() -> T,
) -> T {
    let context = control.fit_context();
    with_fit_context_v1(&context, operation)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorResourceKindV1 {
    Operations,
    EstimatedBytes,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorWorkErrorV1 {
    InvalidBudget,
    Cancelled,
    ResourceExhausted {
        resource: OperatorResourceKindV1,
        required: u64,
        limit: u64,
    },
    DeadlineExceeded {
        elapsed_micros: u64,
        limit_micros: u64,
    },
    Arithmetic,
}

impl fmt::Display for OperatorWorkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorWorkErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorWorkSnapshotV1 {
    pub operations: u64,
    pub estimated_bytes: u64,
    pub elapsed_micros: u64,
}

pub(crate) struct OperatorWorkMeter {
    budget: OperatorResourceBudgetV1,
    control: WorkControlV1,
    started: Instant,
    operations: u64,
    estimated_bytes: u64,
}

impl OperatorWorkMeter {
    pub(crate) fn new(
        budget: OperatorResourceBudgetV1,
    ) -> Result<Self, OperatorWorkErrorV1> {
        if budget.max_operations == 0
            || budget.max_estimated_bytes == 0
            || budget.max_elapsed_micros == 0
        {
            return Err(OperatorWorkErrorV1::InvalidBudget);
        }
        let active = ACTIVE_FIT_CONTEXT.with(|slot| slot.borrow().clone());
        let (control, started) = active.map_or_else(
            || (WorkControlV1::default(), Instant::now()),
            |context| (context.control, context.started),
        );
        if control.is_cancelled() {
            return Err(OperatorWorkErrorV1::Cancelled);
        }
        let meter = Self {
            budget,
            control,
            started,
            operations: 0,
            estimated_bytes: 0,
        };
        meter.checkpoint()?;
        Ok(meter)
    }

    pub(crate) fn preflight_operations(
        &self,
        required: u64,
    ) -> Result<(), OperatorWorkErrorV1> {
        self.checkpoint()?;
        if required > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required,
                limit: self.budget.max_operations,
            });
        }
        Ok(())
    }

    pub(crate) fn reserve_total_bytes(
        &mut self,
        required: u64,
    ) -> Result<(), OperatorWorkErrorV1> {
        self.checkpoint()?;
        if required > self.budget.max_estimated_bytes {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::EstimatedBytes,
                required,
                limit: self.budget.max_estimated_bytes,
            });
        }
        self.estimated_bytes = self.estimated_bytes.max(required);
        Ok(())
    }

    pub(crate) fn consume(&mut self, amount: u64) -> Result<(), OperatorWorkErrorV1> {
        self.operations = self
            .operations
            .checked_add(amount)
            .ok_or(OperatorWorkErrorV1::Arithmetic)?;
        if self.operations > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: self.operations,
                limit: self.budget.max_operations,
            });
        }
        self.checkpoint()
    }

    pub(crate) fn checkpoint(&self) -> Result<(), OperatorWorkErrorV1> {
        if self.control.is_cancelled() {
            return Err(OperatorWorkErrorV1::Cancelled);
        }
        let elapsed = u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX);
        if elapsed > self.budget.max_elapsed_micros {
            return Err(OperatorWorkErrorV1::DeadlineExceeded {
                elapsed_micros: elapsed,
                limit_micros: self.budget.max_elapsed_micros,
            });
        }
        Ok(())
    }

    pub(crate) fn finish(&self) -> Result<OperatorWorkSnapshotV1, OperatorWorkErrorV1> {
        self.checkpoint()?;
        Ok(OperatorWorkSnapshotV1 {
            operations: self.operations,
            estimated_bytes: self.estimated_bytes,
            elapsed_micros: u64::try_from(self.started.elapsed().as_micros())
                .unwrap_or(u64::MAX),
        })
    }
}

pub(crate) fn checked_u64(value: usize) -> Result<u64, OperatorWorkErrorV1> {
    u64::try_from(value).map_err(|_| OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_mul(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_mul(right).ok_or(OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_add(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_add(right).ok_or(OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn sort_work(items: usize) -> Result<u64, OperatorWorkErrorV1> {
    if items <= 1 {
        return Ok(0);
    }
    let n = checked_u64(items)?;
    let levels = u64::from(usize::BITS - (items - 1).leading_zeros());
    checked_mul(n, levels)
}

#[cfg(test)]
mod tests {
    use std::thread;
    use std::time::Duration;

    use super::*;

    fn budget(max_elapsed_micros: u64) -> OperatorResourceBudgetV1 {
        OperatorResourceBudgetV1 {
            max_operations: 1_000,
            max_estimated_bytes: 1_024,
            max_elapsed_micros,
        }
    }

    #[test]
    fn explicit_context_propagates_cancellation_to_worker_thread() {
        let control = WorkControlV1::new();
        let context = control.fit_context();
        let worker_context = context.clone();
        control.cancel();
        let rejected = thread::spawn(move || {
            worker_context.run(|| {
                matches!(
                    OperatorWorkMeter::new(budget(1_000_000)),
                    Err(OperatorWorkErrorV1::Cancelled)
                )
            })
        })
        .join()
        .unwrap();
        assert!(rejected);
    }

    #[test]
    fn explicit_context_preserves_one_deadline_across_dispatch_delay() {
        let context = WorkControlV1::new().fit_context();
        thread::sleep(Duration::from_millis(10));
        let worker_context = context.clone();
        let expired = thread::spawn(move || {
            worker_context.run(|| {
                matches!(
                    OperatorWorkMeter::new(budget(1_000)),
                    Err(OperatorWorkErrorV1::DeadlineExceeded { .. })
                )
            })
        })
        .join()
        .unwrap();
        assert!(expired);
    }

    #[test]
    fn nested_context_restores_outer_cancellation_domain() {
        let outer_control = WorkControlV1::new();
        let inner_control = WorkControlV1::new();
        let outer = outer_control.fit_context();
        let inner = inner_control.fit_context();
        outer.run(|| {
            inner.run(|| {
                inner_control.cancel();
                assert!(matches!(
                    OperatorWorkMeter::new(budget(1_000_000)),
                    Err(OperatorWorkErrorV1::Cancelled)
                ));
            });
            assert!(OperatorWorkMeter::new(budget(1_000_000)).is_ok());
        });
    }

    #[test]
    fn inherited_context_spans_composite_suboperations() {
        let context = WorkControlV1::new().fit_context();
        context.run(|| {
            let first = OperatorWorkMeter::new(budget(1_000_000)).unwrap();
            thread::sleep(Duration::from_millis(2));
            let second = with_inherited_fit_context_v1(|| {
                OperatorWorkMeter::new(budget(1_000_000)).unwrap()
            });
            assert!(second.started >= first.started);
            assert_eq!(second.started, first.started);
        });
    }
}
