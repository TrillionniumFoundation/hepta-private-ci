//! Actionable owner error classification and bounded stage measurement.
//!
//! These types are observations only. They never grant publication, selection,
//! activation, promotion or release authority and they never turn an unknown
//! persistence result into success.

use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactClosureError;
use crate::ArtifactOwnerHostError;
use crate::ArtifactPinMetricsV1;
use crate::ArtifactPublicationError;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;

const STAGE_COUNT: usize = 8;
const BUCKET_COUNT: usize = 10;

/// Upper bounds for the non-cumulative latency buckets, in microseconds.
pub const ARTIFACT_STAGE_BUCKET_UPPER_BOUNDS_MICROS_V1: [u64; BUCKET_COUNT] = [
    100,
    500,
    1_000,
    5_000,
    10_000,
    50_000,
    100_000,
    500_000,
    1_000_000,
    u64::MAX,
];

/// Stable operational failure categories for callers and alerts.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerFailureClassV1 {
    IdentityConflict,
    StaleOwner,
    WithdrawalFrontier,
    PersistenceUnknown,
    Capacity,
    RecoveryRequired,
    Draining,
    InvalidRequest,
    Internal,
}

impl ArtifactOwnerFailureClassV1 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontier => "withdrawal_frontier",
            Self::PersistenceUnknown => "persistence_unknown",
            Self::Capacity => "capacity",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::InvalidRequest => "invalid_request",
            Self::Internal => "internal",
        }
    }
}

/// Retry action attached to a stable failure class.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerRetryDispositionV1 {
    Never,
    ExactSameRequest,
    ReconcileThenRetryExact,
    AfterFreshAuthority,
    AfterCapacityRelief,
}

/// Classifies owner-service errors without erasing their original detail.
pub trait ArtifactOwnerErrorClassificationV1 {
    fn failure_class_v1(&self) -> ArtifactOwnerFailureClassV1;

    fn retry_disposition_v1(&self) -> ArtifactOwnerRetryDispositionV1 {
        match self.failure_class_v1() {
            ArtifactOwnerFailureClassV1::IdentityConflict
            | ArtifactOwnerFailureClassV1::Draining
            | ArtifactOwnerFailureClassV1::InvalidRequest => {
                ArtifactOwnerRetryDispositionV1::Never
            }
            ArtifactOwnerFailureClassV1::StaleOwner
            | ArtifactOwnerFailureClassV1::WithdrawalFrontier => {
                ArtifactOwnerRetryDispositionV1::AfterFreshAuthority
            }
            ArtifactOwnerFailureClassV1::PersistenceUnknown
            | ArtifactOwnerFailureClassV1::Internal => {
                ArtifactOwnerRetryDispositionV1::ReconcileThenRetryExact
            }
            ArtifactOwnerFailureClassV1::Capacity => {
                ArtifactOwnerRetryDispositionV1::AfterCapacityRelief
            }
            ArtifactOwnerFailureClassV1::RecoveryRequired => {
                ArtifactOwnerRetryDispositionV1::ExactSameRequest
            }
        }
    }
}

