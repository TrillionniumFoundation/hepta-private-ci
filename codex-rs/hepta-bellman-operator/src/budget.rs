//! Shared absolute resource budget and cooperative cancellation for bounded
//! operator construction.
//!
//! `FitContextV1` is the explicit cloneable propagation object for worker
//! threads and blocking pools. Installing the same context in each worker shares
//! one monotonic cancellation token, one elapsed-time origin, one cumulative
//! operation ledger, and one concurrent estimated-memory ceiling. The legacy
//! `with_work_control_v1` helper preserves an already installed context when it
//! belongs to the same cancellation domain.

use std::cell::RefCell;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
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

    const fn is_valid(self) -> bool {
        self.max_operations != 0 && self.max_estimated_bytes != 0 && self.max_elapsed_micros != 0
    }

    const fn is_no_larger_than(self, bound: Self) -> bool {
        self.max_operations <= bound.max_operations
            && self.max_estimated_bytes <= bound.max_estimated_bytes
            && self.max_elapsed_micros <= bound.max_elapsed_micros
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

    fn shares_cancellation_domain(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.cancelled, &other.cancelled)
    }
}

#[derive(Debug, Default)]
struct FitBudgetLedger {
    bound: Mutex<Option<OperatorResourceBudgetV1>>,
    operations: AtomicU64,
    reserved_bytes: AtomicU64,
    peak_reserved_bytes: AtomicU64,
}

impl FitBudgetLedger {
    fn bind(
        &self,
        requested: OperatorResourceBudgetV1,
    ) -> Result<OperatorResourceBudgetV1, OperatorWorkErrorV1> {
        if !requested.is_valid() {
            return Err(OperatorWorkErrorV1::InvalidBudget);
        }
        let mut bound = self
            .bound
            .lock()
            .map_err(|_| OperatorWorkErrorV1::BudgetStatePoisoned)?;
        match *bound {
            Some(existing) if requested.is_no_larger_than(existing) => Ok(existing),
            Some(existing) => Err(OperatorWorkErrorV1::BudgetExpansion {
                bound: existing,
                requested,
            }),
            None => {
                *bound = Some(requested);
                Ok(requested)
            }
        }
    }

    fn bound(&self) -> Result<OperatorResourceBudgetV1, OperatorWorkErrorV1> {
        self.bound
            .lock()
            .map_err(|_| OperatorWorkErrorV1::BudgetStatePoisoned)?
            .as_ref()
            .copied()
            .ok_or(OperatorWorkErrorV1::InvalidBudget)
    }

    fn preflight_operations(&self, required: u64) -> Result<(), OperatorWorkErrorV1> {
        let bound = self.bound()?;
        let current = self.operations.load(Ordering::Acquire);
        let total = current
            .checked_add(required)
            .ok_or(OperatorWorkErrorV1::Arithmetic)?;
        if total > bound.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: total,
                limit: bound.max_operations,
            });
        }
        Ok(())
    }

    fn consume_operations(&self, amount: u64) -> Result<(), OperatorWorkErrorV1> {
        let bound = self.bound()?;
        let update = self
            .operations
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current
                    .checked_add(amount)
                    .filter(|next| *next <= bound.max_operations)
            });
        match update {
            Ok(_) => Ok(()),
            Err(current) => Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: current.saturating_add(amount),
                limit: bound.max_operations,
            }),
        }
    }

    fn reserve_bytes(&self, amount: u64) -> Result<(), OperatorWorkErrorV1> {
        if amount == 0 {
            return Ok(());
        }
        let bound = self.bound()?;
        let update =
            self.reserved_bytes
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                    current
                        .checked_add(amount)
                        .filter(|next| *next <= bound.max_estimated_bytes)
                });
        match update {
            Ok(previous) => {
                let total = previous
                    .checked_add(amount)
                    .ok_or(OperatorWorkErrorV1::Arithmetic)?;
                self.peak_reserved_bytes.fetch_max(total, Ordering::AcqRel);
                Ok(())
            }
            Err(current) => Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::EstimatedBytes,
                required: current.saturating_add(amount),
                limit: bound.max_estimated_bytes,
            }),
        }
    }

    fn release_bytes(&self, amount: u64) {
        if amount == 0 {
            return;
        }
        let previous = self.reserved_bytes.fetch_sub(amount, Ordering::AcqRel);
        debug_assert!(previous >= amount, "fit memory reservation underflow");
    }

    fn operations(&self) -> u64 {
        self.operations.load(Ordering::Acquire)
    }

    fn peak_reserved_bytes(&self) -> u64 {
        self.peak_reserved_bytes.load(Ordering::Acquire)
    }
}

