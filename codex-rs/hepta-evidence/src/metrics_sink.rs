//! Evidence-owned bounded background metrics writer. Telemetry cannot authorize
//! effects or turn a successful operation into a retry.

use super::metrics_group_commit::MetricPhaseV1;
use super::metrics_group_commit::MetricSampleV1;
use super::metrics_group_commit::MetricsLocalFrontierV1;
use super::metrics_group_commit::MetricsGroupCommitV1;
use super::metrics_group_commit::MetricsJournalErrorV1;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkErrorV1;
use codex_hepta_types::PhaseMetricSinkV1;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc::Receiver;
use std::sync::mpsc::RecvTimeoutError;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::TrySendError;
use std::sync::mpsc::sync_channel;
use std::thread::JoinHandle;
use std::thread::{self};
use std::time::Duration;

const MAX_QUEUE: usize = 65_536;
const MAX_BATCH: usize = 256;
// A flushed physical Split effect must not stall forever on Evidence I/O.
// Timeout means an indeterminate telemetry barrier, never success.
const MAX_FLUSH_WAIT: Duration = Duration::from_secs(30);

enum WriterCommandV1 {
    Record(MetricSampleV1),
    Flush(SyncSender<bool>),
    // Read-only, self-verifying original WAL+marker history. The response is
    // deliberately unsigned and cannot be used as an effect authorization.
    Observe(SyncSender<Result<MetricsLocalFrontierV1, MetricsJournalErrorV1>>),
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
        path: impl AsRef<Path>,
        capacity: usize,
        group_size: usize,
        flush_interval_ms: u64,
    ) -> Result<Self, MetricsJournalErrorV1> {
        if capacity == 0
            || capacity > MAX_QUEUE
            || group_size == 0
            || group_size > MAX_BATCH
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
            .spawn(move || {
                writer_loop(
                    writer,
                    rx,
                    observed,
                    group_size,
                    Duration::from_millis(flush_interval_ms),
                )
            })?;
        Ok(Self {
            channel: tx,
            health,
            worker: Mutex::new(Some(worker)),
        })
    }

    pub fn healthy(&self) -> bool {
        self.health.healthy.load(Ordering::Acquire)
            && self.health.dropped.load(Ordering::Acquire) == 0
    }

    pub fn dropped(&self) -> u64 {
        self.health.dropped.load(Ordering::Relaxed)
    }

    pub fn status(&self) -> PhaseMetricWriterStatusV1 {
        PhaseMetricWriterStatusV1 {
            healthy: self.healthy(),
            dropped: self.dropped(),
            persisted_batches: self.health.persisted_batches.load(Ordering::Acquire),
            persisted_rows: self.health.persisted_rows.load(Ordering::Acquire),
        }
    }

    /// Synchronous durability barrier, including bounded queue admission.
    /// A stalled writer/fsync must never hold a Split coordinator indefinitely.
    /// On timeout the sink stays unhealthy even if a delayed writer later ACKs:
    /// existing effects remain committed and their next-step gate fails closed.
    pub fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        self.flush_with_timeout(MAX_FLUSH_WAIT)
    }

    /// Read-only local Evidence frontier for independent Observer collection.
    /// It deliberately does not flush staged metrics, mint a signature, or
    /// confer any Cell Split authority. The caller must maintain own custody.
    pub fn read_local_frontier(&self) -> Result<MetricsLocalFrontierV1, PhaseMetricSinkErrorV1> {
        self.read_local_frontier_with_timeout(MAX_FLUSH_WAIT)
    }

    fn read_local_frontier_with_timeout(
        &self,
        timeout: Duration,
    ) -> Result<MetricsLocalFrontierV1, PhaseMetricSinkErrorV1> {
        if !self.healthy() {
            return Err(PhaseMetricSinkErrorV1::Unavailable);
        }
        let deadline = std::time::Instant::now() + timeout;
        let (tx, rx) = sync_channel(1);
        let mut command = WriterCommandV1::Observe(tx);
        loop {
            match self.channel.try_send(command) {
                Ok(()) => break,
                Err(TrySendError::Disconnected(_)) => {
                    self.health.healthy.store(false, Ordering::Release);
                    return Err(PhaseMetricSinkErrorV1::Unavailable);
                }
                Err(TrySendError::Full(pending)) => {
                    command = pending;
                    if !self.healthy() || std::time::Instant::now() >= deadline {
                        self.health.healthy.store(false, Ordering::Release);
                        return Err(PhaseMetricSinkErrorV1::Unavailable);
                    }
                    std::thread::sleep(
                        Duration::from_millis(1)
                            .min(deadline.saturating_duration_since(std::time::Instant::now())),
                    );
                }
            }
        }
        match rx.recv_timeout(deadline.saturating_duration_since(std::time::Instant::now())) {
            Ok(Ok(frontier)) if self.healthy() => Ok(frontier),
            _ => {
                self.health.healthy.store(false, Ordering::Release);
                Err(PhaseMetricSinkErrorV1::Unavailable)
            }
        }
    }

    fn flush_with_timeout(&self, timeout: Duration) -> Result<(), PhaseMetricSinkErrorV1> {
        if !self.healthy() {
            return Err(PhaseMetricSinkErrorV1::Unavailable);
        }
        let deadline = std::time::Instant::now() + timeout;
        let (tx, rx) = sync_channel(1);
        let mut command = WriterCommandV1::Flush(tx);
        loop {
            match self.channel.try_send(command) {
                Ok(()) => break,
                Err(TrySendError::Disconnected(_)) => {
                    self.health.healthy.store(false, Ordering::Release);
                    return Err(PhaseMetricSinkErrorV1::Unavailable);
                }
                Err(TrySendError::Full(pending)) => {
                    command = pending;
                    if !self.healthy() || std::time::Instant::now() >= deadline {
                        self.health.healthy.store(false, Ordering::Release);
                        return Err(PhaseMetricSinkErrorV1::Unavailable);
                    }
                    std::thread::sleep(
                        Duration::from_millis(1)
                            .min(deadline.saturating_duration_since(std::time::Instant::now())),
                    );
                }
            }
        }
        match rx.recv_timeout(deadline.saturating_duration_since(std::time::Instant::now())) {
            Ok(true) if self.healthy() => Ok(()),
            _ => {
                self.health.healthy.store(false, Ordering::Release);
                Err(PhaseMetricSinkErrorV1::Unavailable)
            }
        }
    }
}