impl ArtifactOwnerErrorClassificationV1 for LearningArtifactOwnerServiceError {
    fn failure_class_v1(&self) -> ArtifactOwnerFailureClassV1 {
        match self {
            Self::RequestMismatch
            | Self::CheckpointMismatch
            | Self::Host(
                ArtifactOwnerHostError::IdentityConflict
                | ArtifactOwnerHostError::CheckpointMismatch
                | ArtifactOwnerHostError::RegistryPredecessorMismatch
                | ArtifactOwnerHostError::CurrentHeadConflict
                | ArtifactOwnerHostError::CurrentHeadFork,
            ) => ArtifactOwnerFailureClassV1::IdentityConflict,
            Self::Host(
                ArtifactOwnerHostError::WriterLeaseContext
                | ArtifactOwnerHostError::SignerContext
                | ArtifactOwnerHostError::SignerRevoked
                | ArtifactOwnerHostError::CurrentHeadExpired
                | ArtifactOwnerHostError::CurrentHeadRollback,
            ) => ArtifactOwnerFailureClassV1::StaleOwner,
            Self::WithdrawalFrontierConflict
            | Self::Publication(ArtifactPublicationError::Admission(
                ArtifactAdmissionError::WithdrawalScopeRequired
                | ArtifactAdmissionError::WithdrawalScopeChanged
                | ArtifactAdmissionError::WithdrawalHeadChanged,
            ))
            | Self::Publication(ArtifactPublicationError::Admission(
                ArtifactAdmissionError::Manifest(ArtifactClosureError::WithdrawnDataset),
            )) => ArtifactOwnerFailureClassV1::WithdrawalFrontier,
            Self::WithdrawalDurabilityUnknown
            | Self::ControlIo(_)
            | Self::Host(ArtifactOwnerHostError::Indeterminate | ArtifactOwnerHostError::Io(_)) => {
                ArtifactOwnerFailureClassV1::PersistenceUnknown
            }
            Self::Host(ArtifactOwnerHostError::Capacity) => ArtifactOwnerFailureClassV1::Capacity,
            Self::RecoveryConflict
            | Self::RecoveryRequired(_)
            | Self::CheckpointShape
            | Self::Host(
                ArtifactOwnerHostError::CheckpointGap
                | ArtifactOwnerHostError::CheckpointMissing,
            ) => ArtifactOwnerFailureClassV1::RecoveryRequired,
            Self::Draining => ArtifactOwnerFailureClassV1::Draining,
            Self::InvalidConfiguration
            | Self::UnexpectedPhase
            | Self::Publication(
                ArtifactPublicationError::PayloadMismatch
                | ArtifactPublicationError::RegistryProjectionMismatch
                | ArtifactPublicationError::RegistryReceiptMismatch
                | ArtifactPublicationError::WitnessReceiptMismatch
                | ArtifactPublicationError::AcknowledgementTime
                | ArtifactPublicationError::InvalidPhase
                | ArtifactPublicationError::SnapshotMismatch
                | ArtifactPublicationError::RegistryPredecessorMismatch,
            ) => ArtifactOwnerFailureClassV1::InvalidRequest,
            Self::Publication(ArtifactPublicationError::Admission(_))
            | Self::Publication(ArtifactPublicationError::InternalInvariant)
            | Self::Host(_) => ArtifactOwnerFailureClassV1::Internal,
        }
    }
}

/// Stages whose latency should be measured independently.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerStageV1 {
    StartupRecovery,
    RequestPreflight,
    PayloadEncodeHash,
    PayloadWriteSync,
    RegistryWriteSync,
    CurrentHeadSwitch,
    CheckpointSync,
    PinnedReadRevalidation,
}

impl ArtifactOwnerStageV1 {
    const fn index(self) -> usize {
        match self {
            Self::StartupRecovery => 0,
            Self::RequestPreflight => 1,
            Self::PayloadEncodeHash => 2,
            Self::PayloadWriteSync => 3,
            Self::RegistryWriteSync => 4,
            Self::CurrentHeadSwitch => 5,
            Self::CheckpointSync => 6,
            Self::PinnedReadRevalidation => 7,
        }
    }

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::StartupRecovery => "startup_recovery",
            Self::RequestPreflight => "request_preflight",
            Self::PayloadEncodeHash => "payload_encode_hash",
            Self::PayloadWriteSync => "payload_write_sync",
            Self::RegistryWriteSync => "registry_write_sync",
            Self::CurrentHeadSwitch => "current_head_switch",
            Self::CheckpointSync => "checkpoint_sync",
            Self::PinnedReadRevalidation => "pinned_read_revalidation",
        }
    }
}

/// Bounded non-cumulative histogram for one owner stage.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactStageHistogramV1 {
    pub count: u64,
    pub total_micros: u64,
    pub max_micros: u64,
    pub buckets: [u64; BUCKET_COUNT],
}

impl ArtifactStageHistogramV1 {
    fn record(&mut self, micros: u64) {
        self.count = self.count.saturating_add(1);
        self.total_micros = self.total_micros.saturating_add(micros);
        self.max_micros = self.max_micros.max(micros);
        let index = ARTIFACT_STAGE_BUCKET_UPPER_BOUNDS_MICROS_V1
            .iter()
            .position(|bound| micros <= *bound)
            .unwrap_or(BUCKET_COUNT - 1);
        self.buckets[index] = self.buckets[index].saturating_add(1);
    }
}

/// Snapshot of all bounded stage histograms.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerStageMetricsV1 {
    histograms: [ArtifactStageHistogramV1; STAGE_COUNT],
}

impl ArtifactOwnerStageMetricsV1 {
    #[must_use]
    pub const fn histogram(
        &self,
        stage: ArtifactOwnerStageV1,
    ) -> ArtifactStageHistogramV1 {
        self.histograms[stage.index()]
    }
}

