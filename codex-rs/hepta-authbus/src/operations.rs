use codex_hepta_types::Digest32;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthorityCheckpoint;
use crate::ExpiredReservationSweep;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityOperationalSnapshot {
    pub checkpoint: AuthorityCheckpoint,
    pub checkpoint_dirty: bool,
    pub recovery_required: bool,
    pub active_reservations: u64,
    pub expired_active_reservations: u64,
    pub indeterminate_reservations: u64,
    pub oldest_expired_at_ms: Option<u64>,
    pub frontier_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthorityAlert {
    CheckpointDirty,
    RecoveryRequired,
    ExpiredReservationBacklog { count: u64 },
    IndeterminateReservationBacklog { count: u64 },
    ActiveReservationCapacity { active: u64, threshold: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityMaintenanceConfig {
    pub sweep_limit: u32,
    pub terminal_compaction_limit: u32,
    pub terminal_compaction_before_ms: u64,
    pub active_reservation_warning: u64,
    pub expired_reservation_warning: u64,
    pub indeterminate_reservation_warning: u64,
}

impl AuthorityMaintenanceConfig {
    pub fn validate(&self) -> Result<(), AuthBusAuthorityError> {
        if self.sweep_limit == 0
            || self.sweep_limit > 1024
            || self.terminal_compaction_limit == 0
            || self.terminal_compaction_limit > 1024
            || self.active_reservation_warning == 0
            || self.expired_reservation_warning == 0
            || self.indeterminate_reservation_warning == 0
        {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority maintenance bounds must be non-zero and batches <= 1024",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityMaintenanceReport {
    pub sweep: ExpiredReservationSweep,
    pub compacted_terminal_reservations: u32,
    pub snapshot: AuthorityOperationalSnapshot,
    pub alerts: Vec<AuthorityAlert>,
}

impl AuthorityMaintenanceReport {
    pub(crate) fn from_parts(
        config: &AuthorityMaintenanceConfig,
        sweep: ExpiredReservationSweep,
        compacted_terminal_reservations: u32,
        snapshot: AuthorityOperationalSnapshot,
    ) -> Self {
        let mut alerts = Vec::new();
        if snapshot.checkpoint_dirty {
            alerts.push(AuthorityAlert::CheckpointDirty);
        }
        if snapshot.recovery_required {
            alerts.push(AuthorityAlert::RecoveryRequired);
        }
        if snapshot.expired_active_reservations >= config.expired_reservation_warning {
            alerts.push(AuthorityAlert::ExpiredReservationBacklog {
                count: snapshot.expired_active_reservations,
            });
        }
        if snapshot.indeterminate_reservations >= config.indeterminate_reservation_warning {
            alerts.push(AuthorityAlert::IndeterminateReservationBacklog {
                count: snapshot.indeterminate_reservations,
            });
        }
        if snapshot.active_reservations >= config.active_reservation_warning {
            alerts.push(AuthorityAlert::ActiveReservationCapacity {
                active: snapshot.active_reservations,
                threshold: config.active_reservation_warning,
            });
        }
        Self {
            sweep,
            compacted_terminal_reservations,
            snapshot,
            alerts,
        }
    }
}

impl AuthBusAuthorityStore {
    pub(crate) async fn operational_snapshot(
        &self,
        now_ms: u64,
    ) -> Result<AuthorityOperationalSnapshot, AuthBusAuthorityError> {
        let checkpoint = self
            .authority_checkpoint()
            .await?
            .ok_or(AuthBusAuthorityError::RollbackDetected)?;
        let checkpoint_dirty: i64 = sqlx::query_scalar(
            "SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton = 1",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let recovery_required: i64 = sqlx::query_scalar(
            "SELECT recovery_required FROM authbus_recovery_state WHERE singleton = 1",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let active_reservations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted', 'indeterminate')",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let expired_active_reservations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?",
        )
        .bind(u64_bytes(now_ms).as_slice())
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let indeterminate_reservations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation WHERE state = 'indeterminate'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let oldest_expired: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT MIN(expires_at_ms) FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?",
        )
        .bind(u64_bytes(now_ms).as_slice())
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let oldest_expired_at_ms = oldest_expired
            .map(|bytes| {
                let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
                    AuthBusAuthorityError::CorruptState("invalid reservation expiry width")
                })?;
                Ok(u64::from_be_bytes(bytes))
            })
            .transpose()?;
        Ok(AuthorityOperationalSnapshot {
            checkpoint,
            checkpoint_dirty: checkpoint_dirty != 0,
            recovery_required: recovery_required != 0,
            active_reservations: u64::try_from(active_reservations)
                .map_err(|_| AuthBusAuthorityError::CorruptState("negative active count"))?,
            expired_active_reservations: u64::try_from(expired_active_reservations)
                .map_err(|_| AuthBusAuthorityError::CorruptState("negative expired count"))?,
            indeterminate_reservations: u64::try_from(indeterminate_reservations)
                .map_err(|_| AuthBusAuthorityError::CorruptState("negative indeterminate count"))?,
            oldest_expired_at_ms,
            frontier_digest: self.authority_frontier_digest().await?,
        })
    }
}
