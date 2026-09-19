use codex_hepta_authbus::AuthPolicy;
use codex_hepta_authbus::PolicyDecision;
use codex_hepta_authbus::QuotaDefinition;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::TrustedTime;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

const MAX_TRUSTED_TIME_UNCERTAINTY_MS: u64 = 5_000;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusAuthorityError {
    #[error("invalid AuthBus authority request: {0}")]
    Invalid(&'static str),
    #[error("AuthBus policy is absent")]
    MissingPolicy,
    #[error("AuthBus policy denied the requested action")]
    Denied,
    #[error("AuthBus trust registration is absent")]
    MissingTrust,
    #[error("AuthBus policy or quota revision is stale")]
    StaleRevision,
    #[error("AuthBus identity is already bound to different semantics")]
    Conflict,
    #[error("AuthBus quota is absent")]
    MissingQuota,
    #[error("AuthBus quota is exhausted")]
    QuotaExceeded,
    #[error("AuthBus reservation is absent")]
    MissingReservation,
    #[error("AuthBus reservation is terminal or incompatible with this transition")]
    InvalidReservationState,
    #[error("AuthBus observed cost exceeds the safely accountable endowment")]
    UsageOverrun,
    #[error(transparent)]
    Authority(#[from] codex_hepta_authbus::AuthorityError),
    #[error(transparent)]
    Storage(#[from] EvidenceError),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusQuotaStatus {
    pub quota_key: StableId,
    pub limit: u64,
    pub available: u64,
    pub reserved: u64,
    pub consumed: u64,
    pub revision: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthBusSettlementOutcome {
    Applied { observed_cost: u64 },
    NotApplied,
    Indeterminate,
}

impl HeptaEvidenceStore {
    /// Append one immutable policy revision. Replaying the exact revision is
    /// idempotent; a reused revision with different semantics conflicts.
    pub async fn publish_authbus_policy(
        &self,
        policy: &AuthPolicy,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        policy.validate()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let rows = sqlx::query(
            "SELECT policy_id, principal_id, action_id, scope_digest, revision,
                    allowed, revoked, policy_digest
             FROM authbus_policy_revisions
             WHERE policy_id = ? ORDER BY revision DESC LIMIT 1",
        )
        .bind(policy.policy_id.as_str())
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = rows.first() {
            let revision = i64_to_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
            if revision == policy.revision {
                let stored = decode_policy(row)?;
                if stored == *policy {
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(PolicyDecision::from_policy(policy));
                }
                return Err(AuthBusAuthorityError::Conflict);
            }
            if policy.revision
                != revision
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::StaleRevision)?
            {
                return Err(AuthBusAuthorityError::StaleRevision);
            }
        } else if policy.revision != 1 {
            return Err(AuthBusAuthorityError::StaleRevision);
        }

        let competing: Option<String> = sqlx::query_scalar(
            "SELECT policy_id FROM authbus_policy_revisions
             WHERE principal_id = ? AND action_id = ? AND scope_digest = ?
             ORDER BY revision DESC LIMIT 1",
        )
        .bind(policy.principal_id.as_str())
        .bind(policy.action_id.as_str())
        .bind(policy.scope_digest.as_array().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if competing
            .as_deref()
            .is_some_and(|policy_id| policy_id != policy.policy_id.as_str())
        {
            return Err(AuthBusAuthorityError::Conflict);
        }

        sqlx::query(
            "INSERT INTO authbus_policy_revisions
             (policy_id, principal_id, action_id, scope_digest, revision,
              allowed, revoked, policy_digest, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(policy.policy_id.as_str())
        .bind(policy.principal_id.as_str())
        .bind(policy.action_id.as_str())
        .bind(policy.scope_digest.as_array().as_slice())
        .bind(u64_to_i64(policy.revision)?)
        .bind(policy.allowed)
        .bind(policy.revoked)
        .bind(policy.digest().as_array().as_slice())
        .bind(crate::store::now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(PolicyDecision::from_policy(policy))
    }

    /// Resolve the current exact principal/action/scope policy. Missing policy,
    /// stale revision and revoked/deny revisions all fail closed.
    pub async fn authorize_authbus(
        &self,
        principal_id: &StableId,
        action_id: &StableId,
        scope_digest: Digest32,
        expected_revision: u64,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        if scope_digest.is_zero() || expected_revision == 0 {
            return Err(AuthBusAuthorityError::Invalid("scope/revision is invalid"));
        }
        let row = sqlx::query(
            "SELECT policy_id, principal_id, action_id, scope_digest, revision,
                    allowed, revoked, policy_digest
             FROM authbus_policy_revisions
             WHERE principal_id = ? AND action_id = ? AND scope_digest = ?
             ORDER BY revision DESC LIMIT 1",
        )
        .bind(principal_id.as_str())
        .bind(action_id.as_str())
        .bind(scope_digest.as_array().as_slice())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusAuthorityError::MissingPolicy)?;
        let policy = decode_policy(&row)?;
        if policy.revision != expected_revision {
            return Err(AuthBusAuthorityError::StaleRevision);
        }
        let decision = PolicyDecision::from_policy(&policy);
        if !decision.allowed {
            return Err(AuthBusAuthorityError::Denied);
        }
        Ok(decision)
    }

    /// Create or revise a quota endowment. A revision change is accepted only
    /// when no amount is currently reserved; consumed usage is preserved.
    pub async fn configure_authbus_quota(
        &self,
        definition: &QuotaDefinition,
    ) -> Result<AuthBusQuotaStatus, AuthBusAuthorityError> {
        definition.validate()?;
        let limit = u64_to_i64(definition.limit)?;
        let revision = u64_to_i64(definition.revision)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT limit_value, available, reserved, consumed, revision
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(definition.quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = row {
            let current = decode_quota(definition.quota_key.clone(), &row)?;
            if current.revision == definition.revision && current.limit == definition.limit {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(current);
            }
            if definition.revision
                != current
                    .revision
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::StaleRevision)?
                || current.reserved != 0
                || definition.limit < current.consumed
            {
                return Err(AuthBusAuthorityError::StaleRevision);
            }
            let available = definition.limit - current.consumed;
            sqlx::query(
                "UPDATE authbus_quota_registry
                 SET limit_value = ?, available = ?, revision = ?
                 WHERE quota_key = ? AND revision = ?",
            )
            .bind(limit)
            .bind(u64_to_i64(available)?)
            .bind(revision)
            .bind(definition.quota_key.as_str())
            .bind(u64_to_i64(current.revision)?)
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        } else {
            if definition.revision != 1 {
                return Err(AuthBusAuthorityError::StaleRevision);
            }
            sqlx::query(
                "INSERT INTO authbus_quota_registry
                 (quota_key, limit_value, available, reserved, consumed, revision)
                 VALUES (?, ?, ?, 0, 0, ?)",
            )
            .bind(definition.quota_key.as_str())
            .bind(limit)
            .bind(limit)
            .bind(revision)
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        let status = load_quota(&mut tx, &definition.quota_key).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn authbus_quota_status(
        &self,
        quota_key: &StableId,
    ) -> Result<AuthBusQuotaStatus, AuthBusAuthorityError> {
        let row = sqlx::query(
            "SELECT limit_value, available, reserved, consumed, revision
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(quota_key.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusAuthorityError::MissingQuota)?;
        decode_quota(quota_key.clone(), &row)
    }

    /// Atomically reserve quota. The operation ID is a second idempotency key:
    /// it cannot acquire another hold under a different reservation ID.
    pub async fn reserve_authbus_quota(
        &self,
        reservation_id: StableId,
        quota_key: StableId,
        operation_id: StableId,
        amount: u64,
        expected_revision: u64,
        expires_at_ms: u64,
        time: &TrustedTime,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        time.validate(MAX_TRUSTED_TIME_UNCERTAINTY_MS)?;
        if expires_at_ms <= time.now_ms {
            return Err(AuthBusAuthorityError::Invalid(
                "reservation already expired",
            ));
        }
        let candidate = QuotaReservation::new(
            reservation_id.clone(),
            quota_key.clone(),
            operation_id.clone(),
            amount,
            expires_at_ms,
            expected_revision,
        )?;
        let amount_i64 = u64_to_i64(amount)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;

        if let Some(existing) =
            load_reservation_by_identity(&mut tx, &reservation_id, &operation_id).await?
        {
            if existing.reservation_digest == candidate.reservation_digest {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(existing);
            }
            return Err(AuthBusAuthorityError::Conflict);
        }

        let quota = load_quota(&mut tx, &quota_key).await?;
        if quota.revision != expected_revision {
            return Err(AuthBusAuthorityError::StaleRevision);
        }
        if quota.available < amount {
            return Err(AuthBusAuthorityError::QuotaExceeded);
        }
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or(AuthBusAuthorityError::StaleRevision)?;
        let updated = sqlx::query(
            "UPDATE authbus_quota_registry
             SET available = available - ?, reserved = reserved + ?, revision = ?
             WHERE quota_key = ? AND revision = ? AND available >= ?",
        )
        .bind(amount_i64)
        .bind(amount_i64)
        .bind(u64_to_i64(next_revision)?)
        .bind(quota_key.as_str())
        .bind(u64_to_i64(expected_revision)?)
        .bind(amount_i64)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if updated.rows_affected() != 1 {
            return Err(AuthBusAuthorityError::StaleRevision);
        }

        let now = u64_to_i64(time.now_ms)?;
        sqlx::query(
            "INSERT INTO authbus_quota_reservations
             (reservation_id, quota_key, operation_id, amount, observed_cost,
              expires_at_ms, quota_revision, state, reservation_digest,
              settlement_digest, revision, created_at_ms, updated_at_ms)
             VALUES (?, ?, ?, ?, NULL, ?, ?, 'held', ?, NULL, 1, ?, ?)",
        )
        .bind(reservation_id.as_str())
        .bind(quota_key.as_str())
        .bind(operation_id.as_str())
        .bind(amount_i64)
        .bind(u64_to_i64(expires_at_ms)?)
        .bind(u64_to_i64(expected_revision)?)
        .bind(candidate.reservation_digest.as_array().as_slice())
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let result = load_reservation(&mut tx, &reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    /// Reconcile a held/indeterminate reservation from authenticated terminal
    /// evidence. Unknown outcomes retain the hold; NotApplied releases it;
    /// Applied settles observed cost and refunds only the unused reservation.
    pub async fn reconcile_authbus_reservation(
        &self,
        reservation_id: &StableId,
        terminal_evidence: Digest32,
        outcome: AuthBusSettlementOutcome,
        time: &TrustedTime,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        time.validate(MAX_TRUSTED_TIME_UNCERTAINTY_MS)?;
        if terminal_evidence.is_zero() {
            return Err(AuthBusAuthorityError::Invalid("terminal evidence is empty"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation(&mut tx, reservation_id).await?;

        if reservation.state == ReservationState::Settled {
            if let AuthBusSettlementOutcome::Applied { observed_cost } = outcome
                && reservation.observed_cost == Some(observed_cost)
                && reservation.settlement_digest
                    == Some(reservation_digest_for_outcome(
                        &reservation,
                        terminal_evidence,
                        outcome,
                    ))
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusAuthorityError::Conflict);
        }
        if reservation.state == ReservationState::Cancelled {
            if outcome == AuthBusSettlementOutcome::NotApplied
                && reservation.settlement_digest
                    == Some(reservation_digest_for_outcome(
                        &reservation,
                        terminal_evidence,
                        outcome,
                    ))
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusAuthorityError::Conflict);
        }
        if reservation.state == ReservationState::Indeterminate
            && outcome == AuthBusSettlementOutcome::Indeterminate
        {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(reservation);
        }
        if reservation.state.is_terminal() {
            return Err(AuthBusAuthorityError::InvalidReservationState);
        }

        match outcome {
            AuthBusSettlementOutcome::Indeterminate => {
                sqlx::query(
                    "UPDATE authbus_quota_reservations
                     SET state = 'indeterminate', revision = revision + 1, updated_at_ms = ?
                     WHERE reservation_id = ? AND state IN ('held', 'indeterminate')",
                )
                .bind(u64_to_i64(time.now_ms)?)
                .bind(reservation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            }
            AuthBusSettlementOutcome::NotApplied => {
                release_hold(&mut tx, &reservation, time.now_ms).await?;
                sqlx::query(
                    "UPDATE authbus_quota_reservations
                     SET state = 'cancelled', settlement_digest = ?,
                         revision = revision + 1, updated_at_ms = ?
                     WHERE reservation_id = ? AND state IN ('held', 'indeterminate')",
                )
                .bind(
                    reservation_digest_for_outcome(&reservation, terminal_evidence, outcome)
                        .as_array()
                        .as_slice(),
                )
                .bind(u64_to_i64(time.now_ms)?)
                .bind(reservation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            }
            AuthBusSettlementOutcome::Applied { observed_cost } => {
                if observed_cost > reservation.amount {
                    sqlx::query(
                        "UPDATE authbus_quota_reservations
                         SET state = 'indeterminate', revision = revision + 1, updated_at_ms = ?
                         WHERE reservation_id = ? AND state IN ('held', 'indeterminate')",
                    )
                    .bind(u64_to_i64(time.now_ms)?)
                    .bind(reservation_id.as_str())
                    .execute(&mut *tx)
                    .await
                    .map_err(classify_sqlx_error)?;
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Err(AuthBusAuthorityError::UsageOverrun);
                }
                let refund = reservation.amount - observed_cost;
                let quota = load_quota(&mut tx, &reservation.quota_key).await?;
                let next_revision = quota
                    .revision
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::StaleRevision)?;
                let updated = sqlx::query(
                    "UPDATE authbus_quota_registry
                     SET reserved = reserved - ?, available = available + ?,
                         consumed = consumed + ?, revision = ?
                     WHERE quota_key = ? AND reserved >= ?",
                )
                .bind(u64_to_i64(reservation.amount)?)
                .bind(u64_to_i64(refund)?)
                .bind(u64_to_i64(observed_cost)?)
                .bind(u64_to_i64(next_revision)?)
                .bind(reservation.quota_key.as_str())
                .bind(u64_to_i64(reservation.amount)?)
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
                if updated.rows_affected() != 1 {
                    return Err(EvidenceError::Corrupt(
                        "AuthBus reservation hold is missing".into(),
                    )
                    .into());
                }
                sqlx::query(
                    "UPDATE authbus_quota_reservations
                     SET state = 'settled', observed_cost = ?, settlement_digest = ?,
                         revision = revision + 1, updated_at_ms = ?
                     WHERE reservation_id = ? AND state IN ('held', 'indeterminate')",
                )
                .bind(u64_to_i64(observed_cost)?)
                .bind(
                    reservation_digest_for_outcome(&reservation, terminal_evidence, outcome)
                        .as_array()
                        .as_slice(),
                )
                .bind(u64_to_i64(time.now_ms)?)
                .bind(reservation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            }
        }
        let result = load_reservation(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    /// Expiry never assumes an external effect did not happen. Expired held
    /// reservations become indeterminate and continue holding quota until
    /// authenticated reconciliation proves Applied or NotApplied.
    pub async fn expire_authbus_reservations(
        &self,
        time: &TrustedTime,
        limit: u32,
    ) -> Result<u64, AuthBusAuthorityError> {
        time.validate(MAX_TRUSTED_TIME_UNCERTAINTY_MS)?;
        if limit == 0 || limit > 256 {
            return Err(AuthBusAuthorityError::Invalid(
                "expiry limit must be 1..=256",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let result = sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state = 'indeterminate', revision = revision + 1, updated_at_ms = ?
             WHERE reservation_id IN (
                 SELECT reservation_id FROM authbus_quota_reservations
                 WHERE state = 'held' AND expires_at_ms <= ?
                 ORDER BY expires_at_ms, reservation_id LIMIT ?
             )",
        )
        .bind(u64_to_i64(time.now_ms)?)
        .bind(u64_to_i64(time.now_ms)?)
        .bind(i64::from(limit))
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result.rows_affected())
    }
}

async fn load_quota(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    quota_key: &StableId,
) -> Result<AuthBusQuotaStatus, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT limit_value, available, reserved, consumed, revision
         FROM authbus_quota_registry WHERE quota_key = ?",
    )
    .bind(quota_key.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or(AuthBusAuthorityError::MissingQuota)?;
    decode_quota(quota_key.clone(), &row)
}

fn decode_quota(
    quota_key: StableId,
    row: &sqlx::sqlite::SqliteRow,
) -> Result<AuthBusQuotaStatus, AuthBusAuthorityError> {
    let limit = i64_to_u64(row.try_get("limit_value").map_err(classify_sqlx_error)?)?;
    let available = i64_to_u64(row.try_get("available").map_err(classify_sqlx_error)?)?;
    let reserved = i64_to_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
    let consumed = i64_to_u64(row.try_get("consumed").map_err(classify_sqlx_error)?)?;
    let revision = i64_to_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
    if available
        .checked_add(reserved)
        .and_then(|value| value.checked_add(consumed))
        != Some(limit)
    {
        return Err(EvidenceError::Corrupt("AuthBus quota conservation violated".into()).into());
    }
    Ok(AuthBusQuotaStatus {
        quota_key,
        limit,
        available,
        reserved,
        consumed,
        revision,
    })
}

fn decode_policy(row: &sqlx::sqlite::SqliteRow) -> Result<AuthPolicy, AuthBusAuthorityError> {
    let policy = AuthPolicy {
        policy_id: stable_id(row.try_get("policy_id").map_err(classify_sqlx_error)?)?,
        principal_id: stable_id(row.try_get("principal_id").map_err(classify_sqlx_error)?)?,
        action_id: stable_id(row.try_get("action_id").map_err(classify_sqlx_error)?)?,
        scope_digest: digest(row.try_get("scope_digest").map_err(classify_sqlx_error)?)?,
        revision: i64_to_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?,
        allowed: row.try_get("allowed").map_err(classify_sqlx_error)?,
        revoked: row.try_get("revoked").map_err(classify_sqlx_error)?,
    };
    let stored_digest = digest(row.try_get("policy_digest").map_err(classify_sqlx_error)?)?;
    if policy.digest() != stored_digest {
        return Err(EvidenceError::Corrupt("AuthBus policy digest mismatch".into()).into());
    }
    policy.validate()?;
    Ok(policy)
}

async fn load_reservation_by_identity(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    reservation_id: &StableId,
    operation_id: &StableId,
) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT reservation_id, quota_key, operation_id, amount, observed_cost,
                expires_at_ms, quota_revision, state, reservation_digest, settlement_digest
         FROM authbus_quota_reservations
         WHERE reservation_id = ? OR operation_id = ? LIMIT 1",
    )
    .bind(reservation_id.as_str())
    .bind(operation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_reservation(&row)).transpose()
}

async fn load_reservation(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    reservation_id: &StableId,
) -> Result<QuotaReservation, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT reservation_id, quota_key, operation_id, amount, observed_cost,
                expires_at_ms, quota_revision, state, reservation_digest, settlement_digest
         FROM authbus_quota_reservations WHERE reservation_id = ?",
    )
    .bind(reservation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or(AuthBusAuthorityError::MissingReservation)?;
    decode_reservation(&row)
}

fn decode_reservation(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<QuotaReservation, AuthBusAuthorityError> {
    let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
    let state = match state.as_str() {
        "held" => ReservationState::Held,
        "indeterminate" => ReservationState::Indeterminate,
        "settled" => ReservationState::Settled,
        "cancelled" => ReservationState::Cancelled,
        "expired" => ReservationState::Expired,
        "quarantined" => ReservationState::Quarantined,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into()),
    };
    Ok(QuotaReservation {
        reservation_id: stable_id(row.try_get("reservation_id").map_err(classify_sqlx_error)?)?,
        quota_key: stable_id(row.try_get("quota_key").map_err(classify_sqlx_error)?)?,
        operation_id: stable_id(row.try_get("operation_id").map_err(classify_sqlx_error)?)?,
        amount: i64_to_u64(row.try_get("amount").map_err(classify_sqlx_error)?)?,
        expires_at_ms: i64_to_u64(row.try_get("expires_at_ms").map_err(classify_sqlx_error)?)?,
        quota_revision: i64_to_u64(row.try_get("quota_revision").map_err(classify_sqlx_error)?)?,
        state,
        observed_cost: row
            .try_get::<Option<i64>, _>("observed_cost")
            .map_err(classify_sqlx_error)?
            .map(i64_to_u64)
            .transpose()?,
        reservation_digest: digest(
            row.try_get("reservation_digest")
                .map_err(classify_sqlx_error)?,
        )?,
        settlement_digest: row
            .try_get::<Option<Vec<u8>>, _>("settlement_digest")
            .map_err(classify_sqlx_error)?
            .map(digest)
            .transpose()?,
    })
}

async fn release_hold(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    reservation: &QuotaReservation,
    now_ms: u64,
) -> Result<(), AuthBusAuthorityError> {
    let quota = load_quota(tx, &reservation.quota_key).await?;
    let next_revision = quota
        .revision
        .checked_add(1)
        .ok_or(AuthBusAuthorityError::StaleRevision)?;
    let updated = sqlx::query(
        "UPDATE authbus_quota_registry
         SET reserved = reserved - ?, available = available + ?, revision = ?
         WHERE quota_key = ? AND reserved >= ?",
    )
    .bind(u64_to_i64(reservation.amount)?)
    .bind(u64_to_i64(reservation.amount)?)
    .bind(u64_to_i64(next_revision)?)
    .bind(reservation.quota_key.as_str())
    .bind(u64_to_i64(reservation.amount)?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    if updated.rows_affected() != 1 {
        return Err(EvidenceError::Corrupt("AuthBus reservation hold is missing".into()).into());
    }
    let _ = now_ms;
    Ok(())
}

fn reservation_digest_for_outcome(
    reservation: &QuotaReservation,
    evidence: Digest32,
    outcome: AuthBusSettlementOutcome,
) -> Digest32 {
    let cost = match outcome {
        AuthBusSettlementOutcome::Applied { observed_cost } => observed_cost,
        AuthBusSettlementOutcome::NotApplied => 0,
        AuthBusSettlementOutcome::Indeterminate => u64::MAX,
    };
    reservation.settlement_digest(cost, evidence)
}

fn stable_id(value: String) -> Result<StableId, AuthBusAuthorityError> {
    StableId::new(value)
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus stored identifier".into()).into())
}

fn digest(value: Vec<u8>) -> Result<Digest32, AuthBusAuthorityError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus digest width".into()))?;
    Ok(Digest32::from_array(bytes))
}

fn u64_to_i64(value: u64) -> Result<i64, AuthBusAuthorityError> {
    i64::try_from(value).map_err(|_| AuthBusAuthorityError::Invalid("value exceeds SQLite i64"))
}

fn i64_to_u64(value: i64) -> Result<u64, AuthBusAuthorityError> {
    u64::try_from(value)
        .map_err(|_| EvidenceError::Corrupt("negative AuthBus accounting value".into()).into())
}
