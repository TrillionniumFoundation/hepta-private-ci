use sqlx::Row;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::ExpiredReservationSweep;
use crate::ReservationState;
use crate::TrustedTimeSample;
use crate::authority_store::stable_id;
use crate::authority_store::storage;

const MAX_EXPIRED_SWEEP: u32 = 1024;

impl AuthBusAuthorityStore {
    /// Bounded owner-side sweep. The existing single-reservation transition is
    /// deliberately reused so quota conservation and dispatch-fence semantics
    /// have one implementation: held reservations are refunded and expired;
    /// dispatch-attempted reservations become indeterminate and retain quota.
    pub(crate) async fn reconcile_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        if limit == 0 || limit > MAX_EXPIRED_SWEEP {
            return Err(AuthBusAuthorityError::InvalidInput(
                "expired reservation sweep limit must be 1..=1024",
            ));
        }
        self.observe_time(time.clone()).await?;
        let rows = sqlx::query(
            "SELECT reservation_id, revision FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?
             ORDER BY expires_at_ms, reservation_id LIMIT ?",
        )
        .bind(time.wall_time_ms().to_be_bytes().as_slice())
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        let scanned = u32::try_from(rows.len())
            .map_err(|_| AuthBusAuthorityError::CapacityExceeded)?;
        let mut expired = 0_u32;
        let mut indeterminate = 0_u32;
        for row in rows {
            let reservation_id = stable_id(row.try_get("reservation_id").map_err(storage)?)?;
            let revision: Vec<u8> = row.try_get("revision").map_err(storage)?;
            let revision: [u8; 8] = revision.try_into().map_err(|_| {
                AuthBusAuthorityError::CorruptState("invalid reservation revision")
            })?;
            let reservation = self
                .reconcile_expired_reservation(
                    &reservation_id,
                    u64::from_be_bytes(revision),
                    time.clone(),
                )
                .await?;
            match reservation.state {
                ReservationState::Expired => {
                    expired = expired
                        .checked_add(1)
                        .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
                }
                ReservationState::Indeterminate => {
                    indeterminate = indeterminate
                        .checked_add(1)
                        .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
                }
                _ => {
                    return Err(AuthBusAuthorityError::CorruptState(
                        "expired sweep returned a non-terminal classification",
                    ));
                }
            }
        }
        Ok(ExpiredReservationSweep::new(
            scanned,
            expired,
            indeterminate,
        ))
    }
}
