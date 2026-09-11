use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAdmissionError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_outbox_record::*;
use crate::authbus_store::advance_replay;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

impl HeptaEvidenceStore {
    /// Atomically authenticate, consume replay sequence and enqueue a message.
    /// This REPLACES direct admission for durable delivery; a previously admitted
    /// receipt cannot be upgraded. An exact retained duplicate returns its state.
    /// After terminal pruning a consumed sequence returns Replay, never requeues.
    pub async fn enqueue_authbus_message(
        &self,
        issuer: &IssuerRegistration,
        message: &SignedMessage,
        expected_subject: &StableId,
        expected_scope: Digest32,
        payload: &[u8],
    ) -> Result<AuthBusDeliveryStatus, AuthBusOutboxError> {
        if payload.len() > AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES {
            return Err(AuthBusOutboxError::InvalidRequest("payload exceeds 16 KiB"));
        }
        if &message.claims.subject_id != expected_subject {
            return Err(AuthBusOutboxError::InvalidRequest("subject mismatch"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now = now_millis()?;
        let authenticated = message
            .authenticate(
                issuer,
                expected_scope,
                Digest32::of_bytes(payload),
                clock(now)?,
            )
            .map_err(AuthBusAdmissionError::from)?;
        let delivery_id = authenticated.receipt().envelope_digest;
        if let Some(existing) = load(&mut tx, delivery_id).await? {
            if existing.message.claims != message.claims
                || existing.message.signature != message.signature
                || existing.payload != payload
            {
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: delivery_id.to_string(),
                }
                .into());
            }
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(existing.status);
        }
        let c = &message.claims;
        let reused: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM authbus_outbox WHERE issuer_id = ? AND key_epoch = ? AND message_id = ?)")
            .bind(c.issuer_id.as_str()).bind(c.key_epoch.get().to_be_bytes().as_slice())
            .bind(c.message_id.as_str()).fetch_one(&mut *tx).await.map_err(classify_sqlx_error)?;
        if reused {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: c.message_id.to_string(),
            }
            .into());
        }
        advance_replay(&mut tx, &authenticated).await?;
        maintain(&mut tx, now).await?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox")
            .fetch_one(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        if count >= AUTHBUS_OUTBOX_MAX_ROWS {
            // Roll back the replay advance too. Checking replay first gives a
            // pruned consumed message an unambiguous Replay even at capacity.
            return Err(AuthBusOutboxError::Capacity);
        }
        sqlx::query(
            "INSERT INTO authbus_outbox
            (delivery_id, issuer_id, key_epoch, message_id, subject_id, scope_digest,
             payload_digest, sequence, expires_at_ms, signature, payload, state, fence,
             attempts, available_at_ms, created_at_ms, updated_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?)",
        )
        .bind(delivery_id.as_array().as_slice())
        .bind(c.issuer_id.as_str())
        .bind(c.key_epoch.get().to_be_bytes().as_slice())
        .bind(c.message_id.as_str())
        .bind(c.subject_id.as_str())
        .bind(c.scope_digest.as_array().as_slice())
        .bind(c.payload_digest.as_array().as_slice())
        .bind(c.sequence.to_be_bytes().as_slice())
        .bind(c.expires_at_ms.to_be_bytes().as_slice())
        .bind(message.signature.as_slice())
        .bind(payload)
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let status = load(&mut tx, delivery_id)
            .await?
            .ok_or(AuthBusOutboxError::NotFound)?
            .status;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    /// Lookup is observation only: neither a delivery lease nor effect authority.
    pub async fn authbus_delivery_status(
        &self,
        delivery_id: Digest32,
    ) -> Result<AuthBusDeliveryStatus, AuthBusOutboxError> {
        let row = sqlx::query("SELECT * FROM authbus_outbox WHERE delivery_id = ?")
            .bind(delivery_id.as_array().as_slice())
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?
            .ok_or(AuthBusOutboxError::NotFound)?;
        Ok(OutboxRecord::decode(row)?.status)
    }

    /// Bounded route-specific recovery scan, including abandoned expired leases.
    /// The host resolves each message's current issuer before claiming its ID.
    pub async fn pending_authbus_deliveries(
        &self,
        subject: &StableId,
        scope: Digest32,
        limit: u32,
    ) -> Result<Vec<AuthBusDeliveryStatus>, AuthBusOutboxError> {
        if limit == 0 || limit > 128 {
            return Err(AuthBusOutboxError::InvalidRequest(
                "list limit must be 1..=128",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now = now_millis()?;
        maintain(&mut tx, now).await?;
        let rows = sqlx::query(
            "SELECT * FROM authbus_outbox WHERE subject_id = ? AND scope_digest = ?
            AND available_at_ms <= ? AND updated_at_ms <= ?
            AND (state = 'queued' OR (state = 'leased' AND lease_until_ms <= ?))
            ORDER BY available_at_ms, delivery_id LIMIT ?",
        )
        .bind(subject.as_str())
        .bind(scope.as_array().as_slice())
        .bind(now)
        .bind(now)
        .bind(now)
        .bind(limit)
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let statuses = rows
            .into_iter()
            .map(OutboxRecord::decode)
            .map(|r| r.map(|r| r.status))
            .collect::<Result<_, _>>()?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(statuses)
    }

    /// Explicitly retire active messages for a host-confirmed revoked issuer
    /// epoch. This does not infer revocation from an untrusted message or epoch.
    pub async fn quarantine_authbus_issuer(
        &self,
        issuer: &IssuerRegistration,
    ) -> Result<u64, AuthBusOutboxError> {
        if !issuer.revoked {
            return Err(AuthBusOutboxError::InvalidRequest("issuer is not revoked"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now = now_millis()?;
        let affected = sqlx::query(
            "UPDATE authbus_outbox SET state = 'quarantined', fence = fence + 1,
            worker_id = NULL, lease_until_ms = NULL, updated_at_ms = MAX(updated_at_ms, ?),
            terminal_at_ms = MAX(updated_at_ms, ?) WHERE issuer_id = ? AND key_epoch = ?
            AND state IN ('queued', 'leased')",
        )
        .bind(now)
        .bind(now)
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        .rows_affected();
        maintain(&mut tx, now).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(affected)
    }
}

pub(crate) async fn load(
    tx: &mut Transaction<'_, Sqlite>,
    id: Digest32,
) -> Result<Option<OutboxRecord>, EvidenceError> {
    sqlx::query("SELECT * FROM authbus_outbox WHERE delivery_id = ?")
        .bind(id.as_array().as_slice())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .map(OutboxRecord::decode)
        .transpose()
}

pub(crate) fn clock(now: i64) -> Result<u64, EvidenceError> {
    u64::try_from(now).map_err(|_| EvidenceError::Unavailable("clock predates Unix epoch".into()))
}

// Terminal retention is bounded by age, then count, then queue pressure. Active
// messages cannot be deleted. The independent replay registry is never changed.
pub(crate) async fn maintain(
    tx: &mut Transaction<'_, Sqlite>,
    now: i64,
) -> Result<(), EvidenceError> {
    sqlx::query("UPDATE authbus_outbox SET state = 'expired', fence = fence + 1,
        worker_id = NULL, lease_until_ms = NULL, updated_at_ms = MAX(updated_at_ms, ?),
        terminal_at_ms = MAX(updated_at_ms, ?) WHERE state IN ('queued', 'leased') AND expires_at_ms <= ?")
        .bind(now).bind(now).bind(clock(now)?.to_be_bytes().as_slice())
        .execute(&mut **tx).await.map_err(classify_sqlx_error)?;
    sqlx::query("DELETE FROM authbus_outbox WHERE state IN ('acked', 'expired', 'quarantined')
        AND (terminal_at_ms <= ? OR delivery_id IN (SELECT delivery_id FROM authbus_outbox
        WHERE state IN ('acked', 'expired', 'quarantined') ORDER BY terminal_at_ms DESC, delivery_id DESC LIMIT -1 OFFSET ?))")
        .bind(now.saturating_sub(TERMINAL_RETENTION_MS)).bind(TERMINAL_RETAINED_ROWS)
        .execute(&mut **tx).await.map_err(classify_sqlx_error)?;
    sqlx::query("DELETE FROM authbus_outbox WHERE delivery_id IN
        (SELECT delivery_id FROM authbus_outbox WHERE state IN ('acked', 'expired', 'quarantined')
        ORDER BY terminal_at_ms, delivery_id LIMIT MAX(0, (SELECT COUNT(*) FROM authbus_outbox) - ?))")
        .bind(AUTHBUS_OUTBOX_MAX_ROWS - 1).execute(&mut **tx).await.map_err(classify_sqlx_error)?;
    Ok(())
}
