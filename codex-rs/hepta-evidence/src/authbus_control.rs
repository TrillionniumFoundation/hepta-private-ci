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
use std::collections::BTreeSet;

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
    #[error("AuthBus restore checkpoint indicates rollback or drift")]
    RollbackDetected,
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
        let digest = canonical_policy_digest(policy)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let previous = sqlx::query(
            "SELECT revision, policy_digest, revoked FROM authbus_policy_heads WHERE policy_id = ?",
        )
        .bind(policy.policy_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(previous) = previous {
            let previous_revision =
                decode_u64(previous.try_get("revision").map_err(classify_sqlx_error)?)?;
            let previous_digest = digest32(
                previous
                    .try_get("policy_digest")
                    .map_err(classify_sqlx_error)?,
            )?;
            let previous_revoked: i64 =
                previous.try_get("revoked").map_err(classify_sqlx_error)?;
            if policy.revision == previous_revision {
                if previous_digest == digest && previous_revoked == if revoked { 1 } else { 0 } {
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(());
                }
                return Err(AuthBusControlError::IdempotencyConflict);
            }
            if policy.revision < previous_revision {
                return Err(AuthBusControlError::StaleRevision);
            }
            if previous_revoked != 0 {
                return Err(AuthBusControlError::Denied);
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
            .bind(if rule.allow { 1_i64 } else { 0_i64 })
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        sqlx::query(
            "INSERT INTO authbus_policy_heads(policy_id, revision, policy_digest, revoked, updated_at_ms)
             VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(policy_id) DO UPDATE SET revision=excluded.revision,
             policy_digest=excluded.policy_digest, revoked=excluded.revoked,
             updated_at_ms=excluded.updated_at_ms",
        )
        .bind(policy.policy_id.as_str())
        .bind(policy.revision.to_be_bytes().as_slice())
        .bind(digest.as_array().as_slice())
        .bind(if revoked { 1_i64 } else { 0_i64 })
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
        if !revoked {
            return Err(AuthBusControlError::Invalid(
                "policy revocation is monotonic",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_policy_head(&mut tx, policy_id, revision, Some(false)).await?;
        sqlx::query(
            "UPDATE authbus_policy_heads SET revoked = 1, updated_at_ms = ? WHERE policy_id = ?",
        )
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
        if quota.revision == 0 || quota.window_start_ms >= quota.window_end_ms {
            return Err(AuthBusControlError::Invalid("invalid quota revision/window"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT revision, unit_id, window_start_ms, window_end_ms,
                    endowment, reserved, consumed
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(quota.quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;

        let (reserved, consumed) = if let Some(row) = row {
            let revision = decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
            let unit_id: String = row.try_get("unit_id").map_err(classify_sqlx_error)?;
            let current_start =
                decode_u64(row.try_get("window_start_ms").map_err(classify_sqlx_error)?)?;
            let current_end =
                decode_u64(row.try_get("window_end_ms").map_err(classify_sqlx_error)?)?;
            let current_endowment =
                decode_u64(row.try_get("endowment").map_err(classify_sqlx_error)?)?;
            let reserved =
                decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
            let consumed =
                decode_u64(row.try_get("consumed").map_err(classify_sqlx_error)?)?;

            if quota.revision == revision {
                if unit_id == quota.unit_id.as_str()
                    && current_start == quota.window_start_ms
                    && current_end == quota.window_end_ms
                    && current_endowment == quota.endowment
                {
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(());
                }
                return Err(AuthBusControlError::IdempotencyConflict);
            }
            if quota.revision < revision {
                return Err(AuthBusControlError::StaleRevision);
            }
            if unit_id != quota.unit_id.as_str() {
                return Err(AuthBusControlError::Invalid(
                    "quota unit is immutable for one quota key",
                ));
            }
            if reserved != 0 {
                return Err(AuthBusControlError::Invalid(
                    "quota revision cannot change while reservations are held",
                ));
            }
            if quota.window_start_ms == current_start && quota.window_end_ms == current_end {
                if consumed != 0 {
                    return Err(AuthBusControlError::Invalid(
                        "quota revision cannot change after consumption within a window",
                    ));
                }
                (0, 0)
            } else {
                if quota.window_start_ms < current_end {
                    return Err(AuthBusControlError::Invalid(
                        "quota windows must not overlap",
                    ));
                }
                (0, 0)
            }
        } else {
            (0, 0)
        };

        let now = now_millis()?;
        sqlx::query(
            "INSERT INTO authbus_quota_registry
             (quota_key, revision, unit_id, window_start_ms, window_end_ms,
              endowment, reserved, consumed, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(quota_key) DO UPDATE SET revision=excluded.revision,
             unit_id=excluded.unit_id, window_start_ms=excluded.window_start_ms,
             window_end_ms=excluded.window_end_ms, endowment=excluded.endowment,
             reserved=excluded.reserved, consumed=excluded.consumed,
             updated_at_ms=excluded.updated_at_ms",
        )
        .bind(quota.quota_key.as_str())
        .bind(quota.revision.to_be_bytes().as_slice())
        .bind(quota.unit_id.as_str())
        .bind(quota.window_start_ms.to_be_bytes().as_slice())
        .bind(quota.window_end_ms.to_be_bytes().as_slice())
        .bind(quota.endowment.to_be_bytes().as_slice())
        .bind(reserved.to_be_bytes().as_slice())
        .bind(consumed.to_be_bytes().as_slice())
        .bind(now)
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
        effect_digest: Digest32,
    ) -> Result<(PolicyDecision, Reservation), AuthBusControlError> {
        if amount == 0 || expires_at_ms == 0 || scope_digest.is_zero() || effect_digest.is_zero() {
            return Err(AuthBusControlError::Invalid(
                "reservation amount/expiry/scope/effect must be nonzero",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now_i64 = now_millis()?;
        let now = clock(now_i64)?;

        let binding_digest = reservation_binding_digest(
            policy_id,
            policy_revision,
            principal_id,
            action_id,
            scope_digest,
            quota_key,
            quota_revision,
            reservation_id,
            operation_id,
            amount,
            expires_at_ms,
            effect_digest,
        );

        if let Some(existing) = load_reservation_by_operation(&mut tx, operation_id).await? {
            if existing.reservation_id == *reservation_id
                && existing.principal_id == *principal_id
                && existing.action_id == *action_id
                && existing.scope_digest == scope_digest
                && existing.quota_key == *quota_key
                && existing.quota_revision == quota_revision
                && existing.amount == amount
                && existing.expires_at_ms == expires_at_ms
                && existing.policy_id == *policy_id
                && existing.policy_revision == policy_revision
                && existing.effect_digest == effect_digest
                && existing.binding_digest == binding_digest
            {
                let decision = policy_decision(
                    policy_id,
                    policy_revision,
                    principal_id,
                    action_id,
                    scope_digest,
                );
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok((decision, existing));
            }
            return Err(AuthBusControlError::IdempotencyConflict);
        }

        if now >= expires_at_ms {
            return Err(AuthBusControlError::InvalidTransition);
        }
        let decision = authorize_in_tx(
            &mut tx,
            policy_id,
            policy_revision,
            principal_id,
            action_id,
            scope_digest,
        )
        .await?;

        let row = sqlx::query(
            "SELECT revision, window_start_ms, window_end_ms, endowment, reserved, consumed
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
        let window_start =
            decode_u64(row.try_get("window_start_ms").map_err(classify_sqlx_error)?)?;
        let window_end =
            decode_u64(row.try_get("window_end_ms").map_err(classify_sqlx_error)?)?;
        if now < window_start || now >= window_end || expires_at_ms > window_end {
            return Err(AuthBusControlError::Invalid(
                "reservation is outside the quota window",
            ));
        }
        let endowment = decode_u64(row.try_get("endowment").map_err(classify_sqlx_error)?)?;
        let reserved = decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
        let consumed = decode_u64(row.try_get("consumed").map_err(classify_sqlx_error)?)?;
        let used = reserved
            .checked_add(consumed)
            .ok_or(AuthBusControlError::QuotaExceeded)?;
        let next_reserved = reserved
            .checked_add(amount)
            .ok_or(AuthBusControlError::QuotaExceeded)?;
        if used.checked_add(amount).is_none_or(|next| next > endowment) {
            return Err(AuthBusControlError::QuotaExceeded);
        }

        sqlx::query(
            "INSERT INTO authbus_quota_reservations
             (reservation_id, operation_id, principal_id, action_id, scope_digest,
              quota_key, quota_revision, amount, expires_at_ms, policy_id,
              policy_revision, effect_digest, binding_digest, state, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        )
        .bind(reservation_id.as_str())
        .bind(operation_id.as_str())
        .bind(principal_id.as_str())
        .bind(action_id.as_str())
        .bind(scope_digest.as_array().as_slice())
        .bind(quota_key.as_str())
        .bind(quota_revision.to_be_bytes().as_slice())
        .bind(amount.to_be_bytes().as_slice())
        .bind(expires_at_ms.to_be_bytes().as_slice())
        .bind(policy_id.as_str())
        .bind(policy_revision.to_be_bytes().as_slice())
        .bind(effect_digest.as_array().as_slice())
        .bind(binding_digest.as_array().as_slice())
        .bind(now_i64)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "UPDATE authbus_quota_registry SET reserved = ?, updated_at_ms = ? WHERE quota_key = ?",
        )
        .bind(next_reserved.to_be_bytes().as_slice())
        .bind(now_i64)
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
                principal_id: principal_id.clone(),
                action_id: action_id.clone(),
                scope_digest,
                quota_key: quota_key.clone(),
                quota_revision,
                amount,
                expires_at_ms,
                policy_id: policy_id.clone(),
                policy_revision,
                effect_digest,
                binding_digest,
                state: ReservationState::Active,
                effect_started_at_ms: None,
            },
        ))
    }

    /// Atomically consume an active reservation for one exact final effect.
    /// The owner reads time only after taking the SQLite write lock. Once this
    /// transition commits, ordinary cancellation/expiry can never refund it.
    pub async fn begin_authbus_effect(
        &self,
        reservation_id: &StableId,
        expected_principal_id: &StableId,
        expected_action_id: &StableId,
        expected_scope_digest: Digest32,
        expected_effect_digest: Digest32,
    ) -> Result<Reservation, AuthBusControlError> {
        if expected_scope_digest.is_zero() || expected_effect_digest.is_zero() {
            return Err(AuthBusControlError::Invalid(
                "effect scope/digest is empty",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now_i64 = now_millis()?;
        let now = clock(now_i64)?;
        let mut reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.state != ReservationState::Active
            || reservation.principal_id != *expected_principal_id
            || reservation.action_id != *expected_action_id
            || reservation.scope_digest != expected_scope_digest
            || reservation.effect_digest != expected_effect_digest
        {
            return Err(AuthBusControlError::InvalidTransition);
        }
        if now >= reservation.expires_at_ms {
            release_active_in_tx(
                &mut tx,
                &reservation,
                ReservationState::Expired,
                now_i64,
            )
            .await?;
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Err(AuthBusControlError::InvalidTransition);
        }
        require_policy_head(
            &mut tx,
            &reservation.policy_id,
            reservation.policy_revision,
            Some(false),
        )
        .await?;
        let quota_revision: Vec<u8> = sqlx::query_scalar(
            "SELECT revision FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(reservation.quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::NotFound)?;
        if decode_u64(quota_revision)? != reservation.quota_revision {
            return Err(AuthBusControlError::StaleRevision);
        }

        sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state='effect_started', effect_started_at_ms=?, updated_at_ms=?
             WHERE reservation_id=?",
        )
        .bind(now_i64)
        .bind(now_i64)
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        reservation.state = ReservationState::EffectStarted;
        reservation.effect_started_at_ms = Some(now);
        Ok(reservation)
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
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
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
            let stored_cost =
                decode_u64(row.try_get("observed_cost").map_err(classify_sqlx_error)?)?;
            let stored_evidence =
                digest(row.try_get("terminal_evidence").map_err(classify_sqlx_error)?)?;
            let stored_digest =
                digest(row.try_get("settlement_digest").map_err(classify_sqlx_error)?)?;
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
        if !matches!(
            existing.state,
            ReservationState::EffectStarted | ReservationState::Quarantined
        ) || observed_cost > existing.amount
        {
            return Err(AuthBusControlError::InvalidTransition);
        }

        let quota = sqlx::query(
            "SELECT revision, reserved, consumed
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(existing.quota_key.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if decode_u64(quota.try_get("revision").map_err(classify_sqlx_error)?)?
            != existing.quota_revision
        {
            return Err(
                EvidenceError::Corrupt("AuthBus quota revision changed while held".into()).into(),
            );
        }
        let reserved = decode_u64(quota.try_get("reserved").map_err(classify_sqlx_error)?)?;
        let consumed = decode_u64(quota.try_get("consumed").map_err(classify_sqlx_error)?)?;
        let next_reserved = reserved
            .checked_sub(existing.amount)
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus quota reservation underflow".into()))?;
        let next_consumed = consumed
            .checked_add(observed_cost)
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus quota consumption overflow".into()))?;
        let settlement_digest =
            settlement_digest(reservation_id, observed_cost, terminal_evidence);
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

    /// Cancel only while the reservation is still active. EffectStarted and
    /// Quarantined reservations remain held until observed reconciliation.
    pub async fn cancel_authbus_reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<(), AuthBusControlError> {
        release_reservation(self, reservation_id, ReservationState::Cancelled, false).await
    }

    /// Expiry uses the evidence owner's clock after the write lock. It cannot
    /// expire/refund a reservation once final-use intent has committed.
    pub async fn expire_authbus_reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<(), AuthBusControlError> {
        release_reservation(self, reservation_id, ReservationState::Expired, true).await
    }

    /// Mark an effect-started reservation indeterminate. Quarantine keeps the
    /// full amount reserved and may later be settled from terminal evidence.
    pub async fn quarantine_authbus_reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Quarantined {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(());
        }
        if reservation.state != ReservationState::EffectStarted {
            return Err(AuthBusControlError::InvalidTransition);
        }
        sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state='quarantined', updated_at_ms=? WHERE reservation_id=?",
        )
        .bind(now_millis()?)
        .bind(reservation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    /// Bounded recovery projection for effects that crossed the durable
    /// final-use boundary but do not yet have terminal settlement.
    pub async fn pending_authbus_effect_reservations(
        &self,
        quota_key: &StableId,
        limit: u32,
    ) -> Result<Vec<Reservation>, AuthBusControlError> {
        if limit == 0 || limit > 128 {
            return Err(AuthBusControlError::Invalid("list limit must be 1..=128"));
        }
        let rows = sqlx::query(
            "SELECT * FROM authbus_quota_reservations
             WHERE quota_key=? AND state IN ('effect_started','quarantined')
             ORDER BY updated_at_ms, reservation_id LIMIT ?",
        )
        .bind(quota_key.as_str())
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        rows.into_iter().map(decode_reservation).collect()
    }

    pub async fn reconcile_authbus_quota(
        &self,
        quota_key: &StableId,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT revision, endowment FROM authbus_quota_registry WHERE quota_key=?",
        )
        .bind(quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::NotFound)?;
        let revision = decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
        let endowment = decode_u64(row.try_get("endowment").map_err(classify_sqlx_error)?)?;

        let foreign_held: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservations
             WHERE quota_key=? AND quota_revision != ?
             AND state IN ('active','effect_started','quarantined')",
        )
        .bind(quota_key.as_str())
        .bind(revision.to_be_bytes().as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if foreign_held != 0 {
            return Err(
                EvidenceError::Corrupt("held AuthBus reservation crossed quota revision".into())
                    .into(),
            );
        }

        let rows = sqlx::query(
            "SELECT amount, observed_cost, state FROM authbus_quota_reservations
             WHERE quota_key=? AND quota_revision=?",
        )
        .bind(quota_key.as_str())
        .bind(revision.to_be_bytes().as_slice())
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut reserved = 0_u64;
        let mut consumed = 0_u64;
        for row in rows {
            let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
            let amount = decode_u64(row.try_get("amount").map_err(classify_sqlx_error)?)?;
            match state.as_str() {
                "active" | "effect_started" | "quarantined" => {
                    reserved = reserved
                        .checked_add(amount)
                        .ok_or(AuthBusControlError::QuotaExceeded)?;
                }
                "settled" => {
                    let cost =
                        decode_u64(row.try_get("observed_cost").map_err(classify_sqlx_error)?)?;
                    consumed = consumed
                        .checked_add(cost)
                        .ok_or(AuthBusControlError::QuotaExceeded)?;
                }
                "cancelled" | "expired" => {}
                _ => {
                    return Err(
                        EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into(),
                    );
                }
            }
        }
        if reserved
            .checked_add(consumed)
            .is_none_or(|used| used > endowment)
        {
            return Err(
                EvidenceError::Corrupt("AuthBus quota conservation violated".into()).into(),
            );
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
    Ok(policy_decision(
        policy_id,
        revision,
        principal_id,
        action_id,
        scope_digest,
    ))
}

fn policy_decision(
    policy_id: &StableId,
    revision: u64,
    principal_id: &StableId,
    action_id: &StableId,
    scope_digest: Digest32,
) -> PolicyDecision {
    let mut bytes = b"hepta.authbus.policy-decision.v1\0".to_vec();
    push(&mut bytes, policy_id.as_str());
    bytes.extend_from_slice(&revision.to_be_bytes());
    push(&mut bytes, principal_id.as_str());
    push(&mut bytes, action_id.as_str());
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.push(1);
    PolicyDecision {
        policy_id: policy_id.clone(),
        revision,
        allowed: true,
        decision_digest: Digest32::of_bytes(&bytes),
    }
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
    let expected_revoked = revoked.map(|expected| if expected { 1_i64 } else { 0_i64 });
    if expected_revoked.is_some_and(|expected| current_revoked != expected) || current_revoked != 0
    {
        return Err(AuthBusControlError::Denied);
    }
    Ok(())
}

async fn release_reservation(
    store: &HeptaEvidenceStore,
    reservation_id: &StableId,
    state: ReservationState,
    require_expired: bool,
) -> Result<(), AuthBusControlError> {
    let mut tx = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(classify_sqlx_error)?;
    let reservation = load_reservation(&mut tx, reservation_id).await?;
    if reservation.state != ReservationState::Active {
        return Err(AuthBusControlError::InvalidTransition);
    }
    let now_i64 = now_millis()?;
    let now = clock(now_i64)?;
    if require_expired && now < reservation.expires_at_ms {
        return Err(AuthBusControlError::InvalidTransition);
    }
    release_active_in_tx(&mut tx, &reservation, state, now_i64).await?;
    tx.commit().await.map_err(classify_sqlx_error)?;
    Ok(())
}

async fn release_active_in_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &Reservation,
    state: ReservationState,
    now: i64,
) -> Result<(), AuthBusControlError> {
    if reservation.state != ReservationState::Active
        || !matches!(state, ReservationState::Cancelled | ReservationState::Expired)
    {
        return Err(AuthBusControlError::InvalidTransition);
    }
    let row = sqlx::query("SELECT revision, reserved FROM authbus_quota_registry WHERE quota_key=?")
        .bind(reservation.quota_key.as_str())
        .fetch_one(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
    if decode_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?
        != reservation.quota_revision
    {
        return Err(
            EvidenceError::Corrupt("AuthBus quota revision changed while active".into()).into(),
        );
    }
    let reserved = decode_u64(row.try_get("reserved").map_err(classify_sqlx_error)?)?;
    let next = reserved
        .checked_sub(reservation.amount)
        .ok_or_else(|| EvidenceError::Corrupt("AuthBus quota reservation underflow".into()))?;
    sqlx::query(
        "UPDATE authbus_quota_reservations SET state=?, updated_at_ms=? WHERE reservation_id=?",
    )
    .bind(state.as_str())
    .bind(now)
    .bind(reservation.reservation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    sqlx::query("UPDATE authbus_quota_registry SET reserved=?, updated_at_ms=? WHERE quota_key=?")
        .bind(next.to_be_bytes().as_slice())
        .bind(now)
        .bind(reservation.quota_key.as_str())
        .execute(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
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
        StableId::new(
            row.try_get::<String, _>(name)
                .map_err(classify_sqlx_error)?,
        )
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus control ID".into()).into())
    };
    let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
    let state = match state.as_str() {
        "active" => ReservationState::Active,
        "effect_started" => ReservationState::EffectStarted,
        "settled" => ReservationState::Settled,
        "cancelled" => ReservationState::Cancelled,
        "expired" => ReservationState::Expired,
        "quarantined" => ReservationState::Quarantined,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into()),
    };
    let effect_started_at_ms: Option<i64> = row
        .try_get("effect_started_at_ms")
        .map_err(classify_sqlx_error)?;
    let effect_started_at_ms = effect_started_at_ms
        .map(clock)
        .transpose()?;

    Ok(Reservation {
        reservation_id: id("reservation_id")?,
        operation_id: id("operation_id")?,
        principal_id: id("principal_id")?,
        action_id: id("action_id")?,
        scope_digest: digest(row.try_get("scope_digest").map_err(classify_sqlx_error)?)?,
        quota_key: id("quota_key")?,
        quota_revision: decode_u64(
            row.try_get("quota_revision")
                .map_err(classify_sqlx_error)?,
        )?,
        amount: decode_u64(row.try_get("amount").map_err(classify_sqlx_error)?)?,
        expires_at_ms: decode_u64(
            row.try_get("expires_at_ms")
                .map_err(classify_sqlx_error)?,
        )?,
        policy_id: id("policy_id")?,
        policy_revision: decode_u64(
            row.try_get("policy_revision")
                .map_err(classify_sqlx_error)?,
        )?,
        effect_digest: digest(
            row.try_get("effect_digest")
                .map_err(classify_sqlx_error)?,
        )?,
        binding_digest: digest(
            row.try_get("binding_digest")
                .map_err(classify_sqlx_error)?,
        )?,
        state,
        effect_started_at_ms,
    })
}

fn canonical_policy_digest(policy: &PolicyRevision) -> Result<Digest32, AuthBusControlError> {
    let mut rows = BTreeSet::new();
    for rule in &policy.rules {
        let key = (
            rule.principal_id.as_str().to_owned(),
            rule.action_id.as_str().to_owned(),
            *rule.scope_digest.as_array(),
            rule.allow,
        );
        if !rows.insert(key) {
            return Err(AuthBusControlError::Invalid("duplicate policy rule"));
        }
    }
    let mut bytes = b"hepta.authbus.policy-revision.v1\0".to_vec();
    push(&mut bytes, policy.policy_id.as_str());
    bytes.extend_from_slice(&policy.revision.to_be_bytes());
    for (principal, action, scope, allow) in rows {
        push(&mut bytes, &principal);
        push(&mut bytes, &action);
        bytes.extend_from_slice(&scope);
        bytes.push(u8::from(allow));
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[allow(clippy::too_many_arguments)]
fn reservation_binding_digest(
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
    effect_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.authbus.reservation-binding.v2\0".to_vec();
    push(&mut bytes, policy_id.as_str());
    bytes.extend_from_slice(&policy_revision.to_be_bytes());
    push(&mut bytes, principal_id.as_str());
    push(&mut bytes, action_id.as_str());
    bytes.extend_from_slice(scope_digest.as_array());
    push(&mut bytes, quota_key.as_str());
    bytes.extend_from_slice(&quota_revision.to_be_bytes());
    push(&mut bytes, reservation_id.as_str());
    push(&mut bytes, operation_id.as_str());
    bytes.extend_from_slice(&amount.to_be_bytes());
    bytes.extend_from_slice(&expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(effect_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest32(bytes: Vec<u8>) -> Result<Digest32, AuthBusControlError> {
    digest(bytes)
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

fn clock(now: i64) -> Result<u64, AuthBusControlError> {
    u64::try_from(now)
        .map_err(|_| EvidenceError::Unavailable("clock predates Unix epoch".into()).into())
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