/// Explicit propagation proof for one bounded fit.
///
/// Clones share cancellation, the same monotonic start instant, cumulative
/// operation consumption and concurrent estimated-memory reservations. A caller
/// moving work to another thread must move a clone and invoke
/// `with_fit_context_v1` there; thread-local state is never assumed to follow a
/// task automatically.
#[derive(Clone, Debug)]
pub struct FitContextV1 {
    control: WorkControlV1,
    started: Instant,
    ledger: Arc<FitBudgetLedger>,
}

impl FitContextV1 {
    #[must_use]
    pub fn new(control: WorkControlV1) -> Self {
        Self {
            control,
            started: Instant::now(),
            ledger: Arc::new(FitBudgetLedger::default()),
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

    /// Return the absolute budget already bound to this fit, if a meter has
    /// started. Later workers may use the same or a stricter local budget but
    /// may never expand this bound.
    pub fn bound_budget(&self) -> Result<Option<OperatorResourceBudgetV1>, OperatorWorkErrorV1> {
        self.ledger
            .bound
            .lock()
            .map(|bound| *bound)
            .map_err(|_| OperatorWorkErrorV1::BudgetStatePoisoned)
    }

    /// Cumulative operation count across every meter installed under this fit.
    #[must_use]
    pub fn consumed_operations(&self) -> u64 {
        self.ledger.operations()
    }

    /// Peak sum of live estimated-memory reservations across participating
    /// meters. Reservations are released when a meter is dropped.
    #[must_use]
    pub fn peak_estimated_bytes(&self) -> u64 {
        self.ledger.peak_reserved_bytes()
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
/// When a caller has already installed a context backed by this exact
/// cancellation token, the operation preserves that context's issuance-time
/// origin and fit-wide budget ledger. A different token creates a nested context
/// and restores the parent on exit. Parallel callers still must install a cloned
/// `FitContextV1` explicitly.
pub fn with_work_control_v1<T>(control: &WorkControlV1, operation: impl FnOnce() -> T) -> T {
    let inherited = ACTIVE_FIT_CONTEXT.with(|slot| slot.borrow().clone());
    if inherited
        .as_ref()
        .is_some_and(|context| context.control.shares_cancellation_domain(control))
    {
        operation()
    } else {
        let context = control.fit_context();
        with_fit_context_v1(&context, operation)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorResourceKindV1 {
    Operations,
    EstimatedBytes,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorWorkErrorV1 {
    InvalidBudget,
    BudgetExpansion {
        bound: OperatorResourceBudgetV1,
        requested: OperatorResourceBudgetV1,
    },
    BudgetStatePoisoned,
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
    context: FitContextV1,
    operations: u64,
    estimated_bytes: u64,
    shared_reserved_bytes: u64,
}

impl OperatorWorkMeter {
    pub(crate) fn new(budget: OperatorResourceBudgetV1) -> Result<Self, OperatorWorkErrorV1> {
        if !budget.is_valid() {
            return Err(OperatorWorkErrorV1::InvalidBudget);
        }
        let context = ACTIVE_FIT_CONTEXT
            .with(|slot| slot.borrow().clone())
            .unwrap_or_else(|| WorkControlV1::default().fit_context());
        context.ledger.bind(budget)?;
        if context.control.is_cancelled() {
            return Err(OperatorWorkErrorV1::Cancelled);
        }
        let meter = Self {
            budget,
            context,
            operations: 0,
            estimated_bytes: 0,
            shared_reserved_bytes: 0,
        };
        meter.checkpoint()?;
        Ok(meter)
    }

    pub(crate) fn preflight_operations(&self, required: u64) -> Result<(), OperatorWorkErrorV1> {
        self.checkpoint()?;
        let local_required = self
            .operations
            .checked_add(required)
            .ok_or(OperatorWorkErrorV1::Arithmetic)?;
        if local_required > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: local_required,
                limit: self.budget.max_operations,
            });
        }
        self.context.ledger.preflight_operations(required)
    }

    pub(crate) fn reserve_total_bytes(&mut self, required: u64) -> Result<(), OperatorWorkErrorV1> {
        self.checkpoint()?;
        if required > self.budget.max_estimated_bytes {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::EstimatedBytes,
                required,
                limit: self.budget.max_estimated_bytes,
            });
        }
        if required > self.shared_reserved_bytes {
            let additional = required
                .checked_sub(self.shared_reserved_bytes)
                .ok_or(OperatorWorkErrorV1::Arithmetic)?;
            self.context.ledger.reserve_bytes(additional)?;
            self.shared_reserved_bytes = required;
        }
        self.estimated_bytes = self.estimated_bytes.max(required);
        Ok(())
    }

    pub(crate) fn consume(&mut self, amount: u64) -> Result<(), OperatorWorkErrorV1> {
        let local = self
            .operations
            .checked_add(amount)
            .ok_or(OperatorWorkErrorV1::Arithmetic)?;
        if local > self.budget.max_operations {
            return Err(OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: local,
                limit: self.budget.max_operations,
            });
        }
        self.context.ledger.consume_operations(amount)?;
        self.operations = local;
        self.checkpoint()
    }

    pub(crate) fn checkpoint(&self) -> Result<(), OperatorWorkErrorV1> {
        if self.context.control.is_cancelled() {
            return Err(OperatorWorkErrorV1::Cancelled);
        }
        let elapsed = self.context.elapsed_micros();
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
            elapsed_micros: self.context.elapsed_micros(),
        })
    }
}

