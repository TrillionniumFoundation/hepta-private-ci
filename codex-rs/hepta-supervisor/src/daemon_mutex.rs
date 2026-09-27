//! Timing instrumentation; these counters never grant lifecycle authority.

use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

#[derive(Default)]
struct Timings {
    acquisitions: AtomicU64,
    wait_us: AtomicU64,
    wait_max_us: AtomicU64,
    hold_us: AtomicU64,
    hold_max_us: AtomicU64,
}

pub(super) struct MeasuredMutex<T> {
    inner: Mutex<T>,
    timings: Timings,
}

pub(super) struct MeasuredGuard<'a, T> {
    inner: MutexGuard<'a, T>,
    timings: &'a Timings,
    acquired: Instant,
}

pub(super) fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

impl<T> MeasuredMutex<T> {
    pub(super) fn new(value: T) -> Self {
        Self {
            inner: Mutex::new(value),
            timings: Timings::default(),
        }
    }

    pub(super) async fn lock(&self) -> MeasuredGuard<'_, T> {
        let waiting = Instant::now();
        let inner = self.inner.lock().await;
        self.guard(inner, waiting)
    }

    pub(super) fn blocking_lock(&self) -> MeasuredGuard<'_, T> {
        let waiting = Instant::now();
        let inner = self.inner.blocking_lock();
        self.guard(inner, waiting)
    }

    fn guard<'a>(&'a self, inner: MutexGuard<'a, T>, waiting: Instant) -> MeasuredGuard<'a, T> {
        let wait = micros(waiting.elapsed());
        self.timings.acquisitions.fetch_add(1, Ordering::Relaxed);
        self.timings.wait_us.fetch_add(wait, Ordering::Relaxed);
        self.timings.wait_max_us.fetch_max(wait, Ordering::Relaxed);
        MeasuredGuard {
            inner,
            timings: &self.timings,
            acquired: Instant::now(),
        }
    }

    pub(super) fn log_snapshot(&self) {
        let t = &self.timings;
        eprintln!(
            "hepta_supervisord_mutex acquisitions={} wait_us={} wait_max_us={} hold_us={} hold_max_us={}",
            t.acquisitions.load(Ordering::Relaxed),
            t.wait_us.load(Ordering::Relaxed),
            t.wait_max_us.load(Ordering::Relaxed),
            t.hold_us.load(Ordering::Relaxed),
            t.hold_max_us.load(Ordering::Relaxed),
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
    }
}
