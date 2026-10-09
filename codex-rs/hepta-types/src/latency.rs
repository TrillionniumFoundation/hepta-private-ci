//! Low-overhead, non-authoritative latency histogram for hot owner operations.
//!
//! Atomic counters do not become part of any signed receipt or control state.
//! Reported percentile bounds are logarithmic bucket upper bounds, not exact
//! hardware p50/p95/p99; the hardware benchmark must measure them separately.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

const BUCKETS: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PhaseLatencySnapshotV1 {
    pub observations: u64,
    pub failures: u64,
    pub max_micros: u64,
    pub p50_bound_micros: u64,
    pub p95_bound_micros: u64,
    pub p99_bound_micros: u64,
}

/// Bounded memory and no global mutex in the measured operation hot path.
#[derive(Debug)]
pub struct PhaseLatencyHistogramV1 {
    buckets: [AtomicU64; BUCKETS],
    count: AtomicU64,
    failures: AtomicU64,
    maximum: AtomicU64,
}

impl Default for PhaseLatencyHistogramV1 {
    fn default() -> Self {
        Self {
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
            count: AtomicU64::new(0),
            failures: AtomicU64::new(0),
            maximum: AtomicU64::new(0),
        }
    }
}

impl PhaseLatencyHistogramV1 {
    pub fn observe(&self, latency: Duration, succeeded: bool) {
        let micros = u64::try_from(latency.as_micros()).unwrap_or(u64::MAX);
        let index = bucket_index(micros);
        self.buckets[index].fetch_add(1, Ordering::Relaxed);
        self.count.fetch_add(1, Ordering::Relaxed);
        if !succeeded {
            self.failures.fetch_add(1, Ordering::Relaxed);
        }
        self.maximum.fetch_max(micros, Ordering::Relaxed);
    }

    pub fn time_result<T, E>(&self, action: impl FnOnce() -> Result<T, E>) -> Result<T, E> {
        let started = Instant::now();
        let result = action();
        self.observe(started.elapsed(), result.is_ok());
        result
    }

    pub fn time_value<T>(&self, action: impl FnOnce() -> T) -> T {
        let started = Instant::now();
        let value = action();
        self.observe(started.elapsed(), true);
        value
    }

    pub fn snapshot(&self) -> PhaseLatencySnapshotV1 {
        let observations = self.count.load(Ordering::Relaxed);
        PhaseLatencySnapshotV1 {
            observations,
            failures: self.failures.load(Ordering::Relaxed),
            max_micros: self.maximum.load(Ordering::Relaxed),
            p50_bound_micros: self.percentile_bound(observations, 50),
            p95_bound_micros: self.percentile_bound(observations, 95),
            p99_bound_micros: self.percentile_bound(observations, 99),
        }
    }

    fn percentile_bound(&self, observations: u64, percentile: u64) -> u64 {
        if observations == 0 {
            return 0;
        }
        let rank = observations.saturating_mul(percentile).saturating_add(99) / 100;
        let mut reached = 0_u64;
        for (index, bucket) in self.buckets.iter().enumerate() {
            reached = reached.saturating_add(bucket.load(Ordering::Relaxed));
            if reached >= rank {
                return bucket_upper_bound(index);
            }
        }
        u64::MAX
    }
}

fn bucket_index(micros: u64) -> usize {
    if micros == 0 { 0 } else { (u64::BITS - 1 - micros.leading_zeros()) as usize }
}

fn bucket_upper_bound(index: usize) -> u64 {
    if index == 0 { 1 } else if index >= 63 { u64::MAX } else { (1_u64 << (index + 1)) - 1 }
}

#[cfg(test)]
#[path = "latency_tests.rs"]
mod tests;
