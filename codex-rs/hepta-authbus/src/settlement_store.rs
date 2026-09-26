use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::ExpiredReservationSweep;
use crate::PolicyEffect;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::ReservationState;
use crate::Settlement;
use crate::SettlementStatus;
use crate::SignedSettlementEvidence;
use crate::TrustedTimeSample;
use crate::VerifiedIssuerHandle;
use crate::authority_store::advance_time;
use crate::authority_store::begin;
use crate::authority_store::load_policy_by_id;
use crate::authority_store::next_revision;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;
use crate::quota_store::load_quota;
use crate::quota_store::load_reservation;

impl AuthBusAuthorityStore {
    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        if expected_revision == 0 || dispatch_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "dispatch transition requires revision and digest",
            ));
        }
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        if dispatch_digest != reservation.effect_digest {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        let quota = load_quota(&mut tx, &reservation.quota_key).await?;
        require_current_policy(&mut tx, &reservation, &quota, &time).await?;
        if reservation.state == ReservationState::DispatchAttempted
            && reservation.dispatch_digest == Some(dispatch_digest)
        {
            tx.commit().await.map_err(storage)?;
            return Ok(reservation);
        }
        if reservation.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if reservation.state != ReservationState::Held
            || time.wall_time_ms >= reservation.expires_at_ms
        {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        reservation.state = ReservationState::DispatchAttempted;
        reservation.dispatch_digest = Some(dispatch_digest);
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        sqlx::query(
            "UPDATE authbus_quota_reservation SET state = 'dispatch_attempted',
             dispatch_digest = ?, revision = ?, updated_at_ms = ? WHERE reservation_id = ?",
        )
        .bind(dispatch_digest.as_array().as_slice())
        .bind(u64_bytes(reservation.revision).as_slice())
        .bind(u64_bytes(reservation.updated_at_ms).as_slice())
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Indeterminate {
            tx.commit().await.map_err(storage)?;
            return Ok(reservation);
        }
        if reservation.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if reservation.state != ReservationState::DispatchAttempted {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        reservation.state = ReservationState::Indeterminate;
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        update_reservation_state(&mut tx, &reservation, "indeterminate").await?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Cancelled {
            tx.commit().await.map_err(storage)?;
            return Ok(reservation);
        }
        if reservation.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if reservation.state != ReservationState::Held {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        let mut quota = load_quota(&mut tx, &reservation.quota_key).await?;
        release_reserved(&mut quota, reservation.amount)?;
        persist_quota(&mut tx, &quota).await?;
        reservation.state = ReservationState::Cancelled;
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        update_reservation_state(&mut tx, &reservation, "cancelled").await?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if time.wall_time_ms < reservation.expires_at_ms {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        reconcile_expired_in_tx(&mut tx, &mut reservation, &time).await?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }

    /// Reconcile at most `limit` expired active reservations in one owner-held
    /// transaction. Held work releases quota; attempted work becomes
    /// indeterminate and remains charged until signed settlement evidence.
    pub async fn reconcile_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        if limit == 0 || limit > 1024 {
            return Err(AuthBusAuthorityError::InvalidInput(
                "reservation sweep limit must be in 1..=1024",
            ));
        }
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT reservation_id FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?
             ORDER BY expires_at_ms, reservation_id LIMIT ?",
        )
        .bind(u64_bytes(time.wall_time_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut expired = 0_u32;
        let mut indeterminate = 0_u32;
        for raw_id in &ids {
            let reservation_id = StableId::new(raw_id.clone()).map_err(|_| {
                AuthBusAuthorityError::CorruptState("invalid reservation identity")
            })?;
            let mut reservation = load_reservation(&mut tx, &reservation_id).await?;
            match reservation.state {
                ReservationState::Held => expired += 1,
                ReservationState::DispatchAttempted => indeterminate += 1,
                _ => {
                    return Err(AuthBusAuthorityError::CorruptState(
                        "sweep selected a non-active reservation",
                    ));
                }
            }
            reconcile_expired_in_tx(&mut tx, &mut reservation, &time).await?;
        }
        let remaining: i64 = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM authbus_quota_reservation
             WHERE state IN ('held', 'dispatch_attempted') AND expires_at_ms <= ?)",
        )
        .bind(u64_bytes(time.wall_time_ms).as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(ExpiredReservationSweep {
            scanned: u32::try_from(ids.len())
                .map_err(|_| AuthBusAuthorityError::CapacityExceeded)?,
            expired,
            indeterminate,
            remaining: remaining != 0,
        })
    }

    pub async fn settle(
        &self,
        issuer: &VerifiedIssuerHandle,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let reservation_id = &evidence.claims.reservation_id;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        let mut quota = load_quota(&mut tx, &reservation.quota_key).await?;
        let raw_digest = evidence.receipt_digest();
        if matches!(
            reservation.state,
            ReservationState::Settled | ReservationState::Released
        ) {
            if reservation.settlement_digest != Some(raw_digest)
                || reservation.terminal_evidence != Some(evidence.claims.terminal_evidence_digest)
                || reservation.observed_cost != Some(evidence.claims.observed_cost)
            {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
            tx.commit().await.map_err(storage)?;
            return settlement_from(&reservation);
        }
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        let authenticated = evidence.authenticate(
            issuer,
            &reservation.reservation_id,
            &reservation.operation_id,
            time.wall_time_ms,
        )?;
        if authenticated.claims().observed_at_ms < reservation.updated_at_ms {
            return Err(AuthBusAuthorityError::InvalidSettlementEvidence);
        }
        if authenticated.claims().observed_cost > reservation.amount {
            return Err(AuthBusAuthorityError::ObservedCostExceedsReservation);
        }
        let (next_state, state_text) = match authenticated.claims().status {
            SettlementStatus::Completed => {
                settle_completed(
                    &mut quota,
                    reservation.amount,
                    authenticated.claims().observed_cost,
                )?;
                (ReservationState::Settled, "settled")
            }
            SettlementStatus::Rejected => {
                release_reserved(&mut quota, reservation.amount)?;
                (ReservationState::Released, "released")
            }
        };
        persist_quota(&mut tx, &quota).await?;
        reservation.state = next_state;
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        reservation.terminal_evidence = Some(authenticated.claims().terminal_evidence_digest);
        reservation.observed_cost = Some(authenticated.claims().observed_cost);
        reservation.settlement_digest = Some(authenticated.evidence_digest());
        sqlx::query(
            "UPDATE authbus_quota_reservation SET state = ?, revision = ?, updated_at_ms = ?,
             terminal_evidence = ?, observed_cost = ?, settlement_digest = ?
             WHERE reservation_id = ?",
        )
        .bind(state_text)
        .bind(u64_bytes(reservation.revision).as_slice())
        .bind(u64_bytes(reservation.updated_at_ms).as_slice())
        .bind(
            authenticated
                .claims()
                .terminal_evidence_digest
                .as_array()
                .as_slice(),
        )
        .bind(u64_bytes(authenticated.claims().observed_cost).as_slice())
        .bind(authenticated.evidence_digest().as_array().as_slice())
        .bind(reservation.reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        settlement_from(&reservation)
    }
}

async fn reconcile_expired_in_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &mut QuotaReservation,
    time: &TrustedTimeSample,
) -> Result<(), AuthBusAuthorityError> {
    match reservation.state {
        ReservationState::Held => {
            let mut quota = load_quota(tx, &reservation.quota_key).await?;
            release_reserved(&mut quota, reservation.amount)?;
            persist_quota(tx, &quota).await?;
            reservation.state = ReservationState::Expired;
            reservation.revision = next_revision(reservation.revision)?;
            reservation.updated_at_ms = time.wall_time_ms;
            update_reservation_state(tx, reservation, "expired").await?;
        }
        ReservationState::DispatchAttempted => {
            reservation.state = ReservationState::Indeterminate;
            reservation.revision = next_revision(reservation.revision)?;
            reservation.updated_at_ms = time.wall_time_ms;
            update_reservation_state(tx, reservation, "indeterminate").await?;
        }
        ReservationState::Indeterminate
        | ReservationState::Settled
        | ReservationState::Released
        | ReservationState::Expired
        | ReservationState::Cancelled => {}
    }
    Ok(())
}

async fn require_current_policy(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &QuotaReservation,
    quota: &QuotaSnapshot,
    time: &TrustedTimeSample,
) -> Result<(), AuthBusAuthorityError> {
    let policy = load_policy_by_id(tx, &reservation.policy_id).await?;
    if policy.effect != PolicyEffect::Allow
        || policy.revoked
        || policy.revision != reservation.policy_revision
        || policy.principal != reservation.principal
        || policy.principal != quota.principal
        || policy.scope_digest != quota.scope_digest
        || time.wall_time_ms < policy.not_before_ms
        || time.wall_time_ms >= policy.expires_at_ms
    {
        return Err(AuthBusAuthorityError::PolicyUnavailable);
    }
    Ok(())
}

fn settle_completed(
    quota: &mut QuotaSnapshot,
    amount: u64,
    observed_cost: u64,
) -> Result<(), AuthBusAuthorityError> {
    quota.reserved =
        quota
            .reserved
            .checked_sub(amount)
            .ok_or(AuthBusAuthorityError::CorruptState(
                "reserved quota underflow",
            ))?;
    quota.consumed = quota
        .consumed
        .checked_add(observed_cost)
        .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
    quota.available = quota
        .available
        .checked_add(amount - observed_cost)
        .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
    quota.revision = next_revision(quota.revision)?;
    Ok(())
}

fn release_reserved(quota: &mut QuotaSnapshot, amount: u64) -> Result<(), AuthBusAuthorityError> {
    quota.reserved =
        quota
            .reserved
            .checked_sub(amount)
            .ok_or(AuthBusAuthorityError::CorruptState(
                "reserved quota underflow",
            ))?;
    quota.available = quota
        .available
        .checked_add(amount)
        .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
    quota.revision = next_revision(quota.revision)?;
    Ok(())
}

async fn persist_quota(
    tx: &mut Transaction<'_, Sqlite>,
    quota: &QuotaSnapshot,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "UPDATE authbus_quota_registry SET available = ?, reserved = ?, consumed = ?, revision = ?
         WHERE quota_key = ?",
    )
    .bind(u64_bytes(quota.available).as_slice())
    .bind(u64_bytes(quota.reserved).as_slice())
    .bind(u64_bytes(quota.consumed).as_slice())
    .bind(u64_bytes(quota.revision).as_slice())
    .bind(quota.quota_key.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn update_reservation_state(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &QuotaReservation,
    state: &str,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "UPDATE authbus_quota_reservation SET state = ?, revision = ?, updated_at_ms = ?
         WHERE reservation_id = ?",
    )
    .bind(state)
    .bind(u64_bytes(reservation.revision).as_slice())
    .bind(u64_bytes(reservation.updated_at_ms).as_slice())
    .bind(reservation.reservation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

fn settlement_from(reservation: &QuotaReservation) -> Result<Settlement, AuthBusAuthorityError> {
    Ok(Settlement {
        reservation_id: reservation.reservation_id.clone(),
        operation_id: reservation.operation_id.clone(),
        state: reservation.state,
        reserved_amount: reservation.amount,
        observed_cost: reservation
            .observed_cost
            .ok_or(AuthBusAuthorityError::CorruptState("missing observed cost"))?,
        terminal_evidence_digest: reservation.terminal_evidence.ok_or(
            AuthBusAuthorityError::CorruptState("missing terminal evidence"),
        )?,
        settlement_digest: reservation.settlement_digest.ok_or(
            AuthBusAuthorityError::CorruptState("missing settlement digest"),
        )?,
        reservation_revision: reservation.revision,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "settlement_store_tests.rs"]
mod tests;
