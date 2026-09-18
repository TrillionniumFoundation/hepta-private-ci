use std::collections::BTreeMap;

use codex_hepta_authbus::AUTHBUS_MAX_ACTIVE_RESERVATIONS_PER_POLICY;
use codex_hepta_authbus::AUTHBUS_MAX_EXPIRY_SWEEP_ROWS;
use codex_hepta_authbus::AUTHBUS_MAX_RESERVATION_TTL_MS;
use codex_hepta_authbus::AuthBusReplayCheckpoint;
use codex_hepta_authbus::AuthBusTrustHead;
use codex_hepta_authbus::AuthPolicyRule;
use codex_hepta_authbus::ControlWriteDisposition;
use codex_hepta_authbus::EffectAdmission;
use codex_hepta_authbus::EffectAdmissionRequest;
use codex_hepta_authbus::PolicyDecision;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::QuotaRegistryEntry;
use codex_hepta_authbus::QuotaSnapshot;
use codex_hepta_authbus::Reservation;
use codex_hepta_authbus::ReservationReconcileOutcome;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::Settlement;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusControlError {
    #[error(transparent)]
    Storage(#[from] EvidenceError),
    #[error("invalid AuthBus control request: {0}")]
    InvalidRequest(&'static str),
    #[error("AuthBus policy is not configured")]
    PolicyNotFound,
    #[error("AuthBus policy revision is stale")]
    StalePolicyRevision,
    #[error("AuthBus policy denied the operation")]
    PolicyDenied,
    #[error("AuthBus quota is not configured")]
    QuotaNotFound,
    #[error("AuthBus quota revision is stale")]
    StaleQuotaRevision,
    #[error("AuthBus quota is exhausted")]
    QuotaExceeded,
    #[error("AuthBus principal active-reservation limit is exhausted")]
    ActiveReservationLimitExceeded,
    #[error("AuthBus reservation was not found")]
    ReservationNotFound,
    #[error("AuthBus reservation identity conflicts with existing state")]
    ReservationConflict,
    #[error("invalid AuthBus reservation state transition")]
    InvalidTransition,
    #[error("observed cost exceeds the reserved amount")]
    ObservedCostExceedsReservation,
    #[error("AuthBus trust revision or epoch rolled back")]
    TrustRollback,
    #[error("AuthBus replay checkpoint does not match the durable registry")]
    RollbackDetected,
    #[error("AuthBus replay epoch cannot be retired yet")]
    EpochRetirementBlocked,
}

impl HeptaEvidenceStore {
    pub async fn put_auth_policy(
        &self,
        rule: &AuthPolicyRule,
    ) -> Result<ControlWriteDisposition, AuthBusControlError> {
        validate_policy(rule)?;
        let digest = policy_digest(rule);
        let now = now_millis()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = sqlx::query(
            "SELECT revision, effect, max_active_reservations, record_digest FROM authbus_policy_heads
             WHERE principal_id = ? AND action_id = ? AND scope_digest = ?",
        )
        .bind(rule.principal_id.as_str())
        .bind(rule.action_id.as_str())
        .bind(rule.scope_digest.as_array().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = current {
            let revision = blob_u64(&row, "revision")?;
            let record_digest = blob_digest(&row, "record_digest")?;
            if revision == rule.revision && record_digest == digest {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(ControlWriteDisposition::AlreadyPresent);
            }
            if rule.revision <= revision {
                return Err(AuthBusControlError::StalePolicyRevision);
            }
        }
        let effect = effect_str(rule.effect);
        sqlx::query(
            "INSERT INTO authbus_policy_history
             (principal_id, action_id, scope_digest, revision, effect, max_active_reservations,
              record_digest, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(rule.principal_id.as_str())
        .bind(rule.action_id.as_str())
        .bind(rule.scope_digest.as_array().as_slice())
        .bind(rule.revision.to_be_bytes().as_slice())
        .bind(effect)
        .bind(i64::from(rule.max_active_reservations))
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "INSERT INTO authbus_policy_heads
             (principal_id, action_id, scope_digest, revision, effect, max_active_reservations,
              record_digest, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(principal_id, action_id, scope_digest) DO UPDATE SET
               revision = excluded.revision,
               effect = excluded.effect,
               max_active_reservations = excluded.max_active_reservations,
               record_digest = excluded.record_digest,
               updated_at_ms = excluded.updated_at_ms",
        )
        .bind(rule.principal_id.as_str())
        .bind(rule.action_id.as_str())
        .bind(rule.scope_digest.as_array().as_slice())
        .bind(rule.revision.to_be_bytes().as_slice())
        .bind(effect)
        .bind(i64::from(rule.max_active_reservations))
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(ControlWriteDisposition::Inserted)
    }

    pub async fn authorize(
        &self,
        principal_id: &StableId,
        action_id: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
    ) -> Result<PolicyDecision, AuthBusControlError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let evaluation = authorize_tx(
            &mut tx,
            principal_id,
            action_id,
            scope_digest,
            policy_revision,
        )
        .await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(evaluation.decision)
    }

    pub async fn put_quota_registry(
        &self,
        entry: &QuotaRegistryEntry,
    ) -> Result<ControlWriteDisposition, AuthBusControlError> {
        validate_quota(entry)?;
        let digest = quota_digest(entry);
        let now = now_millis()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = sqlx::query(
            "SELECT revision, capacity, reserved, consumed, period_start_ms, period_end_ms,
                    record_digest
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(entry.quota_key.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;

        let (reserved, consumed) = if let Some(row) = current {
            let revision = blob_u64(&row, "revision")?;
            let record_digest = blob_digest(&row, "record_digest")?;
            if revision == entry.revision && record_digest == digest {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(ControlWriteDisposition::AlreadyPresent);
            }
            if entry.revision <= revision {
                return Err(AuthBusControlError::StaleQuotaRevision);
            }
            let reserved = blob_u64(&row, "reserved")?;
            let consumed = blob_u64(&row, "consumed")?;
            let start = i64_to_u64(
                row.try_get("period_start_ms")
                    .map_err(classify_sqlx_error)?,
            )?;
            let end = i64_to_u64(row.try_get("period_end_ms").map_err(classify_sqlx_error)?)?;
            if start != entry.period_start_ms || end != entry.period_end_ms {
                if reserved != 0 || entry.period_start_ms < end {
                    return Err(AuthBusControlError::InvalidRequest(
                        "quota period cannot roll while reservations are held or periods overlap",
                    ));
                }
                (0, 0)
            } else {
                (reserved, consumed)
            }
        } else {
            (0, 0)
        };
        if reserved
            .checked_add(consumed)
            .is_none_or(|used| used > entry.capacity)
        {
            return Err(AuthBusControlError::QuotaExceeded);
        }

        sqlx::query(
            "INSERT INTO authbus_quota_history
             (quota_key, revision, capacity, period_start_ms, period_end_ms, record_digest, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(entry.quota_key.as_str())
        .bind(entry.revision.to_be_bytes().as_slice())
        .bind(entry.capacity.to_be_bytes().as_slice())
        .bind(u64_to_i64(entry.period_start_ms)?)
        .bind(u64_to_i64(entry.period_end_ms)?)
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "INSERT INTO authbus_quota_registry
             (quota_key, revision, capacity, reserved, consumed, period_start_ms, period_end_ms,
              record_digest, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(quota_key) DO UPDATE SET
               revision = excluded.revision,
               capacity = excluded.capacity,
               reserved = excluded.reserved,
               consumed = excluded.consumed,
               period_start_ms = excluded.period_start_ms,
               period_end_ms = excluded.period_end_ms,
               record_digest = excluded.record_digest,
               updated_at_ms = excluded.updated_at_ms",
        )
        .bind(entry.quota_key.as_str())
        .bind(entry.revision.to_be_bytes().as_slice())
        .bind(entry.capacity.to_be_bytes().as_slice())
        .bind(reserved.to_be_bytes().as_slice())
        .bind(consumed.to_be_bytes().as_slice())
        .bind(u64_to_i64(entry.period_start_ms)?)
        .bind(u64_to_i64(entry.period_end_ms)?)
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(ControlWriteDisposition::Inserted)
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusControlError> {
        let row = sqlx::query(
            "SELECT quota_key, revision, capacity, reserved, consumed, period_start_ms, period_end_ms
             FROM authbus_quota_registry WHERE quota_key = ?",
        )
        .bind(quota_key.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::QuotaNotFound)?;
        decode_quota(&row)
    }

    pub async fn authorize_and_reserve(
        &self,
        request: &EffectAdmissionRequest,
    ) -> Result<EffectAdmission, AuthBusControlError> {
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        validate_admission(request, now)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        sweep_expired_reserved_tx(&mut tx, now).await?;
        let evaluation = authorize_tx(
            &mut tx,
            &request.principal_id,
            &request.action_id,
            request.scope_digest,
            request.policy_revision,
        )
        .await?;
        if evaluation.decision != PolicyDecision::Allowed {
            return Err(AuthBusControlError::PolicyDenied);
        }
        let quota = load_quota_tx(&mut tx, &request.quota_key).await?;
        if quota.revision != request.quota_revision {
            return Err(AuthBusControlError::StaleQuotaRevision);
        }
        if now < quota.period_start_ms
            || now >= quota.period_end_ms
            || request.expires_at_ms > quota.period_end_ms
        {
            return Err(AuthBusControlError::InvalidRequest(
                "reservation is outside the active quota period",
            ));
        }

        // Preserve idempotency before enforcing admission capacity. A retry of an
        // already-held operation must return the same reservation even when that
        // reservation itself fills the principal's active-reservation budget.
        if let Some(existing) =
            load_reservation_by_operation_tx(&mut tx, &request.operation_id).await?
        {
            if reservation_matches_request(&existing, request) {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(EffectAdmission {
                    decision: evaluation.decision,
                    reservation: existing,
                });
            }
            return Err(AuthBusControlError::ReservationConflict);
        }

        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservations
             WHERE principal_id = ? AND state IN ('reserved', 'in_flight', 'quarantined')",
        )
        .bind(request.principal_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active >= i64::from(evaluation.max_active_reservations) {
            return Err(AuthBusControlError::ActiveReservationLimitExceeded);
        }

        if request.amount > quota.available() {
            return Err(AuthBusControlError::QuotaExceeded);
        }
        let reservation_id = reservation_digest(request);
        let now_i64 = u64_to_i64(now)?;
        sqlx::query(
            "INSERT INTO authbus_quota_reservations
             (reservation_id, operation_id, principal_id, action_id, scope_digest,
              policy_revision, quota_key, quota_revision, amount, state, observed_cost,
              expires_at_ms, terminal_evidence, created_at_ms, updated_at_ms, terminal_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', NULL, ?, NULL, ?, ?, NULL)",
        )
        .bind(reservation_id.as_array().as_slice())
        .bind(request.operation_id.as_str())
        .bind(request.principal_id.as_str())
        .bind(request.action_id.as_str())
        .bind(request.scope_digest.as_array().as_slice())
        .bind(request.policy_revision.to_be_bytes().as_slice())
        .bind(request.quota_key.as_str())
        .bind(request.quota_revision.to_be_bytes().as_slice())
        .bind(request.amount.to_be_bytes().as_slice())
        .bind(u64_to_i64(request.expires_at_ms)?)
        .bind(now_i64)
        .bind(now_i64)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        set_quota_counters_tx(
            &mut tx,
            &request.quota_key,
            quota
                .reserved
                .checked_add(request.amount)
                .ok_or(AuthBusControlError::QuotaExceeded)?,
            quota.consumed,
            now_i64,
        )
        .await?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(EffectAdmission {
            decision: evaluation.decision,
            reservation,
        })
    }

    pub async fn begin_reserved_effect(
        &self,
        reservation_id: Digest32,
        operation_id: &StableId,
    ) -> Result<Reservation, AuthBusControlError> {
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        sweep_expired_reserved_tx(&mut tx, now).await?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        if &reservation.operation_id != operation_id {
            return Err(AuthBusControlError::ReservationConflict);
        }
        if reservation.state != ReservationState::Reserved {
            return Err(AuthBusControlError::InvalidTransition);
        }
        let authorization = authorize_tx(
            &mut tx,
            &reservation.principal_id,
            &reservation.action_id,
            reservation.scope_digest,
            reservation.policy_revision,
        )
        .await;
        match authorization {
            Ok(PolicyEvaluation {
                decision: PolicyDecision::Allowed,
                ..
            }) => {}
            Ok(PolicyEvaluation {
                decision: PolicyDecision::Denied,
                ..
            }) => {
                cancel_reserved_tx(&mut tx, &reservation, None, now).await?;
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Err(AuthBusControlError::PolicyDenied);
            }
            Err(error @ AuthBusControlError::StalePolicyRevision)
            | Err(error @ AuthBusControlError::PolicyNotFound) => {
                cancel_reserved_tx(&mut tx, &reservation, None, now).await?;
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Err(error);
            }
            Err(error) => return Err(error),
        }
        sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state = 'in_flight', updated_at_ms = ?
             WHERE reservation_id = ? AND state = 'reserved'",
        )
        .bind(u64_to_i64(now)?)
        .bind(reservation_id.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let result = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn settle_reservation(
        &self,
        reservation_id: Digest32,
        observed_cost: u64,
        terminal_evidence: Digest32,
    ) -> Result<Settlement, AuthBusControlError> {
        if terminal_evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "terminal evidence digest is empty",
            ));
        }
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Settled {
            if reservation.observed_cost == Some(observed_cost)
                && reservation.terminal_evidence == Some(terminal_evidence)
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(Settlement {
                    reservation_id,
                    observed_cost,
                    terminal_evidence,
                });
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        settle_tx(&mut tx, &reservation, observed_cost, terminal_evidence, now).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(Settlement {
            reservation_id,
            observed_cost,
            terminal_evidence,
        })
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: Digest32,
        terminal_evidence: Digest32,
    ) -> Result<Reservation, AuthBusControlError> {
        if terminal_evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "cancellation evidence digest is empty",
            ));
        }
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Cancelled {
            if reservation.terminal_evidence == Some(terminal_evidence) {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        if reservation.state != ReservationState::Reserved {
            return Err(AuthBusControlError::InvalidTransition);
        }
        cancel_reserved_tx(&mut tx, &reservation, Some(terminal_evidence), now).await?;
        let result = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn quarantine_reservation(
        &self,
        reservation_id: Digest32,
        uncertainty_evidence: Digest32,
    ) -> Result<Reservation, AuthBusControlError> {
        if uncertainty_evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "uncertainty evidence digest is empty",
            ));
        }
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        if reservation.state == ReservationState::Quarantined {
            if reservation.terminal_evidence == Some(uncertainty_evidence) {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        if reservation.state != ReservationState::InFlight {
            return Err(AuthBusControlError::InvalidTransition);
        }
        sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state = 'quarantined', terminal_evidence = ?, updated_at_ms = ?
             WHERE reservation_id = ? AND state = 'in_flight'",
        )
        .bind(uncertainty_evidence.as_array().as_slice())
        .bind(u64_to_i64(now)?)
        .bind(reservation_id.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let result = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn reconcile_reservation(
        &self,
        reservation_id: Digest32,
        outcome: ReservationReconcileOutcome,
    ) -> Result<Reservation, AuthBusControlError> {
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        if reservation.state != ReservationState::Quarantined {
            return Err(AuthBusControlError::InvalidTransition);
        }
        match outcome {
            ReservationReconcileOutcome::Settled {
                observed_cost,
                terminal_evidence,
            } => {
                if terminal_evidence.is_zero() {
                    return Err(AuthBusControlError::InvalidRequest(
                        "terminal evidence digest is empty",
                    ));
                }
                settle_tx(&mut tx, &reservation, observed_cost, terminal_evidence, now).await?;
            }
            ReservationReconcileOutcome::NotApplied { terminal_evidence } => {
                if terminal_evidence.is_zero() {
                    return Err(AuthBusControlError::InvalidRequest(
                        "terminal evidence digest is empty",
                    ));
                }
                release_held_tx(&mut tx, &reservation, now).await?;
                sqlx::query(
                    "UPDATE authbus_quota_reservations
                     SET state = 'cancelled', terminal_evidence = ?, updated_at_ms = ?,
                         terminal_at_ms = ?
                     WHERE reservation_id = ? AND state = 'quarantined'",
                )
                .bind(terminal_evidence.as_array().as_slice())
                .bind(u64_to_i64(now)?)
                .bind(u64_to_i64(now)?)
                .bind(reservation_id.as_array().as_slice())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            }
        }
        let result = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn expire_reservations(&self) -> Result<u64, AuthBusControlError> {
        let now = u64::try_from(now_millis()?)
            .map_err(|_| AuthBusControlError::InvalidRequest("clock predates Unix epoch"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let count = sweep_expired_reserved_tx(&mut tx, now).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(count)
    }

    pub async fn reservation(
        &self,
        reservation_id: Digest32,
    ) -> Result<Reservation, AuthBusControlError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let reservation = load_reservation_tx(&mut tx, reservation_id).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(reservation)
    }

    pub async fn observe_authbus_trust_head(
        &self,
        head: &AuthBusTrustHead,
    ) -> Result<ControlWriteDisposition, AuthBusControlError> {
        if head.revision == 0
            || head.key_epoch == 0
            || head.verifying_key_digest.is_zero()
            || head.registration_digest.is_zero()
        {
            return Err(AuthBusControlError::InvalidRequest(
                "trust revision, epoch and key digest must be nonzero",
            ));
        }
        let now = now_millis()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = sqlx::query(
            "SELECT revision, key_epoch, verifying_key_digest, registration_digest, revoked
             FROM authbus_trust_heads WHERE issuer_id = ?",
        )
        .bind(head.issuer_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = current {
            let revision = blob_u64(&row, "revision")?;
            let epoch = blob_u64(&row, "key_epoch")?;
            let key = blob_digest(&row, "verifying_key_digest")?;
            let registration = blob_digest(&row, "registration_digest")?;
            let revoked = row
                .try_get::<i64, _>("revoked")
                .map_err(classify_sqlx_error)?
                != 0;
            if revision == head.revision
                && epoch == head.key_epoch
                && key == head.verifying_key_digest
                && registration == head.registration_digest
                && revoked == head.revoked
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(ControlWriteDisposition::AlreadyPresent);
            }
            if head.revision <= revision
                || head.key_epoch < epoch
                || (head.revision == revision && registration != head.registration_digest)
                || (head.key_epoch == epoch && key != head.verifying_key_digest)
                || (head.key_epoch == epoch && revoked && !head.revoked)
            {
                return Err(AuthBusControlError::TrustRollback);
            }
        }
        sqlx::query(
            "INSERT INTO authbus_trust_heads
             (issuer_id, revision, key_epoch, verifying_key_digest, registration_digest, revoked, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(issuer_id) DO UPDATE SET
               revision = excluded.revision,
               key_epoch = excluded.key_epoch,
               verifying_key_digest = excluded.verifying_key_digest,
               registration_digest = excluded.registration_digest,
               revoked = excluded.revoked,
               updated_at_ms = excluded.updated_at_ms",
        )
        .bind(head.issuer_id.as_str())
        .bind(head.revision.to_be_bytes().as_slice())
        .bind(head.key_epoch.to_be_bytes().as_slice())
        .bind(head.verifying_key_digest.as_array().as_slice())
        .bind(head.registration_digest.as_array().as_slice())
        .bind(if head.revoked { 1_i64 } else { 0_i64 })
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(ControlWriteDisposition::Inserted)
    }

    pub async fn advance_authbus_replay_checkpoint(
        &self,
        expected_generation: u64,
    ) -> Result<AuthBusReplayCheckpoint, AuthBusControlError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_checkpoint_tx(&mut tx).await?;
        let current_generation = current.as_ref().map_or(0, |value| value.generation);
        if current_generation != expected_generation {
            return Err(AuthBusControlError::RollbackDetected);
        }
        let generation =
            expected_generation
                .checked_add(1)
                .ok_or(AuthBusControlError::InvalidRequest(
                    "checkpoint generation overflow",
                ))?;
        let replay_digest = replay_digest_tx(&mut tx).await?;
        write_checkpoint_tx(
            &mut tx,
            &AuthBusReplayCheckpoint {
                generation,
                replay_digest,
            },
        )
        .await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(AuthBusReplayCheckpoint {
            generation,
            replay_digest,
        })
    }

    pub async fn verify_authbus_replay_checkpoint(
        &self,
        expected: &AuthBusReplayCheckpoint,
    ) -> Result<(), AuthBusControlError> {
        if expected.generation == 0 || expected.replay_digest.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "external replay checkpoint is empty",
            ));
        }
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let stored = load_checkpoint_tx(&mut tx)
            .await?
            .ok_or(AuthBusControlError::RollbackDetected)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        if stored != *expected {
            return Err(AuthBusControlError::RollbackDetected);
        }
        Ok(())
    }

    pub async fn retire_authbus_replay_epoch(
        &self,
        issuer_id: &StableId,
        key_epoch: u64,
        expected_checkpoint: &AuthBusReplayCheckpoint,
    ) -> Result<AuthBusReplayCheckpoint, AuthBusControlError> {
        if key_epoch == 0 {
            return Err(AuthBusControlError::InvalidRequest(
                "retired key epoch must be nonzero",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let checkpoint = load_checkpoint_tx(&mut tx)
            .await?
            .ok_or(AuthBusControlError::RollbackDetected)?;
        let current_digest = replay_digest_tx(&mut tx).await?;
        if checkpoint != *expected_checkpoint || current_digest != expected_checkpoint.replay_digest
        {
            return Err(AuthBusControlError::RollbackDetected);
        }
        let trust =
            sqlx::query("SELECT key_epoch, revoked FROM authbus_trust_heads WHERE issuer_id = ?")
                .bind(issuer_id.as_str())
                .fetch_optional(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?
                .ok_or(AuthBusControlError::EpochRetirementBlocked)?;
        let current_epoch = blob_u64(&trust, "key_epoch")?;
        let revoked = trust
            .try_get::<i64, _>("revoked")
            .map_err(classify_sqlx_error)?
            != 0;
        if current_epoch < key_epoch || (current_epoch == key_epoch && !revoked) {
            return Err(AuthBusControlError::EpochRetirementBlocked);
        }
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_outbox
             WHERE issuer_id = ? AND key_epoch = ? AND state IN ('queued', 'leased')",
        )
        .bind(issuer_id.as_str())
        .bind(key_epoch.to_be_bytes().as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active != 0 {
            return Err(AuthBusControlError::EpochRetirementBlocked);
        }
        let next_generation = expected_checkpoint.generation.checked_add(1).ok_or(
            AuthBusControlError::InvalidRequest("checkpoint generation overflow"),
        )?;
        sqlx::query(
            "INSERT INTO authbus_retired_epochs
             (issuer_id, key_epoch, checkpoint_generation, retired_at_ms)
             VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
        )
        .bind(issuer_id.as_str())
        .bind(key_epoch.to_be_bytes().as_slice())
        .bind(next_generation.to_be_bytes().as_slice())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query("DELETE FROM authbus_replay_sequences WHERE issuer_id = ? AND key_epoch = ?")
            .bind(issuer_id.as_str())
            .bind(key_epoch.to_be_bytes().as_slice())
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        let replay_digest = replay_digest_tx(&mut tx).await?;
        let next = AuthBusReplayCheckpoint {
            generation: next_generation,
            replay_digest,
        };
        write_checkpoint_tx(&mut tx, &next).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(next)
    }
}

pub(crate) async fn authbus_epoch_retired(
    tx: &mut Transaction<'_, Sqlite>,
    issuer_id: &StableId,
    key_epoch: u64,
) -> Result<bool, EvidenceError> {
    sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM authbus_retired_epochs WHERE issuer_id = ? AND key_epoch = ?
         )",
    )
    .bind(issuer_id.as_str())
    .bind(key_epoch.to_be_bytes().as_slice())
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)
}

pub(crate) async fn verify_authbus_control_invariants(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let quota_rows = sqlx::query(
        "SELECT quota_key, capacity, reserved, consumed, period_start_ms, period_end_ms
         FROM authbus_quota_registry",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let mut expected_reserved = BTreeMap::<String, u128>::new();
    let held = sqlx::query(
        "SELECT quota_key, amount FROM authbus_quota_reservations
         WHERE state IN ('reserved', 'in_flight', 'quarantined')",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in held {
        let key: String = row.try_get("quota_key").map_err(classify_sqlx_error)?;
        let amount = u128::from(blob_u64_evidence(&row, "amount")?);
        *expected_reserved.entry(key).or_default() += amount;
    }
    for row in quota_rows {
        let key: String = row.try_get("quota_key").map_err(classify_sqlx_error)?;
        let capacity = u128::from(blob_u64_evidence(&row, "capacity")?);
        let reserved = u128::from(blob_u64_evidence(&row, "reserved")?);
        let consumed = u128::from(blob_u64_evidence(&row, "consumed")?);
        let start: i64 = row
            .try_get("period_start_ms")
            .map_err(classify_sqlx_error)?;
        let end: i64 = row.try_get("period_end_ms").map_err(classify_sqlx_error)?;
        if start < 0
            || end <= start
            || reserved + consumed > capacity
            || expected_reserved.remove(&key).unwrap_or_default() != reserved
        {
            return Err(EvidenceError::Corrupt(format!(
                "AuthBus quota conservation failed for {key}"
            )));
        }
    }
    if !expected_reserved.is_empty() {
        return Err(EvidenceError::Corrupt(
            "AuthBus reservations reference a missing quota registry row".into(),
        ));
    }
    let invalid_settled: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM authbus_quota_reservations
         WHERE state = 'settled' AND (observed_cost IS NULL OR terminal_evidence IS NULL)",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if invalid_settled != 0 {
        return Err(EvidenceError::Corrupt(
            "AuthBus settled reservations are missing terminal evidence".into(),
        ));
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct PolicyEvaluation {
    decision: PolicyDecision,
    max_active_reservations: u32,
}

async fn authorize_tx(
    tx: &mut Transaction<'_, Sqlite>,
    principal_id: &StableId,
    action_id: &StableId,
    scope_digest: Digest32,
    policy_revision: u64,
) -> Result<PolicyEvaluation, AuthBusControlError> {
    if policy_revision == 0 || scope_digest.is_zero() {
        return Err(AuthBusControlError::InvalidRequest(
            "policy revision, scope and active reservation limit are invalid",
        ));
    }
    let row = sqlx::query(
        "SELECT revision, effect, max_active_reservations FROM authbus_policy_heads
         WHERE principal_id = ? AND action_id = ? AND scope_digest = ?",
    )
    .bind(principal_id.as_str())
    .bind(action_id.as_str())
    .bind(scope_digest.as_array().as_slice())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or(AuthBusControlError::PolicyNotFound)?;
    if blob_u64(&row, "revision")? != policy_revision {
        return Err(AuthBusControlError::StalePolicyRevision);
    }
    let max_active = row
        .try_get::<i64, _>("max_active_reservations")
        .map_err(classify_sqlx_error)?;
    let max_active_reservations = u32::try_from(max_active)
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus active reservation limit".into()))?;
    if max_active_reservations == 0
        || max_active_reservations > AUTHBUS_MAX_ACTIVE_RESERVATIONS_PER_POLICY
    {
        return Err(EvidenceError::Corrupt(
            "AuthBus active reservation limit exceeds owner bound".into(),
        )
        .into());
    }
    let decision = match row
        .try_get::<String, _>("effect")
        .map_err(classify_sqlx_error)?
        .as_str()
    {
        "allow" => PolicyDecision::Allowed,
        "deny" => PolicyDecision::Denied,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus policy effect".into()).into()),
    };
    Ok(PolicyEvaluation {
        decision,
        max_active_reservations,
    })
}
async fn load_quota_tx(
    tx: &mut Transaction<'_, Sqlite>,
    quota_key: &StableId,
) -> Result<QuotaSnapshot, AuthBusControlError> {
    let row = sqlx::query(
        "SELECT quota_key, revision, capacity, reserved, consumed, period_start_ms, period_end_ms
         FROM authbus_quota_registry WHERE quota_key = ?",
    )
    .bind(quota_key.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or(AuthBusControlError::QuotaNotFound)?;
    decode_quota(&row)
}

fn decode_quota(row: &SqliteRow) -> Result<QuotaSnapshot, AuthBusControlError> {
    Ok(QuotaSnapshot {
        quota_key: StableId::new(
            row.try_get::<String, _>("quota_key")
                .map_err(classify_sqlx_error)?,
        )
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus quota key".into()))?,
        revision: blob_u64(row, "revision")?,
        capacity: blob_u64(row, "capacity")?,
        reserved: blob_u64(row, "reserved")?,
        consumed: blob_u64(row, "consumed")?,
        period_start_ms: i64_to_u64(
            row.try_get("period_start_ms")
                .map_err(classify_sqlx_error)?,
        )?,
        period_end_ms: i64_to_u64(row.try_get("period_end_ms").map_err(classify_sqlx_error)?)?,
    })
}

async fn load_reservation_by_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<Reservation>, AuthBusControlError> {
    sqlx::query("SELECT * FROM authbus_quota_reservations WHERE operation_id = ?")
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .map(|row| decode_reservation(&row))
        .transpose()
}

async fn load_reservation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation_id: Digest32,
) -> Result<Reservation, AuthBusControlError> {
    let row = sqlx::query("SELECT * FROM authbus_quota_reservations WHERE reservation_id = ?")
        .bind(reservation_id.as_array().as_slice())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::ReservationNotFound)?;
    decode_reservation(&row)
}

fn decode_reservation(row: &SqliteRow) -> Result<Reservation, AuthBusControlError> {
    let stable = |column| -> Result<StableId, AuthBusControlError> {
        StableId::new(
            row.try_get::<String, _>(column)
                .map_err(classify_sqlx_error)?,
        )
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {column}")).into())
    };
    let state = match row
        .try_get::<String, _>("state")
        .map_err(classify_sqlx_error)?
        .as_str()
    {
        "reserved" => ReservationState::Reserved,
        "in_flight" => ReservationState::InFlight,
        "settled" => ReservationState::Settled,
        "cancelled" => ReservationState::Cancelled,
        "expired" => ReservationState::Expired,
        "quarantined" => ReservationState::Quarantined,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into()).into()),
    };
    let observed_cost = row
        .try_get::<Option<Vec<u8>>, _>("observed_cost")
        .map_err(classify_sqlx_error)?
        .map(|value| vec_u64(value, "observed_cost"))
        .transpose()?;
    let terminal_evidence = row
        .try_get::<Option<Vec<u8>>, _>("terminal_evidence")
        .map_err(classify_sqlx_error)?
        .map(|value| vec_digest(value, "terminal_evidence"))
        .transpose()?;
    Ok(Reservation {
        reservation_id: blob_digest(row, "reservation_id")?,
        operation_id: stable("operation_id")?,
        principal_id: stable("principal_id")?,
        action_id: stable("action_id")?,
        scope_digest: blob_digest(row, "scope_digest")?,
        policy_revision: blob_u64(row, "policy_revision")?,
        quota_key: stable("quota_key")?,
        quota_revision: blob_u64(row, "quota_revision")?,
        amount: blob_u64(row, "amount")?,
        state,
        observed_cost,
        expires_at_ms: i64_to_u64(row.try_get("expires_at_ms").map_err(classify_sqlx_error)?)?,
        terminal_evidence,
    })
}

async fn settle_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &Reservation,
    observed_cost: u64,
    terminal_evidence: Digest32,
    now: u64,
) -> Result<(), AuthBusControlError> {
    if !matches!(
        reservation.state,
        ReservationState::InFlight | ReservationState::Quarantined
    ) {
        return Err(AuthBusControlError::InvalidTransition);
    }
    if observed_cost > reservation.amount {
        return Err(AuthBusControlError::ObservedCostExceedsReservation);
    }
    let quota = load_quota_tx(tx, &reservation.quota_key).await?;
    if quota.reserved < reservation.amount {
        return Err(
            EvidenceError::Corrupt("AuthBus quota reserved counter underflow".into()).into(),
        );
    }
    let reserved = quota.reserved - reservation.amount;
    let consumed = quota
        .consumed
        .checked_add(observed_cost)
        .ok_or(AuthBusControlError::QuotaExceeded)?;
    if reserved
        .checked_add(consumed)
        .is_none_or(|used| used > quota.capacity)
    {
        return Err(EvidenceError::Corrupt(
            "AuthBus settlement violates quota conservation".into(),
        )
        .into());
    }
    set_quota_counters_tx(
        tx,
        &reservation.quota_key,
        reserved,
        consumed,
        u64_to_i64(now)?,
    )
    .await?;
    sqlx::query(
        "UPDATE authbus_quota_reservations
         SET state = 'settled', observed_cost = ?, terminal_evidence = ?,
             updated_at_ms = ?, terminal_at_ms = ?
         WHERE reservation_id = ? AND state IN ('in_flight', 'quarantined')",
    )
    .bind(observed_cost.to_be_bytes().as_slice())
    .bind(terminal_evidence.as_array().as_slice())
    .bind(u64_to_i64(now)?)
    .bind(u64_to_i64(now)?)
    .bind(reservation.reservation_id.as_array().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn cancel_reserved_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &Reservation,
    terminal_evidence: Option<Digest32>,
    now: u64,
) -> Result<(), AuthBusControlError> {
    if reservation.state != ReservationState::Reserved {
        return Err(AuthBusControlError::InvalidTransition);
    }
    release_held_tx(tx, reservation, now).await?;
    sqlx::query(
        "UPDATE authbus_quota_reservations
         SET state = 'cancelled', terminal_evidence = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE reservation_id = ? AND state = 'reserved'",
    )
    .bind(terminal_evidence.map(|digest| digest.as_array().to_vec()))
    .bind(u64_to_i64(now)?)
    .bind(u64_to_i64(now)?)
    .bind(reservation.reservation_id.as_array().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn release_held_tx(
    tx: &mut Transaction<'_, Sqlite>,
    reservation: &Reservation,
    now: u64,
) -> Result<(), AuthBusControlError> {
    if !reservation.state.holds_quota() {
        return Err(AuthBusControlError::InvalidTransition);
    }
    let quota = load_quota_tx(tx, &reservation.quota_key).await?;
    let reserved = quota
        .reserved
        .checked_sub(reservation.amount)
        .ok_or_else(|| {
            AuthBusControlError::Storage(EvidenceError::Corrupt(
                "AuthBus quota reserved counter underflow".into(),
            ))
        })?;
    set_quota_counters_tx(
        tx,
        &reservation.quota_key,
        reserved,
        quota.consumed,
        u64_to_i64(now)?,
    )
    .await
}

async fn set_quota_counters_tx(
    tx: &mut Transaction<'_, Sqlite>,
    quota_key: &StableId,
    reserved: u64,
    consumed: u64,
    now: i64,
) -> Result<(), AuthBusControlError> {
    let affected = sqlx::query(
        "UPDATE authbus_quota_registry
         SET reserved = ?, consumed = ?, updated_at_ms = ?
         WHERE quota_key = ?",
    )
    .bind(reserved.to_be_bytes().as_slice())
    .bind(consumed.to_be_bytes().as_slice())
    .bind(now)
    .bind(quota_key.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .rows_affected();
    if affected != 1 {
        return Err(AuthBusControlError::QuotaNotFound);
    }
    Ok(())
}

async fn sweep_expired_reserved_tx(
    tx: &mut Transaction<'_, Sqlite>,
    now: u64,
) -> Result<u64, AuthBusControlError> {
    let rows = sqlx::query(
        "SELECT * FROM authbus_quota_reservations
         WHERE state = 'reserved' AND expires_at_ms <= ?
         ORDER BY expires_at_ms, reservation_id LIMIT ?",
    )
    .bind(u64_to_i64(now)?)
    .bind(i64::from(AUTHBUS_MAX_EXPIRY_SWEEP_ROWS))
    .fetch_all(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let mut count = 0_u64;
    for row in rows {
        let reservation = decode_reservation(&row)?;
        release_held_tx(tx, &reservation, now).await?;
        sqlx::query(
            "UPDATE authbus_quota_reservations
             SET state = 'expired', updated_at_ms = ?, terminal_at_ms = ?
             WHERE reservation_id = ? AND state = 'reserved'",
        )
        .bind(u64_to_i64(now)?)
        .bind(u64_to_i64(now)?)
        .bind(reservation.reservation_id.as_array().as_slice())
        .execute(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
        count += 1;
    }
    Ok(count)
}

fn reservation_matches_request(
    reservation: &Reservation,
    request: &EffectAdmissionRequest,
) -> bool {
    reservation.operation_id == request.operation_id
        && reservation.principal_id == request.principal_id
        && reservation.action_id == request.action_id
        && reservation.scope_digest == request.scope_digest
        && reservation.policy_revision == request.policy_revision
        && reservation.quota_key == request.quota_key
        && reservation.quota_revision == request.quota_revision
        && reservation.amount == request.amount
        && reservation.expires_at_ms == request.expires_at_ms
}

fn validate_policy(rule: &AuthPolicyRule) -> Result<(), AuthBusControlError> {
    if rule.revision == 0
        || rule.scope_digest.is_zero()
        || rule.max_active_reservations == 0
        || rule.max_active_reservations > AUTHBUS_MAX_ACTIVE_RESERVATIONS_PER_POLICY
    {
        return Err(AuthBusControlError::InvalidRequest(
            "policy revision and scope must be nonzero",
        ));
    }
    Ok(())
}

fn validate_quota(entry: &QuotaRegistryEntry) -> Result<(), AuthBusControlError> {
    if entry.revision == 0
        || entry.capacity == 0
        || entry.period_end_ms <= entry.period_start_ms
        || entry.period_end_ms > i64::MAX as u64
    {
        return Err(AuthBusControlError::InvalidRequest(
            "quota revision, capacity or period is invalid",
        ));
    }
    Ok(())
}

fn validate_admission(
    request: &EffectAdmissionRequest,
    now: u64,
) -> Result<(), AuthBusControlError> {
    if request.policy_revision == 0
        || request.quota_revision == 0
        || request.amount == 0
        || request.scope_digest.is_zero()
        || request.expires_at_ms <= now
        || request.expires_at_ms.saturating_sub(now) > AUTHBUS_MAX_RESERVATION_TTL_MS
        || request.expires_at_ms > i64::MAX as u64
    {
        return Err(AuthBusControlError::InvalidRequest(
            "effect admission revision, amount, scope or expiry is invalid",
        ));
    }
    Ok(())
}

fn effect_str(effect: PolicyEffect) -> &'static str {
    match effect {
        PolicyEffect::Allow => "allow",
        PolicyEffect::Deny => "deny",
    }
}

fn policy_digest(rule: &AuthPolicyRule) -> Digest32 {
    let mut bytes = b"hepta.authbus.policy.v1\0".to_vec();
    push_id(&mut bytes, &rule.principal_id);
    push_id(&mut bytes, &rule.action_id);
    bytes.extend_from_slice(rule.scope_digest.as_array());
    bytes.extend_from_slice(&rule.revision.to_be_bytes());
    bytes.push(match rule.effect {
        PolicyEffect::Allow => 1,
        PolicyEffect::Deny => 0,
    });
    bytes.extend_from_slice(&rule.max_active_reservations.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn quota_digest(entry: &QuotaRegistryEntry) -> Digest32 {
    let mut bytes = b"hepta.authbus.quota.v1\0".to_vec();
    push_id(&mut bytes, &entry.quota_key);
    bytes.extend_from_slice(&entry.revision.to_be_bytes());
    bytes.extend_from_slice(&entry.capacity.to_be_bytes());
    bytes.extend_from_slice(&entry.period_start_ms.to_be_bytes());
    bytes.extend_from_slice(&entry.period_end_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn reservation_digest(request: &EffectAdmissionRequest) -> Digest32 {
    let mut bytes = b"hepta.authbus.reservation.v1\0".to_vec();
    push_id(&mut bytes, &request.operation_id);
    push_id(&mut bytes, &request.principal_id);
    push_id(&mut bytes, &request.action_id);
    bytes.extend_from_slice(request.scope_digest.as_array());
    bytes.extend_from_slice(&request.policy_revision.to_be_bytes());
    push_id(&mut bytes, &request.quota_key);
    bytes.extend_from_slice(&request.quota_revision.to_be_bytes());
    bytes.extend_from_slice(&request.amount.to_be_bytes());
    bytes.extend_from_slice(&request.expires_at_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

async fn replay_digest_tx(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Digest32, AuthBusControlError> {
    let rows = sqlx::query(
        "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
         FROM authbus_replay_sequences
         ORDER BY issuer_id, key_epoch, subject_id, scope_digest",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let mut bytes = b"hepta.authbus.replay-checkpoint.v1\0".to_vec();
    for row in rows {
        bytes.push(0);
        push_text(
            &mut bytes,
            &row.try_get::<String, _>("issuer_id")
                .map_err(classify_sqlx_error)?,
        );
        bytes.extend_from_slice(&blob_u64(&row, "key_epoch")?.to_be_bytes());
        push_text(
            &mut bytes,
            &row.try_get::<String, _>("subject_id")
                .map_err(classify_sqlx_error)?,
        );
        bytes.extend_from_slice(blob_digest(&row, "scope_digest")?.as_array());
        bytes.extend_from_slice(&blob_u64(&row, "sequence")?.to_be_bytes());
        bytes.extend_from_slice(blob_digest(&row, "envelope_digest")?.as_array());
    }
    let retired = sqlx::query(
        "SELECT issuer_id, key_epoch, checkpoint_generation
         FROM authbus_retired_epochs ORDER BY issuer_id, key_epoch",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    for row in retired {
        bytes.push(1);
        push_text(
            &mut bytes,
            &row.try_get::<String, _>("issuer_id")
                .map_err(classify_sqlx_error)?,
        );
        bytes.extend_from_slice(&blob_u64(&row, "key_epoch")?.to_be_bytes());
        bytes.extend_from_slice(&blob_u64(&row, "checkpoint_generation")?.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

async fn load_checkpoint_tx(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<AuthBusReplayCheckpoint>, AuthBusControlError> {
    sqlx::query(
        "SELECT generation, replay_digest FROM authbus_replay_checkpoint WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .map(|row| {
        Ok(AuthBusReplayCheckpoint {
            generation: blob_u64(&row, "generation")?,
            replay_digest: blob_digest(&row, "replay_digest")?,
        })
    })
    .transpose()
}

async fn write_checkpoint_tx(
    tx: &mut Transaction<'_, Sqlite>,
    checkpoint: &AuthBusReplayCheckpoint,
) -> Result<(), AuthBusControlError> {
    sqlx::query(
        "INSERT INTO authbus_replay_checkpoint
         (singleton, generation, replay_digest, updated_at_ms)
         VALUES (1, ?, ?, ?)
         ON CONFLICT(singleton) DO UPDATE SET
           generation = excluded.generation,
           replay_digest = excluded.replay_digest,
           updated_at_ms = excluded.updated_at_ms",
    )
    .bind(checkpoint.generation.to_be_bytes().as_slice())
    .bind(checkpoint.replay_digest.as_array().as_slice())
    .bind(now_millis()?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn blob_u64(row: &SqliteRow, column: &str) -> Result<u64, AuthBusControlError> {
    blob_u64_evidence(row, column).map_err(Into::into)
}

fn blob_u64_evidence(row: &SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    vec_u64_evidence(bytes, column)
}

fn vec_u64(value: Vec<u8>, column: &str) -> Result<u64, AuthBusControlError> {
    vec_u64_evidence(value, column).map_err(Into::into)
}

fn vec_u64_evidence(value: Vec<u8>, column: &str) -> Result<u64, EvidenceError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {column} width")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn blob_digest(row: &SqliteRow, column: &str) -> Result<Digest32, AuthBusControlError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    vec_digest(bytes, column)
}

fn vec_digest(value: Vec<u8>, column: &str) -> Result<Digest32, AuthBusControlError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {column} width")))?;
    Ok(Digest32::from_array(bytes))
}

fn u64_to_i64(value: u64) -> Result<i64, AuthBusControlError> {
    i64::try_from(value)
        .map_err(|_| AuthBusControlError::InvalidRequest("timestamp exceeds SQLite range"))
}

fn i64_to_u64(value: i64) -> Result<u64, AuthBusControlError> {
    u64::try_from(value)
        .map_err(|_| EvidenceError::Corrupt("negative AuthBus timestamp".into()).into())
}
