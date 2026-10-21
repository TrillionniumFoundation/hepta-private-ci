//! Durable scope quarantine preserves unknown Core and Matrix effect identity.
//! It does not cancel Core work, settle a send, or authorize a new generation.

use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::model::MAX_PAGE_ITEMS;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixRedactionQuarantine {
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub generation: u64,
    pub source_redaction_event_id: MatrixEventId,
    pub target_event_id: MatrixEventId,
    pub quarantined_at_ms: u64,
}

impl MatrixDurableStore {
    pub async fn is_scope_quarantined(
        &self,
        room_id: &MatrixRoomId,
        binding_revision: u64,
        generation: u64,
    ) -> Result<bool, MatrixDurableError> {
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let quarantined =
            is_scope_quarantined_tx(&mut transaction, room_id, binding_revision, generation)
                .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(quarantined)
    }

    /// Bounded operator observation; every returned scope remains quarantined.
    pub async fn redaction_quarantines(
        &self,
        limit: usize,
    ) -> Result<Vec<MatrixRedactionQuarantine>, MatrixDurableError> {
        if !(1..=MAX_PAGE_ITEMS).contains(&limit) {
            return Err(MatrixDurableError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT room_id, binding_revision, generation, source_redaction_event_id,
                    target_event_id, quarantined_at_ms
             FROM matrix_redaction_quarantines
             ORDER BY quarantined_at_ms, room_id, binding_revision, generation LIMIT ?",
        )
        .bind(i64::try_from(limit).map_err(|_| MatrixDurableError::Invalid)?)
        .fetch_all(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        rows.iter()
            .map(|row| {
                Ok(MatrixRedactionQuarantine {
                    room_id: MatrixRoomId::parse(
                        row.try_get::<String, _>("room_id").map_err(unavailable)?,
                    )
                    .map_err(|_| MatrixDurableError::Corrupt)?,
                    binding_revision: from_i64(
                        row.try_get("binding_revision").map_err(unavailable)?,
                    )?,
                    generation: from_i64(row.try_get("generation").map_err(unavailable)?)?,
                    source_redaction_event_id: MatrixEventId::parse(
                        row.try_get::<String, _>("source_redaction_event_id")
                            .map_err(unavailable)?,
                    )
                    .map_err(|_| MatrixDurableError::Corrupt)?,
                    target_event_id: MatrixEventId::parse(
                        row.try_get::<String, _>("target_event_id")
                            .map_err(unavailable)?,
                    )
                    .map_err(|_| MatrixDurableError::Corrupt)?,
                    quarantined_at_ms: from_i64(
                        row.try_get("quarantined_at_ms").map_err(unavailable)?,
                    )?,
                })
            })
            .collect()
    }
}

pub(crate) async fn is_scope_quarantined_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<bool, MatrixDurableError> {
    if binding_revision == 0 || generation == 0 {
        return Err(MatrixDurableError::Invalid);
    }
    let exists: i64 = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM matrix_redaction_quarantines
         WHERE room_id = ? AND binding_revision = ? AND generation = ?)",
    )
    .bind(room_id.as_str())
    .bind(i64::try_from(binding_revision).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(i64::try_from(generation).map_err(|_| MatrixDurableError::Invalid)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(exists == 1)
}

pub(crate) async fn quarantine_dispatched_redaction_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    mutation: &MatrixSyncMutationV2,
) -> Result<bool, MatrixDurableError> {
    let MatrixSyncMutationBodyV2::Redaction { target_event_id } = &mutation.body else {
        return Err(MatrixDurableError::Invalid);
    };
    let inserted = sqlx::query(
        "INSERT INTO matrix_redaction_quarantines (
            room_id, binding_revision, generation, source_redaction_event_id,
            target_event_id, reason_code, quarantined_at_ms
         ) VALUES (?, ?, ?, ?, ?, 'dispatched_source_redaction', ?)
         ON CONFLICT(room_id, binding_revision, generation) DO NOTHING",
    )
    .bind(mutation.room_id.as_str())
    .bind(i64::try_from(mutation.binding_revision).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(i64::try_from(mutation.generation).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(mutation.source_event_id.as_str())
    .bind(target_event_id.as_str())
    .bind(i64::try_from(mutation.received_at_ms).map_err(|_| MatrixDurableError::Invalid)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(inserted.rows_affected() == 1)
}

fn from_i64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_error: impl std::fmt::Display) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