/// Thread-safe stage recorder. It records observations; it never changes policy.
#[derive(Debug, Default)]
pub struct ArtifactOwnerStageRecorderV1 {
    metrics: Mutex<ArtifactOwnerStageMetricsV1>,
}

impl ArtifactOwnerStageRecorderV1 {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            metrics: Mutex::new(ArtifactOwnerStageMetricsV1 {
                histograms: [ArtifactStageHistogramV1 {
                    count: 0,
                    total_micros: 0,
                    max_micros: 0,
                    buckets: [0; BUCKET_COUNT],
                }; STAGE_COUNT],
            }),
        }
    }

    pub fn record(&self, stage: ArtifactOwnerStageV1, duration: Duration) {
        let micros = u64::try_from(duration.as_micros()).unwrap_or(u64::MAX);
        let mut metrics = match self.metrics.lock() {
            Ok(metrics) => metrics,
            Err(poisoned) => poisoned.into_inner(),
        };
        metrics.histograms[stage.index()].record(micros);
    }

    pub fn measure<T>(
        &self,
        stage: ArtifactOwnerStageV1,
        operation: impl FnOnce() -> T,
    ) -> T {
        let started = Instant::now();
        let result = operation();
        self.record(stage, started.elapsed());
        result
    }

    #[must_use]
    pub fn snapshot(&self) -> ArtifactOwnerStageMetricsV1 {
        match self.metrics.lock() {
            Ok(metrics) => *metrics,
            Err(poisoned) => *poisoned.into_inner(),
        }
    }
}

/// Point-in-time state that answers why the owner is not ready or erasable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerOperationalSnapshotV1 {
    pub observed_at: u64,
    pub registry_records: usize,
    pub withdrawal_records: usize,
    pub recovery_operation_id: Option<StableId>,
    pub withdrawal_frontier_durable: bool,
    pub durable_drain_requested: bool,
    pub drained: bool,
    pub pin_metrics: ArtifactPinMetricsV1,
    pub stage_metrics: ArtifactOwnerStageMetricsV1,
}

/// Builds an operational snapshot from the authoritative service plus explicit
/// process-local pin accounting. The caller owns trusted time.
#[must_use]
pub fn artifact_owner_operational_snapshot_v1(
    service: &LearningArtifactOwnerService,
    observed_at: u64,
    pin_metrics: ArtifactPinMetricsV1,
    stages: &ArtifactOwnerStageRecorderV1,
) -> ArtifactOwnerOperationalSnapshotV1 {
    ArtifactOwnerOperationalSnapshotV1 {
        observed_at,
        registry_records: service.registry().records().len(),
        withdrawal_records: service.withdrawal_registry().snapshot().records().len(),
        recovery_operation_id: service.recovery_required().cloned(),
        withdrawal_frontier_durable: service.withdrawal_frontier_is_durable(),
        durable_drain_requested: service.durable_drain_requested(),
        drained: service.is_drained(),
        pin_metrics,
        stage_metrics: stages.snapshot(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stage_histogram_is_bounded_and_non_cumulative() {
        let recorder = ArtifactOwnerStageRecorderV1::new();
        recorder.record(
            ArtifactOwnerStageV1::PayloadWriteSync,
            Duration::from_micros(700),
        );
        recorder.record(
            ArtifactOwnerStageV1::PayloadWriteSync,
            Duration::from_micros(7_000),
        );
        let histogram = recorder
            .snapshot()
            .histogram(ArtifactOwnerStageV1::PayloadWriteSync);
        assert_eq!(histogram.count, 2);
        assert_eq!(histogram.buckets.iter().sum::<u64>(), 2);
        assert_eq!(histogram.max_micros, 7_000);
    }

    #[test]
    fn stable_failure_classes_do_not_collapse_retry_semantics() {
        let identity = LearningArtifactOwnerServiceError::RequestMismatch;
        assert_eq!(
            identity.failure_class_v1(),
            ArtifactOwnerFailureClassV1::IdentityConflict
        );
        assert_eq!(
            identity.retry_disposition_v1(),
            ArtifactOwnerRetryDispositionV1::Never
        );
        let persistence = LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown;
        assert_eq!(
            persistence.retry_disposition_v1(),
            ArtifactOwnerRetryDispositionV1::ReconcileThenRetryExact
        );
    }
}
