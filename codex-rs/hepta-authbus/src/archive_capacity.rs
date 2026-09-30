//! Bounded diagnostics and retention policy for immutable AuthBus archives.
//!
//! Reservation archive rows retain operation identity and terminal bindings so
//! retries cannot be reinterpreted after live-row compaction. This module does
//! not delete archive rows. It exposes a fail-closed capacity decision and a
//! retention-review signal; destructive compaction requires the separately
//! governed archive-retention contract and independent operation-owner proof.

use serde::Serialize;
use sqlx::Row;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::TrustedTimeSample;
use crate::authority_store::storage;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusArchiveAlertSeverity {
    Warning,
    Critical,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthBusArchiveAlertKind {
    ReservationRows,
    ReservationBytes,
    CompactionReviewDue,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusArchiveAlert {
    pub kind: AuthBusArchiveAlertKind,
    pub severity: AuthBusArchiveAlertSeverity,
    pub observed: u64,
    pub threshold: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusArchiveCapacityPolicy {
    pub warning_reservation_rows: u64,
    pub critical_reservation_rows: u64,
    pub warning_reservation_bytes: u64,
    pub critical_reservation_bytes: u64,
    pub operation_id_reuse_window_ms: u64,
    pub backup_restore_window_ms: u64,
    pub incident_investigation_window_ms: u64,
    pub canary_rollback_window_ms: u64,
}

impl AuthBusArchiveCapacityPolicy {
    pub fn validate(self) -> Result<Self, AuthBusAuthorityError> {
        if self.warning_reservation_rows == 0
            || self.warning_reservation_rows >= self.critical_reservation_rows
            || self.warning_reservation_bytes == 0
            || self.warning_reservation_bytes >= self.critical_reservation_bytes
            || self.minimum_audit_retention_ms() == 0
        {
            return Err(AuthBusAuthorityError::InvalidInput(
                "AuthBus archive policy is outside supported bounds",
            ));
        }
        Ok(self)
    }

    #[must_use]
    pub fn minimum_audit_retention_ms(self) -> u64 {
        self.operation_id_reuse_window_ms
            .max(self.backup_restore_window_ms)
            .max(self.incident_investigation_window_ms)
            .max(self.canary_rollback_window_ms)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusArchiveCapacitySnapshot {
    pub observed_at_ms: u64,
    pub reservation_rows: u64,
    pub policy_rows: u64,
    pub estimated_reservation_bytes: u64,
    pub oldest_reservation_age_ms: u64,
    pub newest_reservation_age_ms: u64,
}

impl AuthBusArchiveCapacitySnapshot {
    pub fn evaluate(
        &self,
        policy: AuthBusArchiveCapacityPolicy,
    ) -> Result<Vec<AuthBusArchiveAlert>, AuthBusAuthorityError> {
        let policy = policy.validate()?;
        let mut alerts = Vec::new();
        if self.reservation_rows >= policy.critical_reservation_rows {
            alerts.push(alert(
                AuthBusArchiveAlertKind::ReservationRows,
                AuthBusArchiveAlertSeverity::Critical,
                self.reservation_rows,
                policy.critical_reservation_rows,
            ));
        } else if self.reservation_rows >= policy.warning_reservation_rows {
            alerts.push(alert(
                AuthBusArchiveAlertKind::ReservationRows,
                AuthBusArchiveAlertSeverity::Warning,
                self.reservation_rows,
                policy.warning_reservation_rows,
            ));
        }
        if self.estimated_reservation_bytes >= policy.critical_reservation_bytes {
            alerts.push(alert(
                AuthBusArchiveAlertKind::ReservationBytes,
                AuthBusArchiveAlertSeverity::Critical,
                self.estimated_reservation_bytes,
                policy.critical_reservation_bytes,
            ));
        } else if self.estimated_reservation_bytes >= policy.warning_reservation_bytes {
            alerts.push(alert(
                AuthBusArchiveAlertKind::ReservationBytes,
                AuthBusArchiveAlertSeverity::Warning,
                self.estimated_reservation_bytes,
                policy.warning_reservation_bytes,
            ));
        }
        let minimum_retention = policy.minimum_audit_retention_ms();
        if self.reservation_rows != 0
            && self.oldest_reservation_age_ms >= minimum_retention
            && (self.reservation_rows >= policy.warning_reservation_rows
                || self.estimated_reservation_bytes >= policy.warning_reservation_bytes)
        {
            alerts.push(alert(
                AuthBusArchiveAlertKind::CompactionReviewDue,
                AuthBusArchiveAlertSeverity::Warning,
                self.oldest_reservation_age_ms,
                minimum_retention,
            ));
        }
        Ok(alerts)
    }

    pub fn admission_blocked(
        &self,
        policy: AuthBusArchiveCapacityPolicy,
    ) -> Result<bool, AuthBusAuthorityError> {
        let policy = policy.validate()?;
        Ok(self.reservation_rows >= policy.critical_reservation_rows
            || self.estimated_reservation_bytes >= policy.critical_reservation_bytes)
    }
}

impl AuthBusAuthorityStore {
    pub(crate) async fn archive_capacity_snapshot(
        &self,
        time: &TrustedTimeSample,
    ) -> Result<AuthBusArchiveCapacitySnapshot, AuthBusAuthorityError> {
        let row = sqlx::query(
            "SELECT
                COUNT(*) AS reservation_rows,
                COALESCE(SUM(
                    LENGTH(reservation_id) + LENGTH(operation_id) + LENGTH(quota_key) +
                    LENGTH(period_id) + LENGTH(principal) + LENGTH(amount) +
                    LENGTH(effect_digest) + LENGTH(policy_id) + LENGTH(policy_revision) +
                    LENGTH(policy_decision_digest) + LENGTH(state) + LENGTH(revision) +
                    LENGTH(expires_at_ms) + LENGTH(created_at_ms) + LENGTH(updated_at_ms) +
                    COALESCE(LENGTH(dispatch_digest), 0) +
                    COALESCE(LENGTH(terminal_evidence), 0) +
                    COALESCE(LENGTH(observed_cost), 0) +
                    COALESCE(LENGTH(settlement_digest), 0) + LENGTH(archived_at_ms)
                ), 0) AS reservation_bytes,
                MIN(archived_at_ms) AS oldest_archived_at_ms,
                MAX(archived_at_ms) AS newest_archived_at_ms
             FROM authbus_quota_reservation_archive",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let reservation_rows = nonnegative_i64(
            row.try_get::<i64, _>("reservation_rows").map_err(storage)?,
            "negative reservation archive row count",
        )?;
        let estimated_reservation_bytes = nonnegative_i64(
            row.try_get::<i64, _>("reservation_bytes").map_err(storage)?,
            "negative reservation archive byte count",
        )?;
        let oldest_archived_at_ms = row
            .try_get::<Option<Vec<u8>>, _>("oldest_archived_at_ms")
            .map_err(storage)?
            .map(|value| blob_u64(&value, "invalid oldest archive time"))
            .transpose()?;
        let newest_archived_at_ms = row
            .try_get::<Option<Vec<u8>>, _>("newest_archived_at_ms")
            .map_err(storage)?
            .map(|value| blob_u64(&value, "invalid newest archive time"))
            .transpose()?;
        let policy_rows = nonnegative_i64(
            sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM authbus_policy_archive")
                .fetch_one(&self.pool)
                .await
                .map_err(storage)?,
            "negative policy archive row count",
        )?;
        Ok(AuthBusArchiveCapacitySnapshot {
            observed_at_ms: time.wall_time_ms(),
            reservation_rows,
            policy_rows,
            estimated_reservation_bytes,
            oldest_reservation_age_ms: oldest_archived_at_ms
                .map(|archived| time.wall_time_ms().saturating_sub(archived))
                .unwrap_or(0),
            newest_reservation_age_ms: newest_archived_at_ms
                .map(|archived| time.wall_time_ms().saturating_sub(archived))
                .unwrap_or(0),
        })
    }
}

fn alert(
    kind: AuthBusArchiveAlertKind,
    severity: AuthBusArchiveAlertSeverity,
    observed: u64,
    threshold: u64,
) -> AuthBusArchiveAlert {
    AuthBusArchiveAlert {
        kind,
        severity,
        observed,
        threshold,
    }
}

fn nonnegative_i64(value: i64, invalid: &'static str) -> Result<u64, AuthBusAuthorityError> {
    u64::try_from(value).map_err(|_| AuthBusAuthorityError::CorruptState(invalid))
}

fn blob_u64(value: &[u8], invalid: &'static str) -> Result<u64, AuthBusAuthorityError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| AuthBusAuthorityError::CorruptState(invalid))?;
    Ok(u64::from_be_bytes(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> AuthBusArchiveCapacityPolicy {
        AuthBusArchiveCapacityPolicy {
            warning_reservation_rows: 10,
            critical_reservation_rows: 20,
            warning_reservation_bytes: 1_000,
            critical_reservation_bytes: 2_000,
            operation_id_reuse_window_ms: 100,
            backup_restore_window_ms: 200,
            incident_investigation_window_ms: 300,
            canary_rollback_window_ms: 400,
        }
    }

    #[test]
    fn critical_capacity_blocks_admission_without_authorizing_deletion() {
        let snapshot = AuthBusArchiveCapacitySnapshot {
            reservation_rows: 20,
            estimated_reservation_bytes: 1_500,
            oldest_reservation_age_ms: 500,
            ..AuthBusArchiveCapacitySnapshot::default()
        };
        assert!(snapshot.admission_blocked(policy()).expect("policy"));
        let alerts = snapshot.evaluate(policy()).expect("evaluate");
        assert!(alerts.iter().any(|alert| {
            alert.kind == AuthBusArchiveAlertKind::ReservationRows
                && alert.severity == AuthBusArchiveAlertSeverity::Critical
        }));
        assert!(alerts
            .iter()
            .any(|alert| alert.kind == AuthBusArchiveAlertKind::CompactionReviewDue));
    }
}
