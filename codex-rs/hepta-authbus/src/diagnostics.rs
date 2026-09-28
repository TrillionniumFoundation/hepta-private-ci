//! Bounded, process-local observations of the owner boundary. These are not
//! durable authority facts. No request IDs, keys, payloads or error strings are
//! retained. Exporters must label them by owner instance, not by request.
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use serde::Serialize;

use crate::AuthBusAuthorityError;
use crate::AuthBusMutationDisposition;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusBlockingReason {
    OwnerActive,
    CheckpointUnavailable,
    CheckpointDrift,
    RecoveryRequired,
    RevisionConflict,
    Capacity,
    StorageUnavailable,
    CommitIndeterminate,
    Cancelled,
    Rejected,
}

impl AuthBusAuthorityError {
    /// Stable, bounded labels; callers can count owner-open failures even when
    /// no host exists. Never use the error Display string as a metric label.
    pub fn blocking_reason(&self) -> AuthBusBlockingReason {
        use AuthBusBlockingReason as Reason;
        match self {
            Self::OwnerAlreadyActive => Reason::OwnerActive,
            Self::UnsafeCheckpoint => Reason::CheckpointUnavailable,
            Self::RollbackDetected => Reason::CheckpointDrift,
            Self::RecoveryRequired => Reason::RecoveryRequired,
            Self::RevisionConflict
            | Self::IdempotencyConflict
            | Self::StalePolicyRevision
            | Self::KeyEpochRegression => Reason::RevisionConflict,
            Self::CapacityExceeded | Self::QuotaExceeded => Reason::Capacity,
            Self::Storage(_) => Reason::StorageUnavailable,
            Self::CommitIndeterminate(_) => Reason::CommitIndeterminate,
            Self::MutationNotStarted { source } | Self::MaintenanceIncomplete(source) => {
                source.blocking_reason()
            }
            Self::MutationIncomplete {
                checkpoint_error, ..
            } => checkpoint_error.blocking_reason(),
            _ => Reason::Rejected,
        }
    }
}

/// Non-cumulative buckets, in microseconds. Quantiles are bucket UPPER BOUNDS,
/// not exact samples; overflow returns None rather than a fabricated bound.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct LatencyDistribution {
    pub samples: u64,
    pub total_micros: u64,
    pub max_micros: u64,
    pub buckets: [u64; 16],
}

impl LatencyDistribution {
    pub const UPPER_BOUNDS_MICROS: [u64; 16] = [
        1,
        10,
        100,
        500,
        1_000,
        5_000,
        10_000,
        50_000,
        100_000,
        500_000,
        1_000_000,
        5_000_000,
        10_000_000,
        30_000_000,
        60_000_000,
        u64::MAX,
    ];

    fn observe(&mut self, duration: Duration) {
        let micros = u64::try_from(duration.as_micros()).unwrap_or(u64::MAX);
        let index = Self::UPPER_BOUNDS_MICROS
            .iter()
            .position(|upper| micros <= *upper)
            .unwrap_or(15);
        self.samples = self.samples.saturating_add(1);
        self.total_micros = self.total_micros.saturating_add(micros);
        self.max_micros = self.max_micros.max(micros);
        self.buckets[index] = self.buckets[index].saturating_add(1);
    }

    pub fn percentile_upper_bound_micros(&self, percentile: u8) -> Option<u64> {
        if self.samples == 0 || percentile == 0 || percentile > 100 {
            return None;
        }
        let target = (u128::from(self.samples) * u128::from(percentile)).div_ceil(100);
        let mut count = 0_u128;
        for (bucket, upper) in self.buckets.iter().zip(Self::UPPER_BOUNDS_MICROS) {
            count += u128::from(*bucket);
            if count >= target {
                return (upper != u64::MAX).then_some(upper);
            }
        }
        None
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusOwnerDiagnostics {
    pub attempts: u64,
    pub waiting: u64,
    pub in_flight: u64,
    pub committed: u64,
    pub rejected: u64,
    pub not_started: u64,
    pub reconcile_required: u64,
    pub checkpoint_pending_returns: u64,
    pub cancelled: u64,
    pub checkpoint_sync_failures: u64,
    pub revision_conflicts: u64,
    pub storage_failures: u64,
    pub checkpoint_pending: bool,
    pub last_blocking_reason: Option<AuthBusBlockingReason>,
    /// Entry to terminal return/drop, including gate wait and publication.
    pub operation_latency: LatencyDistribution,
    pub gate_wait_latency: LatencyDistribution,
    pub checkpoint_latency: LatencyDistribution,
}

#[derive(Default)]
pub(crate) struct OwnerDiagnostics(Mutex<AuthBusOwnerDiagnostics>);

impl OwnerDiagnostics {
    fn with<R>(&self, f: impl FnOnce(&mut AuthBusOwnerDiagnostics) -> R) -> R {
        // Observability poisoning must neither panic nor unlock authority.
        let mut state = self.0.lock().unwrap_or_else(|poison| poison.into_inner());
        f(&mut state)
    }

    pub(crate) fn snapshot(&self) -> AuthBusOwnerDiagnostics {
        self.with(|state| state.clone())
    }

    pub(crate) fn begin(&self) -> OperationObservation<'_> {
        self.with(|state| {
            state.attempts = state.attempts.saturating_add(1);
            state.waiting = state.waiting.saturating_add(1);
        });
        OperationObservation {
            diagnostics: self,
            started: Instant::now(),
            acquired: false,
            entered: false,
            finished: false,
        }
    }

    pub(crate) fn checkpoint_finished(
        &self,
        elapsed: Duration,
        result: &Result<(), AuthBusAuthorityError>,
    ) {
        self.with(|state| {
            state.checkpoint_latency.observe(elapsed);
            state.checkpoint_pending = result.is_err();
            if let Err(error) = result {
                state.checkpoint_sync_failures = state.checkpoint_sync_failures.saturating_add(1);
                state.last_blocking_reason = Some(error.blocking_reason());
            }
        });
    }
}

pub(crate) struct OperationObservation<'a> {
    diagnostics: &'a OwnerDiagnostics,
    started: Instant,
    acquired: bool,
    entered: bool,
    finished: bool,
}

