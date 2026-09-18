use std::collections::BTreeMap;

use codex_hepta_authbus::AUTHBUS_MAX_RESERVATIONS;
use codex_hepta_authbus::AuthPolicy;
use codex_hepta_authbus::AuthorizationDecision;
use codex_hepta_authbus::AuthorizationRequest;
use codex_hepta_authbus::PolicyDecisionKind;
use codex_hepta_authbus::PolicyDenyReason;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::QuotaState;
use codex_hepta_authbus::ReservationRecord;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::ReservationResolution;
use codex_hepta_authbus::ReservationState;
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
    #[error("invalid AuthBus control request: {0}")]
    InvalidRequest(&'static str),
    #[error("stale AuthBus policy revision")]
    StalePolicyRevision,
    #[error("stale AuthBus quota revision")]
    StaleQuotaRevision,
    #[error("AuthBus quota exceeded")]
    QuotaExceeded,
    #[error("AuthBus quota period is inactive")]
    QuotaPeriodInactive,
    #[error("AuthBus quota period cannot change while reservations are held")]
    QuotaPeriodBusy,
    #[error("AuthBus reservation identity conflict")]
    ReservationConflict,
    #[error("AuthBus reservation is unavailable for this transition")]
    ReservationUnavailable,
    #[error("AuthBus observed cost exceeds the reservation")]
    ObservedCostOverrun,
    #[error("AuthBus rollback checkpoint does not match this store")]
    RollbackDetected,
    #[error("AuthBus issuer epoch was permanently retired")]
    RetiredIssuer,
    #[error(transparent)]
    Storage(#[from] EvidenceError),
}

impl HeptaEvidenceStore {
    pub async fn install_authbus_policy(
        &self,
        policy: &AuthPolicy,
    ) -> Result<AuthPolicy, AuthBusControlError> {
        if !policy.validate() {
            return Err(AuthBusControlError::InvalidRequest("invalid policy"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let head: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT revision FROM authbus_policy_heads WHERE policy_id = ?",
        )
        .bind(policy.policy_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(head) = head {
            let current = u64_blob_value(&head, "policy head revision")?;
            if policy.revision < current {
                return Err(AuthBusControlError::StalePolicyRevision);
            }
            if policy.revision == current {
                let stored = load_policy_version(&mut tx, &policy.policy_id, current)
                    .await?
                    .ok_or_else(|| {
                        EvidenceError::Corrupt("AuthBus policy head has no version row".into())
                    })?;
                if &stored != policy {
                    return Err(AuthBusControlError::ReservationConflict);
                }
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(stored);
            }
            if policy.revision != current.saturating_add(1) {
                return Err(AuthBusControlError::StalePolicyRevision);
            }
        }
        let now = now_millis()?;
        let revision = policy.revision.to_be_bytes();
        let max_reservation = policy.max_reservation.to_be_bytes();
        let digest = policy.digest();
        sqlx::query(
            "INSERT INTO authbus_policy_versions (
                policy_id, revision, principal_id, action, resource_digest,
                scope_digest, audience, quota_key, max_reservation, enabled, policy_digest, created_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(policy.policy_id.as_str())
        .bind(revision.as_slice())
        .bind(policy.principal_id.as_str())
        .bind(policy.action.as_str())
        .bind(policy.resource_digest.as_array().as_slice())
        .bind(policy.scope_digest.as_array().as_slice())
        .bind(policy.audience.as_str())
        .bind(policy.quota_key.as_str())
        .bind(max_reservation.as_slice())
        .bind(i64::from(policy.enabled))
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "INSERT INTO authbus_policy_heads(policy_id, revision, policy_digest, updated_at_ms)
             VALUES (?, ?, ?, ?)
             ON CONFLICT(policy_id) DO UPDATE SET
               revision = excluded.revision,
               policy_digest = excluded.policy_digest,
               updated_at_ms = excluded.updated_at_ms",
        )
        .bind(policy.policy_id.as_str())
        .bind(revision.as_slice())
        .bind(digest.as_array().as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut event = b"policy-install\0".to_vec();
        push_text(&mut event, policy.policy_id.as_str());
        event.extend_from_slice(&revision);
        event.extend_from_slice(digest.as_array());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(policy.clone())
    }

    pub async fn authorize_authbus(
        &self,
        request: &AuthorizationRequest,
    ) -> Result<AuthorizationDecision, AuthBusControlError> {
        if !request.validate() {
            return Err(AuthBusControlError::InvalidRequest(
                "invalid authorization request",
            ));
        }
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let Some(head) = load_policy_head(&mut tx, &request.policy_id).await? else {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(AuthorizationDecision::denied(
                request,
                PolicyDenyReason::MissingPolicy,
            ));
        };
        let (revision, head_digest) = head;
        if revision != request.expected_policy_revision {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(AuthorizationDecision::denied(
                request,
                PolicyDenyReason::StaleRevision,
            ));
        }
        let policy = load_policy_version(&mut tx, &request.policy_id, revision)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus policy head is dangling".into()))?;
        if policy.digest() != head_digest {
            return Err(EvidenceError::Corrupt("AuthBus policy head digest mismatch".into()).into());
        }
        let reason = if !policy.enabled {
            Some(PolicyDenyReason::Disabled)
        } else if policy.principal_id != request.principal_id {
            Some(PolicyDenyReason::PrincipalMismatch)
        } else if policy.action != request.action {
            Some(PolicyDenyReason::ActionMismatch)
        } else if policy.resource_digest != request.resource_digest {
            Some(PolicyDenyReason::ResourceMismatch)
        } else if policy.scope_digest != request.scope_digest {
            Some(PolicyDenyReason::ScopeMismatch)
        } else if policy.audience != request.audience {
            Some(PolicyDenyReason::AudienceMismatch)
        } else {
            None
        };
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(reason.map_or_else(
            || AuthorizationDecision::allowed(request, &policy),
            |reason| AuthorizationDecision::denied(request, reason),
        ))
    }

    pub async fn install_authbus_quota(
        &self,
        spec: &QuotaSpec,
    ) -> Result<QuotaState, AuthBusControlError> {
        if !spec.validate() {
            return Err(AuthBusControlError::InvalidRequest("invalid quota spec"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_quota(&mut tx, &spec.quota_key).await?;
        let now = now_millis()?;
        let state = if let Some(mut current) = current {
            if spec.config_revision < current.spec.config_revision {
                return Err(AuthBusControlError::StaleQuotaRevision);
            }
            if spec.config_revision == current.spec.config_revision {
                if &current.spec != spec {
                    return Err(AuthBusControlError::ReservationConflict);
                }
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(current);
            }
            if spec.config_revision != current.spec.config_revision.saturating_add(1) {
                return Err(AuthBusControlError::StaleQuotaRevision);
            }
            let period_changed = spec.period_start_ms != current.spec.period_start_ms
                || spec.period_end_ms != current.spec.period_end_ms;
            if period_changed {
                if current.reserved != 0 {
                    return Err(AuthBusControlError::QuotaPeriodBusy);
                }
                if spec.period_start_ms < current.spec.period_end_ms {
                    return Err(AuthBusControlError::InvalidRequest(
                        "quota periods must not overlap",
                    ));
                }
                current.consumed = 0;
            }
            let committed = current
                .reserved
                .checked_add(current.consumed)
                .ok_or(AuthBusControlError::QuotaExceeded)?;
            if spec.capacity < committed {
                return Err(AuthBusControlError::QuotaExceeded);
            }
            current.spec = spec.clone();
            current.ledger_revision = current
                .ledger_revision
                .checked_add(1)
                .ok_or(AuthBusControlError::InvalidRequest("quota revision overflow"))?;
            write_quota(&mut tx, &current, now).await?;
            current
        } else {
            let state = QuotaState {
                spec: spec.clone(),
                ledger_revision: 1,
                reserved: 0,
                consumed: 0,
            };
            write_quota(&mut tx, &state, now).await?;
            state
        };
        let mut event = b"quota-install\0".to_vec();
        push_text(&mut event, spec.quota_key.as_str());
        event.extend_from_slice(&spec.config_revision.to_be_bytes());
        event.extend_from_slice(&state.ledger_revision.to_be_bytes());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(state)
    }

    pub async fn authbus_quota_state(
        &self,
        quota_key: &StableId,
    ) -> Result<Option<QuotaState>, AuthBusControlError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let value = load_quota(&mut tx, quota_key).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(value)
    }

    pub async fn reserve_authbus_quota(
        &self,
        decision: &AuthorizationDecision,
        request: &ReservationRequest,
        now_ms: u64,
    ) -> Result<ReservationRecord, AuthBusControlError> {
        if decision.kind != PolicyDecisionKind::Allowed
            || !request.validate()
            || !decision.permits(request)
            || now_ms == 0
            || request.expires_at_ms <= now_ms
        {
            return Err(AuthBusControlError::InvalidRequest(
                "authorization does not permit this reservation",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        verify_current_policy_for_reservation(&mut tx, decision, request).await?;
        if let Some(existing) = load_reservation(&mut tx, &request.reservation_id).await? {
            let exact = existing.operation_id == request.operation_id
                && existing.quota_key == request.quota_key
                && existing.amount == request.amount
                && existing.expires_at_ms == request.expires_at_ms
                && existing.policy_digest == request.policy_digest
                && existing.authorization_digest == request.authorization_digest;
            if !exact {
                return Err(AuthBusControlError::ReservationConflict);
            }
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(existing);
        }
        let reused: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM authbus_quota_reservations WHERE operation_id = ?)",
        )
        .bind(request.operation_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if reused {
            return Err(AuthBusControlError::ReservationConflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_quota_reservations")
            .fetch_one(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        if usize::try_from(count).unwrap_or(usize::MAX) >= AUTHBUS_MAX_RESERVATIONS {
            return Err(AuthBusControlError::QuotaExceeded);
        }
        let mut quota = load_quota(&mut tx, &request.quota_key)
            .await?
            .ok_or(AuthBusControlError::QuotaExceeded)?;
        if quota.ledger_revision != request.expected_quota_revision {
            return Err(AuthBusControlError::StaleQuotaRevision);
        }
        if now_ms < quota.spec.period_start_ms || now_ms >= quota.spec.period_end_ms {
            return Err(AuthBusControlError::QuotaPeriodInactive);
        }
        if quota.available().is_none_or(|available| request.amount > available) {
            return Err(AuthBusControlError::QuotaExceeded);
        }
        quota.reserved = quota
            .reserved
            .checked_add(request.amount)
            .ok_or(AuthBusControlError::QuotaExceeded)?;
        quota.ledger_revision = quota
            .ledger_revision
            .checked_add(1)
            .ok_or(AuthBusControlError::InvalidRequest("quota revision overflow"))?;
        if !quota.invariant_holds() {
            return Err(AuthBusControlError::QuotaExceeded);
        }
        write_quota(&mut tx, &quota, i64_from_u64(now_ms)?).await?;
        let record = ReservationRecord {
            reservation_id: request.reservation_id.clone(),
            operation_id: request.operation_id.clone(),
            quota_key: request.quota_key.clone(),
            amount: request.amount,
            state: ReservationState::Active,
            expires_at_ms: request.expires_at_ms,
            policy_digest: request.policy_digest,
            authorization_digest: request.authorization_digest,
            quota_revision_at_reserve: request.expected_quota_revision,
            observed_cost: None,
            terminal_evidence: None,
        };
        insert_reservation(&mut tx, &record, i64_from_u64(now_ms)?).await?;
        let mut event = b"quota-reserve\0".to_vec();
        push_text(&mut event, record.reservation_id.as_str());
        push_text(&mut event, record.operation_id.as_str());
        event.extend_from_slice(&record.amount.to_be_bytes());
        event.extend_from_slice(&quota.ledger_revision.to_be_bytes());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(record)
    }

    pub async fn settle_authbus_reservation(
        &self,
        reservation_id: &StableId,
        observed_cost: u64,
        terminal_evidence: Digest32,
    ) -> Result<ReservationRecord, AuthBusControlError> {
        if observed_cost == 0 || terminal_evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "settlement requires observed cost and terminal evidence",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let mut reservation = load_reservation(&mut tx, reservation_id)
            .await?
            .ok_or(AuthBusControlError::ReservationUnavailable)?;
        if reservation.state == ReservationState::Settled {
            if reservation.observed_cost == Some(observed_cost)
                && reservation.terminal_evidence == Some(terminal_evidence)
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        if reservation.state == ReservationState::Cancelled {
            return Err(AuthBusControlError::ReservationUnavailable);
        }
        if observed_cost > reservation.amount {
            reservation.state = ReservationState::Quarantined;
            reservation.terminal_evidence = Some(terminal_evidence);
            update_reservation(&mut tx, &reservation, now_millis()?).await?;
            let mut event = b"quota-overrun-quarantine\0".to_vec();
            push_text(&mut event, reservation.reservation_id.as_str());
            event.extend_from_slice(&observed_cost.to_be_bytes());
            event.extend_from_slice(terminal_evidence.as_array());
            crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Err(AuthBusControlError::ObservedCostOverrun);
        }
        let mut quota = load_quota(&mut tx, &reservation.quota_key)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("reservation quota is missing".into()))?;
        quota.reserved = quota
            .reserved
            .checked_sub(reservation.amount)
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus reserved quota underflow".into()))?;
        quota.consumed = quota
            .consumed
            .checked_add(observed_cost)
            .ok_or(AuthBusControlError::QuotaExceeded)?;
        quota.ledger_revision = quota
            .ledger_revision
            .checked_add(1)
            .ok_or(AuthBusControlError::InvalidRequest("quota revision overflow"))?;
        if !quota.invariant_holds() {
            return Err(EvidenceError::Corrupt("AuthBus quota conservation failure".into()).into());
        }
        let now = now_millis()?;
        write_quota(&mut tx, &quota, now).await?;
        reservation.state = ReservationState::Settled;
        reservation.observed_cost = Some(observed_cost);
        reservation.terminal_evidence = Some(terminal_evidence);
        update_reservation(&mut tx, &reservation, now).await?;
        let mut event = b"quota-settle\0".to_vec();
        push_text(&mut event, reservation.reservation_id.as_str());
        event.extend_from_slice(&observed_cost.to_be_bytes());
        event.extend_from_slice(terminal_evidence.as_array());
        event.extend_from_slice(&quota.ledger_revision.to_be_bytes());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(reservation)
    }

    pub async fn cancel_authbus_reservation(
        &self,
        reservation_id: &StableId,
        terminal_evidence: Digest32,
    ) -> Result<ReservationRecord, AuthBusControlError> {
        if terminal_evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "cancellation requires no-effect evidence",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let mut reservation = load_reservation(&mut tx, reservation_id)
            .await?
            .ok_or(AuthBusControlError::ReservationUnavailable)?;
        if reservation.state == ReservationState::Cancelled {
            if reservation.terminal_evidence == Some(terminal_evidence) {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        if reservation.state == ReservationState::Settled {
            return Err(AuthBusControlError::ReservationUnavailable);
        }
        let mut quota = load_quota(&mut tx, &reservation.quota_key)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("reservation quota is missing".into()))?;
        quota.reserved = quota
            .reserved
            .checked_sub(reservation.amount)
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus reserved quota underflow".into()))?;
        quota.ledger_revision = quota
            .ledger_revision
            .checked_add(1)
            .ok_or(AuthBusControlError::InvalidRequest("quota revision overflow"))?;
        let now = now_millis()?;
        write_quota(&mut tx, &quota, now).await?;
        reservation.state = ReservationState::Cancelled;
        reservation.terminal_evidence = Some(terminal_evidence);
        update_reservation(&mut tx, &reservation, now).await?;
        let mut event = b"quota-cancel\0".to_vec();
        push_text(&mut event, reservation.reservation_id.as_str());
        event.extend_from_slice(terminal_evidence.as_array());
        event.extend_from_slice(&quota.ledger_revision.to_be_bytes());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(reservation)
    }

    pub async fn expire_authbus_reservations(
        &self,
        now_ms: u64,
        limit: u32,
    ) -> Result<u64, AuthBusControlError> {
        if now_ms == 0 || limit == 0 || limit > 128 {
            return Err(AuthBusControlError::InvalidRequest(
                "expiry scan requires time and limit 1..=128",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let rows = sqlx::query(
            "SELECT reservation_id, operation_id, quota_key, amount, state, expires_at_ms,
                    policy_digest, authorization_digest, quota_revision_at_reserve, observed_cost, terminal_evidence
             FROM authbus_quota_reservations
             WHERE state = 'active' ORDER BY expires_at_ms, reservation_id LIMIT ?",
        )
        .bind(limit)
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let now = now_millis()?;
        let mut expired = 0_u64;
        for row in rows {
            let mut reservation = decode_reservation(&row)?;
            if reservation.expires_at_ms > now_ms {
                continue;
            }
            reservation.state = ReservationState::Expired;
            update_reservation(&mut tx, &reservation, now).await?;
            expired = expired.saturating_add(1);
        }
        if expired != 0 {
            let mut event = b"quota-expire\0".to_vec();
            event.extend_from_slice(&now_ms.to_be_bytes());
            event.extend_from_slice(&expired.to_be_bytes());
            crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(expired)
    }

    pub async fn quarantine_authbus_reservation(
        &self,
        reservation_id: &StableId,
        evidence: Digest32,
    ) -> Result<ReservationRecord, AuthBusControlError> {
        if evidence.is_zero() {
            return Err(AuthBusControlError::InvalidRequest(
                "quarantine requires evidence",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let mut reservation = load_reservation(&mut tx, reservation_id)
            .await?
            .ok_or(AuthBusControlError::ReservationUnavailable)?;
        if reservation.state == ReservationState::Settled
            || reservation.state == ReservationState::Cancelled
        {
            return Err(AuthBusControlError::ReservationUnavailable);
        }
        if reservation.state == ReservationState::Quarantined {
            if reservation.terminal_evidence == Some(evidence) {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(reservation);
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        reservation.state = ReservationState::Quarantined;
        reservation.terminal_evidence = Some(evidence);
        let now = now_millis()?;
        update_reservation(&mut tx, &reservation, now).await?;
        let mut event = b"quota-quarantine\0".to_vec();
        push_text(&mut event, reservation.reservation_id.as_str());
        event.extend_from_slice(evidence.as_array());
        crate::authbus_trust_store::advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(reservation)
    }

    pub async fn reconcile_authbus_reservation(
        &self,
        reservation_id: &StableId,
        resolution: ReservationResolution,
    ) -> Result<ReservationRecord, AuthBusControlError> {
        match resolution {
            ReservationResolution::NoEffect { evidence } => {
                self.cancel_authbus_reservation(reservation_id, evidence).await
            }
            ReservationResolution::Consumed {
                observed_cost,
                evidence,
            } => {
                self.settle_authbus_reservation(reservation_id, observed_cost, evidence)
                    .await
            }
            ReservationResolution::Indeterminate { evidence } => {
                self.quarantine_authbus_reservation(reservation_id, evidence)
                    .await
            }
        }
    }
}

pub(crate) async fn verify_authbus_control_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    verify_policy_heads(pool).await?;
    verify_quota_conservation(pool).await?;
    let retired_overlap: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM authbus_replay_sequences AS replay
         JOIN authbus_replay_retired_epochs AS retired
           ON retired.issuer_id = replay.issuer_id AND retired.key_epoch = replay.key_epoch",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if retired_overlap != 0 {
        return Err(EvidenceError::Corrupt(
            "retired AuthBus replay epoch still has high-water rows".into(),
        ));
    }
    Ok(())
}

async fn verify_policy_heads(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT policy_id, revision, policy_digest FROM authbus_policy_heads",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in rows {
        let policy_id = stable_id_column(&row, "policy_id")?;
        let revision = u64_blob(&row, "revision")?;
        let expected = digest_column(&row, "policy_digest")?;
        let mut tx = pool.begin().await.map_err(classify_sqlx_error)?;
        let policy = load_policy_version(&mut tx, &policy_id, revision)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("dangling AuthBus policy head".into()))?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        if policy.digest() != expected {
            return Err(EvidenceError::Corrupt(
                "AuthBus policy head digest does not match its version".into(),
            ));
        }
    }
    Ok(())
}

async fn verify_quota_conservation(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let quota_rows = sqlx::query(
        "SELECT quota_key, config_revision, ledger_revision, capacity, reserved, consumed,
                period_start_ms, period_end_ms FROM authbus_quota_registry",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let mut held_by_key = BTreeMap::<String, u64>::new();
    let reservations = sqlx::query(
        "SELECT quota_key, amount, state FROM authbus_quota_reservations",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in reservations {
        let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
        if matches!(state.as_str(), "active" | "expired" | "quarantined") {
            let key: String = row.try_get("quota_key").map_err(classify_sqlx_error)?;
            let amount = u64_blob(&row, "amount")?;
            let slot = held_by_key.entry(key).or_default();
            *slot = slot
                .checked_add(amount)
                .ok_or_else(|| EvidenceError::Corrupt("AuthBus held quota overflow".into()))?;
        }
    }
    for row in quota_rows {
        let key: String = row.try_get("quota_key").map_err(classify_sqlx_error)?;
        let capacity = u64_blob(&row, "capacity")?;
        let reserved = u64_blob(&row, "reserved")?;
        let consumed = u64_blob(&row, "consumed")?;
        let held = held_by_key.remove(&key).unwrap_or_default();
        if reserved != held
            || reserved
                .checked_add(consumed)
                .is_none_or(|committed| committed > capacity)
        {
            return Err(EvidenceError::Corrupt(format!(
                "AuthBus quota conservation failed for {key}"
            )));
        }
    }
    if !held_by_key.is_empty() {
        return Err(EvidenceError::Corrupt(
            "AuthBus reservation references an unknown quota".into(),
        ));
    }
    Ok(())
}

async fn verify_current_policy_for_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    decision: &AuthorizationDecision,
    request: &ReservationRequest,
) -> Result<(), AuthBusControlError> {
    let Some(policy_id) = decision.policy_id.as_ref() else {
        return Err(AuthBusControlError::StalePolicyRevision);
    };
    let Some(expected_revision) = decision.policy_revision else {
        return Err(AuthBusControlError::StalePolicyRevision);
    };
    let Some(expected_digest) = decision.policy_digest else {
        return Err(AuthBusControlError::StalePolicyRevision);
    };
    if expected_digest != request.policy_digest {
        return Err(AuthBusControlError::StalePolicyRevision);
    }
    let Some((revision, digest)) = load_policy_head(tx, policy_id).await? else {
        return Err(AuthBusControlError::StalePolicyRevision);
    };
    if revision != expected_revision || digest != expected_digest {
        return Err(AuthBusControlError::StalePolicyRevision);
    }
    Ok(())
}

async fn load_policy_head(
    tx: &mut Transaction<'_, Sqlite>,
    policy_id: &StableId,
) -> Result<Option<(u64, Digest32)>, EvidenceError> {
    let row = sqlx::query(
        "SELECT revision, policy_digest FROM authbus_policy_heads WHERE policy_id = ?",
    )
    .bind(policy_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| Ok((u64_blob(&row, "revision")?, digest_column(&row, "policy_digest")?)))
        .transpose()
}

async fn load_policy_version(
    tx: &mut Transaction<'_, Sqlite>,
    policy_id: &StableId,
    revision: u64,
) -> Result<Option<AuthPolicy>, EvidenceError> {
    let bytes = revision.to_be_bytes();
    let row = sqlx::query(
        "SELECT policy_id, revision, principal_id, action, resource_digest,
                scope_digest, audience, quota_key, max_reservation, enabled, policy_digest
         FROM authbus_policy_versions WHERE policy_id = ? AND revision = ?",
    )
    .bind(policy_id.as_str())
    .bind(bytes.as_slice())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| {
        let policy = AuthPolicy {
            policy_id: stable_id_column(&row, "policy_id")?,
            revision: u64_blob(&row, "revision")?,
            principal_id: stable_id_column(&row, "principal_id")?,
            action: stable_id_column(&row, "action")?,
            resource_digest: digest_column(&row, "resource_digest")?,
            scope_digest: digest_column(&row, "scope_digest")?,
            audience: stable_id_column(&row, "audience")?,
            quota_key: stable_id_column(&row, "quota_key")?,
            max_reservation: u64_blob(&row, "max_reservation")?,
            enabled: row.try_get::<i64, _>("enabled").map_err(classify_sqlx_error)? == 1,
        };
        if !policy.validate() || policy.digest() != digest_column(&row, "policy_digest")? {
            return Err(EvidenceError::Corrupt("invalid AuthBus policy row".into()));
        }
        Ok(policy)
    })
    .transpose()
}

async fn load_quota(
    tx: &mut Transaction<'_, Sqlite>,
    quota_key: &StableId,
) -> Result<Option<QuotaState>, EvidenceError> {
    let row = sqlx::query(
        "SELECT quota_key, config_revision, ledger_revision, capacity, reserved, consumed,
                period_start_ms, period_end_ms
         FROM authbus_quota_registry WHERE quota_key = ?",
    )
    .bind(quota_key.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_quota(&row)).transpose()
}

fn decode_quota(row: &SqliteRow) -> Result<QuotaState, EvidenceError> {
    let state = QuotaState {
        spec: QuotaSpec {
            quota_key: stable_id_column(row, "quota_key")?,
            config_revision: u64_blob(row, "config_revision")?,
            capacity: u64_blob(row, "capacity")?,
            period_start_ms: u64_blob(row, "period_start_ms")?,
            period_end_ms: u64_blob(row, "period_end_ms")?,
        },
        ledger_revision: u64_blob(row, "ledger_revision")?,
        reserved: u64_blob(row, "reserved")?,
        consumed: u64_blob(row, "consumed")?,
    };
    if !state.spec.validate() || !state.invariant_holds() {
        return Err(EvidenceError::Corrupt("invalid AuthBus quota row".into()));
    }
    Ok(state)
}

async fn write_quota(
    tx: &mut Transaction<'_, Sqlite>,
    state: &QuotaState,
    now: i64,
) -> Result<(), EvidenceError> {
    if !state.spec.validate() || !state.invariant_holds() {
        return Err(EvidenceError::InvalidRecord("invalid AuthBus quota state".into()));
    }
    let config_revision = state.spec.config_revision.to_be_bytes();
    let ledger_revision = state.ledger_revision.to_be_bytes();
    let capacity = state.spec.capacity.to_be_bytes();
    let reserved = state.reserved.to_be_bytes();
    let consumed = state.consumed.to_be_bytes();
    let period_start = state.spec.period_start_ms.to_be_bytes();
    let period_end = state.spec.period_end_ms.to_be_bytes();
    sqlx::query(
        "INSERT INTO authbus_quota_registry(
            quota_key, config_revision, ledger_revision, capacity, reserved, consumed,
            period_start_ms, period_end_ms, updated_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(quota_key) DO UPDATE SET
            config_revision = excluded.config_revision,
            ledger_revision = excluded.ledger_revision,
            capacity = excluded.capacity,
            reserved = excluded.reserved,
            consumed = excluded.consumed,
            period_start_ms = excluded.period_start_ms,
            period_end_ms = excluded.period_end_ms,
            updated_at_ms = excluded.updated_at_ms",
    )
    .bind(state.spec.quota_key.as_str())
    .bind(config_revision.as_slice())
    .bind(ledger_revision.as_slice())
    .bind(capacity.as_slice())
    .bind(reserved.as_slice())
    .bind(consumed.as_slice())
    .bind(period_start.as_slice())
    .bind(period_end.as_slice())
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn load_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    reservation_id: &StableId,
) -> Result<Option<ReservationRecord>, EvidenceError> {
    sqlx::query(
        "SELECT reservation_id, operation_id, quota_key, amount, state, expires_at_ms,
                policy_digest, authorization_digest, quota_revision_at_reserve, observed_cost, terminal_evidence
         FROM authbus_quota_reservations WHERE reservation_id = ?",
    )
    .bind(reservation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .map(|row| decode_reservation(&row))
    .transpose()
}

fn decode_reservation(row: &SqliteRow) -> Result<ReservationRecord, EvidenceError> {
    let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
    let state = match state.as_str() {
        "active" => ReservationState::Active,
        "settled" => ReservationState::Settled,
        "cancelled" => ReservationState::Cancelled,
        "expired" => ReservationState::Expired,
        "quarantined" => ReservationState::Quarantined,
        _ => return Err(EvidenceError::Corrupt("invalid AuthBus reservation state".into())),
    };
    let observed: Option<Vec<u8>> = row.try_get("observed_cost").map_err(classify_sqlx_error)?;
    let terminal: Option<Vec<u8>> = row
        .try_get("terminal_evidence")
        .map_err(classify_sqlx_error)?;
    Ok(ReservationRecord {
        reservation_id: stable_id_column(row, "reservation_id")?,
        operation_id: stable_id_column(row, "operation_id")?,
        quota_key: stable_id_column(row, "quota_key")?,
        amount: u64_blob(row, "amount")?,
        state,
        expires_at_ms: u64_blob(row, "expires_at_ms")?,
        policy_digest: digest_column(row, "policy_digest")?,
        authorization_digest: digest_column(row, "authorization_digest")?,
        quota_revision_at_reserve: u64_blob(row, "quota_revision_at_reserve")?,
        observed_cost: observed
            .map(|value| u64_blob_value(&value, "observed cost"))
            .transpose()?,
        terminal_evidence: terminal
            .map(|value| digest_value(&value, "terminal evidence"))
            .transpose()?,
    })
}

async fn insert_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    record: &ReservationRecord,
    now: i64,
) -> Result<(), EvidenceError> {
    let amount = record.amount.to_be_bytes();
    let expires = record.expires_at_ms.to_be_bytes();
    let revision = record.quota_revision_at_reserve.to_be_bytes();
    sqlx::query(
        "INSERT INTO authbus_quota_reservations(
           reservation_id, operation_id, quota_key, amount, state, expires_at_ms,
           policy_digest, authorization_digest, quota_revision_at_reserve, observed_cost, terminal_evidence,
           created_at_ms, updated_at_ms
         ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, NULL, NULL, ?, ?)",
    )
    .bind(record.reservation_id.as_str())
    .bind(record.operation_id.as_str())
    .bind(record.quota_key.as_str())
    .bind(amount.as_slice())
    .bind(expires.as_slice())
    .bind(record.policy_digest.as_array().as_slice())
    .bind(record.authorization_digest.as_array().as_slice())
    .bind(revision.as_slice())
    .bind(now)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn update_reservation(
    tx: &mut Transaction<'_, Sqlite>,
    record: &ReservationRecord,
    now: i64,
) -> Result<(), EvidenceError> {
    let state = match record.state {
        ReservationState::Active => "active",
        ReservationState::Settled => "settled",
        ReservationState::Cancelled => "cancelled",
        ReservationState::Expired => "expired",
        ReservationState::Quarantined => "quarantined",
    };
    let observed = record
        .observed_cost
        .map(|value| value.to_be_bytes().to_vec());
    let evidence = record
        .terminal_evidence
        .as_ref()
        .map(|digest| digest.as_array().to_vec());
    sqlx::query(
        "UPDATE authbus_quota_reservations
         SET state = ?, observed_cost = ?, terminal_evidence = ?, updated_at_ms = ?
         WHERE reservation_id = ?",
    )
    .bind(state)
    .bind(observed.as_deref())
    .bind(evidence.as_deref())
    .bind(now)
    .bind(record.reservation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

fn stable_id_column(row: &SqliteRow, name: &str) -> Result<StableId, EvidenceError> {
    let value: String = row.try_get(name).map_err(classify_sqlx_error)?;
    StableId::new(value)
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {name} identifier")))
}

fn u64_blob(row: &SqliteRow, name: &str) -> Result<u64, EvidenceError> {
    let value: Vec<u8> = row.try_get(name).map_err(classify_sqlx_error)?;
    u64_blob_value(&value, name)
}

fn u64_blob_value(value: &[u8], name: &str) -> Result<u64, EvidenceError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {name} width")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn digest_column(row: &SqliteRow, name: &str) -> Result<Digest32, EvidenceError> {
    let value: Vec<u8> = row.try_get(name).map_err(classify_sqlx_error)?;
    digest_value(&value, name)
}

fn digest_value(value: &[u8], name: &str) -> Result<Digest32, EvidenceError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {name} width")))?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(EvidenceError::Corrupt(format!("empty AuthBus {name}")));
    }
    Ok(digest)
}

fn i64_from_u64(value: u64) -> Result<i64, AuthBusControlError> {
    i64::try_from(value)
        .map_err(|_| AuthBusControlError::InvalidRequest("timestamp exceeds SQLite integer range"))
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
