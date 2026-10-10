//! Evidence-owned bounded background metrics writer. Telemetry cannot authorize
//! effects or turn a successful operation into a retry.

use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, SyncSender, TrySendError, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use codex_hepta_types::{
    PhaseMetricEventV1, PhaseMetricKindV1, PhaseMetricSinkErrorV1, PhaseMetricSinkV1,
};
use super::metrics_group_commit::{
    MetricPhaseV1, MetricSampleV1, MetricsGroupCommitV1, MetricsJournalErrorV1,
};

const MAX_QUEUE: usize = 65_536;
const MAX_BATCH: usize = 256;

enum WriterCommandV1 {
    Record(MetricSampleV1),
    Flush(SyncSender<bool>),
    Stop(SyncSender<bool>),
}

#[derive(Debug)]
struct WriterHealthV1 {
    healthy: AtomicBool,
    dropped: AtomicU64,
    persisted_batches: AtomicU64,
    persisted_rows: AtomicU64,
}

pub struct DurablePhaseMetricSinkV1 {
    channel: SyncSender<WriterCommandV1>,
    health: Arc<WriterHealthV1>,
    worker: Mutex<Option<JoinHandle<()>>>,
}

impl std::fmt::Debug for DurablePhaseMetricSinkV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DurablePhaseMetricSinkV1")
            .field("healthy", &self.healthy())
            .field("dropped", &self.dropped())
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PhaseMetricWriterStatusV1 {
    pub healthy: bool,
    pub dropped: u64,
    pub persisted_batches: u64,
    pub persisted_rows: u64,
}

impl DurablePhaseMetricSinkV1 {
    pub fn open(
        path: impl AsRef<Path>, capacity: usize, group_size: usize, flush_interval_ms: u64,
    ) -> Result<Self, MetricsJournalErrorV1> {
        if capacity == 0 || capacity > MAX_QUEUE
            || group_size == 0 || group_size > MAX_BATCH
            || !(1..=60_000).contains(&flush_interval_ms)
        {
            return Err(MetricsJournalErrorV1::Capacity);
        }
        // Open, lock and replay before advertising readiness.
        let writer = MetricsGroupCommitV1::open(path)?;
        let health = Arc::new(WriterHealthV1 {
            healthy: AtomicBool::new(true),
            dropped: AtomicU64::new(0),
            persisted_batches: AtomicU64::new(0),
            persisted_rows: AtomicU64::new(0),
        });
        let (tx, rx) = sync_channel(capacity);
        let observed = Arc::clone(&health);
        let worker = thread::Builder::new()
            .name("hepta-metrics-evidence-writer".to_string())
            .spawn(move || writer_loop(writer, rx, observed, group_size, Duration::from_millis(flush_interval_ms)))?;
        Ok(Self { channel: tx, health, worker: Mutex::new(Some(worker)) })
    }

    pub fn healthy(&self) -> bool {
        self.health.healthy.load(Ordering::Acquire)
            && self.health.dropped.load(Ordering::Acquire) == 0
    }

    pub fn dropped(&self) -> u64 { self.health.dropped.load(Ordering::Relaxed) }

    pub fn status(&self) -> PhaseMetricWriterStatusV1 {
        PhaseMetricWriterStatusV1 {
            healthy: self.healthy(), dropped: self.dropped(),
            persisted_batches: self.health.persisted_batches.load(Ordering::Acquire),
            persisted_rows: self.health.persisted_rows.load(Ordering::Acquire),
        }
    }

    /// Synchronous export barrier; never called inside an effect boundary.
    pub fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        if !self.healthy() { return Err(PhaseMetricSinkErrorV1::Unavailable); }
        let (tx, rx) = sync_channel(1);
        self.channel.send(WriterCommandV1::Flush(tx))
            .map_err(|_| PhaseMetricSinkErrorV1::Unavailable)?;
        match rx.recv() {
            Ok(true) if self.healthy() => Ok(()),
            _ => Err(PhaseMetricSinkErrorV1::Unavailable),
        }
    }
}

