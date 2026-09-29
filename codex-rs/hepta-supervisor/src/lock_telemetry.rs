use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

const DEFAULT_SLOW_WAIT: Duration = Duration::from_millis(5);
const DEFAULT_SLOW_HOLD: Duration = Duration::from_millis(25);

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LockTelemetrySnapshot {
    pub acquisitions: u64,
    pub contended_acquisitions: u64,
    pub total_wait_ns: u64,
    pub max_wait_ns: u64,
    pub slow_waits: u64,
    pub total_hold_ns: u64,
    pub max_hold_ns: u64,
    pub slow_holds: u64,
}

impl LockTelemetrySnapshot {
    pub fn delta(self, earlier: Self) -> Self {
        Self {
            acquisitions: self.acquisitions.saturating_sub(earlier.acquisitions),
            contended_acquisitions: self
                .contended_acquisitions
                .saturating_sub(earlier.contended_acquisitions),
            total_wait_ns: self.total_wait_ns.saturating_sub(earlier.total_wait_ns),
            max_wait_ns: self.max_wait_ns,
            slow_waits: self.slow_waits.saturating_sub(earlier.slow_waits),
            total_hold_ns: self.total_hold_ns.saturating_sub(earlier.total_hold_ns),
            max_hold_ns: self.max_hold_ns,
            slow_holds: self.slow_holds.saturating_sub(earlier.slow_holds),
        }
    }
}

#[derive(Debug)]
struct LockTelemetry {
    acquisitions: AtomicU64,
    contended_acquisitions: AtomicU64,
    total_wait_ns: AtomicU64,
    max_wait_ns: AtomicU64,
    slow_waits: AtomicU64,
    total_hold_ns: AtomicU64,
    max_hold_ns: AtomicU64,
    slow_holds: AtomicU64,
}

impl LockTelemetry {
    const fn new() -> Self {
        Self {
            acquisitions: AtomicU64::new(0),
            contended_acquisitions: AtomicU64::new(0),
            total_wait_ns: AtomicU64::new(0),
            max_wait_ns: AtomicU64::new(0),
            slow_waits: AtomicU64::new(0),
            total_hold_ns: AtomicU64::new(0),
            max_hold_ns: AtomicU64::new(0),
            slow_holds: AtomicU64::new(0),
        }
    }

    fn snapshot(&self) -> LockTelemetrySnapshot {
        LockTelemetrySnapshot {
            acquisitions: self.acquisitions.load(Ordering::Relaxed),
            contended_acquisitions: self.contended_acquisitions.load(Ordering::Relaxed),
            total_wait_ns: self.total_wait_ns.load(Ordering::Relaxed),
            max_wait_ns: self.max_wait_ns.load(Ordering::Relaxed),
            slow_waits: self.slow_waits.load(Ordering::Relaxed),
            total_hold_ns: self.total_hold_ns.load(Ordering::Relaxed),
            max_hold_ns: self.max_hold_ns.load(Ordering::Relaxed),
            slow_holds: self.slow_holds.load(Ordering::Relaxed),
        }
    }

    fn record_wait(&self, wait: Duration, contended: bool, slow_wait: Duration, name: &str) {
        let wait_ns = duration_ns(wait);
        self.acquisitions.fetch_add(1, Ordering::Relaxed);
        if contended {
            self.contended_acquisitions.fetch_add(1, Ordering::Relaxed);
        }
        self.total_wait_ns.fetch_add(wait_ns, Ordering::Relaxed);
        update_max(&self.max_wait_ns, wait_ns);
        if wait >= slow_wait {
            self.slow_waits.fetch_add(1, Ordering::Relaxed);
            eprintln!(
                "runtime.supervisor mutex slow_wait name={name} wait_ns={wait_ns} contended={contended}"
            );
        }
    }

    fn record_hold(&self, hold: Duration, slow_hold: Duration, name: &str) {
        let hold_ns = duration_ns(hold);
        self.total_hold_ns.fetch_add(hold_ns, Ordering::Relaxed);
        update_max(&self.max_hold_ns, hold_ns);
        if hold >= slow_hold {
            self.slow_holds.fetch_add(1, Ordering::Relaxed);
            eprintln!(
                "runtime.supervisor mutex slow_hold name={name} hold_ns={hold_ns}"
            );
        }
    }
}

