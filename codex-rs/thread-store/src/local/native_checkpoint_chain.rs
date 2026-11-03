//! Bounded observation of the complete original checkpoint chain.
//! No new database, currentness permit, checkpoint, or execution grant is created.

use super::*;

const MAX_CHAIN_BYTES: u64 = 64 * 1024 * 1024;

pub(in crate::local) async fn load(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
) -> ThreadStoreResult<Vec<StoredNativeCheckpoint>> {
    let _lifecycle = store
        .live_writer_locks
        .reserve_lifecycle(session.binding.thread_id)
        .await;
    let _writer = store.live_writer_locks.lock(session.binding.thread_id).await;
    verify_writer(store, session).await?;
    if !tokio::fs::try_exists(store.config.codex_home.join(DATABASE))
        .await.map_err(storage_error)?
    {
        if store.native_checkpoint_db.get().is_some() {
            return Err(storage_error("native checkpoint database disappeared during chain observation"));
        }
        if session.mode == NativeCheckpointOpenMode::Inspect {
            return Ok(Vec::new());
        }
        return Err(storage_error("checkpoint chain observation cannot create a missing database"));
    }
    // Even a Create session is read-only here; only the existing commit API may
    // create storage. A single SQLite snapshot covers the byte preflight and rows.
    let pool = database(store, NativeCheckpointOpenMode::Inspect).await?;
    let mut transaction = pool.begin().await.map_err(storage_error)?;
    let records = read_bounded(&mut transaction, session, MAX_REVISIONS, MAX_CHAIN_BYTES).await?;
    transaction.commit().await.map_err(storage_error)?;
    if records.is_empty() && session.mode == NativeCheckpointOpenMode::Recover {
        return Err(storage_error("recovery checkpoint is missing; it is not new work"));
    }
    Ok(records)
}

pub(super) async fn read_bounded(
    connection: &mut SqliteConnection,
    session: &NativeCheckpointSession,
    max_revisions: u64,
    max_bytes: u64,
) -> ThreadStoreResult<Vec<StoredNativeCheckpoint>> {
    // SQLite length(TEXT) counts characters. CAST AS BLOB counts the actual
    // UTF-8 bytes, including all identity/hash fields that the reader loads.
    let (count, bytes): (i64, i64) = sqlx::query_as(
        "SELECT COUNT(*), COALESCE(SUM(
            length(CAST(binding_json AS BLOB)) + length(CAST(rollout_id AS BLOB)) +
            length(CAST(previous_hash AS BLOB)) + length(CAST(record_hash AS BLOB)) +
            length(CAST(payload AS BLOB)) + 8), 0)
         FROM checkpoint_rows WHERE thread_id = ? AND turn_id = ?",
    )
    .bind(session.binding.thread_id.to_string()).bind(&session.binding.turn_id)
    .fetch_one(&mut *connection).await.map_err(storage_error)?;
    let head_bytes: Option<i64> = sqlx::query_scalar(
        "SELECT length(CAST(record_hash AS BLOB)) + 8 FROM checkpoint_heads WHERE thread_id = ? AND turn_id = ?",
    ).bind(session.binding.thread_id.to_string()).bind(&session.binding.turn_id)
        .fetch_optional(&mut *connection).await.map_err(storage_error)?;
    let bytes = bytes.checked_add(head_bytes.unwrap_or(0)).ok_or_else(|| {
        storage_error("native checkpoint chain byte count overflow")
    })?;
    if count < 0 || bytes < 0 || count as u64 > max_revisions || bytes as u64 > max_bytes {
        return Err(storage_error("complete native checkpoint chain exceeds its bounded read budget"));
    }
    let mut records = Vec::new();
    read_chain_collect(connection, session, Some(&mut records)).await?;
    if records.len() as u64 != count as u64 {
        return Err(storage_error("native checkpoint chain changed during observation"));
    }
    Ok(records)
}