impl PhaseMetricSinkV1 for DurablePhaseMetricSinkV1 {
    fn record(&self, event: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        if !self.healthy() || event.scope_digest.is_zero() || event.operation_digest.is_zero() {
            return Err(PhaseMetricSinkErrorV1::Unavailable);
        }
        let phase = match event.phase {
            PhaseMetricKindV1::Admission => MetricPhaseV1::Admission,
            PhaseMetricKindV1::Microbatch => MetricPhaseV1::Microbatch,
            PhaseMetricKindV1::Cas => MetricPhaseV1::Cas,
            PhaseMetricKindV1::Signature => MetricPhaseV1::Signature,
            PhaseMetricKindV1::Cns => MetricPhaseV1::Cns,
            PhaseMetricKindV1::NeuronFeature => MetricPhaseV1::NeuronFeature,
        };
        let sample = MetricSampleV1 {
            scope_digest: event.scope_digest,
            operation_digest: event.operation_digest,
            phase, latency_micros: event.latency_micros, succeeded: event.succeeded,
        };
        match self.channel.try_send(WriterCommandV1::Record(sample)) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => {
                self.health.dropped.fetch_add(1, Ordering::Relaxed);
                self.health.healthy.store(false, Ordering::Release);
                Err(PhaseMetricSinkErrorV1::Backpressure)
            }
            Err(TrySendError::Disconnected(_)) => {
                self.health.healthy.store(false, Ordering::Release);
                Err(PhaseMetricSinkErrorV1::Unavailable)
            }
        }
    }
}

impl Drop for DurablePhaseMetricSinkV1 {
    fn drop(&mut self) {
        let (tx, rx) = sync_channel(1);
        if self.channel.send(WriterCommandV1::Stop(tx)).is_ok() { let _ = rx.recv(); }
        if let Ok(mut handle) = self.worker.lock() {
            if let Some(worker) = handle.take() { let _ = worker.join(); }
        }
    }
}

fn flush(writer: &mut MetricsGroupCommitV1, health: &WriterHealthV1) -> Result<(), MetricsJournalErrorV1> {
    if let Some(receipt) = writer.flush()? {
        health.persisted_rows.fetch_add(receipt.rows as u64, Ordering::Release);
        health.persisted_batches.fetch_add(1, Ordering::Release);
    }
    Ok(())
}

fn writer_loop(
    mut writer: MetricsGroupCommitV1, rx: Receiver<WriterCommandV1>,
    health: Arc<WriterHealthV1>, group_size: usize, interval: Duration,
) {
    loop {
        match rx.recv_timeout(interval) {
            Ok(WriterCommandV1::Record(sample)) => {
                let result = writer.stage(sample).and_then(|()| {
                    if writer.pending() >= group_size { flush(&mut writer, &health)?; }
                    Ok(())
                });
                if result.is_err() { health.healthy.store(false, Ordering::Release); break; }
            }
            Ok(WriterCommandV1::Flush(reply)) => {
                let ok = flush(&mut writer, &health).is_ok();
                if !ok { health.healthy.store(false, Ordering::Release); }
                let _ = reply.send(ok);
                if !ok { break; }
            }
            Ok(WriterCommandV1::Stop(reply)) => {
                let ok = flush(&mut writer, &health).is_ok();
                if !ok { health.healthy.store(false, Ordering::Release); }
                let _ = reply.send(ok);
                break;
            }
            Err(RecvTimeoutError::Timeout) => {
                if flush(&mut writer, &health).is_err() {
                    health.healthy.store(false, Ordering::Release); break;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                if flush(&mut writer, &health).is_err() {
                    health.healthy.store(false, Ordering::Release);
                }
                break;
            }
        }
    }
}

#[cfg(test)]
#[path = "metrics_sink_tests.rs"]
mod tests;
