//! Bounded rolling latency samples. No secret, digest, subject, path or operation
//! ID is accepted by this module. Samples include failed/cancelled calls; these
//! projections never decide admission and are not a production SLA.
use std::collections::VecDeque;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;
use serde::Serialize;

const SAMPLE_LIMIT: usize = 1024;
#[derive(Default)]
struct Latencies { total: u64, samples: VecDeque<u64> }
#[derive(Default)]
pub(crate) struct BaoRuntimeMetrics {
    requests: Mutex<Latencies>,
    recoveries: Mutex<Latencies>,
    observer_failures: AtomicU64,
}
#[derive(Clone, Debug, Serialize)]
pub struct BaoLatencySnapshot {
    pub available: bool,
    pub total_observations: u64,
    pub retained_samples: usize,
    pub p50_nanoseconds: Option<u64>,
    pub p95_nanoseconds: Option<u64>,
    pub p99_nanoseconds: Option<u64>,
}
#[derive(Clone, Debug, Serialize)]
pub struct BaoRuntimeSnapshot {
    pub full_requests: BaoLatencySnapshot,
    pub recovery_requests: BaoLatencySnapshot,
    pub observer_failures: u64,
}

pub(crate) struct BaoLatencyTimer<'a> { started: Instant, observations: &'a Mutex<Latencies> }
impl Drop for BaoLatencyTimer<'_> {
    fn drop(&mut self) {
        if let Ok(mut data) = self.observations.lock() {
            data.total = data.total.saturating_add(1);
            if data.samples.len() == SAMPLE_LIMIT { data.samples.pop_front(); }
            data.samples.push_back(self.started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64);
        }
    }
}
impl BaoRuntimeMetrics {
    pub(crate) fn request_timer(&self) -> BaoLatencyTimer<'_> {
        BaoLatencyTimer { started: Instant::now(), observations: &self.requests }
    }
    pub(crate) fn recovery_timer(&self) -> BaoLatencyTimer<'_> {
        BaoLatencyTimer { started: Instant::now(), observations: &self.recoveries }
    }
    pub(crate) fn observer_failed(&self) { self.observer_failures.fetch_add(1, Ordering::Relaxed); }
    fn snapshot(&self) -> BaoRuntimeSnapshot {
        BaoRuntimeSnapshot { full_requests: snapshot(&self.requests), recovery_requests: snapshot(&self.recoveries),
            observer_failures: self.observer_failures.load(Ordering::Relaxed) }
    }
}
fn snapshot(source: &Mutex<Latencies>) -> BaoLatencySnapshot {
    let mut result = BaoLatencySnapshot { available: false, total_observations: 0, retained_samples: 0,
        p50_nanoseconds: None, p95_nanoseconds: None, p99_nanoseconds: None };
    if let Ok(data) = source.lock() {
        result.available = true;
        result.total_observations = data.total;
        let mut samples: Vec<_> = data.samples.iter().copied().collect();
        samples.sort_unstable();
        result.retained_samples = samples.len();
        let percentile = |p: usize| samples.get((samples.len() * p).div_ceil(100).saturating_sub(1)).copied();
        result.p50_nanoseconds = percentile(50);
        result.p95_nanoseconds = percentile(95);
        result.p99_nanoseconds = percentile(99);
    }
    result
}
impl crate::BaoFinalUseHost {
    pub fn runtime_metrics(&self) -> BaoRuntimeSnapshot { self.metrics.snapshot() }
}
