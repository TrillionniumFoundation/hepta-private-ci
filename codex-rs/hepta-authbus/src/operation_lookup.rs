//! Transactional operation-identity lookup for restart reconciliation.
//!
//! Hot/archive selection and row decoding share one immediate transaction. A
//! lookup must not mix snapshots while compaction or a pending commit runs.
//! Absence is an observation, not a durable tombstone: the product owner must
//! additionally exclude a still-live request that could create a reservation.

use codex_hepta_types::StableId;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::QuotaReservation;
use crate::authority_store::begin;
use crate::authority_store::storage;
use crate::quota_store::load_reservation;

impl AuthBusAuthorityStore {
    pub async fn reservation_by_operation(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        let mut transaction = begin(&self.pool).await?;
        let identities: Vec<String> = sqlx::query_scalar(
            "SELECT reservation_id FROM authbus_quota_reservation WHERE operation_id = ?
             UNION ALL
             SELECT reservation_id FROM authbus_quota_reservation_archive WHERE operation_id = ?
             LIMIT 2",
        )
        .bind(operation_id.as_str())
        .bind(operation_id.as_str())
        .fetch_all(&mut *transaction)
        .await
        .map_err(storage)?;
        let result = match identities.as_slice() {
            [] => None,
            [reservation_id] => {
                let reservation_id = StableId::new(reservation_id.clone()).map_err(|_| {
                    AuthBusAuthorityError::CorruptState("invalid operation reservation identity")
                })?;
                let reservation = load_reservation(&mut transaction, &reservation_id).await?;
                if reservation.operation_id != *operation_id {
                    return Err(AuthBusAuthorityError::CorruptState(
                        "operation lookup resolved a different operation",
                    ));
                }
                Some(reservation)
            }
            _ => {
                return Err(AuthBusAuthorityError::CorruptState(
                    "operation identity duplicated across hot and archived reservations",
                ));
            }
        };
        transaction.commit().await.map_err(storage)?;
        Ok(result)
    }
}

#[cfg(test)]
#[path = "operation_lookup_tests.rs"]
mod tests;