/// A Tokio mutex that measures acquisition wait time and guard hold time.
///
/// It deliberately preserves one global serialization boundary. The telemetry
/// exists to qualify head-of-line behavior before any lock partitioning or
/// collect/effect/apply refactor changes ordering semantics.
pub struct MeasuredMutex<T> {
    inner: Mutex<T>,
    telemetry: LockTelemetry,
    name: &'static str,
    slow_wait: Duration,
    slow_hold: Duration,
}

impl<T> MeasuredMutex<T> {
    pub fn new(value: T) -> Self {
        Self::named("runtime.supervisor", value)
    }

    pub fn named(name: &'static str, value: T) -> Self {
        Self::with_thresholds(name, value, DEFAULT_SLOW_WAIT, DEFAULT_SLOW_HOLD)
    }

    pub fn with_thresholds(
        name: &'static str,
        value: T,
        slow_wait: Duration,
        slow_hold: Duration,
    ) -> Self {
        Self {
            inner: Mutex::new(value),
            telemetry: LockTelemetry::new(),
            name,
            slow_wait,
            slow_hold,
        }
    }

    pub async fn lock(&self) -> MeasuredMutexGuard<'_, T> {
        let wait_started = Instant::now();
        let (guard, contended) = if let Ok(guard) = self.inner.try_lock() {
            (guard, false)
        } else {
            (self.inner.lock().await, true)
        };
        self.telemetry.record_wait(
            wait_started.elapsed(),
            contended,
            self.slow_wait,
            self.name,
        );
        MeasuredMutexGuard {
            guard: Some(guard),
            telemetry: &self.telemetry,
            hold_started: Instant::now(),
            slow_hold: self.slow_hold,
            name: self.name,
        }
    }

    pub fn telemetry(&self) -> LockTelemetrySnapshot {
        self.telemetry.snapshot()
    }
}

pub struct MeasuredMutexGuard<'a, T> {
    guard: Option<MutexGuard<'a, T>>,
    telemetry: &'a LockTelemetry,
    hold_started: Instant,
    slow_hold: Duration,
    name: &'static str,
}

impl<T> Deref for MeasuredMutexGuard<'_, T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        self.guard.as_deref().expect("measured mutex guard")
    }
}

impl<T> DerefMut for MeasuredMutexGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.guard
            .as_deref_mut()
            .expect("measured mutex guard")
    }
}

impl<T> Drop for MeasuredMutexGuard<'_, T> {
    fn drop(&mut self) {
        let hold = self.hold_started.elapsed();
        drop(self.guard.take());
        self.telemetry.record_hold(hold, self.slow_hold, self.name);
    }
}

fn duration_ns(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}

fn update_max(target: &AtomicU64, value: u64) {
    let mut observed = target.load(Ordering::Relaxed);
    while value > observed {
        match target.compare_exchange_weak(observed, value, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return,
            Err(actual) => observed = actual,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn records_contention_wait_and_hold_without_changing_serialization() {
        let lock = Arc::new(MeasuredMutex::with_thresholds(
            "test",
            0_u64,
            Duration::from_millis(1),
            Duration::from_millis(1),
        ));
        let held = lock.clone();
        let first = tokio::spawn(async move {
            let mut guard = held.lock().await;
            *guard = 1;
            tokio::time::sleep(Duration::from_millis(10)).await;
        });
        tokio::time::sleep(Duration::from_millis(1)).await;
        let waited = lock.clone();
        let second = tokio::spawn(async move {
            let mut guard = waited.lock().await;
            *guard += 1;
        });
        first.await.expect("first lock task");
        second.await.expect("second lock task");

        assert_eq!(*lock.lock().await, 2);
        let telemetry = lock.telemetry();
        assert_eq!(telemetry.acquisitions, 3);
        assert!(telemetry.contended_acquisitions >= 1);
        assert!(telemetry.max_wait_ns >= 1_000_000);
        assert!(telemetry.max_hold_ns >= 1_000_000);
    }
}
