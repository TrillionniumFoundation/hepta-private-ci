//! Operation-identity lookup for restart reconciliation.
//!
//! Reservation IDs are derived from authorization decisions and therefore are
//! not reconstructible from the Bao operation row alone. The authority already
//! enforces a unique operation identity across hot and archived reservations;
//! this read-only projection exposes that identity without weakening reserve's
//! idempotency checks.

use codex_hepta_types::StableId;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::QuotaReservation;
use crate::authority_store::storage;

impl AuthBusAuthorityStore {
    pub async fn reservation_by_operation(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        let mut tx = crate::authority_store::begin(&self.pool).await?;
        let result =
            crate::quota_store::load_reservation_by_operation(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(result)
    }
    /// Close an absent operation under the same SQLite write transaction used by
    /// reserve. `None` proves durable non-admission, not merely current absence.
    /// Existing reservations are returned unchanged for original-ID recovery.
    pub async fn seal_unreserved_operation(
        &self,
        operation_id: &StableId,
        effect_digest: codex_hepta_types::Digest32,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        if effect_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "empty operation effect",
            ));
        }
        let mut tx = crate::authority_store::begin(&self.pool).await?;
        if let Some(existing) =
            crate::quota_store::load_reservation_by_operation(&mut tx, operation_id).await?
        {
            if existing.effect_digest != effect_digest {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
            tx.commit().await.map_err(storage)?;
            return Ok(Some(existing));
        }
        let existing: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT effect_digest FROM authbus_operation_admission_fence WHERE operation_id = ?",
        )
        .bind(operation_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if let Some(existing) = existing {
            if existing.as_slice() != effect_digest.as_array() {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
        } else {
            let count: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM authbus_operation_admission_fence")
                    .fetch_one(&mut *tx)
                    .await
                    .map_err(storage)?;
            if count >= 65_536 {
                return Err(AuthBusAuthorityError::CapacityExceeded);
            }
            sqlx::query("INSERT INTO authbus_operation_admission_fence(operation_id, effect_digest) VALUES (?, ?)")
                .bind(operation_id.as_str()).bind(effect_digest.as_array().as_slice())
                .execute(&mut *tx).await.map_err(storage)?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(None)
    }
}

#[cfg(test)]
#[path = "operation_lookup_tests.rs"]
mod tests;
