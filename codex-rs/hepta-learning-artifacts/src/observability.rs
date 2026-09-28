//! Actionable owner telemetry and bounded stage measurement.
//!
//! These counters grant no authority and do not infer success from latency.
//! Callers explicitly share one metrics object across the host and read-side
//! consumers; there is no process-global registry or hidden mutable singleton.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use crate::ArtifactOwnerHostError;
use crate::LearningArtifactOwnerServiceError;
use crate::owner::ArtifactOwnerCommandError;
use crate::owner::OwnerJournalError;

const NONE_TIMESTAMP: u64 = u64::MAX;
pub const ARTIFACT_OWNER_STAGE_COUNT_V1: usize = 12;
const LATENCY_BUCKET_UPPER_MICROS: [u64; 24] = [
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1_000,
    2_000,
    4_000,
    8_000,
    16_000,
    32_000,
    64_000,
    125_000,
    250_000,
    500_000,
    1_000_000,
    5_000_000,
    60_000_000,
    u64::MAX,
];

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerStageV1 {
    PayloadEncodeHash,
    PayloadWriteSync,
    CurrentHeadSwitch,
    CheckpointSync,
    StartupRecoveryScan,
    PinnedLoad,
    PublicationTotal,
    RecoveryReconciliation,
    RequestDispatch,
    WithdrawalPersistence,
    Backup,
    DrainTransition,
}

impl ArtifactOwnerStageV1 {
    pub const ALL: [Self; ARTIFACT_OWNER_STAGE_COUNT_V1] = [
        Self::PayloadEncodeHash,
        Self::PayloadWriteSync,
        Self::CurrentHeadSwitch,
        Self::CheckpointSync,
        Self::StartupRecoveryScan,
        Self::PinnedLoad,
        Self::PublicationTotal,
        Self::RecoveryReconciliation,
        Self::RequestDispatch,
        Self::WithdrawalPersistence,
        Self::Backup,
        Self::DrainTransition,
    ];

    const fn index(self) -> usize {
        match self {
            Self::PayloadEncodeHash => 0,
            Self::PayloadWriteSync => 1,
            Self::CurrentHeadSwitch => 2,
            Self::CheckpointSync => 3,
            Self::StartupRecoveryScan => 4,
            Self::PinnedLoad => 5,
            Self::PublicationTotal => 6,
            Self::RecoveryReconciliation => 7,
            Self::RequestDispatch => 8,
            Self::WithdrawalPersistence => 9,
            Self::Backup => 10,
            Self::DrainTransition => 11,
        }
    }

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PayloadEncodeHash => "payload_encode_hash",
            Self::PayloadWriteSync => "payload_write_sync",
            Self::CurrentHeadSwitch => "current_head_switch",
            Self::CheckpointSync => "checkpoint_sync",
            Self::StartupRecoveryScan => "startup_recovery_scan",
            Self::PinnedLoad => "pinned_load",
            Self::PublicationTotal => "publication_total",
            Self::RecoveryReconciliation => "recovery_reconciliation",
            Self::RequestDispatch => "request_dispatch",
            Self::WithdrawalPersistence => "withdrawal_persistence",
            Self::Backup => "backup",
            Self::DrainTransition => "drain_transition",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerLatencySnapshotV1 {
    pub stage: ArtifactOwnerStageV1,
    pub samples: u64,
    pub total_micros: u64,
    pub maximum_micros: u64,
    pub p50_upper_micros: u64,
    pub p95_upper_micros: u64,
    pub p99_upper_micros: u64,
}

#[derive(Debug)]
struct LatencyHistogramV1 {
    buckets: [AtomicU64; LATENCY_BUCKET_UPPER_MICROS.len()],
    samples: AtomicU64,
    total_micros: AtomicU64,
    maximum_micros: AtomicU64,
}

impl Default for LatencyHistogramV1 {
    fn default() -> Self {
        Self {
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
            samples: AtomicU64::new(0),
            total_micros: AtomicU64::new(0),
            maximum_micros: AtomicU64::new(0),
        }
    }
}

impl LatencyHistogramV1 {
    fn record(&self, elapsed: Duration) {
        let micros = elapsed.as_micros().min(u128::from(u64::MAX)) as u64;
        saturating_add(&self.samples, 1);
        saturating_add(&self.total_micros, micros);
        update_maximum(&self.maximum_micros, micros);
        let bucket = LATENCY_BUCKET_UPPER_MICROS
            .iter()
            .position(|upper| micros <= *upper)
            .unwrap_or(LATENCY_BUCKET_UPPER_MICROS.len() - 1);
        saturating_add(&self.buckets[bucket], 1);
    }

