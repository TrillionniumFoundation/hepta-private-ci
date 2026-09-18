use codex_hepta_authbus::PolicyDecision;
use codex_hepta_authbus::PolicyRevision;
use codex_hepta_authbus::QuotaConfig;
use codex_hepta_authbus::Reservation;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::Settlement;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusControlError {
    #[error("AuthBus control request is invalid: {0}")]
    Invalid(&'static str),
    #[error("AuthBus policy denied the operation")]
    Denied,
    #[error("AuthBus policy or quota revision is stale")]
    StaleRevision,
    #[error("AuthBus quota is exhausted")]
    QuotaExceeded,
    #[error("AuthBus control identity was reused with different semantics")]
    IdempotencyConflict,
    #[error("AuthBus reservation was not found")]
    NotFound,
    #[error("AuthBus reservation state does not permit this transition")]
    InvalidTransition,
    #[error(transparent)]
    Storage(#[from] EvidenceError),
}

impl HeptaEvidenceStore {
    pub async fn install_authbus_policy(
        &self,
        policy: &PolicyRevision,
        revoked: bool,
    ) -> Result<(), AuthBusControlError> {
        if policy.revision == 0 || policy.rules.is_empty() || policy.rules.len() > 1024 {
            return Err(AuthBusControlError::Invalid("invalid policy revision"));
        }
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let previous: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT revision FROM authbus_policy_heads WHERE policy_id = ?",
        )
        .bind(policy.policy_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(previous) = previous {
            let previous = decode_u64(previous)?;
            if policy.revision <= previous {
                return Err(AuthBusControlError::StaleRevision);
            }
        }
        for rule in &policy.rules {
            sqlx::query(
                "INSERT INTO authbus_policy_rules
                (policy_id, revision, principal_id, action_id, scope_digest, allow)
                VALUES (?, ?, ?, ?, ?, ?)",
            )
            .bind(policy.policy_id.as_str())
            .bind(policy.revision.to_be_bytes().as_slice())
            .bind(rule.principal_id.as_str())
            .bind(rule.action_id.as_str())
            .bind(rule.scope_digest.as_array().as_slice())
            .bind(i64::from(rule.allow))
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        sqlx::query(
            "INSERT INTO authbus_policy_heads(policy_id, revision, revoked, updated_at_ms)
             VALUES (?, ?, ?, ?)
             ON CONFLICT(policy_id) DO UPDATE SET revision=excluded.revision,
             revoked=excluded.revoked, updated_at_ms=excluded.updated_at_ms",
        )
        .bind(policy.policy_id.as_str())
        .bind(policy.revision.to_be_bytes().as_slice())
        .bind(i64::from(revoked))
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn set_authbus_policy_revoked(
        &self,
        policy_id: &StableId,
        revision: u64,
        revoked: bool,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        require_policy_head(&mut tx, policy_id, revision, None).await?;
        sqlx::query("UPDATE authbus_policy_heads SET revoked = ?, updated_at_ms = ? WHERE policy_id = ?")
            .bind(i64::from(revoked))
            .bind(now_millis()?)
            .bind(policy_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn configure_authbus_quota(
        &self,
        quota: &QuotaConfig,
    ) -> Result<(), AuthBusControlError> {
        if quota.revision == 0 {
            return Err(AuthBusControlError::Invalid("quota revision must be nonzero"));
        }
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT revision, reserved, consumed FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(quota.quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let (reserved, consumed) = if let Some(row) = row {
            let revision = decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
            if quota.revision <= revision {
                return Err(AuthBusControlError::StaleRevision);
            }
            (
                decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?,
                decode_u64(row.try_get("consumed").map_err(classify_sqlx_error)?)?,
            )
        } else {
            (0, 0)
        };
        if reserved.checked_add(consumed).is_none_or(|used| used > quota.endowment) {
            return Err(AuthBusControlError::Invalid("new endowment is below committed quota"));
        }
        sqlx::query(
            "INSERT INTO authbus_quota_registry
             (quota_key, revision, endowment, reserved, consumed, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(quota_key) DO UPDATE SET revision=excluded.revision,
             endowment=excluded.endowment, updated_at_ms=excluded.updated_at_ms",
        )
        .bind(quota.quota_key.as_str())
        .bind(quota.revision.to_be_bytes().as_slice())
        .bind(quota.endowment.to_be_bytes().as_slice())
        .bind(reserved.to_be_bytes().as_slice())
        .bind(consumed.to_be_bytes().as_slice())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn authorize_and_reserve_authbus(
        &self,
        policy_id: &StableId,
        policy_revision: u64,
        principal_id: &StableId,
        action_id: &StableId,
        scope_digest: Digest32,
        quota_key: &StableId,
        quota_revision: u64,
        reservation_id: &StableId,
        operation_id: &StableId,
        amount: u64,
        expires_at_ms: u64,
    ) -> Result<(PolicyDecision, Reservation), AuthBusControlError> {
        if amount == 0 || expires_at_ms == 0 {
            return Err(AuthBusControlError::Invalid("reservation amount/expiry must be nonzero"));
        }
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let decision = authorize_in_tx(
            &mut tx,
            policy_id,
            policy_revision,
            principal_id,
            action_id,
            scope_digest,
        )
        .await?;
        if let Some(existing) = load_reservation_by_operation(&mut tx, operation_id).await? {
            if existing.reservation_id == *reservation_id
                && existing.quota_key == *quota_key
                && existing.amount == amount
                && existing.expires_at_ms == expires_at_ms
                && existing.policy_id == *policy_id
                && existing.policy_revision == policy_revision
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok((decision, existing));
            }
            return Err(AuthBusControlError::IdempotencyConflict);
        }
        let row = sqlx::query(
            "SELECT revision, endowment, reserved, consumed
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::NotFound)?;
        if decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)? != quota_revision {
            return Err(AuthBusControlError::StaleRevision);
        }
        let endowment = decode_u64(row.try_get("endowment").map_err(classify_sqlx_error)?)?;
        let reserved = decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
        let consumed = decode_u64(row.try_get("consumed").map_err(classify_sqlx_error)?)?;
        let used = reserved.checked_add(consumed).ok_or(AuthBusControlError::QuotaExceeded)?;
        let next_reserved = reserved.checked_add(amount).ok_or(AuthBusControlError::QuotaExceeded)?;
        if used.checked_add(amount).is_none_or(|next| next > endowment) {
            return Err(AuthBusControlError::QuotaExceeded);
        }
        let now = now_millis()?;
        sqlx::query(
            "INSERT INTO authbus_quota_reservations
             (reservation_id, operation_id, quota_key, amount, expires_at_ms, policy_id,
              policy_revision, state, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        )
        .bind(reservation_id.as_str())
        .bind(operation_id.as_str())
        .bind(quota_key.as_str())
        .bind(amount.to_be_bytes().as_slice())
        .bind(expires_at_ms.to_be_bytes().as_slice())
        .bind(policy_id.as_str())
        .bind(policy_revision.to_be_bytes().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "UPDATE authbus_quota_registry SET reserved = ?, updated_at_ms = ? WHERE quota_key = ?",
        )
        .bind(next_reserved.to_be_bytes().as_slice())
        .bind(now)
        .bind(quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok((
            decision,
            Reservation {
                reservation_id: reservation_id.clone(),
                operation_id: operation_id.clone(),
                quota_key: quota_key.clone(),
                amount,
                expires_at_ms,
                policy_id: policy_id.clone(),
                policy_revision,
                state: ReservationState::Active,
            },
        ))
    }

    pub async fn settle_authbus_reservation(
        &self,
        reservation_id: &StableId,
        observed_cost: u64,
        terminal_evidence: Digest32,
    ) -> Result<Settlement, AuthBusControlError> {
        if terminal_evidence.is_zero() {
            return Err(AuthBusControlError::Invalid("terminal evidence is empty"));
        }
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let existing = load_reservation(&mut tx, reservation_id).await?;
        if existing.state == ReservationState::Settled {
            let row = sqlx::query(
                "SELECT observed_cost, terminal_evidence, settlement_digest
                 FROM authbus_quota_reservations WHERE reservation_id = ?",
            )
            .bind(reservation_id.as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
            let stored_cost = decode_u64(row.try_get("observed_cost").map_err(classify_sqlx_error)?)?;
            let stored_evidence = digest(row.try_get("terminal_evidence").map_err(classify_sqlx_error)?)?;
            let stored_digest = digest(row.try_get("settlement_digest").map_err(classify_sqlx_error)?)?;
            if stored_cost == observed_cost && stored_evidence == terminal_evidence {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(Settlement {
                    reservation_id: reservation_id.clone(),
                    observed_cost,
                    terminal_evidence,
                    settlement_digest: stored_digest,
                });
            }
            return Err(AuthBusControlError::IdempotencyConflict);
        }
        if !matches!(existing.state, ReservationState::Active | ReservationState::Quarantined)
            || observed_cost > existing.amount
        {
            return Err(AuthBusControlError::InvalidTransition);
        }
        let quota = sqlx::query(
            "SELECT reserved, consumed FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(existing.quota_key.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let reserved = decode_u64(quota.try_get("reserved").map_err(classify_sqlx_error)?)?;
        let consumed = decode_u64(quota.try_get("consumed").map_err(classify_sqlx_error)?)?;
        let next_reserved = reserved.checked_sub(existing.amount).ok_or_else(|| {
            EvidenceError::Corrupt("AuthBus quota reservation underflow".into())
        })?;
        let next_consumed = consumed.checked_add(observed_cost).ok_or_else(|| {
            EvidenceError::Corrupt("AuthBus quota consumption overflow".into())
        })?;
        let settlement_digest = settlement_digest(reservation_id, observed_cost, terminal_evidence);
        let now = now_millis()?;
        sqlx::query(
            "UPDATE authbus_quota_reservations SET state='settled', observed_cost=?,
             terminal_evidence=?, settlement_digest=?, updated_at_ms=? WHERE reservation_id=?",
        )
        .bind(observed_cost.to_be_bytes().as_slice())
        .bind(terminal_evidence.as_array().as_slice())
        .bind(settlement_digest.as_array().as_slice())
        .bind(now)
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "UPDATE authbus_quota_registry SET reserved=?, consumed=?, updated_at_ms=? WHERE quota_key=?",
        )
        .bind(next_reserved.to_be_bytes().as_slice())
        .bind(next_consumed.to_be_bytes().as_slice())
        .bind(now)
        .bind(existing.quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(Settlement {
            reservation_id: reservation_id.clone(),
            observed_cost,
            terminal_evidence,
            settlement_digest,
        })
    }

    pub async fn cancel_authbus_reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<(), AuthBusControlError> {
        release_reservation(self, reservation_id, ReservationState::Cancelled, None).await
    }

    pub async fn expire_authbus_reservation(
        &self,
        reservation_id: &StableId,
        now_ms: u64,
    ) -> Result<(), AuthBusControlError> {
        release_reservation(self, reservation_id, ReservationState::Expired, Some(now_ms)).await
    }

    pub async fn quarantine_authbus_reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.state != ReservationState::Active {
            return Err(AuthBusControlError::InvalidTransition);
        }
        sqlx::query(
            "UPDATE authbus_quota_reservations SET state='quarantined', updated_at_ms=? WHERE reservation_id=?",
        )
        .bind(now_millis()?)
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn reconcile_authbus_quota(
        &self,
        quota_key: &StableId,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
        let row = sqlx::query("SELECT endowment FROM authbus_quota_registry WHERE quota_key=?")
            .bind(quota_key.as_str())
            .fetch_optional(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?
            .ok_or(AuthBusControlError::NotFound)?;
        let endowment = decode_u64(row.try_get("endowment").map_err(classify_sqlx_error)?)?;
        let rows = sqlx::query(
            "SELECT amount, observed_cost, state FROM authbus_quota_reservations WHERE quota_key=?",
        )
        .bind(quota_key.as_str())
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut reserved = 0_u64;
        let mut consumed = 0_u64;
        for row in rows {
            let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
            let amount = decode_u64(row.try_get("amount").map_err(classify_sqlx_error)?)?;
            match state.as_str() {
                "active" | "quarantined" => {
                    reserved = reserved.checked_add(amount).ok_or(AuthBusControlError::QuotaExceeded)?;
                }
                "settled" => {
                    let cost = decode_u64(row.try_get("observed_cost").map_err(classify_sqlx_error)?)?;
                    consumed = consumed.checked_add(cost).ok_or(AuthBusControlError::QuotaExceeded)?;
                }
                "cancelled" | "expired" => {}
                _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into()),
            }
        }
        if reserved.checked_add(consumed).is_none_or(|used| used > endowment) {
            return Err(EvidenceError::Corrupt("AuthBus quota conservation violated".into()).into());
        }
        sqlx::query(
            "UPDATE authbus_quota_registry SET reserved=?, consumed=?, updated_at_ms=? WHERE quota_key=?",
        )
        .bind(reserved.to_be_bytes().as_slice())
        .bind(consumed.to_be_bytes().as_slice())
        .bind(now_millis()?)
        .bind(quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }
}

async fn authorize_in_tx(
    tx: &mut Transaction<'_, Sqlite>,
    policy_id: &StableId,
    revision: u64,
    principal_id: &StableId,
    action_id: &StableId,
    scope_digest: Digest32,
) -> Result<PolicyDecision, AuthBusControlError> {
    require_policy_head(tx, policy_id, revision, Some(false)).await?;
    let allowed: Option<i64> = sqlx::query_scalar(
        "SELECT allow FROM authbus_policy_rules
         WHERE policy_id=? AND revision=? AND principal_id=? AND action_id=? AND scope_digest=?",
    )
    .bind(policy_id.as_str())
    .bind(revision.to_be_bytes().as_slice())
    .bind(principal_id.as_str())
    .bind(action_id.as_str())
    .bind(scope_digest.as_array().as_slice())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    if allowed != Some(1) {
        return Err(AuthBusControlError::Denied);
    }
    let mut bytes = b"hepta.authbus.policy-decision.v1\0".to_vec();
    push(&mut bytes, policy_id.as_str());
    bytes.extend_from_slice(&revision.to_be_bytes());
    push(&mut bytes, principal_id.as_str());
    push(&mut bytes, action_id.as_str());
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.push(1);
    Ok(PolicyDecision {
        policy_id: policy_id.clone(),
        revision,
        allowed: true,
        decision_digest: Digest32::of_bytes(&bytes),
    })
}

async fn require_policy_head(
    tx: &mut Transaction<'_, Sqlite>,
    policy_id: &StableId,
    revision: u64,
    revoked: Option<bool>,
) -> Result<(), AuthBusControlError> {
    let row = sqlx::query("SELECT revision, revoked FROM authbus_policy_heads WHERE policy_id=?")
        .bind(policy_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::Denied)?;
    if decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)? != revision {
        return Err(AuthBusControlError::StaleRevision);
    }
    let current_revoked: i64 = row.try_get("revoked").map_err(classify_sqlx_error)?;
    if revoked.is_some_and(|expected| current_revoked != i64::from(expected)) || current_revoked != 0 {
        return Err(AuthBusControlError::Denied);
    }
    Ok(())
}

async fn release_reservation(
    store: &HeptaEvidenceStore,
    reservation_id: &StableId,
    state: ReservationState,
    now_ms: Option<u64>,
) -> Result<(), AuthBusControlError> {
    let mut tx = store.pool.begin_with("BEGIN IMMEDIATE").await.map_err(classify_sqlx_error)?;
    let reservation = load_reservation(&mut tx, reservation_id).await?;
    if reservation.state != ReservationState::Active {
        return Err(AuthBusControlError::InvalidTransition);
    }
    if now_ms.is_some_and(|now| now < reservation.expires_at_ms) {
        return Err(AuthBusControlError::InvalidTransition);
    }
    let row = sqlx::query("SELECT reserved FROM authbus_quota_registry WHERE quota_key=?")
        .bind(reservation.quota_key.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
    let reserved = decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
    let next = reserved.checked_sub(reservation.amount).ok_or_else(|| {
        EvidenceError::Corrupt("AuthBus quota reservation underflow".into())
    })?;
    let now = i64::try_from(now_ms.unwrap_or(u64::try_from(now_millis()?).unwrap_or(u64::MAX)))
        .unwrap_or(i64::MAX);
    sqlx::query("UPDATE authbus_quota_reservations SET state=?, updated_at_ms=? WHERE reservation_id=?")
        .bind(state.as_str())
        .bind(now)
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
    sqlx::query("UPDATE authbus_quota_registry SET reserved=?, updated_at_ms=? WHERE quota_key=?")
        .bind(next.to_be_bytes().as_slice())
        .bind(now)
        .bind(reservation.quota_key.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
    tx.commit().await.map_err(classify_sqlx_error)?;
    Ok(())
}

async fn load_reservation_by_operation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<Reservation>, AuthBusControlError> {
    let row = sqlx::query("SELECT * FROM authbus_quota_reservations WHERE operation_id=?")
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
    row.map(decode_reservation).transpose()
}

async fn load_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    reservation_id: &StableId,
) -> Result<Reservation, AuthBusControlError> {
    sqlx::query("SELECT * FROM authbus_quota_reservations WHERE reservation_id=?")
        .bind(reservation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .map(decode_reservation)
        .transpose()?
        .ok_or(AuthBusControlError::NotFound)
}

fn decode_reservation(row: sqlx::sqlite::SqliteRow) -> Result<Reservation, AuthBusControlError> {
    let id = |name| -> Result<StableId, AuthBusControlError> {
        StableId::new(row.try_get::<String, _>(name).map_err(classify_sqlx_error)?)
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus control ID".into()).into())
    };
    let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
    let state = match state.as_str() {
        "active" => ReservationState::Active,
        "settled" => ReservationState::Settled,
        "cancelled" => ReservationState::Cancelled,
        "expired" => ReservationState::Expired,
        "quarantined" => ReservationState::Quarantined,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into()),
    };
    Ok(Reservation {
        reservation_id: id("reservation_id")?,
        operation_id: id("operation_id")?,
        quota_key: id("quota_key")?,
        amount: decode_u64(row.try_get("amount").map_err(classify_sqlx_error)?)?,
        expires_at_ms: decode_u64(row.try_get("expires_at_ms").map_err(classify_sqlx_error)?)?,
        policy_id: id("policy_id")?,
        policy_revision: decode_u64(row.try_get("policy_revision").map_err(classify_sqlx_error)?)?,
        state,
    })
}

fn decode_u64(bytes: Vec<u8>) -> Result<u64, AuthBusControlError> {
    let bytes: [u8; 8] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus u64 width".into()))?;
    Ok(u64::from_be_bytes(bytes))
}

fn digest(bytes: Vec<u8>) -> Result<Digest32, AuthBusControlError> {
    let bytes: [u8; 32] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus digest width".into()))?;
    Ok(Digest32::from_array(bytes))
}

fn settlement_digest(
    reservation_id: &StableId,
    observed_cost: u64,
    terminal_evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.authbus.settlement.v1\0".to_vec();
    push(&mut bytes, reservation_id.as_str());
    bytes.extend_from_slice(&observed_cost.to_be_bytes());
    bytes.extend_from_slice(terminal_evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn push(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