impl OperationObservation<'_> {
    pub(crate) fn acquired(&mut self) {
        self.acquired = true;
        self.diagnostics.with(|state| {
            state.waiting = state.waiting.saturating_sub(1);
            state.in_flight = state.in_flight.saturating_add(1);
            state.gate_wait_latency.observe(self.started.elapsed());
        });
    }

    pub(crate) fn entered(&mut self) {
        self.entered = true;
    }

    pub(crate) fn finished(&mut self, result: Result<(), &AuthBusAuthorityError>) {
        self.finished = true;
        self.diagnostics.with(|state| {
            state.in_flight = state.in_flight.saturating_sub(1);
            state.operation_latency.observe(self.started.elapsed());
            let disposition = match result {
                Ok(()) => {
                    state.last_blocking_reason = None;
                    AuthBusMutationDisposition::Committed
                }
                Err(error) => {
                    let reason = error.blocking_reason();
                    state.last_blocking_reason = Some(reason);
                    if reason == AuthBusBlockingReason::RevisionConflict {
                        state.revision_conflicts = state.revision_conflicts.saturating_add(1);
                    }
                    if matches!(
                        reason,
                        AuthBusBlockingReason::StorageUnavailable
                            | AuthBusBlockingReason::CommitIndeterminate
                    ) {
                        state.storage_failures = state.storage_failures.saturating_add(1);
                    }
                    if matches!(error, AuthBusAuthorityError::MutationIncomplete { .. }) {
                        state.checkpoint_pending_returns =
                            state.checkpoint_pending_returns.saturating_add(1);
                    }
                    error.mutation_disposition()
                }
            };
            count_disposition(state, disposition);
        });
    }
}

fn count_disposition(state: &mut AuthBusOwnerDiagnostics, disposition: AuthBusMutationDisposition) {
    let counter = match disposition {
        AuthBusMutationDisposition::Committed => &mut state.committed,
        AuthBusMutationDisposition::Rejected => &mut state.rejected,
        AuthBusMutationDisposition::NotStarted => &mut state.not_started,
        AuthBusMutationDisposition::ReconcileRequired => &mut state.reconcile_required,
    };
    *counter = counter.saturating_add(1);
}

impl Drop for OperationObservation<'_> {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        self.diagnostics.with(|state| {
            if self.acquired {
                state.in_flight = state.in_flight.saturating_sub(1);
            } else {
                state.waiting = state.waiting.saturating_sub(1);
            }
            state.cancelled = state.cancelled.saturating_add(1);
            state.last_blocking_reason = Some(AuthBusBlockingReason::Cancelled);
            state.operation_latency.observe(self.started.elapsed());
            if self.entered {
                state.checkpoint_pending = true;
                count_disposition(state, AuthBusMutationDisposition::ReconcileRequired);
            } else {
                count_disposition(state, AuthBusMutationDisposition::NotStarted);
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn histogram_reports_bounds_and_no_fabricated_overflow() {
        let mut latency = LatencyDistribution::default();
        assert_eq!(latency.percentile_upper_bound_micros(50), None);
        for micros in [1, 2, 100, 1_001, 70_000_000] {
            latency.observe(Duration::from_micros(micros));
        }
        assert_eq!(latency.percentile_upper_bound_micros(50), Some(100));
        assert_eq!(latency.percentile_upper_bound_micros(95), None);
        assert_eq!(latency.samples, 5);
        assert_eq!(latency.buckets.iter().sum::<u64>(), 5);
    }

    #[test]
    fn cancellation_is_not_reported_as_success() {
        let diagnostics = OwnerDiagnostics::default();
        drop(diagnostics.begin());
        {
            let mut observation = diagnostics.begin();
            observation.acquired();
            observation.entered();
        }
        let snapshot = diagnostics.snapshot();
        assert_eq!(snapshot.cancelled, 2);
        assert_eq!(snapshot.not_started, 1);
        assert_eq!(snapshot.reconcile_required, 1);
        assert_eq!(snapshot.committed, 0);
        assert_eq!((snapshot.waiting, snapshot.in_flight), (0, 0));
        assert!(snapshot.checkpoint_pending);
    }
}
