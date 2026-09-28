use std::array;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_types::StableId;
use serde::Serialize;
use sqlx::Acquire;
use sqlx::Row;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthBusAuthorityStore;
use crate::ExpiredReservationSweep;
use crate::TrustedTimeSample;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;

const LATENCY_BUCKETS_US: [u64; 19] = [
    100,
    250,
    500,
    1_000,
    2_500,
    5_000,
    10_000,
    25_000,
    50_000,
    100_000,
    250_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    10_000_000,
    30_000_000,
    60_000_000,
    u64::MAX,
];

static OWNER_ALREADY_ACTIVE_FAILURES: AtomicU64 = AtomicU64::new(0);
static OWNER_UNSAFE_PATH_FAILURES: AtomicU64 = AtomicU64::new(0);
static OWNER_STORAGE_FAILURES: AtomicU64 = AtomicU64::new(0);
static REPLAY_REJECTIONS: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusLatencySummary {
    pub count: u64,
    pub p50_us: u64,
    pub p95_us: u64,
    pub p99_us: u64,
    pub max_us: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusRuntimeSnapshot {
    pub owner_already_active_failures: u64,
    pub owner_unsafe_path_failures: u64,
    pub owner_storage_failures: u64,
    pub checkpoint_sync_failures: u64,
    pub checkpoint_rollback_conflicts: u64,
    pub checkpoint_storage_failures: u64,
    pub authority_use_blocks: u64,
    pub mutation_attempts: u64,
    pub mutation_rejections: u64,
    pub mutation_outcome_unknown: u64,
    pub mutation_committed_reconciliation_required: u64,
    pub replay_rejections: u64,
    pub maintenance_ticks: u64,
    pub maintenance_failures: u64,
    pub recovery_incomplete_ticks: u64,
    pub mutation_latency: AuthBusLatencySummary,
    pub maintenance_latency: AuthBusLatencySummary,
}

struct LatencyHistogram {
    buckets: [AtomicU64; LATENCY_BUCKETS_US.len()],
    max_us: AtomicU64,
}

impl Default for LatencyHistogram {
    fn default() -> Self {
        Self {
            buckets: array::from_fn(|_| AtomicU64::new(0)),
            max_us: AtomicU64::new(0),
        }
    }
}

impl LatencyHistogram {
    fn record(&self, duration: Duration) {
        let micros = u64::try_from(duration.as_micros()).unwrap_or(u64::MAX);
        let index = LATENCY_BUCKETS_US
            .iter()
            .position(|bound| micros <= *bound)
            .unwrap_or(LATENCY_BUCKETS_US.len() - 1);
        self.buckets[index].fetch_add(1, Ordering::Relaxed);
        self.max_us.fetch_max(micros, Ordering::Relaxed);
    }

    fn snapshot(&self) -> AuthBusLatencySummary {
        let counts: [u64; LATENCY_BUCKETS_US.len()] =
            array::from_fn(|index| self.buckets[index].load(Ordering::Relaxed));
        let count = counts.iter().copied().sum();
        let max_us = self.max_us.load(Ordering::Relaxed);
        AuthBusLatencySummary {
            count,
            p50_us: percentile(&counts, count, 50, max_us),
            p95_us: percentile(&counts, count, 95, max_us),
            p99_us: percentile(&counts, count, 99, max_us),
            max_us,
        }
    }
}

fn percentile(
    counts: &[u64; LATENCY_BUCKETS_US.len()],
    total: u64,
    percentile: u64,
    max_us: u64,
) -> u64 {
    if total == 0 {
        return 0;
    }
    let numerator = u128::from(total) * u128::from(percentile) + 99;
    let target = u64::try_from(numerator / 100).unwrap_or(u64::MAX);
    let mut cumulative = 0_u64;
    for (index, count) in counts.iter().copied().enumerate() {
        cumulative = cumulative.saturating_add(count);
        if cumulative >= target {
            let bound = LATENCY_BUCKETS_US[index];
            return if bound == u64::MAX { max_us } else { bound };
        }
    }
    max_us
}

#[derive(Default)]
pub(crate) struct AuthBusRuntimeMetrics {
    checkpoint_sync_failures: AtomicU64,
    checkpoint_rollback_conflicts: AtomicU64,
    checkpoint_storage_failures: AtomicU64,
    authority_use_blocks: AtomicU64,
    mutation_attempts: AtomicU64,
    mutation_rejections: AtomicU64,
    mutation_outcome_unknown: AtomicU64,
    mutation_committed_reconciliation_required: AtomicU64,
    maintenance_ticks: AtomicU64,
    maintenance_failures: AtomicU64,
    recovery_incomplete_ticks: AtomicU64,
    mutation_latency: LatencyHistogram,
    maintenance_latency: LatencyHistogram,
}

impl AuthBusRuntimeMetrics {
    pub(crate) fn record_checkpoint_sync_failure(&self, error: &AuthBusAuthorityError) {
        self.checkpoint_sync_failures
            .fetch_add(1, Ordering::Relaxed);
        match error {
            AuthBusAuthorityError::RollbackDetected => {
                self.checkpoint_rollback_conflicts
                    .fetch_add(1, Ordering::Relaxed);
            }
            AuthBusAuthorityError::Storage(_) | AuthBusAuthorityError::UnsafeCheckpoint => {
                self.checkpoint_storage_failures
                    .fetch_add(1, Ordering::Relaxed);
            }
            _ => {}
        }
    }

    pub(crate) fn record_authority_use_block(&self) {
        self.authority_use_blocks.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_mutation<T>(
        &self,
        duration: Duration,
        result: &Result<T, AuthBusAuthorityError>,
    ) {
        self.mutation_attempts.fetch_add(1, Ordering::Relaxed);
        self.mutation_latency.record(duration);
        let Err(error) = result else {
            return;
        };
        match error {
            AuthBusAuthorityError::AuthorityUseBlocked(_) => {
                self.record_authority_use_block();
            }
            AuthBusAuthorityError::CheckpointReconciliationRequired(_) => {
                self.mutation_committed_reconciliation_required
                    .fetch_add(1, Ordering::Relaxed);
            }
            AuthBusAuthorityError::MutationOutcomeUnknown(_)
            | AuthBusAuthorityError::Storage(_) => {
                self.mutation_outcome_unknown
                    .fetch_add(1, Ordering::Relaxed);
            }
            _ => {
                self.mutation_rejections.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    pub(crate) fn record_maintenance(
        &self,
        duration: Duration,
        result: &Result<(bool, ExpiredReservationSweep), AuthBusAuthorityError>,
    ) {
        self.maintenance_ticks.fetch_add(1, Ordering::Relaxed);
        self.maintenance_latency.record(duration);
        match result {
            Ok((false, _)) => {
                self.recovery_incomplete_ticks
                    .fetch_add(1, Ordering::Relaxed);
            }
            Err(AuthBusAuthorityError::AuthorityUseBlocked(_)) => {
                self.record_authority_use_block();
                self.maintenance_failures.fetch_add(1, Ordering::Relaxed);
            }
            Err(_) => {
                self.maintenance_failures.fetch_add(1, Ordering::Relaxed);
            }
            Ok((true, _)) => {}
        }
    }

    pub(crate) fn snapshot(&self) -> AuthBusRuntimeSnapshot {
        AuthBusRuntimeSnapshot {
            owner_already_active_failures: OWNER_ALREADY_ACTIVE_FAILURES.load(Ordering::Relaxed),
            owner_unsafe_path_failures: OWNER_UNSAFE_PATH_FAILURES.load(Ordering::Relaxed),
            owner_storage_failures: OWNER_STORAGE_FAILURES.load(Ordering::Relaxed),
            checkpoint_sync_failures: self.checkpoint_sync_failures.load(Ordering::Relaxed),
            checkpoint_rollback_conflicts: self
                .checkpoint_rollback_conflicts
                .load(Ordering::Relaxed),
            checkpoint_storage_failures: self.checkpoint_storage_failures.load(Ordering::Relaxed),
            authority_use_blocks: self.authority_use_blocks.load(Ordering::Relaxed),
            mutation_attempts: self.mutation_attempts.load(Ordering::Relaxed),
            mutation_rejections: self.mutation_rejections.load(Ordering::Relaxed),
            mutation_outcome_unknown: self.mutation_outcome_unknown.load(Ordering::Relaxed),
            mutation_committed_reconciliation_required: self
                .mutation_committed_reconciliation_required
                .load(Ordering::Relaxed),
            replay_rejections: REPLAY_REJECTIONS.load(Ordering::Relaxed),
            maintenance_ticks: self.maintenance_ticks.load(Ordering::Relaxed),
            maintenance_failures: self.maintenance_failures.load(Ordering::Relaxed),
            recovery_incomplete_ticks: self.recovery_incomplete_ticks.load(Ordering::Relaxed),
            mutation_latency: self.mutation_latency.snapshot(),
            maintenance_latency: self.maintenance_latency.snapshot(),
        }
    }
}

pub(crate) fn record_owner_acquisition_failure(error: &AuthBusAuthorityError) {
    match error {
        AuthBusAuthorityError::OwnerAlreadyActive => {
            OWNER_ALREADY_ACTIVE_FAILURES.fetch_add(1, Ordering::Relaxed);
        }
        AuthBusAuthorityError::UnsafeCheckpoint | AuthBusAuthorityError::InvalidInput(_) => {
            OWNER_UNSAFE_PATH_FAILURES.fetch_add(1, Ordering::Relaxed);
        }
        _ => {
            OWNER_STORAGE_FAILURES.fetch_add(1, Ordering::Relaxed);
        }
    }
}

pub(crate) fn record_replay_rejection() {
    REPLAY_REJECTIONS.fetch_add(1, Ordering::Relaxed);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusAlertSeverity {
    Warning,
    Critical,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusAlertKind {
    CheckpointDirty,
    RecoveryRequired,
    ExpiredActiveReservation,
    IndeterminateReservation,
    ActiveReservationCapacity,
    QuotaUtilization,
    OldestActiveReservation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusBlockingReason {
    CheckpointReconciliation,
    RestartRecovery,
    ExpiredReservationReconciliation,
    IndeterminateSettlement,
    ActiveReservationCapacity,
    QuotaCapacity,
    OldestActiveReservation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusOperationalAlert {
    pub kind: AuthBusAlertKind,
    pub severity: AuthBusAlertSeverity,
    pub observed: u64,
    pub threshold: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusSloPolicy {
    pub max_indeterminate_reservations: u64,
    pub max_active_reservations: u64,
    pub max_quota_utilization_basis_points: u64,
    pub max_oldest_active_reservation_age_ms: u64,
}

impl AuthBusSloPolicy {
    pub const PRODUCTION: Self = Self {
        max_indeterminate_reservations: 0,
        max_active_reservations: 13_107,
        max_quota_utilization_basis_points: 9_000,
        max_oldest_active_reservation_age_ms: 120_000,
    };

    pub fn validate(self) -> Result<Self, AuthBusAuthorityError> {
        if self.max_active_reservations == 0
            || self.max_active_reservations > 16_384
            || self.max_quota_utilization_basis_points == 0
            || self.max_quota_utilization_basis_points > 10_000
            || self.max_oldest_active_reservation_age_ms == 0
        {
            return Err(AuthBusAuthorityError::InvalidInput(
                "AuthBus SLO policy is outside supported bounds",
            ));
        }
        Ok(self)
    }
}

impl Default for AuthBusSloPolicy {
    fn default() -> Self {
        Self::PRODUCTION
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusOperationalSnapshot {
    pub observed_at_ms: u64,
    pub checkpoint_generation: u64,
    pub checkpoint_dirty: bool,
    pub recovery_required: bool,
    pub active_reservations: u64,
    pub expired_active_reservations: u64,
    pub indeterminate_reservations: u64,
    pub oldest_active_reservation_age_ms: u64,
    pub quota_available: u64,
    pub quota_reserved: u64,
    pub quota_consumed: u64,
    pub quota_utilization_basis_points: u64,
    pub active_issuer_epochs: u64,
    pub revoked_issuer_epochs: u64,
    pub retired_issuer_epochs: u64,
    pub runtime: AuthBusRuntimeSnapshot,
}

impl AuthBusOperationalSnapshot {
    pub fn blocking_reasons(
        &self,
        policy: AuthBusSloPolicy,
    ) -> Result<Vec<AuthBusBlockingReason>, AuthBusAuthorityError> {
        let policy = policy.validate()?;
        let mut reasons = Vec::new();
        if self.checkpoint_dirty {
            reasons.push(AuthBusBlockingReason::CheckpointReconciliation);
        }
        if self.recovery_required {
            reasons.push(AuthBusBlockingReason::RestartRecovery);
        }
        if self.expired_active_reservations > 0 {
            reasons.push(AuthBusBlockingReason::ExpiredReservationReconciliation);
        }
        if self.indeterminate_reservations > policy.max_indeterminate_reservations {
            reasons.push(AuthBusBlockingReason::IndeterminateSettlement);
        }
        if self.active_reservations >= policy.max_active_reservations {
            reasons.push(AuthBusBlockingReason::ActiveReservationCapacity);
        }
        if self.quota_utilization_basis_points >= policy.max_quota_utilization_basis_points {
            reasons.push(AuthBusBlockingReason::QuotaCapacity);
        }
        if self.oldest_active_reservation_age_ms >= policy.max_oldest_active_reservation_age_ms {
            reasons.push(AuthBusBlockingReason::OldestActiveReservation);
        }
        Ok(reasons)
    }

    pub fn evaluate(
        &self,
        policy: AuthBusSloPolicy,
    ) -> Result<Vec<AuthBusOperationalAlert>, AuthBusAuthorityError> {
        let policy = policy.validate()?;
        let mut alerts = Vec::new();
        if self.checkpoint_dirty {
            alerts.push(alert(
                AuthBusAlertKind::CheckpointDirty,
                AuthBusAlertSeverity::Critical,
                1,
                0,
            ));
        }
        if self.recovery_required {
            alerts.push(alert(
                AuthBusAlertKind::RecoveryRequired,
                AuthBusAlertSeverity::Critical,
                1,
                0,
            ));
        }
        if self.expired_active_reservations > 0 {
            alerts.push(alert(
                AuthBusAlertKind::ExpiredActiveReservation,
                AuthBusAlertSeverity::Critical,
                self.expired_active_reservations,
                0,
            ));
        }
        if self.indeterminate_reservations > policy.max_indeterminate_reservations {
            alerts.push(alert(
                AuthBusAlertKind::IndeterminateReservation,
                AuthBusAlertSeverity::Warning,
                self.indeterminate_reservations,
                policy.max_indeterminate_reservations,
            ));
        }
        if self.active_reservations >= policy.max_active_reservations {
            alerts.push(alert(
                AuthBusAlertKind::ActiveReservationCapacity,
                AuthBusAlertSeverity::Warning,
                self.active_reservations,
                policy.max_active_reservations,
            ));
        }
        if self.quota_utilization_basis_points >= policy.max_quota_utilization_basis_points {
            alerts.push(alert(
                AuthBusAlertKind::QuotaUtilization,
                AuthBusAlertSeverity::Warning,
                self.quota_utilization_basis_points,
                policy.max_quota_utilization_basis_points,
            ));
        }
        if self.oldest_active_reservation_age_ms >= policy.max_oldest_active_reservation_age_ms {
            alerts.push(alert(
                AuthBusAlertKind::OldestActiveReservation,
                AuthBusAlertSeverity::Warning,
                self.oldest_active_reservation_age_ms,
                policy.max_oldest_active_reservation_age_ms,
            ));
        }
        Ok(alerts)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusMaintenanceReport {
    pub recovery_complete: bool,
    pub expired_reservation_sweep: ExpiredReservationSweep,
    pub snapshot: AuthBusOperationalSnapshot,
    pub alerts: Vec<AuthBusOperationalAlert>,
}

impl AuthBusAuthorityHost {
    pub async fn operational_snapshot(
        &self,
        time: &TrustedTimeSample,
    ) -> Result<AuthBusOperationalSnapshot, AuthBusAuthorityError> {
        let mut snapshot = self.store.operational_snapshot(time).await?;
        snapshot.runtime = self.metrics.snapshot();
        Ok(snapshot)
    }

    /// Execute one bounded owner-maintenance iteration through the same owner
    /// gate and checkpoint boundary used by normal mutations.
    pub async fn maintenance_tick(
        &self,
        time: TrustedTimeSample,
        limit: u32,
        policy: AuthBusSloPolicy,
    ) -> Result<AuthBusMaintenanceReport, AuthBusAuthorityError> {
        if limit == 0 || limit > 1024 {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority worker batch must be in 1..=1024",
            ));
        }
        let (recovery_complete, expired_reservation_sweep) =
            self.run_maintenance_mutations(time.clone(), limit).await?;
        let snapshot = self.operational_snapshot(&time).await?;
        let alerts = snapshot.evaluate(policy)?;
        Ok(AuthBusMaintenanceReport {
            recovery_complete,
            expired_reservation_sweep,
            snapshot,
            alerts,
        })
    }
}

impl AuthBusAuthorityStore {
    pub(crate) async fn operational_snapshot(
        &self,
        time: &TrustedTimeSample,
    ) -> Result<AuthBusOperationalSnapshot, AuthBusAuthorityError> {
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let checkpoint_generation = required_blob_u64(
            sqlx::query_scalar::<_, Option<Vec<u8>>>(
                "SELECT generation FROM authbus_authority_checkpoint WHERE singleton = 1",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?,
            "missing authority checkpoint generation",
        )?;
        let checkpoint_dirty: i64 = sqlx::query_scalar(
            "SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton = 1",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let recovery_required: i64 = sqlx::query_scalar(
            "SELECT recovery_required FROM authbus_recovery_state WHERE singleton = 1",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let active_reservations = count(
            sqlx::query_scalar::<_, i64>(
                "SELECT COUNT(*) FROM authbus_quota_reservation
                 WHERE state IN ('held','dispatch_attempted','indeterminate')",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?,
        )?;
        let expired_active_reservations = count(
            sqlx::query_scalar::<_, i64>(
                "SELECT COUNT(*) FROM authbus_quota_reservation
                 WHERE state IN ('held','dispatch_attempted') AND expires_at_ms <= ?",
            )
            .bind(u64_bytes(time.wall_time_ms()).as_slice())
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?,
        )?;
        let indeterminate_reservations = count(
            sqlx::query_scalar::<_, i64>(
                "SELECT COUNT(*) FROM authbus_quota_reservation WHERE state = 'indeterminate'",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?,
        )?;
        let oldest_created = sqlx::query_scalar::<_, Option<Vec<u8>>>(
            "SELECT MIN(created_at_ms) FROM authbus_quota_reservation
             WHERE state IN ('held','dispatch_attempted','indeterminate')",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?
        .map(|value| blob_u64(&value, "invalid reservation creation time"))
        .transpose()?;
        let oldest_active_reservation_age_ms = oldest_created
            .map(|created| time.wall_time_ms().saturating_sub(created))
            .unwrap_or(0);

        let mut quota_available = 0_u64;
        let mut quota_reserved = 0_u64;
        let mut quota_consumed = 0_u64;
        for row in sqlx::query(
            "SELECT available, reserved, consumed FROM authbus_quota_registry ORDER BY quota_key",
        )
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?
        {
            quota_available = checked_sum(
                quota_available,
                blob_u64(
                    &row.try_get::<Vec<u8>, _>("available").map_err(storage)?,
                    "invalid available quota",
                )?,
            )?;
            quota_reserved = checked_sum(
                quota_reserved,
                blob_u64(
                    &row.try_get::<Vec<u8>, _>("reserved").map_err(storage)?,
                    "invalid reserved quota",
                )?,
            )?;
            quota_consumed = checked_sum(
                quota_consumed,
                blob_u64(
                    &row.try_get::<Vec<u8>, _>("consumed").map_err(storage)?,
                    "invalid consumed quota",
                )?,
            )?;
        }
        let quota_endowment = checked_sum(
            checked_sum(quota_available, quota_reserved)?,
            quota_consumed,
        )?;
        let quota_used = checked_sum(quota_reserved, quota_consumed)?;
        let quota_utilization_basis_points = if quota_endowment == 0 {
            0
        } else {
            u64::try_from((u128::from(quota_used) * 10_000) / u128::from(quota_endowment))
                .map_err(|_| AuthBusAuthorityError::CapacityExceeded)?
        };

        let mut active_issuer_epochs = 0_u64;
        let mut revoked_issuer_epochs = 0_u64;
        let mut retired_issuer_epochs = 0_u64;
        for row in sqlx::query(
            "SELECT state, COUNT(*) AS count FROM authbus_issuer_registry GROUP BY state",
        )
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?
        {
            let state: String = row.try_get("state").map_err(storage)?;
            let value = count(row.try_get::<i64, _>("count").map_err(storage)?)?;
            match state.as_str() {
                "active" => active_issuer_epochs = value,
                "revoked" => revoked_issuer_epochs = value,
                "retired" => retired_issuer_epochs = value,
                _ => {
                    return Err(AuthBusAuthorityError::CorruptState(
                        "invalid issuer lifecycle state",
                    ));
                }
            }
        }
        tx.commit().await.map_err(storage)?;
        Ok(AuthBusOperationalSnapshot {
            observed_at_ms: time.wall_time_ms(),
            checkpoint_generation,
            checkpoint_dirty: checkpoint_dirty != 0,
            recovery_required: recovery_required != 0,
            active_reservations,
            expired_active_reservations,
            indeterminate_reservations,
            oldest_active_reservation_age_ms,
            quota_available,
            quota_reserved,
            quota_consumed,
            quota_utilization_basis_points,
            active_issuer_epochs,
            revoked_issuer_epochs,
            retired_issuer_epochs,
            runtime: AuthBusRuntimeSnapshot::default(),
        })
    }
}

fn alert(
    kind: AuthBusAlertKind,
    severity: AuthBusAlertSeverity,
    observed: u64,
    threshold: u64,
) -> AuthBusOperationalAlert {
    AuthBusOperationalAlert {
        kind,
        severity,
        observed,
        threshold,
    }
}

fn count(value: i64) -> Result<u64, AuthBusAuthorityError> {
    u64::try_from(value).map_err(|_| AuthBusAuthorityError::CorruptState("negative row count"))
}

fn checked_sum(left: u64, right: u64) -> Result<u64, AuthBusAuthorityError> {
    left.checked_add(right)
        .ok_or(AuthBusAuthorityError::CapacityExceeded)
}

fn required_blob_u64(
    value: Option<Vec<u8>>,
    missing: &'static str,
) -> Result<u64, AuthBusAuthorityError> {
    blob_u64(
        &value.ok_or(AuthBusAuthorityError::CorruptState(missing))?,
        missing,
    )
}

fn blob_u64(value: &[u8], invalid: &'static str) -> Result<u64, AuthBusAuthorityError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| AuthBusAuthorityError::CorruptState(invalid))?;
    Ok(u64::from_be_bytes(bytes))
}

#[allow(dead_code)]
fn _stable_id_type_anchor(_: &StableId) {}