    fn snapshot(&self, stage: ArtifactOwnerStageV1) -> ArtifactOwnerLatencySnapshotV1 {
        let samples = self.samples.load(Ordering::Relaxed);
        let maximum_micros = self.maximum_micros.load(Ordering::Relaxed);
        ArtifactOwnerLatencySnapshotV1 {
            stage,
            samples,
            total_micros: self.total_micros.load(Ordering::Relaxed),
            maximum_micros,
            p50_upper_micros: self.percentile(samples, 50, maximum_micros),
            p95_upper_micros: self.percentile(samples, 95, maximum_micros),
            p99_upper_micros: self.percentile(samples, 99, maximum_micros),
        }
    }

    fn percentile(&self, samples: u64, percent: u64, maximum_micros: u64) -> u64 {
        if samples == 0 {
            return 0;
        }
        let target = samples
            .saturating_mul(percent)
            .saturating_add(99)
            .checked_div(100)
            .unwrap_or(samples)
            .max(1);
        let mut observed = 0u64;
        for (index, counter) in self.buckets.iter().enumerate() {
            observed = observed.saturating_add(counter.load(Ordering::Relaxed));
            if observed >= target {
                let upper = LATENCY_BUCKET_UPPER_MICROS[index];
                return if upper == u64::MAX {
                    maximum_micros
                } else {
                    upper
                };
            }
        }
        maximum_micros
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerFailureClassV1 {
    IdentityConflict,
    StaleOwner,
    WithdrawalFrontier,
    PersistenceUnknown,
    Capacity,
    RecoveryRequired,
    Draining,
    Busy,
    NotReady,
    InvalidConfiguration,
    CorruptDurableState,
    UnauthorizedOrIntegrity,
    PublicationRejected,
    InternalInvariant,
}

impl ArtifactOwnerFailureClassV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontier => "withdrawal_frontier_conflict",
            Self::PersistenceUnknown => "persistence_unknown",
            Self::Capacity => "capacity_exhausted",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::Busy => "writer_busy",
            Self::NotReady => "not_ready",
            Self::InvalidConfiguration => "invalid_configuration",
            Self::CorruptDurableState => "corrupt_durable_state",
            Self::UnauthorizedOrIntegrity => "unauthorized_or_integrity",
            Self::PublicationRejected => "publication_rejected",
            Self::InternalInvariant => "internal_invariant",
        }
    }
}

impl LearningArtifactOwnerServiceError {
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        self.failure_class().as_str()
    }

    #[must_use]
    pub fn failure_class(&self) -> ArtifactOwnerFailureClassV1 {
        match self {
            Self::Host(error) => classify_host_error(error),
            Self::Publication(_) => ArtifactOwnerFailureClassV1::PublicationRejected,
            Self::ControlIo(_) | Self::WithdrawalDurabilityUnknown => {
                ArtifactOwnerFailureClassV1::PersistenceUnknown
            }
            Self::InvalidConfiguration => ArtifactOwnerFailureClassV1::InvalidConfiguration,
            Self::WithdrawalFrontierConflict => {
                ArtifactOwnerFailureClassV1::WithdrawalFrontier
            }
            Self::RecoveryConflict | Self::RecoveryRequired(_) => {
                ArtifactOwnerFailureClassV1::RecoveryRequired
            }
            Self::RequestMismatch => ArtifactOwnerFailureClassV1::IdentityConflict,
            Self::CheckpointShape | Self::CheckpointMismatch => {
                ArtifactOwnerFailureClassV1::CorruptDurableState
            }
            Self::UnexpectedPhase => ArtifactOwnerFailureClassV1::InternalInvariant,
            Self::Draining => ArtifactOwnerFailureClassV1::Draining,
        }
    }
}

