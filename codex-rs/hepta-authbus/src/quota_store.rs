use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::PolicyDecision;
use crate::PolicyEffect;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::ReservationState;
use crate::TrustedTimeSample;
use crate::authority_store::advance_time;
use crate::authority_store::begin;
use crate::authority_store::blob_array;
use crate::authority_store::load_policy_by_id;
use crate::authority_store::next_revision;
use crate::authority_store::nonzero_u64;
use crate::authority_store::stable_id;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;

const MAX_QUOTAS: i64 = 4096;
const MAX_RESERVATIONS: i64 = 16_384;
const MAX_ACTIVE_RESERVATIONS_PER_PRINCIPAL: i64 = 1024;

impl AuthBusAuthorityStore {
    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        validate_quota_spec(&spec)?;
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_quota_registry")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if count >= MAX_QUOTAS {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let result = sqlx::query(
            "INSERT INTO authbus_quota_registry
             (quota_key, principal, scope_digest, unit, period_id, limit_amount,
              available, reserved, consumed, revision)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(spec.quota_key.as_str())
        .bind(spec.principal.as_str())
        .bind(spec.scope_digest.as_array().as_slice())
        .bind(spec.unit.as_str())
        .bind(spec.period_id.as_str())
        .bind(u64_bytes(spec.limit))
        .bind(u64_bytes(spec.limit))
        .bind(u64_bytes(0))
        .bind(u64_bytes(0))
        .bind(u64_bytes(1))
        .execute(&mut *tx)
        .await;
        if let Err(error) = result {
            if error
                .as_database_error()
                .is_some_and(|database| database.is_unique_violation())
            {
                return Err(AuthBusAuthorityError::AlreadyExists);
            }
            return Err(storage(error));
        }
        tx.commit().await.map_err(storage)?;
        Ok(QuotaSnapshot {
            quota_key: spec.quota_key,
            principal: spec.principal,
            scope_digest: spec.scope_digest,
            unit: spec.unit,
            period_id: spec.period_id,
            limit: spec.limit,
            available: spec.limit,
            reserved: 0,
            consumed: 0,
            revision: 1,
        })
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        validate_quota_spec(&spec)?;
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut quota = load_quota(&mut tx, &spec.quota_key).await?;
        if quota.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if quota.principal != spec.principal
            || quota.scope_digest != spec.scope_digest
            || quota.unit != spec.unit
        {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        if quota.period_id == spec.period_id {
            let committed = quota
                .reserved
                .checked_add(quota.consumed)
                .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
            if spec.limit < committed {
                return Err(AuthBusAuthorityError::QuotaExceeded);
            }
            quota.available = spec.limit - committed;
        } else {
            if quota.reserved != 0 {
                return Err(AuthBusAuthorityError::InvalidTransition);
            }
            quota.period_id = spec.period_id;
            quota.available = spec.limit;
            quota.consumed = 0;
        }
        quota.limit = spec.limit;
        quota.revision = next_revision(quota.revision)?;
        sqlx::query(
            "UPDATE authbus_quota_registry SET period_id = ?, limit_amount = ?,
             available = ?, reserved = ?, consumed = ?, revision = ? WHERE quota_key = ?",
        )
        .bind(quota.period_id.as_str())
        .bind(u64_bytes(quota.limit))
        .bind(u64_bytes(quota.available))
        .bind(u64_bytes(quota.reserved))
        .bind(u64_bytes(quota.consumed))
        .bind(u64_bytes(quota.revision))
        .bind(quota.quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(quota)
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        if request.amount == 0
            || request.effect_digest.is_zero()
            || request.expected_quota_revision == 0
            || request.expires_at_ms <= time.wall_time_ms
        {
            return Err(AuthBusAuthorityError::InvalidInput(
                "reservation amount, revision or expiry is invalid",
            ));
        }
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        if let Some(existing) =
            load_reservation_by_operation(&mut tx, &request.operation_id).await?
        {
            if reservation_matches(&existing, decision, &request) {
                tx.commit().await.map_err(storage)?;
                return Ok(existing);
            }
            return Err(AuthBusAuthorityError::IdempotencyConflict);
        }
        let policy = load_policy_by_id(&mut tx, decision.policy_id()).await?;
        if !decision.allowed()
            || policy.effect != PolicyEffect::Allow
            || policy.revoked
            || policy.revision != decision.policy_revision()
            || policy.principal != *decision.principal()
            || policy.action != *decision.action()
            || policy.scope_digest != decision.scope_digest()
            || time.wall_time_ms < policy.not_before_ms
            || time.wall_time_ms >= policy.expires_at_ms
        {
            return Err(AuthBusAuthorityError::PolicyUnavailable);
        }
        if request.expires_at_ms > policy.expires_at_ms {
            return Err(AuthBusAuthorityError::InvalidInput(
                "reservation cannot outlive its authorization policy",
            ));
        }
        let mut quota = load_quota(&mut tx, &request.quota_key).await?;
        if quota.revision != request.expected_quota_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if quota.principal != *decision.principal()
            || quota.scope_digest != decision.scope_digest()
        {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        if request.amount > quota.available {
            return Err(AuthBusAuthorityError::QuotaExceeded);
        }
        let total: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_quota_reservation")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if total >= MAX_RESERVATIONS {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE principal = ? AND state IN ('held', 'dispatch_attempted', 'indeterminate')",
        )
        .bind(decision.principal().as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if active >= MAX_ACTIVE_RESERVATIONS_PER_PRINCIPAL {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let reservation_id = reservation_id(decision, &request)?;
        quota.available -= request.amount;
        quota.reserved = quota
            .reserved
            .checked_add(request.amount)
            .ok_or(AuthBusAuthorityError::CapacityExceeded)?;
        quota.revision = next_revision(quota.revision)?;
        sqlx::query(
            "UPDATE authbus_quota_registry SET available = ?, reserved = ?, revision = ?
             WHERE quota_key = ?",
        )
        .bind(u64_bytes(quota.available))
        .bind(u64_bytes(quota.reserved))
        .bind(u64_bytes(quota.revision))
        .bind(quota.quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "INSERT INTO authbus_quota_reservation
             (reservation_id, operation_id, quota_key, period_id, principal, amount,
              effect_digest, policy_id, policy_revision, policy_decision_digest, state, revision,
              expires_at_ms, created_at_ms, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'held', ?, ?, ?, ?)",
        )
        .bind(reservation_id.as_str())
        .bind(request.operation_id.as_str())
        .bind(quota.quota_key.as_str())
        .bind(quota.period_id.as_str())
        .bind(quota.principal.as_str())
        .bind(u64_bytes(request.amount))
        .bind(request.effect_digest.as_array().as_slice())
        .bind(decision.policy_id().as_str())
        .bind(u64_bytes(decision.policy_revision()))
        .bind(decision.decision_digest().as_array().as_slice())
        .bind(u64_bytes(1))
        .bind(u64_bytes(request.expires_at_ms))
        .bind(u64_bytes(time.wall_time_ms))
        .bind(u64_bytes(time.wall_time_ms))
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let reservation = load_reservation(&mut tx, &reservation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let quota = load_quota(&mut tx, quota_key).await?;
        tx.commit().await.map_err(storage)?;
        Ok(quota)
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let reservation = load_reservation(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(reservation)
    }
}

pub(crate) async fn load_quota(
    tx: &mut Transaction<'_, Sqlite>,
    quota_key: &StableId,
) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT quota_key, principal, scope_digest, unit, period_id, limit_amount,
                available, reserved, consumed, revision
         FROM authbus_quota_registry WHERE quota_key = ?",
    )
    .bind(quota_key.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AuthBusAuthorityError::QuotaMissing)?;
    quota_from_row(&row)
}

pub(crate) async fn load_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    reservation_id: &StableId,
) -> Result<QuotaReservation, AuthBusAuthorityError> {
    let row = sqlx::query("SELECT * FROM authbus_quota_reservation WHERE reservation_id = ?")
        .bind(reservation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?
        .ok_or(AuthBusAuthorityError::ReservationMissing)?;
    reservation_from_row(&row)
}

async fn load_reservation_by_operation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
    sqlx::query("SELECT * FROM authbus_quota_reservation WHERE operation_id = ?")
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?
        .map(|row| reservation_from_row(&row))
        .transpose()
}

fn quota_from_row(row: &SqliteRow) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
    let quota = QuotaSnapshot {
        quota_key: stable_id(row.try_get("quota_key").map_err(storage)?)?,
        principal: stable_id(row.try_get("principal").map_err(storage)?)?,
        scope_digest: Digest32::from_array(blob_array::<32>(row, "scope_digest")?),
        unit: stable_id(row.try_get("unit").map_err(storage)?)?,
        period_id: stable_id(row.try_get("period_id").map_err(storage)?)?,
        limit: nonzero_u64(row, "limit_amount")?,
        available: blob_u64(row, "available")?,
        reserved: blob_u64(row, "reserved")?,
        consumed: blob_u64(row, "consumed")?,
        revision: nonzero_u64(row, "revision")?,
    };
    let total = quota
        .available
        .checked_add(quota.reserved)
        .and_then(|value| value.checked_add(quota.consumed))
        .ok_or(AuthBusAuthorityError::CorruptState(
            "quota accounting overflow",
        ))?;
    if quota.scope_digest.is_zero() || total != quota.limit {
        return Err(AuthBusAuthorityError::CorruptState(
            "quota conservation invariant failed",
        ));
    }
    Ok(quota)
}

fn reservation_from_row(row: &SqliteRow) -> Result<QuotaReservation, AuthBusAuthorityError> {
    let state: String = row.try_get("state").map_err(storage)?;
    let amount = nonzero_u64(row, "amount")?;
    let reservation = QuotaReservation {
        reservation_id: stable_id(row.try_get("reservation_id").map_err(storage)?)?,
        operation_id: stable_id(row.try_get("operation_id").map_err(storage)?)?,
        quota_key: stable_id(row.try_get("quota_key").map_err(storage)?)?,
        period_id: stable_id(row.try_get("period_id").map_err(storage)?)?,
        principal: stable_id(row.try_get("principal").map_err(storage)?)?,
        amount,
        effect_digest: Digest32::from_array(blob_array::<32>(row, "effect_digest")?),
        policy_id: stable_id(row.try_get("policy_id").map_err(storage)?)?,
        policy_revision: nonzero_u64(row, "policy_revision")?,
        policy_decision_digest: Digest32::from_array(blob_array::<32>(
            row,
            "policy_decision_digest",
        )?),
        state: reservation_state(&state)?,
        revision: nonzero_u64(row, "revision")?,
        expires_at_ms: nonzero_u64(row, "expires_at_ms")?,
        created_at_ms: nonzero_u64(row, "created_at_ms")?,
        updated_at_ms: nonzero_u64(row, "updated_at_ms")?,
        dispatch_digest: optional_digest(row, "dispatch_digest")?,
        terminal_evidence: optional_digest(row, "terminal_evidence")?,
        observed_cost: optional_u64(row, "observed_cost")?,
        settlement_digest: optional_digest(row, "settlement_digest")?,
    };
    if reservation.policy_decision_digest.is_zero()
        || reservation.effect_digest.is_zero()
        || reservation.updated_at_ms < reservation.created_at_ms
    {
        return Err(AuthBusAuthorityError::CorruptState(
            "invalid quota reservation record",
        ));
    }
    Ok(reservation)
}

fn reservation_matches(
    existing: &QuotaReservation,
    decision: &PolicyDecision,
    request: &ReservationRequest,
) -> bool {
    existing.quota_key == request.quota_key
        && existing.operation_id == request.operation_id
        && existing.amount == request.amount
        && existing.effect_digest == request.effect_digest
        && existing.policy_id == *decision.policy_id()
        && existing.policy_revision == decision.policy_revision()
        && existing.policy_decision_digest == decision.decision_digest()
        && existing.expires_at_ms == request.expires_at_ms
}

fn reservation_id(
    decision: &PolicyDecision,
    request: &ReservationRequest,
) -> Result<StableId, AuthBusAuthorityError> {
    let mut bytes = b"hepta.authbus.quota-reservation.v1\0".to_vec();
    crate::push_id(&mut bytes, &request.operation_id);
    crate::push_id(&mut bytes, &request.quota_key);
    bytes.extend_from_slice(&request.amount.to_be_bytes());
    bytes.extend_from_slice(request.effect_digest.as_array());
    bytes.extend_from_slice(decision.decision_digest().as_array());
    bytes.extend_from_slice(&request.expires_at_ms.to_be_bytes());
    StableId::new(format!("reservation:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| AuthBusAuthorityError::CorruptState("reservation ID overflow"))
}

fn validate_quota_spec(spec: &QuotaSpec) -> Result<(), AuthBusAuthorityError> {
    if spec.scope_digest.is_zero() || spec.limit == 0 {
        return Err(AuthBusAuthorityError::InvalidInput(
            "quota scope and limit must be non-zero",
        ));
    }
    Ok(())
}

fn reservation_state(value: &str) -> Result<ReservationState, AuthBusAuthorityError> {
    match value {
        "held" => Ok(ReservationState::Held),
        "dispatch_attempted" => Ok(ReservationState::DispatchAttempted),
        "indeterminate" => Ok(ReservationState::Indeterminate),
        "settled" => Ok(ReservationState::Settled),
        "released" => Ok(ReservationState::Released),
        "expired" => Ok(ReservationState::Expired),
        _ => Err(AuthBusAuthorityError::CorruptState(
            "invalid quota reservation state",
        )),
    }
}

fn blob_u64(row: &SqliteRow, column: &str) -> Result<u64, AuthBusAuthorityError> {
    Ok(u64::from_be_bytes(blob_array::<8>(row, column)?))
}

fn optional_u64(row: &SqliteRow, column: &str) -> Result<Option<u64>, AuthBusAuthorityError> {
    row.try_get::<Option<Vec<u8>>, _>(column)
        .map_err(storage)?
        .map(|bytes| {
            bytes
                .try_into()
                .map(u64::from_be_bytes)
                .map_err(|_| AuthBusAuthorityError::CorruptState("invalid optional u64"))
        })
        .transpose()
}

fn optional_digest(
    row: &SqliteRow,
    column: &str,
) -> Result<Option<Digest32>, AuthBusAuthorityError> {
    row.try_get::<Option<Vec<u8>>, _>(column)
        .map_err(storage)?
        .map(|bytes| {
            bytes
                .try_into()
                .map(Digest32::from_array)
                .map_err(|_| AuthBusAuthorityError::CorruptState("invalid optional digest"))
        })
        .transpose()
}

#[cfg(test)]
#[path = "quota_store_tests.rs"]
mod tests;
