//! Bounded, authority-free latency evidence for lifecycle control.
//!
//! Counters are process-local observations. They never grant mutation authority
//! and zero samples mean that a stage has not been observed on this process.

use std::sync::OnceLock;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;

const LATENCY_BUCKETS: usize = 64;
const OPERATION_COUNT: usize = 7;
const STAGE_COUNT: usize = 7;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[repr(usize)]
#[serde(rename_all = "snake_case")]
pub enum ControlLatencyOperation {
    Start = 0,
    Drain = 1,
    Stop = 2,
    Kill = 3,
    Restart = 4,
    ReleaseChange = 5,
    Recovery = 6,
}

const OPERATIONS: [ControlLatencyOperation; OPERATION_COUNT] = [
    ControlLatencyOperation::Start,
    ControlLatencyOperation::Drain,
    ControlLatencyOperation::Stop,
    ControlLatencyOperation::Kill,
    ControlLatencyOperation::Restart,
    ControlLatencyOperation::ReleaseChange,
    ControlLatencyOperation::Recovery,
];

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[repr(usize)]
#[serde(rename_all = "snake_case")]
pub enum ControlLatencyStage {
    Total = 0,
    TargetValidation = 1,
    IntentPersistence = 2,
    EffectDispatch = 3,
    ExitObservation = 4,
    MetadataCommit = 5,
    AuditPublication = 6,
}

const STAGES: [ControlLatencyStage; STAGE_COUNT] = [
    ControlLatencyStage::Total,
    ControlLatencyStage::TargetValidation,
    ControlLatencyStage::IntentPersistence,
    ControlLatencyStage::EffectDispatch,
    ControlLatencyStage::ExitObservation,
    ControlLatencyStage::MetadataCommit,
    ControlLatencyStage::AuditPublication,
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlLatencySeries {
    pub operation: ControlLatencyOperation,
    pub stage: ControlLatencyStage,
    pub samples: u64,
    pub total_us: u64,
    pub max_us: u64,
    pub p50_us: u64,
    pub p95_us: u64,
    pub p99_us: u64,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlLatencySnapshot {
    pub series: Vec<ControlLatencySeries>,
}

struct Histogram {
    count: AtomicU64,
    total_us: AtomicU64,
    max_us: AtomicU64,
    buckets: [AtomicU64; LATENCY_BUCKETS],
}

impl Default for Histogram {
    fn default() -> Self {
        Self {
            count: AtomicU64::new(0),
            total_us: AtomicU64::new(0),
            max_us: AtomicU64::new(0),
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }
}

impl Histogram {
    fn record(&self, duration: Duration) {
        let value_us = micros(duration);
        self.total_us.fetch_add(value_us, Ordering::Relaxed);
        self.max_us.fetch_max(value_us, Ordering::Relaxed);
        self.buckets[bucket(value_us)].fetch_add(1, Ordering::Relaxed);
        self.count.fetch_add(1, Ordering::Release);
    }

    fn snapshot(
        &self,
        operation: ControlLatencyOperation,
        stage: ControlLatencyStage,
    ) -> ControlLatencySeries {
        let samples = self.count.load(Ordering::Acquire);
        ControlLatencySeries {
            operation,
            stage,
            samples,
            total_us: self.total_us.load(Ordering::Relaxed),
            max_us: self.max_us.load(Ordering::Relaxed),
            p50_us: self.percentile(samples, 50),
            p95_us: self.percentile(samples, 95),
            p99_us: self.percentile(samples, 99),
        }
    }

    fn percentile(&self, samples: u64, percentile: u64) -> u64 {
        if samples == 0 {
            return 0;
        }
        let target = samples
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

struct Metrics {
    series: [[Histogram; STAGE_COUNT]; OPERATION_COUNT],
}

impl Default for Metrics {
    fn default() -> Self {
        Self {
            series: std::array::from_fn(|_| std::array::from_fn(|_| Histogram::default())),
        }
    }
}

static METRICS: OnceLock<Metrics> = OnceLock::new();

fn metrics() -> &'static Metrics {
    METRICS.get_or_init(Metrics::default)
}

pub(crate) fn record_stage(
    operation: ControlLatencyOperation,
    stage: ControlLatencyStage,
    duration: Duration,
) {
    metrics().series[operation as usize][stage as usize].record(duration);
}

pub(crate) struct OperationTimer {
    operation: ControlLatencyOperation,
    started: Instant,
}

impl OperationTimer {
    pub(crate) fn start(operation: ControlLatencyOperation) -> Self {
        Self {
            operation,
            started: Instant::now(),
        }
    }
}

impl Drop for OperationTimer {
    fn drop(&mut self) {
        record_stage(
            self.operation,
            ControlLatencyStage::Total,
            self.started.elapsed(),
        );
    }
}

pub fn control_latency_snapshot() -> ControlLatencySnapshot {
    let metrics = metrics();
    let mut series = Vec::with_capacity(OPERATION_COUNT * STAGE_COUNT);
    for operation in OPERATIONS {
        for stage in STAGES {
            series.push(
                metrics.series[operation as usize][stage as usize].snapshot(operation, stage),
            );
        }
    }
    ControlLatencySnapshot { series }
}

pub(crate) fn log_snapshot() {
    for series in control_latency_snapshot()
        .series
        .into_iter()
        .filter(|series| series.samples > 0)
    {
        eprintln!(
            "hepta_supervisord_control_latency operation={:?} stage={:?} samples={} total_us={} max_us={} p50_us={} p95_us={} p99_us={}",
            series.operation,
            series.stage,
            series.samples,
            series.total_us,
            series.max_us,
            series.p50_us,
            series.p95_us,
            series.p99_us,
        );
    }
}

fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn histogram_percentiles_are_monotone_and_bounded() {
        let histogram = Histogram::default();
        for value in [1_u64, 2, 4, 8, 16, 32, 64, 128] {
            histogram.record(Duration::from_micros(value));
        }
        let snapshot = histogram.snapshot(
            ControlLatencyOperation::Stop,
            ControlLatencyStage::IntentPersistence,
        );
        assert_eq!(snapshot.samples, 8);
        assert!(snapshot.p50_us <= snapshot.p95_us);
        assert!(snapshot.p95_us <= snapshot.p99_us);
        assert!(snapshot.p99_us >= 128);
        assert!(snapshot.max_us >= 128);
    }

    #[test]
    fn snapshot_keeps_zero_sample_stages_explicit() {
        let snapshot = control_latency_snapshot();
        assert_eq!(snapshot.series.len(), OPERATION_COUNT * STAGE_COUNT);
        assert!(snapshot.series.iter().any(|series| {
            series.operation == ControlLatencyOperation::Recovery
                && series.stage == ControlLatencyStage::AuditPublication
        }));
    }
}
