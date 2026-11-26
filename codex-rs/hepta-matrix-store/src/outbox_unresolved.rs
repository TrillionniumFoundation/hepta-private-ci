//! Owner-local reconciliation parking, separate from a server terminal result.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;

use crate::ChangeKind;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixRoomId;
use crate::MatrixTransactionId;
use crate::model::MAX_PAGE_ITEMS;

/// An unknown send outcome whose exact outstanding attempt needs observation.
/// The original outbox row remains in flight; this record forbids new claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutboxUnresolvedRecord {
    pub stable_txn_id: MatrixTransactionId,
    pub attempts: u64,
    pub recorded_at_ms: u64,
}

pub(crate) async fn verify_storage(pool: &SqlitePool) -> Result<(), MatrixDurableError> {
    let rows = sqlx::query(
        "SELECT name, type, sql FROM sqlite_schema
         WHERE name IN ('outbox_unresolved', 'outbox_unresolved_guard_insert',
                       'outbox_unresolved_no_update', 'outbox_unresolved_guard_delete')
         ORDER BY name",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if rows.len() != 4 {
        return Err(MatrixDurableError::Corrupt);
    }
    let mut identity = Vec::new();
    for row in rows {
        for column in ["name", "type", "sql"] {
            let value: String = row.try_get(column).map_err(unavailable)?;
            identity.extend_from_slice(value.replace("\r\n", "\n").replace('\r', "\n").as_bytes());
            identity.push(0);
        }
    }
    if Sha256Digest::for_bytes(&identity).as_str()
        != "46bb9e1eb1fada0dd3b4b280a91f1e4e26d6102e82a1ee6e6d37050b84032776"
    {
        return Err(MatrixDurableError::Corrupt);
    }
    let invalid: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM outbox_unresolved AS unresolved
         LEFT JOIN outbox_messages AS message USING (stable_txn_id)
         WHERE message.stable_txn_id IS NULL OR message.state != 'in_flight'
            OR message.attempts != unresolved.attempts
            OR message.updated_at_ms > unresolved.recorded_at_ms",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}

impl MatrixDurableStore {
    /// Preserve an unknown terminal outcome after exhausted retries, a crash,
    /// or a later rejection which cannot settle a previous unknown delivery.
    /// This parks only the exact stable transaction and current issued attempt,
    /// never a coalesced fragment alias, and grants no retry or effect authority.
    pub async fn park_outbox_unresolved(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<OutboxUnresolvedRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let recorded_at_ms = i64::try_from(now_ms).map_err(|_| MatrixDurableError::Invalid)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT stable_txn_id, room_id, state, attempts, updated_at_ms
             FROM outbox_messages WHERE stable_txn_id = ?",
        )
        .bind(txn_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(MatrixDurableError::Conflict)?;
        let state: String = row.try_get("state").map_err(unavailable)?;
        let attempts = stored_u64(row.try_get("attempts").map_err(unavailable)?)?;
        if state != "in_flight" || attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(existing) = sqlx::query(
            "SELECT stable_txn_id, attempts, reason, recorded_at_ms
             FROM outbox_unresolved WHERE stable_txn_id = ?",
        )
        .bind(txn_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        {
            let existing = from_row(&existing)?;
            if existing.attempts != expected_attempt {
                return Err(MatrixDurableError::Corrupt);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        let updated_at_ms: i64 = row.try_get("updated_at_ms").map_err(unavailable)?;
        if recorded_at_ms < updated_at_ms {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "INSERT INTO outbox_unresolved (stable_txn_id, attempts, reason, recorded_at_ms)
             VALUES (?, ?, 'unknown_delivery', ?)",
        )
        .bind(txn_id.as_str())
        .bind(i64::try_from(expected_attempt).map_err(|_| MatrixDurableError::Invalid)?)
        .bind(recorded_at_ms)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let room_id =
            MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
                .map_err(|_| MatrixDurableError::Corrupt)?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxNeedsReconciliation,
            Some(&room_id),
            /*event_id*/ None,
            Some(txn_id),
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(OutboxUnresolvedRecord {
            stable_txn_id: txn_id.clone(),
            attempts: expected_attempt,
            recorded_at_ms: now_ms,
        })
    }

    /// Inspect a bounded page of outstanding unknown outcomes, including rows
    /// fenced by a later room leave. Inspection cannot resume a parked sender.
    pub async fn unresolved_outbox(
        &self,
        limit: usize,
    ) -> Result<Vec<OutboxUnresolvedRecord>, MatrixDurableError> {
        if !(1..=MAX_PAGE_ITEMS).contains(&limit) {
            return Err(MatrixDurableError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT stable_txn_id, attempts, reason, recorded_at_ms
             FROM outbox_unresolved ORDER BY recorded_at_ms, stable_txn_id LIMIT ?",
        )
        .bind(i64::try_from(limit).map_err(|_| MatrixDurableError::Invalid)?)
        .fetch_all(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        rows.iter().map(from_row).collect()
    }
}

fn from_row(row: &SqliteRow) -> Result<OutboxUnresolvedRecord, MatrixDurableError> {
    let reason: String = row.try_get("reason").map_err(unavailable)?;
    let attempts = stored_u64(row.try_get("attempts").map_err(unavailable)?)?;
    if reason != "unknown_delivery" || attempts == 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(OutboxUnresolvedRecord {
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        attempts,
        recorded_at_ms: stored_u64(row.try_get("recorded_at_ms").map_err(unavailable)?)?,
    })
}

fn stored_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