impl Drop for OperatorWorkMeter {
    fn drop(&mut self) {
        self.context
            .ledger
            .release_bytes(self.shared_reserved_bytes);
    }
}

pub(crate) fn checked_u64(value: usize) -> Result<u64, OperatorWorkErrorV1> {
    u64::try_from(value).map_err(|_| OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_mul(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_mul(right)
        .ok_or(OperatorWorkErrorV1::Arithmetic)
}

pub(crate) fn checked_add(left: u64, right: u64) -> Result<u64, OperatorWorkErrorV1> {
    left.checked_add(right)
        .ok_or(OperatorWorkErrorV1::Arithmetic)
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

    fn bounded_budget(max_operations: u64, max_estimated_bytes: u64) -> OperatorResourceBudgetV1 {
        OperatorResourceBudgetV1 {
            max_operations,
            max_estimated_bytes,
            max_elapsed_micros: 1_000_000,
        }
    }

    #[test]
    fn explicit_context_propagates_cancellation_to_worker_thread() {
        let control = WorkControlV1::new();
        let context = control.fit_context();
        let worker_context = context;
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
        let worker_context = context;
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
    fn matching_work_control_preserves_capability_issue_time() {
        let control = WorkControlV1::new();
        let context = control.fit_context();
        context.run(|| {
            let first = OperatorWorkMeter::new(budget(1_000_000)).unwrap();
            thread::sleep(Duration::from_millis(2));
            let second = with_work_control_v1(&control, || {
                OperatorWorkMeter::new(budget(1_000_000)).unwrap()
            });
            assert_eq!(second.context.started, first.context.started);
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
            assert_eq!(second.context.started, first.context.started);
        });
    }

    #[test]
    fn operation_budget_is_cumulative_across_worker_meters() {
        let context = WorkControlV1::new().fit_context();
        let first_context = context.clone();
        thread::spawn(move || {
            first_context.run(|| {
                let mut meter = OperatorWorkMeter::new(bounded_budget(100, 1_024)).unwrap();
                meter.consume(60).unwrap();
            });
        })
        .join()
        .unwrap();
        let second_context = context.clone();
        let error = thread::spawn(move || {
            second_context.run(|| {
                let mut meter = OperatorWorkMeter::new(bounded_budget(100, 1_024)).unwrap();
                meter.consume(41).unwrap_err()
            })
        })
        .join()
        .unwrap();
        assert!(matches!(
            error,
            OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: 101,
                limit: 100,
            }
        ));
        assert_eq!(context.consumed_operations(), 60);
    }

    #[test]
    fn concurrent_memory_reservations_share_one_absolute_ceiling() {
        let context = WorkControlV1::new().fit_context();
        context.run(|| {
            let mut first = OperatorWorkMeter::new(bounded_budget(100, 100)).unwrap();
            first.reserve_total_bytes(60).unwrap();
            let mut second = OperatorWorkMeter::new(bounded_budget(100, 100)).unwrap();
            let error = second.reserve_total_bytes(41).unwrap_err();
            assert!(matches!(
                error,
                OperatorWorkErrorV1::ResourceExhausted {
                    resource: OperatorResourceKindV1::EstimatedBytes,
                    required: 101,
                    limit: 100,
                }
            ));
            drop(first);
            second.reserve_total_bytes(41).unwrap();
        });
        assert_eq!(context.peak_estimated_bytes(), 60);
    }

    #[test]
    fn worker_cannot_expand_an_already_bound_budget() {
        let context = WorkControlV1::new().fit_context();
        context.run(|| {
            drop(OperatorWorkMeter::new(bounded_budget(100, 100)).unwrap());
            assert!(matches!(
                OperatorWorkMeter::new(bounded_budget(101, 100)),
                Err(OperatorWorkErrorV1::BudgetExpansion { .. })
            ));
        });
    }
}
