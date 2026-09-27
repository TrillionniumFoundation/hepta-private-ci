//! Operation lookup and durable pre-reservation closure for restart recovery.
//!
//! A lookup returning None is only a projection. Only seal_unreserved_operation
//! returning None proves that a late reserve cannot commit for this identity.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::QuotaReservation;
use crate::TrustedTimeSample;
use crate::authority_store::advance_time;
use crate::authority_store::begin;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;
use crate::quota_store::load_reservation;

impl AuthBusAuthorityStore {
    /// Read the hot/archive projection in one transaction. Absence is not a seal.
    pub async fn reservation_by_operation(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let result = lookup(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(result)
    }

    /// Atomically adopt the existing reservation or prohibit every future
    /// reservation for this exact operation. The caller must own this operation;
    /// this control API must not be exposed to an unauthenticated request.
    ///
    /// BEGIN IMMEDIATE and migration-5 insertion triggers serialize the seal
    /// with reserve, including SQL work which outlives a cancelled future.
    /// None means the matching immutable closure has committed. Some means
    /// recovery must reconcile the original reservation instead of aborting it.
    pub async fn seal_unreserved_operation(
        &self,
        operation_id: &StableId,
        effect_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        if effect_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput("empty operation effect"));
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let recovery_required: i64 = sqlx::query_scalar(
            "SELECT recovery_required FROM authbus_recovery_state WHERE singleton = 1",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if recovery_required != 0 {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        if let Some(reservation) = lookup(&mut tx, operation_id).await? {
            if reservation.effect_digest != effect_digest {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
            tx.commit().await.map_err(storage)?;
            return Ok(Some(reservation));
        }
        let existing: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT effect_digest FROM authbus_operation_closure WHERE operation_id = ?",
        )
        .bind(operation_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if let Some(existing) = existing {
            if existing.as_slice() != effect_digest.as_array().as_slice() {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
        } else {
            let count: i64 = sqlx::query_scalar("SELECT count(*) FROM authbus_operation_closure")
                .fetch_one(&mut *tx)
                .await
                .map_err(storage)?;
            if count >= 65_536 {
                return Err(AuthBusAuthorityError::CapacityExceeded);
            }
            sqlx::query(
                "INSERT INTO authbus_operation_closure(operation_id, effect_digest, closed_at_ms)
                 VALUES (?, ?, ?)",
            )
            .bind(operation_id.as_str())
            .bind(effect_digest.as_array().as_slice())
            .bind(u64_bytes(time.wall_time_ms()).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(None)
    }
}

async fn lookup(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
    let identities: Vec<String> = sqlx::query_scalar(
        "SELECT reservation_id FROM authbus_quota_reservation WHERE operation_id = ?
         UNION ALL
         SELECT reservation_id FROM authbus_quota_reservation_archive WHERE operation_id = ?",
    )
    .bind(operation_id.as_str())
    .bind(operation_id.as_str())
    .fetch_all(&mut **tx)
    .await
    .map_err(storage)?;
    match identities.as_slice() {
        [] => Ok(None),
        [value] => {
            let id = StableId::new(value.clone()).map_err(|_| {
                AuthBusAuthorityError::CorruptState("invalid operation reservation identity")
            })?;
            load_reservation(tx, &id).await.map(Some)
        }
        _ => Err(AuthBusAuthorityError::CorruptState(
            "operation exists in both hot and archive reservation stores",
        )),
    }
}

#[cfg(test)]
#[path = "operation_lookup_tests.rs"]
mod tests;
#[cfg(test)]
#[path = "operation_seal_tests.rs"]
mod seal_tests;
