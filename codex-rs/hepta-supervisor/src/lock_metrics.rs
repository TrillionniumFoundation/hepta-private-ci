use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

const LOCK_METRICS_SCHEMA_VERSION: u32 = 1;
const HISTOGRAM_BUCKETS: usize = 64;
static SNAPSHOT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SupervisorLockClass {
    Tick,
    Read,
    Mutation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorLockLatencySnapshot {
    pub count: u64,
    pub total_nanos: u64,
    pub max_nanos: u64,
    pub p50_upper_bound_nanos: u64,
    pub p95_upper_bound_nanos: u64,
    pub p99_upper_bound_nanos: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorLockClassSnapshot {
    pub wait: SupervisorLockLatencySnapshot,
    pub hold: SupervisorLockLatencySnapshot,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorLockMetricsSnapshot {
    pub schema_version: u32,
    pub observed_at_unix_millis: u64,
    pub tick: SupervisorLockClassSnapshot,
    pub read: SupervisorLockClassSnapshot,
    pub mutation: SupervisorLockClassSnapshot,
}

struct Histogram {
    count: AtomicU64,
    total_nanos: AtomicU64,
    max_nanos: AtomicU64,
    buckets: [AtomicU64; HISTOGRAM_BUCKETS],
}

impl Histogram {
    fn new() -> Self {
        Self {
            count: AtomicU64::new(0),
            total_nanos: AtomicU64::new(0),
            max_nanos: AtomicU64::new(0),
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }

    fn record(&self, elapsed: std::time::Duration) {
        let nanos = u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX);
        self.count.fetch_add(1, Ordering::Relaxed);
        self.total_nanos.fetch_add(nanos, Ordering::Relaxed);
        self.max_nanos.fetch_max(nanos, Ordering::Relaxed);
        self.buckets[bucket_index(nanos)].fetch_add(1, Ordering::Relaxed);
    }

    fn snapshot(&self) -> SupervisorLockLatencySnapshot {
        let count = self.count.load(Ordering::Relaxed);
        let buckets = std::array::from_fn(|index| self.buckets[index].load(Ordering::Relaxed));
        SupervisorLockLatencySnapshot {
            count,
            total_nanos: self.total_nanos.load(Ordering::Relaxed),
            max_nanos: self.max_nanos.load(Ordering::Relaxed),
            p50_upper_bound_nanos: quantile_upper_bound(&buckets, count, 50),
            p95_upper_bound_nanos: quantile_upper_bound(&buckets, count, 95),
            p99_upper_bound_nanos: quantile_upper_bound(&buckets, count, 99),
        }
    }
}

struct LockClassMetrics {
    wait: Histogram,
    hold: Histogram,
}

impl LockClassMetrics {
    fn new() -> Self {
        Self {
            wait: Histogram::new(),
            hold: Histogram::new(),
        }
    }

    fn snapshot(&self) -> SupervisorLockClassSnapshot {
        SupervisorLockClassSnapshot {
            wait: self.wait.snapshot(),
            hold: self.hold.snapshot(),
        }
    }
}

struct SupervisorLockMetrics {
    tick: LockClassMetrics,
    read: LockClassMetrics,
    mutation: LockClassMetrics,
}

impl SupervisorLockMetrics {
    fn new() -> Self {
        Self {
            tick: LockClassMetrics::new(),
            read: LockClassMetrics::new(),
            mutation: LockClassMetrics::new(),
        }
    }

    fn class(&self, class: SupervisorLockClass) -> &LockClassMetrics {
        match class {
            SupervisorLockClass::Tick => &self.tick,
            SupervisorLockClass::Read => &self.read,
            SupervisorLockClass::Mutation => &self.mutation,
        }
    }

    fn snapshot(&self) -> SupervisorLockMetricsSnapshot {
        let observed_at_unix_millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()
            .and_then(|duration| u64::try_from(duration.as_millis()).ok())
            .unwrap_or(0);
        SupervisorLockMetricsSnapshot {
            schema_version: LOCK_METRICS_SCHEMA_VERSION,
            observed_at_unix_millis,
            tick: self.tick.snapshot(),
            read: self.read.snapshot(),
            mutation: self.mutation.snapshot(),
        }
    }
}

pub(crate) struct InstrumentedMutex<T> {
    inner: Mutex<T>,
    metrics: Arc<SupervisorLockMetrics>,
}

impl<T> InstrumentedMutex<T> {
    pub(crate) fn new(value: T) -> Self {
        Self {
            inner: Mutex::new(value),
            metrics: Arc::new(SupervisorLockMetrics::new()),
        }
    }

    pub(crate) async fn lock(
        &self,
        class: SupervisorLockClass,
    ) -> InstrumentedMutexGuard<'_, T> {
        let waiting_since = Instant::now();
        let guard = self.inner.lock().await;
        self.metrics.class(class).wait.record(waiting_since.elapsed());
        InstrumentedMutexGuard {
            guard,
            metrics: Arc::clone(&self.metrics),
            class,
            acquired_at: Instant::now(),
        }
    }

    pub(crate) fn snapshot(&self) -> SupervisorLockMetricsSnapshot {
        self.metrics.snapshot()
    }
}

pub(crate) struct InstrumentedMutexGuard<'a, T> {
    guard: MutexGuard<'a, T>,
    metrics: Arc<SupervisorLockMetrics>,
    class: SupervisorLockClass,
    acquired_at: Instant,
}

impl<T> Deref for InstrumentedMutexGuard<'_, T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.guard
    }
}