impl ArtifactOwnerCommandError {
    #[must_use]
    pub fn operational_code(&self) -> &'static str {
        self.failure_class().as_str()
    }

    #[must_use]
    pub fn failure_class(&self) -> ArtifactOwnerFailureClassV1 {
        match self {
            Self::Service(error) => error.failure_class(),
            Self::Config(_) => ArtifactOwnerFailureClassV1::InvalidConfiguration,
            Self::Capability(_) => ArtifactOwnerFailureClassV1::UnauthorizedOrIntegrity,
            Self::Journal(OwnerJournalError::ReplayConflict) => {
                ArtifactOwnerFailureClassV1::IdentityConflict
            }
            Self::Journal(_) | Self::Status(_) | Self::Io(_) => {
                ArtifactOwnerFailureClassV1::PersistenceUnknown
            }
            Self::Decode(_)
            | Self::Admission(_)
            | Self::Storage(_)
            | Self::RequestTimeMismatch
            | Self::UnexpectedPayload
            | Self::SnapshotPath => ArtifactOwnerFailureClassV1::IdentityConflict,
            Self::Reconciliation(_) | Self::RecoveryOperationMismatch => {
                ArtifactOwnerFailureClassV1::RecoveryRequired
            }
            Self::Owner(_) | Self::Poisoned | Self::InvalidState => {
                ArtifactOwnerFailureClassV1::InternalInvariant
            }
            Self::NotReady | Self::RecoveryNotRequired => {
                ArtifactOwnerFailureClassV1::NotReady
            }
            Self::KeyringRollback => ArtifactOwnerFailureClassV1::StaleOwner,
        }
    }
}