impl PhaseMetricSinkV1 for DurablePhaseMetricSinkV1 {
    fn healthy(&self) -> bool {
        DurablePhaseMetricSinkV1::healthy(self)
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        DurablePhaseMetricSinkV1::flush(self)
    }

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
            PhaseMetricKindV1::Wal => MetricPhaseV1::Wal,
            PhaseMetricKindV1::NduRead => MetricPhaseV1::NduRead,
            PhaseMetricKindV1::FinalUse => MetricPhaseV1::FinalUse,
        };
        let sample = MetricSampleV1 {
            scope_digest: event.scope_digest,
            operation_digest: event.operation_digest,
            phase,
            latency_micros: event.latency_micros,
            succeeded: event.succeeded,
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

impl DurablePhaseMetricSinkV1 {
    fn stop_with_timeout(&mut self, timeout: Duration) {
        // Preserve the normal durable Drop barrier even when the bounded
        // channel is temporarily full. Detach only if the writer is already
        // unhealthy, disconnected or makes no progress by the deadline.
        if !self.healthy() {
            return;
        }
        let deadline = std::time::Instant::now() + timeout;
        let (tx, rx) = sync_channel(1);
        let mut command = WriterCommandV1::Stop(tx);
        loop {
            match self.channel.try_send(command) {
                Ok(()) => break,
                Err(TrySendError::Disconnected(_)) => {
                    self.health.healthy.store(false, Ordering::Release);
                    return;
                }
                Err(TrySendError::Full(pending)) => {
                    command = pending;
                    if !self.healthy() || std::time::Instant::now() >= deadline {
                        self.health.healthy.store(false, Ordering::Release);
                        return;
                    }
                    std::thread::sleep(
                        Duration::from_millis(1)
                            .min(deadline.saturating_duration_since(std::time::Instant::now())),
                    );
                }
            }
        }
        if rx
            .recv_timeout(deadline.saturating_duration_since(std::time::Instant::now()))
            .is_err()
        {
            // A timed-out writer remains in its own locked journal; never
            // falsely report a flush or block process teardown indefinitely.
            self.health.healthy.store(false, Ordering::Release);
            return;
        }
        if let Ok(mut handle) = self.worker.lock() {
            if let Some(worker) = handle.take() {
                let _ = worker.join();
            }
        }
    }
}

impl Drop for DurablePhaseMetricSinkV1 {
    fn drop(&mut self) {
        self.stop_with_timeout(MAX_FLUSH_WAIT);
    }
}

fn flush(
    writer: &mut MetricsGroupCommitV1,
    health: &WriterHealthV1,
) -> Result<(), MetricsJournalErrorV1> {
    if let Some(receipt) = writer.flush()? {
        health
            .persisted_rows
            .fetch_add(receipt.rows as u64, Ordering::Release);
        health.persisted_batches.fetch_add(1, Ordering::Release);
    }
    Ok(())
}

fn writer_loop(
    mut writer: MetricsGroupCommitV1,
    rx: Receiver<WriterCommandV1>,
    health: Arc<WriterHealthV1>,
    group_size: usize,
    interval: Duration,
) {
    loop {
        match rx.recv_timeout(interval) {
            Ok(WriterCommandV1::Record(sample)) => {
                let result = writer.stage(sample).and_then(|()| {
                    if writer.pending() >= group_size {
                        flush(&mut writer, &health)?;
                    }
                    Ok(())
                });
                if result.is_err() {
                    health.healthy.store(false, Ordering::Release);
                    break;
                }
            }
            Ok(WriterCommandV1::Flush(reply)) => {
                let ok = flush(&mut writer, &health).is_ok();
                if !ok {
                    health.healthy.store(false, Ordering::Release);
                }
                let _ = reply.send(ok);
                if !ok {
                    break;
                }
            }
            Ok(WriterCommandV1::Observe(reply)) => {
                let frontier = writer.read_local_frontier();
                let success = frontier.is_ok();
                if !success {
                    health.healthy.store(false, Ordering::Release);
                }
                let _ = reply.send(frontier);
                if !success {
                    break;
                }
            }
            Ok(WriterCommandV1::Stop(reply)) => {
                let ok = flush(&mut writer, &health).is_ok();
                if !ok {
                    health.healthy.store(false, Ordering::Release);
                }
                // The Stop ACK is the original WAL+marker lock handoff.
                // The next process must not reopen until BOTH owned fds
                // are dropped, even when flush already completed.
                drop(writer);
                let _ = reply.send(ok);
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if flush(&mut writer, &health).is_err() {
                    health.healthy.store(false, Ordering::Release);
                    break;
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