impl<T> DerefMut for InstrumentedMutexGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.guard
    }
}

impl<T> Drop for InstrumentedMutexGuard<'_, T> {
    fn drop(&mut self) {
        self.metrics
            .class(self.class)
            .hold
            .record(self.acquired_at.elapsed());
    }
}

pub(crate) fn write_lock_metrics_snapshot(
    path: &Path,
    snapshot: &SupervisorLockMetricsSnapshot,
) -> io::Result<()> {
    let parent = path.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "lock metrics output has no parent directory",
        )
    })?;
    std::fs::create_dir_all(parent)?;
    let sequence = SNAPSHOT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp = parent.join(format!(
        ".{}.{}.{sequence}.tmp",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("supervisor-lock-metrics"),
        std::process::id()
    ));
    let mut bytes = serde_json::to_vec_pretty(snapshot)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = crate::durable_publish::publish(&temp, path) {
        let _ = std::fs::remove_file(temp);
        return Err(error);
    }
    Ok(())
}

fn bucket_index(nanos: u64) -> usize {
    if nanos <= 1 {
        0
    } else {
        usize::try_from(u64::BITS - (nanos - 1).leading_zeros())
            .unwrap_or(HISTOGRAM_BUCKETS - 1)
            .min(HISTOGRAM_BUCKETS - 1)
    }
}

fn bucket_upper_bound(index: usize) -> u64 {
    if index >= 63 {
        u64::MAX
    } else {
        1_u64 << index
    }
}

fn quantile_upper_bound(
    buckets: &[u64; HISTOGRAM_BUCKETS],
    count: u64,
    percentile: u64,
) -> u64 {
    if count == 0 {
        return 0;
    }
    let target = count
        .saturating_mul(percentile)
        .saturating_add(99)
        .saturating_div(100)
        .max(1);
    let mut observed = 0_u64;
    for (index, bucket) in buckets.iter().enumerate() {
        observed = observed.saturating_add(*bucket);
        if observed >= target {
            return bucket_upper_bound(index);
        }
    }
    u64::MAX
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[test]
    fn histogram_quantiles_are_bounded_and_monotone() {
        let histogram = Histogram::new();
        for nanos in [1_u64, 2, 3, 8, 13, 21, 34, 55, 89, 144] {
            histogram.record(Duration::from_nanos(nanos));
        }
        let snapshot = histogram.snapshot();
        assert_eq!(snapshot.count, 10);
        assert!(snapshot.p50_upper_bound_nanos <= snapshot.p95_upper_bound_nanos);
        assert!(snapshot.p95_upper_bound_nanos <= snapshot.p99_upper_bound_nanos);
        assert!(snapshot.max_nanos >= 144);
    }

    #[tokio::test]
    async fn guard_records_wait_and_hold_for_each_class() {
        let mutex = InstrumentedMutex::new(0_u64);
        {
            let mut guard = mutex.lock(SupervisorLockClass::Mutation).await;
            *guard += 1;
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        let snapshot = mutex.snapshot();
        assert_eq!(snapshot.mutation.wait.count, 1);
        assert_eq!(snapshot.mutation.hold.count, 1);
        assert!(snapshot.mutation.hold.max_nanos > 0);
    }
}
