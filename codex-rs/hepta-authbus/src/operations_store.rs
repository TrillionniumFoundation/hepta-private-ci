use codex_hepta_types::AuthorityPosture;
use sqlx::Row;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthBusHealthSnapshot;
use crate::authority_store::storage;

impl AuthBusAuthorityStore {
    pub(crate) async fn health_snapshot(
        &self,
        _observed_at_ms: u64,
    ) -> Result<AuthBusHealthSnapshot, AuthBusAuthorityError> {
        let last_trusted_time_ms = sqlx::query(
            "SELECT wall_time_ms FROM authbus_trusted_time WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(|row| decode_u64(&row, "wall_time_ms"))
        .transpose()?;
        let checkpoint_generation = sqlx::query(
            "SELECT generation FROM authbus_authority_checkpoint WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(|row| decode_u64(&row, "generation"))
        .transpose()?;
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
        let active_reservations = count(
            &self.pool,
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted', 'indeterminate')",
        )
        .await?;
        let dispatch_attempted_reservations = count(
            &self.pool,
            "SELECT COUNT(*) FROM authbus_quota_reservation WHERE state = 'dispatch_attempted'",
        )
        .await?;
        let indeterminate_reservations = count(
            &self.pool,
            "SELECT COUNT(*) FROM authbus_quota_reservation WHERE state = 'indeterminate'",
        )
        .await?;
        let expired_active_reservations = if let Some(now) = last_trusted_time_ms {
            let value: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM authbus_quota_reservation
                 WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?",
            )
            .bind(now.to_be_bytes().as_slice())
            .fetch_one(&self.pool)
            .await
            .map_err(storage)?;
            nonnegative_count(value)?
        } else {
            0
        };
        let oldest_active_expires_at_ms = sqlx::query_scalar::<_, Option<Vec<u8>>>(
            "SELECT MIN(expires_at_ms) FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted', 'indeterminate')",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?
        .map(|bytes| decode_u64_bytes(bytes, "reservation expiry"))
        .transpose()?;
        Ok(AuthBusHealthSnapshot {
            active_reservations,
            expired_active_reservations,
            dispatch_attempted_reservations,
            indeterminate_reservations,
            oldest_active_expires_at_ms,
            last_trusted_time_ms,
            checkpoint_generation,
            checkpoint_dirty: checkpoint_dirty != 0,
            recovery_required: recovery_required != 0,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

async fn count(pool: &sqlx::SqlitePool, query: &str) -> Result<u64, AuthBusAuthorityError> {
    let value: i64 = sqlx::query_scalar(query)
        .fetch_one(pool)
        .await
        .map_err(storage)?;
    nonnegative_count(value)
}

fn nonnegative_count(value: i64) -> Result<u64, AuthBusAuthorityError> {
    u64::try_from(value)
        .map_err(|_| AuthBusAuthorityError::CorruptState("negative authority row count"))
}

fn decode_u64(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<u64, AuthBusAuthorityError> {
    decode_u64_bytes(row.try_get(column).map_err(storage)?, column)
}

fn decode_u64_bytes(bytes: Vec<u8>, field: &str) -> Result<u64, AuthBusAuthorityError> {
    let raw: [u8; 8] = bytes
        .try_into()
        .map_err(|_| AuthBusAuthorityError::CorruptState("invalid fixed-width u64"))?;
    let value = u64::from_be_bytes(raw);
    if value == 0 && field == "generation" {
        return Err(AuthBusAuthorityError::CorruptState(
            "invalid zero checkpoint generation",
        ));
    }
    Ok(value)
}
