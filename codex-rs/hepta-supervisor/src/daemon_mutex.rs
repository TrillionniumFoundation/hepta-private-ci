//! Timing instrumentation; these counters never grant lifecycle authority.

use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

const LATENCY_BUCKETS: usize = 64;

struct Histogram {
    buckets: [AtomicU64; LATENCY_BUCKETS],
}

#[derive(Clone, Copy, Debug, Default)]
struct Percentiles {
    p50_us: u64,
    p95_us: u64,
    p99_us: u64,
}

impl Default for Histogram {
    fn default() -> Self {
        Self {
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }
}

impl Histogram {
    fn record(&self, value_us: u64) {
        self.buckets[bucket(value_us)].fetch_add(1, Ordering::Relaxed);
    }

    fn percentiles(&self, count: u64) -> Percentiles {
        if count == 0 {
            return Percentiles::default();
        }
        Percentiles {
            p50_us: self.percentile(count, 50),
            p95_us: self.percentile(count, 95),
            p99_us: self.percentile(count, 99),
        }
    }

    fn percentile(&self, count: u64, percentile: u64) -> u64 {
        let target = count
            .saturating_mul(percentile)
            .saturating_add(99)
            .saturating_div(100)
            .max(1);
        let mut observed = 0_u64;
        for (index, bucket) in self.buckets.iter().enumerate() {
            observed = observed.saturating_add(bucket.load(Ordering::Relaxed));
            if observed >= target {
                return bucket_upper_bound(index);
            }
        }
        u64::MAX
    }
}

fn bucket(value_us: u64) -> usize {
    if value_us <= 1 {
        return 0;
    }
    usize::try_from(u64::BITS - value_us.leading_zeros())
        .unwrap_or(LATENCY_BUCKETS - 1)
        .min(LATENCY_BUCKETS - 1)
}

fn bucket_upper_bound(index: usize) -> u64 {
    if index == 0 {
        return 1;
    }
    1_u64
        .checked_shl(u32::try_from(index).unwrap_or(u32::MAX))
        .unwrap_or(u64::MAX)
}

#[derive(Default)]
struct Timings {
    acquisitions: AtomicU64,
    wait_us: AtomicU64,
    wait_max_us: AtomicU64,
    wait_histogram: Histogram,
    hold_us: AtomicU64,
    hold_max_us: AtomicU64,
    hold_histogram: Histogram,
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
        self.timings.wait_histogram.record(wait);
        MeasuredGuard {
            inner,
            timings: &self.timings,
            acquired: Instant::now(),
        }
    }

    pub(super) fn log_snapshot(&self) {
        let timings = &self.timings;
        let acquisitions = timings.acquisitions.load(Ordering::Relaxed);
        let wait = timings.wait_histogram.percentiles(acquisitions);
        let hold = timings.hold_histogram.percentiles(acquisitions);
        eprintln!(
            "hepta_supervisord_mutex acquisitions={} wait_us={} wait_max_us={} wait_p50_us={} wait_p95_us={} wait_p99_us={} hold_us={} hold_max_us={} hold_p50_us={} hold_p95_us={} hold_p99_us={}",
            acquisitions,
            timings.wait_us.load(Ordering::Relaxed),
            timings.wait_max_us.load(Ordering::Relaxed),
            wait.p50_us,
            wait.p95_us,
            wait.p99_us,
            timings.hold_us.load(Ordering::Relaxed),
            timings.hold_max_us.load(Ordering::Relaxed),
            hold.p50_us,
            hold.p95_us,
            hold.p99_us,
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
        self.timings.hold_histogram.record(hold);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn histogram_percentiles_are_monotone() {
        let histogram = Histogram::default();
        for value in [1_u64, 2, 4, 8, 16, 32, 64, 128] {
            histogram.record(value);
        }
        let percentiles = histogram.percentiles(8);
        assert!(percentiles.p50_us <= percentiles.p95_us);
        assert!(percentiles.p95_us <= percentiles.p99_us);
        assert!(percentiles.p99_us >= 128);
    }
}