fn classify_host_error(error: &ArtifactOwnerHostError) -> ArtifactOwnerFailureClassV1 {
    match error {
        ArtifactOwnerHostError::Capacity => ArtifactOwnerFailureClassV1::Capacity,
        ArtifactOwnerHostError::Indeterminate | ArtifactOwnerHostError::Io(_) => {
            ArtifactOwnerFailureClassV1::PersistenceUnknown
        }
        ArtifactOwnerHostError::WriterFenceBusy => ArtifactOwnerFailureClassV1::Busy,
        ArtifactOwnerHostError::SignerContext
        | ArtifactOwnerHostError::SignerRevoked
        | ArtifactOwnerHostError::WriterLeaseContext
        | ArtifactOwnerHostError::CurrentHeadExpired
        | ArtifactOwnerHostError::CurrentHeadRollback => {
            ArtifactOwnerFailureClassV1::StaleOwner
        }
        ArtifactOwnerHostError::RegistryPredecessorMismatch
        | ArtifactOwnerHostError::CurrentHeadConflict
        | ArtifactOwnerHostError::CurrentHeadFork
        | ArtifactOwnerHostError::IdentityConflict => {
            ArtifactOwnerFailureClassV1::IdentityConflict
        }
        ArtifactOwnerHostError::CheckpointMissing
        | ArtifactOwnerHostError::CheckpointGap => {
            ArtifactOwnerFailureClassV1::RecoveryRequired
        }
        ArtifactOwnerHostError::CheckpointMismatch => {
            ArtifactOwnerFailureClassV1::CorruptDurableState
        }
        ArtifactOwnerHostError::InvalidTrust
        | ArtifactOwnerHostError::InvalidKey
        | ArtifactOwnerHostError::UnknownSigner
        | ArtifactOwnerHostError::InvalidSignature
        | ArtifactOwnerHostError::CurrentHeadContext
        | ArtifactOwnerHostError::PathBoundary => {
            ArtifactOwnerFailureClassV1::UnauthorizedOrIntegrity
        }
        ArtifactOwnerHostError::Storage(_)
        | ArtifactOwnerHostError::Publication(_)
        | ArtifactOwnerHostError::Registry(_) => {
            ArtifactOwnerFailureClassV1::PublicationRejected
        }
        ArtifactOwnerHostError::InternalInvariant => {
            ArtifactOwnerFailureClassV1::InternalInvariant
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerOperationalSnapshotV1 {
    pub stage_latencies: [ArtifactOwnerLatencySnapshotV1; ARTIFACT_OWNER_STAGE_COUNT_V1],
    pub oldest_pending_attempt_age_seconds: Option<u64>,
    pub withdrawal_block_duration_seconds: Option<u64>,
    pub drain_duration_seconds: Option<u64>,
    pub identity_conflicts: u64,
    pub stale_owner_rejections: u64,
    pub withdrawal_blocks: u64,
    pub persistence_unknown_events: u64,
    pub capacity_rejections: u64,
    pub recovery_reconciliation_failures: u64,
    pub owner_epoch_conflicts: u64,
    pub withdrawal_epoch_conflicts: u64,
    pub current_pinned_bytes: u64,
    pub peak_pinned_bytes: u64,
    pub pending_erasure_bytes: u64,
}

#[derive(Debug)]
pub struct ArtifactOwnerOperationalMetricsV1 {
    stage_latencies: [LatencyHistogramV1; ARTIFACT_OWNER_STAGE_COUNT_V1],
    oldest_pending_started_at: AtomicU64,
    withdrawal_blocked_since: AtomicU64,
    drain_started_at: AtomicU64,
    identity_conflicts: AtomicU64,
    stale_owner_rejections: AtomicU64,
    withdrawal_blocks: AtomicU64,
    persistence_unknown_events: AtomicU64,
    capacity_rejections: AtomicU64,
    recovery_reconciliation_failures: AtomicU64,
    owner_epoch_conflicts: AtomicU64,
    withdrawal_epoch_conflicts: AtomicU64,
    current_pinned_bytes: AtomicU64,
    peak_pinned_bytes: AtomicU64,
    pending_erasure_bytes: AtomicU64,
}

impl Default for ArtifactOwnerOperationalMetricsV1 {
    fn default() -> Self {
        Self {
            stage_latencies: std::array::from_fn(|_| LatencyHistogramV1::default()),
            oldest_pending_started_at: AtomicU64::new(NONE_TIMESTAMP),
            withdrawal_blocked_since: AtomicU64::new(NONE_TIMESTAMP),
            drain_started_at: AtomicU64::new(NONE_TIMESTAMP),
            identity_conflicts: AtomicU64::new(0),
            stale_owner_rejections: AtomicU64::new(0),
            withdrawal_blocks: AtomicU64::new(0),
            persistence_unknown_events: AtomicU64::new(0),
            capacity_rejections: AtomicU64::new(0),
            recovery_reconciliation_failures: AtomicU64::new(0),
            owner_epoch_conflicts: AtomicU64::new(0),
            withdrawal_epoch_conflicts: AtomicU64::new(0),
            current_pinned_bytes: AtomicU64::new(0),
            peak_pinned_bytes: AtomicU64::new(0),
            pending_erasure_bytes: AtomicU64::new(0),
        }
    }
}

impl ArtifactOwnerOperationalMetricsV1 {
    pub fn record_stage(&self, stage: ArtifactOwnerStageV1, elapsed: Duration) {
        self.stage_latencies[stage.index()].record(elapsed);
    }

    #[must_use]
    pub fn start_stage(&self, stage: ArtifactOwnerStageV1) -> ArtifactOwnerStageTimerV1<'_> {
        ArtifactOwnerStageTimerV1 {
            metrics: self,
            stage,
            started: Instant::now(),
        }
    }

    pub fn observe_failure(&self, failure: ArtifactOwnerFailureClassV1, now: u64) {
        match failure {
            ArtifactOwnerFailureClassV1::IdentityConflict => {
                saturating_add(&self.identity_conflicts, 1);
            }
            ArtifactOwnerFailureClassV1::StaleOwner => {
                saturating_add(&self.stale_owner_rejections, 1);
                saturating_add(&self.owner_epoch_conflicts, 1);
            }
            ArtifactOwnerFailureClassV1::WithdrawalFrontier => {
                saturating_add(&self.withdrawal_blocks, 1);
                saturating_add(&self.withdrawal_epoch_conflicts, 1);
                set_earliest(&self.withdrawal_blocked_since, now);
            }
            ArtifactOwnerFailureClassV1::PersistenceUnknown => {
                saturating_add(&self.persistence_unknown_events, 1);
            }
            ArtifactOwnerFailureClassV1::Capacity => {
                saturating_add(&self.capacity_rejections, 1);
            }
            ArtifactOwnerFailureClassV1::RecoveryRequired
            | ArtifactOwnerFailureClassV1::CorruptDurableState => {
                saturating_add(&self.recovery_reconciliation_failures, 1);
                set_earliest(&self.oldest_pending_started_at, now);
            }
            ArtifactOwnerFailureClassV1::Draining
            | ArtifactOwnerFailureClassV1::Busy
            | ArtifactOwnerFailureClassV1::NotReady
            | ArtifactOwnerFailureClassV1::InvalidConfiguration
            | ArtifactOwnerFailureClassV1::UnauthorizedOrIntegrity
            | ArtifactOwnerFailureClassV1::PublicationRejected
            | ArtifactOwnerFailureClassV1::InternalInvariant => {}
        }
    }

    pub fn mark_pending_attempt(&self, started_at: u64) {
        set_earliest(&self.oldest_pending_started_at, started_at);
    }

    pub fn clear_pending_attempts(&self) {
        self.oldest_pending_started_at
            .store(NONE_TIMESTAMP, Ordering::Release);
    }

    pub fn clear_withdrawal_block(&self) {
        self.withdrawal_blocked_since
            .store(NONE_TIMESTAMP, Ordering::Release);
    }

    pub fn begin_drain(&self, started_at: u64) {
        set_earliest(&self.drain_started_at, started_at);
    }

    pub fn finish_drain(&self) {
        self.drain_started_at
            .store(NONE_TIMESTAMP, Ordering::Release);
    }

    pub fn note_reconciliation_failure(&self, now: u64) {
        saturating_add(&self.recovery_reconciliation_failures, 1);
        set_earliest(&self.oldest_pending_started_at, now);
    }

    pub fn note_owner_epoch_conflict(&self) {
        saturating_add(&self.owner_epoch_conflicts, 1);
    }

    pub fn note_withdrawal_epoch_conflict(&self, now: u64) {
        saturating_add(&self.withdrawal_epoch_conflicts, 1);
        saturating_add(&self.withdrawal_blocks, 1);
        set_earliest(&self.withdrawal_blocked_since, now);
    }

    pub fn track_pinned_bytes(
        self: &Arc<Self>,
        bytes: u64,
    ) -> Result<ArtifactPinLeaseV1, ArtifactByteAccountingError> {
        if bytes == 0 {
            return Err(ArtifactByteAccountingError::ZeroBytes);
        }
        let current = checked_add(&self.current_pinned_bytes, bytes)?;
        update_maximum(&self.peak_pinned_bytes, current);
        Ok(ArtifactPinLeaseV1 {
            metrics: Arc::clone(self),
            bytes,
            released: false,
        })
    }

    pub fn reserve_erasure_bytes(
        &self,
        bytes: u64,
    ) -> Result<(), ArtifactByteAccountingError> {
        if bytes == 0 {
            return Err(ArtifactByteAccountingError::ZeroBytes);
        }
        checked_add(&self.pending_erasure_bytes, bytes).map(|_| ())
    }

    pub fn complete_erasure_bytes(
        &self,
        bytes: u64,
    ) -> Result<(), ArtifactByteAccountingError> {
        if bytes == 0 {
            return Err(ArtifactByteAccountingError::ZeroBytes);
        }
        checked_subtract(&self.pending_erasure_bytes, bytes)
    }

    #[must_use]
    pub fn snapshot(&self, now: u64) -> ArtifactOwnerOperationalSnapshotV1 {
        ArtifactOwnerOperationalSnapshotV1 {
            stage_latencies: std::array::from_fn(|index| {
                let stage = ArtifactOwnerStageV1::ALL[index];
                self.stage_latencies[index].snapshot(stage)
            }),
            oldest_pending_attempt_age_seconds: age_seconds(
                now,
                self.oldest_pending_started_at.load(Ordering::Acquire),
            ),
            withdrawal_block_duration_seconds: age_seconds(
                now,
                self.withdrawal_blocked_since.load(Ordering::Acquire),
            ),
            drain_duration_seconds: age_seconds(
                now,
                self.drain_started_at.load(Ordering::Acquire),
            ),
            identity_conflicts: self.identity_conflicts.load(Ordering::Relaxed),
            stale_owner_rejections: self.stale_owner_rejections.load(Ordering::Relaxed),
            withdrawal_blocks: self.withdrawal_blocks.load(Ordering::Relaxed),
            persistence_unknown_events: self
                .persistence_unknown_events
                .load(Ordering::Relaxed),
            capacity_rejections: self.capacity_rejections.load(Ordering::Relaxed),
            recovery_reconciliation_failures: self
                .recovery_reconciliation_failures
                .load(Ordering::Relaxed),
            owner_epoch_conflicts: self.owner_epoch_conflicts.load(Ordering::Relaxed),
            withdrawal_epoch_conflicts: self
                .withdrawal_epoch_conflicts
                .load(Ordering::Relaxed),
            current_pinned_bytes: self.current_pinned_bytes.load(Ordering::Acquire),
            peak_pinned_bytes: self.peak_pinned_bytes.load(Ordering::Relaxed),
            pending_erasure_bytes: self.pending_erasure_bytes.load(Ordering::Acquire),
        }
    }
}

pub struct ArtifactOwnerStageTimerV1<'a> {
    metrics: &'a ArtifactOwnerOperationalMetricsV1,
    stage: ArtifactOwnerStageV1,
    started: Instant,
}

impl Drop for ArtifactOwnerStageTimerV1<'_> {
    fn drop(&mut self) {
        self.metrics.record_stage(self.stage, self.started.elapsed());
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactByteAccountingError {
    ZeroBytes,
    Overflow,
    Underflow,
}

pub struct ArtifactPinLeaseV1 {
    metrics: Arc<ArtifactOwnerOperationalMetricsV1>,
    bytes: u64,
    released: bool,
}

impl ArtifactPinLeaseV1 {
    #[must_use]
    pub const fn bytes(&self) -> u64 {
        self.bytes
    }

    pub fn release(mut self) -> Result<(), ArtifactByteAccountingError> {
        checked_subtract(&self.metrics.current_pinned_bytes, self.bytes)?;
        self.released = true;
        Ok(())
    }
}

impl Drop for ArtifactPinLeaseV1 {
    fn drop(&mut self) {
        if self.released {
            return;
        }
        if checked_subtract(&self.metrics.current_pinned_bytes, self.bytes).is_err() {
            saturating_add(&self.metrics.recovery_reconciliation_failures, 1);
        }
        self.released = true;
    }
}

pub fn measure_artifact_owner_stage<T, E>(
    metrics: &ArtifactOwnerOperationalMetricsV1,
    stage: ArtifactOwnerStageV1,
    operation: impl FnOnce() -> Result<T, E>,
) -> Result<T, E> {
    let _timer = metrics.start_stage(stage);
    operation()
}

fn checked_add(counter: &AtomicU64, value: u64) -> Result<u64, ArtifactByteAccountingError> {
    let mut current = counter.load(Ordering::Acquire);
    loop {
        let next = current
            .checked_add(value)
            .ok_or(ArtifactByteAccountingError::Overflow)?;
        match counter.compare_exchange_weak(
            current,
            next,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return Ok(next),
            Err(observed) => current = observed,
        }
    }
}

fn checked_subtract(
    counter: &AtomicU64,
    value: u64,
) -> Result<(), ArtifactByteAccountingError> {
    let mut current = counter.load(Ordering::Acquire);
    loop {
        let next = current
            .checked_sub(value)
            .ok_or(ArtifactByteAccountingError::Underflow)?;
        match counter.compare_exchange_weak(
            current,
            next,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return Ok(()),
            Err(observed) => current = observed,
        }
    }
}

fn saturating_add(counter: &AtomicU64, value: u64) {
    let mut current = counter.load(Ordering::Relaxed);
    loop {
        let next = current.saturating_add(value);
        match counter.compare_exchange_weak(
            current,
            next,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

fn update_maximum(counter: &AtomicU64, candidate: u64) {
    let mut current = counter.load(Ordering::Relaxed);
    while candidate > current {
        match counter.compare_exchange_weak(
            current,
            candidate,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

fn set_earliest(counter: &AtomicU64, candidate: u64) {
    let mut current = counter.load(Ordering::Acquire);
    while current == NONE_TIMESTAMP || candidate < current {
        match counter.compare_exchange_weak(
            current,
            candidate,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

fn age_seconds(now: u64, since: u64) -> Option<u64> {
    (since != NONE_TIMESTAMP).then(|| now.saturating_sub(since))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stage_histogram_reports_bounded_percentiles() {
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        metrics.record_stage(
            ArtifactOwnerStageV1::PayloadEncodeHash,
            Duration::from_micros(3),
        );
        metrics.record_stage(
            ArtifactOwnerStageV1::PayloadEncodeHash,
            Duration::from_micros(900),
        );
        let snapshot = metrics.snapshot(10);
        let latency = snapshot.stage_latencies[ArtifactOwnerStageV1::PayloadEncodeHash.index()];
        assert_eq!(latency.samples, 2);
        assert_eq!(latency.maximum_micros, 900);
        assert!(latency.p50_upper_micros >= 3);
        assert!(latency.p99_upper_micros >= 900);
    }

    #[test]
    fn pinned_and_erasure_bytes_are_not_reported_released_early() {
        let metrics = Arc::new(ArtifactOwnerOperationalMetricsV1::default());
        let lease = metrics.track_pinned_bytes(128).expect("pin");
        metrics.reserve_erasure_bytes(64).expect("reserve erasure");
        let snapshot = metrics.snapshot(10);
        assert_eq!(snapshot.current_pinned_bytes, 128);
        assert_eq!(snapshot.peak_pinned_bytes, 128);
        assert_eq!(snapshot.pending_erasure_bytes, 64);
        assert_eq!(
            metrics.complete_erasure_bytes(65),
            Err(ArtifactByteAccountingError::Underflow)
        );
        lease.release().expect("release pin");
        metrics.complete_erasure_bytes(64).expect("complete erasure");
        let snapshot = metrics.snapshot(10);
        assert_eq!(snapshot.current_pinned_bytes, 0);
        assert_eq!(snapshot.pending_erasure_bytes, 0);
    }

    #[test]
    fn operational_ages_answer_why_the_owner_is_blocked() {
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        metrics.mark_pending_attempt(10);
        metrics.note_withdrawal_epoch_conflict(12);
        metrics.begin_drain(14);
        let snapshot = metrics.snapshot(20);
        assert_eq!(snapshot.oldest_pending_attempt_age_seconds, Some(10));
        assert_eq!(snapshot.withdrawal_block_duration_seconds, Some(8));
        assert_eq!(snapshot.drain_duration_seconds, Some(6));
        assert_eq!(snapshot.withdrawal_epoch_conflicts, 1);
    }

    #[test]
    fn service_errors_have_stable_actionable_classes() {
        assert_eq!(
            LearningArtifactOwnerServiceError::RequestMismatch.stable_code(),
            "identity_conflict"
        );
        assert_eq!(
            LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown.stable_code(),
            "persistence_unknown"
        );
        assert_eq!(
            LearningArtifactOwnerServiceError::Draining.stable_code(),
            "draining"
        );
    }
}
