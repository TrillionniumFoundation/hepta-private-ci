//! Timing instrumentation; these counters never grant lifecycle authority.

use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

const SLOW_WAIT_US: u64 = 5_000;
const SLOW_HOLD_US: u64 = 25_000;

#[derive(Default)]
struct Timings {
    acquisitions: AtomicU64,
    contended_acquisitions: AtomicU64,
    wait_us: AtomicU64,
    wait_max_us: AtomicU64,
    slow_waits: AtomicU64,
    hold_us: AtomicU64,
    hold_max_us: AtomicU64,
    slow_holds: AtomicU64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct LockTelemetrySnapshot {
    pub acquisitions: u64,
    pub contended_acquisitions: u64,
    pub wait_us: u64,
    pub wait_max_us: u64,
    pub slow_waits: u64,
    pub hold_us: u64,
    pub hold_max_us: u64,
    pub slow_holds: u64,
}

impl LockTelemetrySnapshot {
    pub fn delta(self, earlier: Self) -> Self {
        Self {
            acquisitions: self.acquisitions.saturating_sub(earlier.acquisitions),
            contended_acquisitions: self
                .contended_acquisitions
                .saturating_sub(earlier.contended_acquisitions),
            wait_us: self.wait_us.saturating_sub(earlier.wait_us),
            // Maxima are cumulative counters. Do not attribute an older
            // scenario's record to the current measurement window.
            wait_max_us: (self.wait_max_us > earlier.wait_max_us)
                .then_some(self.wait_max_us)
                .unwrap_or(0),
            slow_waits: self.slow_waits.saturating_sub(earlier.slow_waits),
            hold_us: self.hold_us.saturating_sub(earlier.hold_us),
            hold_max_us: (self.hold_max_us > earlier.hold_max_us)
                .then_some(self.hold_max_us)
                .unwrap_or(0),
            slow_holds: self.slow_holds.saturating_sub(earlier.slow_holds),
        }
    }
}

pub struct MeasuredMutex<T> {
    inner: Mutex<T>,
    timings: Timings,
}

pub struct MeasuredGuard<'a, T> {
    inner: MutexGuard<'a, T>,
    timings: &'a Timings,
    acquired: Instant,
}

pub fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

impl<T> MeasuredMutex<T> {
    pub fn new(value: T) -> Self {
        Self {
            inner: Mutex::new(value),
            timings: Timings::default(),
        }
    }

    pub async fn lock(&self) -> MeasuredGuard<'_, T> {
        let waiting = Instant::now();
        match self.inner.try_lock() {
            Ok(inner) => self.guard(inner, waiting, false),
            Err(_) => {
                let inner = self.inner.lock().await;
                self.guard(inner, waiting, true)
            }
        }
    }

    pub fn blocking_lock(&self) -> MeasuredGuard<'_, T> {
        let waiting = Instant::now();
        match self.inner.try_lock() {
            Ok(inner) => self.guard(inner, waiting, false),
            Err(_) => {
                let inner = self.inner.blocking_lock();
                self.guard(inner, waiting, true)
            }
        }
    }

    fn guard<'a>(
        &'a self,
        inner: MutexGuard<'a, T>,
        waiting: Instant,
        contended: bool,
    ) -> MeasuredGuard<'a, T> {
        let wait = micros(waiting.elapsed());
        self.timings.acquisitions.fetch_add(1, Ordering::Relaxed);
        if contended {
            self.timings
                .contended_acquisitions
                .fetch_add(1, Ordering::Relaxed);
        }
        self.timings.wait_us.fetch_add(wait, Ordering::Relaxed);
        self.timings.wait_max_us.fetch_max(wait, Ordering::Relaxed);
        if wait >= SLOW_WAIT_US {
            self.timings.slow_waits.fetch_add(1, Ordering::Relaxed);
            eprintln!("hepta_supervisord_mutex_slow_wait wait_us={wait} contended={contended}");
        }
        MeasuredGuard {
            inner,
            timings: &self.timings,
            acquired: Instant::now(),
        }
    }

    pub fn snapshot(&self) -> LockTelemetrySnapshot {
        let t = &self.timings;
        LockTelemetrySnapshot {
            acquisitions: t.acquisitions.load(Ordering::Relaxed),
            contended_acquisitions: t.contended_acquisitions.load(Ordering::Relaxed),
            wait_us: t.wait_us.load(Ordering::Relaxed),
            wait_max_us: t.wait_max_us.load(Ordering::Relaxed),
            slow_waits: t.slow_waits.load(Ordering::Relaxed),
            hold_us: t.hold_us.load(Ordering::Relaxed),
            hold_max_us: t.hold_max_us.load(Ordering::Relaxed),
            slow_holds: t.slow_holds.load(Ordering::Relaxed),
        }
    }

    pub fn log_snapshot(&self) {
        let t = self.snapshot();
        eprintln!(
            "hepta_supervisord_mutex acquisitions={} contended={} wait_us={} wait_max_us={} slow_waits={} hold_us={} hold_max_us={} slow_holds={}",
            t.acquisitions,
            t.contended_acquisitions,
            t.wait_us,
            t.wait_max_us,
            t.slow_waits,
            t.hold_us,
            t.hold_max_us,
            t.slow_holds,
        );
    }
}

impl<T> Deref for MeasuredGuard<'_, T> {
    type Target = T;

    fn deref(&self) -> &T {
        &self.inner
    }
}

impl<T> DerefMut for MeasuredGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.inner
    }
}

impl<T> Drop for MeasuredGuard<'_, T> {
    fn drop(&mut self) {
        let hold = micros(self.acquired.elapsed());
        self.timings.hold_us.fetch_add(hold, Ordering::Relaxed);
        self.timings.hold_max_us.fetch_max(hold, Ordering::Relaxed);
        if hold >= SLOW_HOLD_US {
            self.timings.slow_holds.fetch_add(1, Ordering::Relaxed);
            eprintln!("hepta_supervisord_mutex_slow_hold hold_us={hold}");
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn records_contention_and_preserves_serialization() {
        let lock = Arc::new(MeasuredMutex::new(0_u64));
        let first_lock = Arc::clone(&lock);
        let first = tokio::spawn(async move {
            let mut guard = first_lock.lock().await;
            *guard = 1;
            tokio::time::sleep(Duration::from_millis(10)).await;
        });
        tokio::time::sleep(Duration::from_millis(1)).await;
        let second_lock = Arc::clone(&lock);
        let second = tokio::spawn(async move {
            let mut guard = second_lock.lock().await;
            *guard += 1;
        });
        first.await.expect("first holder");
        second.await.expect("second holder");
        assert_eq!(*lock.lock().await, 2);
        let snapshot = lock.snapshot();
        assert_eq!(snapshot.acquisitions, 3);
        assert!(snapshot.contended_acquisitions >= 1);
        assert!(snapshot.wait_max_us >= 1_000);

        let unchanged = lock.snapshot();
        let empty_window = unchanged.delta(snapshot);
        assert_eq!(empty_window.wait_max_us, 0);
        assert_eq!(empty_window.hold_max_us, 0);
    }
}
