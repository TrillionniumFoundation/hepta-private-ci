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
        let current: Option<String> = sqlx::query_scalar(
            "SELECT reservation_id FROM authbus_quota_reservation WHERE operation_id = ?",
        )
        .bind(operation_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        let reservation_id = match current {
            Some(value) => Some(value),
            None => {
                sqlx::query_scalar(
                    "SELECT reservation_id FROM authbus_quota_reservation_archive \
                     WHERE operation_id = ?",
                )
                .bind(operation_id.as_str())
                .fetch_optional(&self.pool)
                .await
                .map_err(storage)?
            }
        };
        let Some(reservation_id) = reservation_id else {
            return Ok(None);
        };
        let reservation_id = StableId::new(reservation_id).map_err(|_| {
            AuthBusAuthorityError::CorruptState("invalid operation reservation identity")
        })?;
        self.reservation(&reservation_id).await.map(Some)
    }
}

#[cfg(test)]
#[path = "operation_lookup_tests.rs"]
mod tests;
