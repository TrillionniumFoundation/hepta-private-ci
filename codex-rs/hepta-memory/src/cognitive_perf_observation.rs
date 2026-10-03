//! Bounded diagnostic timings, compiled only by `cognitive-perf-observe`.
//!
//! Counters contain no owner data and never participate in admission or receipts.
//! Read snapshots between awaited operations: concurrent snapshots need not be
//! mutually consistent. Process termination cannot run an in-flight guard's Drop.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use serde::Serialize;

const PHASES: [&str; 4] = [
    "projection",
    "admission_schema",
    "admission_budget",
    "commit",
];
static COUNTERS: [Counters; 4] = [const { Counters::new() }; 4];

#[derive(Clone, Copy)]
pub(crate) enum Phase {
    Projection,
    AdmissionSchema,
    AdmissionBudget,
    Commit,
}

struct Counters {
    started: AtomicU64,
    completed: AtomicU64,
    interrupted: AtomicU64,
    elapsed_us: AtomicU64,
    work_units: AtomicU64,
}

impl Counters {
    const fn new() -> Self {
        Self {
            started: AtomicU64::new(0),
            completed: AtomicU64::new(0),
            interrupted: AtomicU64::new(0),
            elapsed_us: AtomicU64::new(0),
            work_units: AtomicU64::new(0),
        }
    }

    fn snapshot(&self, phase: &'static str) -> PhaseObservation {
        PhaseObservation {
            phase,
            started: self.started.load(Ordering::Relaxed),
            completed: self.completed.load(Ordering::Relaxed),
            interrupted: self.interrupted.load(Ordering::Relaxed),
            elapsed_us: self.elapsed_us.load(Ordering::Relaxed),
            work_units: self.work_units.load(Ordering::Relaxed),
        }
    }
}

fn add(counter: &AtomicU64, value: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |old| {
        Some(old.saturating_add(value))
    });
}

/// One fixed phase's process-local diagnostic counters, never a state witness.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PhaseObservation {
    pub phase: &'static str,
    pub started: u64,
    pub completed: u64,
    pub interrupted: u64,
    pub elapsed_us: u64,
    pub work_units: u64,
}

/// Capture bounded counters without resetting concurrent observers.
pub fn snapshot() -> [PhaseObservation; 4] {
    std::array::from_fn(|index| COUNTERS[index].snapshot(PHASES[index]))
}

/// Report only counters accrued after the example's workload began.
pub fn since(baseline: &[PhaseObservation; 4]) -> [PhaseObservation; 4] {
    let current = snapshot();
    std::array::from_fn(|index| {
        let now = current[index];
        let before = baseline[index];
        PhaseObservation {
            phase: PHASES[index],
            started: now.started.saturating_sub(before.started),
            completed: now.completed.saturating_sub(before.completed),
            interrupted: now.interrupted.saturating_sub(before.interrupted),
            elapsed_us: now.elapsed_us.saturating_sub(before.elapsed_us),
            work_units: now.work_units.saturating_sub(before.work_units),
        }
    })
}

pub(crate) struct Guard<'a> {
    counters: &'a Counters,
    start: Instant,
    completed: bool,
}

impl Guard<'_> {
    pub(crate) fn start(phase: Phase) -> Guard<'static> {
        Guard::new(&COUNTERS[phase as usize])
    }

    fn new(counters: &Counters) -> Guard<'_> {
        add(&counters.started, 1);
        Guard {
            counters,
            start: Instant::now(),
            completed: false,
        }
    }

    pub(crate) fn work_unit(&self) {
        add(&self.counters.work_units, 1);
    }

    // Consuming the guard prevents double completion; Drop records it once.
    pub(crate) fn finish(mut self) {
        self.completed = true;
    }

    pub(crate) fn finish_result<T, E>(mut self, result: Result<T, E>) -> Result<T, E> {
        self.completed = result.is_ok();
        result
    }
}

impl Drop for Guard<'_> {
    fn drop(&mut self) {
        let elapsed = u64::try_from(self.start.elapsed().as_micros()).unwrap_or(u64::MAX);
        add(&self.counters.elapsed_us, elapsed);
        add(
            if self.completed {
                &self.counters.completed
            } else {
                &self.counters.interrupted
            },
            1,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use std::future::Future;
    use std::task::Context;
    use std::task::Poll;
    use std::task::Waker;

    #[test]
    fn nested_distinct_phases_finish_once_and_preserve_result() {
        let outer = Counters::new();
        let inner = Counters::new();
        let outer_guard = Guard::new(&outer);
        let inner_guard = Guard::new(&inner);
        inner_guard.work_unit();
        inner_guard.finish();
        assert_eq!(outer_guard.finish_result(Ok::<_, &'static str>(17)), Ok(17));
        assert_eq!(outer.snapshot("outer").completed, 1);
        assert_eq!(inner.snapshot("inner").completed, 1);
        assert_eq!(inner.snapshot("inner").work_units, 1);
        assert_eq!(outer.snapshot("outer").interrupted, 0);
        assert_eq!(inner.snapshot("inner").interrupted, 0);
    }

    #[test]
    fn failed_result_and_cancelled_future_are_not_completed() {
        let failed = Counters::new();
        assert_eq!(
            Guard::new(&failed).finish_result(Err::<(), _>("denied")),
            Err("denied")
        );
        assert_eq!(failed.snapshot("failed").interrupted, 1);
        let cancelled = Counters::new();
        let mut future = Box::pin(async {
            let guard = Guard::new(&cancelled);
            std::future::pending::<()>().await;
            guard.finish();
        });
        assert_eq!(
            future
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop())),
            Poll::Pending
        );
        drop(future);
        let observed = cancelled.snapshot("cancelled");
        assert_eq!(
            (observed.started, observed.completed, observed.interrupted),
            (1, 0, 1)
        );
    }

    #[test]
    fn counters_saturate_and_schema_contains_only_fixed_names_and_numbers()
    -> Result<(), Box<dyn std::error::Error>> {
        let counters = Counters::new();
        counters.work_units.store(u64::MAX - 1, Ordering::Relaxed);
        add(&counters.work_units, 2);
        assert_eq!(counters.work_units.load(Ordering::Relaxed), u64::MAX);
        let encoded = serde_json::to_value(counters.snapshot(PHASES[0]))?;
        assert_eq!(encoded.as_object().map(|object| object.len()), Some(6));
        assert_eq!(encoded["phase"], "projection");
        for name in [
            "started",
            "completed",
            "interrupted",
            "elapsedUs",
            "workUnits",
        ] {
            assert!(encoded[name].is_u64());
        }
        Ok(())
    }
}
