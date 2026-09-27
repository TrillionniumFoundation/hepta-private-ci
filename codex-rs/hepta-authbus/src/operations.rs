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
}

impl AuthBusOperationalSnapshot {
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
        if self.oldest_active_reservation_age_ms
            >= policy.max_oldest_active_reservation_age_ms
        {
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
        self.store.operational_snapshot(time).await
    }

    /// Execute one bounded owner-maintenance iteration. Any committed mutation
    /// is externally checkpointed before the report is returned.
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
        let recovery_complete = self.store.reconcile_after_restart(limit).await?;
        let expired_reservation_sweep = self
            .store
            .sweep_expired_reservations(time.clone(), limit)
            .await?;
        self.sync_checkpoint().await?;
        let snapshot = self.store.operational_snapshot(&time).await?;
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
        let quota_endowment = checked_sum(checked_sum(quota_available, quota_reserved)?, quota_consumed)?;
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
