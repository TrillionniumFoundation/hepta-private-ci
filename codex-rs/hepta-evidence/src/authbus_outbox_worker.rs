use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Digest32;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAdmissionError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_outbox::clock;
use crate::authbus_outbox::load;
use crate::authbus_outbox_record::*;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

impl HeptaEvidenceStore {
    /// Claim a queued message or recover an expired lease. The supplied issuer
    /// is a fresh trusted-host snapshot, not a registration stored in the queue.
    /// Claiming never retries an indeterminate provider effect.
    pub async fn claim_authbus_delivery(
        &self,
        issuer: &IssuerRegistration,
        request: AuthBusClaimRequest<'_>,
    ) -> Result<AuthBusDelivery, AuthBusOutboxError> {
        validate_duration(request.lease_ms)?;
        let (mut tx, record, now) = current(self, request.delivery_id, issuer).await?;
        if &record.message.claims.subject_id != request.subject_id
            || record.message.claims.scope_digest != request.scope_digest
        {
            return Err(AuthBusOutboxError::InvalidRequest("claim route mismatch"));
        }
        if record.status.available_at_ms > now
            || record.status.lease_until_ms.is_some_and(|end| end > now)
        {
            return Err(AuthBusOutboxError::Unavailable);
        }
        if record.status.attempts >= AUTHBUS_OUTBOX_MAX_ATTEMPTS {
            terminalize(&mut tx, request.delivery_id, "quarantined", now).await?;
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Err(AuthBusOutboxError::Unavailable);
        }
        let until = lease_end(&record, now, request.lease_ms)?;
        sqlx::query(
            "UPDATE authbus_outbox SET state = 'leased', fence = fence + 1,
            attempts = attempts + 1, worker_id = ?, lease_until_ms = ?, updated_at_ms = ?
            WHERE delivery_id = ?",
        )
        .bind(request.worker_id.as_str())
        .bind(until)
        .bind(now)
        .bind(request.delivery_id.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(AuthBusDelivery {
            lease: AuthBusLease {
                delivery_id: request.delivery_id,
                worker_id: request.worker_id.clone(),
                fence: record.status.fence + 1,
                expires_at_ms: until,
            },
            message: record.message,
            payload: record.payload,
        })
    }

    /// Renew with a new fence. Even the previous token of this worker becomes
    /// stale. A failed/ambiguous response is recovered by waiting for expiry.
    pub async fn renew_authbus_delivery(
        &self,
        issuer: &IssuerRegistration,
        lease: &AuthBusLease,
        lease_ms: i64,
    ) -> Result<AuthBusLease, AuthBusOutboxError> {
        validate_duration(lease_ms)?;
        let (mut tx, record, now) = current(self, lease.delivery_id, issuer).await?;
        require_lease(&record, lease, now)?;
        let until = lease_end(&record, now, lease_ms)?;
        sqlx::query(
            "UPDATE authbus_outbox SET fence = fence + 1, lease_until_ms = ?,
            updated_at_ms = ? WHERE delivery_id = ?",
        )
        .bind(until)
        .bind(now)
        .bind(lease.delivery_id.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(AuthBusLease {
            delivery_id: lease.delivery_id,
            worker_id: lease.worker_id.clone(),
            fence: lease.fence + 1,
            expires_at_ms: until,
        })
    }

    /// Release ownership for another *message delivery*. This is not permission
    /// to repeat a provider/network/filesystem effect with an unknown outcome.
    pub async fn retry_authbus_delivery(
        &self,
        issuer: &IssuerRegistration,
        lease: &AuthBusLease,
        delay_ms: i64,
    ) -> Result<(), AuthBusOutboxError> {
        if !(0..=AUTHBUS_OUTBOX_MAX_LEASE_MS).contains(&delay_ms) {
            return Err(AuthBusOutboxError::InvalidRequest(
                "retry delay must be 0..=60000 ms",
            ));
        }
        let (mut tx, record, now) = current(self, lease.delivery_id, issuer).await?;
        require_lease(&record, lease, now)?;
        let available = now
            .checked_add(delay_ms)
            .ok_or(AuthBusOutboxError::InvalidRequest("retry time overflow"))?;
        let expiry = record.message.claims.expires_at_ms;
        if record.status.attempts >= AUTHBUS_OUTBOX_MAX_ATTEMPTS || clock(available)? >= expiry {
            terminalize(&mut tx, lease.delivery_id, "quarantined", now).await?;
        } else {
            sqlx::query(
                "UPDATE authbus_outbox SET state = 'queued', fence = fence + 1,
                worker_id = NULL, lease_until_ms = NULL, available_at_ms = ?, updated_at_ms = ?
                WHERE delivery_id = ?",
            )
            .bind(available)
            .bind(now)
            .bind(lease.delivery_id.as_array().as_slice())
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    /// Record the consumer's delivery acknowledgement. Its digest is ordinary
    /// evidence, not proof of an external effect. Send and ack are not atomic:
    /// a crash between them permits delivery of the same ID under a new lease.
    pub async fn ack_authbus_delivery(
        &self,
        issuer: &IssuerRegistration,
        lease: &AuthBusLease,
        acknowledgement: Digest32,
    ) -> Result<(), AuthBusOutboxError> {
        if acknowledgement.is_zero() {
            return Err(AuthBusOutboxError::InvalidRequest(
                "empty acknowledgement digest",
            ));
        }
        let (mut tx, record, now) = current(self, lease.delivery_id, issuer).await?;
        require_lease(&record, lease, now)?;
        sqlx::query(
            "UPDATE authbus_outbox SET state = 'acked', fence = fence + 1,
            worker_id = NULL, lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?,
            acknowledgement = ? WHERE delivery_id = ?",
        )
        .bind(now)
        .bind(now)
        .bind(acknowledgement.as_array().as_slice())
        .bind(lease.delivery_id.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }
}

fn validate_duration(lease_ms: i64) -> Result<(), AuthBusOutboxError> {
    if !(1..=AUTHBUS_OUTBOX_MAX_LEASE_MS).contains(&lease_ms) {
        return Err(AuthBusOutboxError::InvalidRequest(
            "lease must be 1..=60000 ms",
        ));
    }
    Ok(())
}

fn lease_end(record: &OutboxRecord, now: i64, lease_ms: i64) -> Result<i64, AuthBusOutboxError> {
    let end = now
        .checked_add(lease_ms)
        .ok_or(AuthBusOutboxError::InvalidRequest("lease time overflow"))?;
    Ok(end.min(i64::try_from(record.message.claims.expires_at_ms).unwrap_or(i64::MAX)))
}

fn require_lease(
    record: &OutboxRecord,
    lease: &AuthBusLease,
    now: i64,
) -> Result<(), AuthBusOutboxError> {
    if record.status.state != AuthBusDeliveryState::Leased
        || record.status.fence != lease.fence
        || record.worker_id.as_deref() != Some(lease.worker_id.as_str())
        || record
            .status
            .lease_until_ms
            .is_none_or(|until| until <= now)
    {
        return Err(AuthBusOutboxError::StaleLease);
    }
    Ok(())
}

// Time and authentication are refreshed after the write lock for every worker
// transition, including ack. Clock rollback fails closed until time catches up.
async fn current(
    store: &HeptaEvidenceStore,
    id: Digest32,
    issuer: &IssuerRegistration,
) -> Result<(Transaction<'static, Sqlite>, OutboxRecord, i64), AuthBusOutboxError> {
    let mut tx = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(classify_sqlx_error)?;
    let record = load(&mut tx, id)
        .await?
        .ok_or(AuthBusOutboxError::NotFound)?;
    let now = now_millis()?;
    if !matches!(
        record.status.state,
        AuthBusDeliveryState::Queued | AuthBusDeliveryState::Leased
    ) {
        return Err(AuthBusOutboxError::Unavailable);
    }
    if now < record.updated_at_ms {
        return Err(AuthBusOutboxError::StaleLease);
    }
    let result = record.message.authenticate(
        issuer,
        record.message.claims.scope_digest,
        Digest32::of_bytes(&record.payload),
        clock(now)?,
    );
    match result {
        Ok(authenticated) => {
            if authenticated.receipt().envelope_digest != id {
                return Err(
                    EvidenceError::Corrupt("AuthBus envelope identity mismatch".into()).into(),
                );
            }
        }
        Err(error) => {
            use codex_hepta_authbus::Error;
            if matches!(
                error,
                Error::Expired | Error::Revoked | Error::InvalidSignature
            ) {
                let state = if error == Error::Expired {
                    "expired"
                } else {
                    "quarantined"
                };
                terminalize(&mut tx, id, state, now).await?;
                tx.commit().await.map_err(classify_sqlx_error)?;
            }
            return Err(AuthBusAdmissionError::from(error).into());
        }
    }
    Ok((tx, record, now))
}

async fn terminalize(
    tx: &mut Transaction<'_, Sqlite>,
    id: Digest32,
    state: &str,
    now: i64,
) -> Result<(), EvidenceError> {
    sqlx::query(
        "UPDATE authbus_outbox SET state = ?, fence = fence + 1,
        worker_id = NULL, lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
        WHERE delivery_id = ?",
    )
    .bind(state)
    .bind(now)
    .bind(now)
    .bind(id.as_array().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}
