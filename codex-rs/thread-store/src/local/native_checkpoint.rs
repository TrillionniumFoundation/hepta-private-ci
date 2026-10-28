//! Authoritative pending-state sidecar of LocalThreadStore, never a history projection.
//! The existing live-writer lock owns all access. No effect or new lease is issued here.
//! This slice requires a materialized live thread and commits self-contained pending
//! bytes. It does not promise an atomic transaction with the separate rollout file.

use std::sync::Arc;

use futures::TryStreamExt;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::SqlitePool;

use super::LocalThreadStore;
use crate::NativeCheckpointBinding;
use crate::NativeCheckpointCurrentness;
use crate::NativeCheckpointExpected;
use crate::NativeCheckpointLoad;
use crate::NativeCheckpointOpenMode;
use crate::NativeCheckpointSession;
use crate::NativeCheckpointState;
use crate::NativeCheckpointVersion;
use crate::StoredNativeCheckpoint;
use crate::ThreadStore;
use crate::ThreadStoreError;
use crate::ThreadStoreResult;

const DATABASE: &str = "native-turn-checkpoints.sqlite";
const MAX_PAYLOAD: usize = 4 * 1024 * 1024;
const MAX_REVISIONS: u64 = 4096;

pub(super) async fn open(
    store: &LocalThreadStore,
    binding: NativeCheckpointBinding,
    mode: NativeCheckpointOpenMode,
    currentness: Arc<dyn NativeCheckpointCurrentness>,
) -> ThreadStoreResult<NativeCheckpointSession> {
    validate_binding(&binding)?;
    let _lifecycle = store
        .live_writer_locks
        .reserve_lifecycle(binding.thread_id)
        .await;
    let _writer = store.live_writer_locks.lock(binding.thread_id).await;
    let (rollout_path, rollout_id, writer_epoch) = {
        let entries = store.live_recorders.lock().await;
        let entry = entries
            .get(&binding.thread_id)
            .ok_or(ThreadStoreError::ThreadNotFound {
                thread_id: binding.thread_id,
            })?;
        (
            entry.recorder.rollout_path().to_path_buf(),
            entry.rollout_id,
            Arc::clone(entry.native_checkpoint_epoch.get_or_init(|| Arc::new(()))),
        )
    };
    let session = NativeCheckpointSession {
        binding,
        rollout_id,
        writer_epoch,
        currentness,
        mode,
    };
    if !tokio::fs::try_exists(rollout_path)
        .await
        .map_err(storage_error)?
    {
        return Err(conflict(
            "native checkpoint requires an already materialized live thread",
        ));
    }
    Ok(session)
}

pub(super) async fn load(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
) -> ThreadStoreResult<NativeCheckpointLoad> {
    let _lifecycle = store
        .live_writer_locks
        .reserve_lifecycle(session.binding.thread_id)
        .await;
    let _writer = store
        .live_writer_locks
        .lock(session.binding.thread_id)
        .await;
    verify_writer(store, session).await?;
    let pool = database(store, session.mode).await?;
    let mut connection = pool.acquire().await.map_err(storage_error)?;
    match read_chain(&mut connection, session).await? {
        Some(record) => Ok(NativeCheckpointLoad::Present(record)),
        None if session.mode == NativeCheckpointOpenMode::Create => {
            Ok(NativeCheckpointLoad::Missing)
        }
        None => Err(storage_error(
            "recovery checkpoint is missing; it is not new work",
        )),
    }
}

pub(super) async fn commit(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
    expected: NativeCheckpointExpected,
    state: NativeCheckpointState,
) -> ThreadStoreResult<StoredNativeCheckpoint> {
    let store = store.clone();
    let session = session.clone();
    // SQLx may finish an enqueued COMMIT after its receiver is dropped. Keep the
    // existing store and all its guards in an owner task through that outcome.
    tokio::spawn(async move { commit_owned(&store, &session, expected, state).await })
        .await
        .map_err(storage_error)?
}

async fn commit_owned(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
    expected: NativeCheckpointExpected,
    state: NativeCheckpointState,
) -> ThreadStoreResult<StoredNativeCheckpoint> {
    if state.binding != session.binding
        || state.payload.is_empty()
        || state.payload.len() > MAX_PAYLOAD
    {
        return Err(conflict(
            "checkpoint binding changed or payload exceeds its bound",
        ));
    }
    let _lifecycle = store
        .live_writer_locks
        .reserve_lifecycle(session.binding.thread_id)
        .await;
    let _writer = store
        .live_writer_locks
        .lock(session.binding.thread_id)
        .await;
    verify_writer(store, session).await?;
    // The host's actual guard, not a boolean, remains alive through COMMIT.
    // This never substitutes for the later physical-entry FinalUse check.
    let _permit = session.currentness.acquire(&session.binding).await?;
    let pool = database(store, session.mode).await?;
    let mut transaction = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(storage_error)?;
    let previous = read_chain(&mut transaction, session).await?;
    let previous_hash = match (&expected, &previous) {
        (NativeCheckpointExpected::Absent, None)
            if session.mode == NativeCheckpointOpenMode::Create =>
        {
            String::new()
        }
        (NativeCheckpointExpected::Version(expected), Some(previous))
            if expected == &previous.version =>
        {
            previous.version.sha256.clone()
        }
        _ => return Err(conflict("native checkpoint CAS head does not match")),
    };
    let revision = previous
        .as_ref()
        .map_or(1, |record| record.version.revision + 1);
    if revision > MAX_REVISIONS {
        return Err(conflict("native checkpoint revision budget exhausted"));
    }
    let binding_json = serde_json::to_string(&state.binding).map_err(storage_error)?;
    let rollout_id = session.rollout_id.to_string();
    let sha256 = record_hash(
        &binding_json,
        &rollout_id,
        revision,
        &previous_hash,
        &state.payload,
    );
    sqlx::query("INSERT INTO checkpoint_rows (thread_id, turn_id, revision, binding_json, rollout_id, previous_hash, record_hash, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
        .bind(state.binding.thread_id.to_string()).bind(&state.binding.turn_id)
        .bind(revision as i64).bind(&binding_json).bind(&rollout_id)
        .bind(&previous_hash).bind(&sha256).bind(&state.payload)
        .execute(&mut *transaction).await.map_err(storage_error)?;
    sqlx::query("INSERT INTO checkpoint_heads (thread_id, turn_id, revision, record_hash) VALUES (?, ?, ?, ?) ON CONFLICT(thread_id, turn_id) DO UPDATE SET revision=excluded.revision, record_hash=excluded.record_hash")
        .bind(state.binding.thread_id.to_string()).bind(&state.binding.turn_id)
        .bind(revision as i64).bind(&sha256)
        .execute(&mut *transaction).await.map_err(storage_error)?;
    transaction.commit().await.map_err(storage_error)?;
    Ok(StoredNativeCheckpoint {
        rollout_id: session.rollout_id,
        version: NativeCheckpointVersion { revision, sha256 },
        state,
    })
}

async fn verify_writer(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
) -> ThreadStoreResult<()> {
    {
        let entries = store.live_recorders.lock().await;
        let entry = entries
            .get(&session.binding.thread_id)
            .ok_or_else(|| conflict("native checkpoint writer is closed"))?;
        if entry.rollout_id != session.rollout_id
            || !entry
                .native_checkpoint_epoch
                .get()
                .is_some_and(|epoch| Arc::ptr_eq(epoch, &session.writer_epoch))
        {
            return Err(conflict(
                "native checkpoint writer instance or rollout changed",
            ));
        }
    }
    if store
        .is_thread_hard_delete_fenced(session.binding.thread_id)
        .await?
    {
        return Err(conflict("native checkpoint thread is fenced for deletion"));
    }
    Ok(())
}

async fn database(
    store: &LocalThreadStore,
    mode: NativeCheckpointOpenMode,
) -> ThreadStoreResult<&SqlitePool> {
    let path = store.config.codex_home.join(DATABASE);
    let exists = tokio::fs::try_exists(&path).await.map_err(storage_error)?;
    if !exists
        && (mode == NativeCheckpointOpenMode::Recover || store.native_checkpoint_db.get().is_some())
    {
        return Err(storage_error(
            "native checkpoint database is missing; refusing recreation",
        ));
    }
    store.native_checkpoint_db.get_or_try_init(|| async {
        // Exclusive creation distinguishes a new DB from an empty/corrupt existing one.
        // Interrupted initialization remains an error, never an automatic fresh start.
        let initialize = if exists {
            false
        } else {
            match tokio::fs::OpenOptions::new().read(true).write(true).create_new(true).open(&path).await {
                Ok(file) => { drop(file); true }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => false,
                Err(error) => return Err(storage_error(error)),
            }
        };
        let pool = store.config.sqlite.open_durable_evidence_pool(&path).await.map_err(storage_error)?;
        if initialize {
            let mut transaction = pool.begin().await.map_err(storage_error)?;
            sqlx::query("CREATE TABLE checkpoint_rows (thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), binding_json TEXT NOT NULL, rollout_id TEXT NOT NULL, previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL CHECK(length(record_hash)=64), payload BLOB NOT NULL, PRIMARY KEY(thread_id, turn_id, revision))")
                .execute(&mut *transaction).await.map_err(storage_error)?;
            sqlx::query("CREATE TABLE checkpoint_heads (thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), record_hash TEXT NOT NULL CHECK(length(record_hash)=64), PRIMARY KEY(thread_id, turn_id))")
                .execute(&mut *transaction).await.map_err(storage_error)?;
            sqlx::query("PRAGMA user_version=1").execute(&mut *transaction).await.map_err(storage_error)?;
            transaction.commit().await.map_err(storage_error)?;
        }
        let version: i64 = sqlx::query_scalar("PRAGMA user_version").fetch_one(&pool).await.map_err(storage_error)?;
        if version != 1 {
            pool.close().await;
            return Err(storage_error("unknown or incomplete native checkpoint database schema"));
        }
        Ok(pool)
    }).await
}

async fn read_chain(
    connection: &mut SqliteConnection,
    session: &NativeCheckpointSession,
) -> ThreadStoreResult<Option<StoredNativeCheckpoint>> {
    let integrity: Vec<String> = sqlx::query_scalar("PRAGMA quick_check(1)")
        .fetch_all(&mut *connection)
        .await
        .map_err(storage_error)?;
    if integrity.len() != 1 || integrity[0] != "ok" {
        return Err(storage_error(
            "native checkpoint SQLite integrity check failed",
        ));
    }
    let head: Option<(i64, String)> = sqlx::query_as(
        "SELECT revision, record_hash FROM checkpoint_heads WHERE thread_id=? AND turn_id=?",
    )
    .bind(session.binding.thread_id.to_string())
    .bind(&session.binding.turn_id)
    .fetch_optional(&mut *connection)
    .await
    .map_err(storage_error)?;
    let mut rows = sqlx::query("SELECT revision, binding_json, rollout_id, previous_hash, record_hash, length(payload) AS payload_len, substr(payload,1,4194305) AS payload FROM checkpoint_rows WHERE thread_id=? AND turn_id=? ORDER BY revision")
        .bind(session.binding.thread_id.to_string()).bind(&session.binding.turn_id).fetch(&mut *connection);
    let mut latest: Option<StoredNativeCheckpoint> = None;
    let mut expected_revision = 1_u64;
    let mut expected_hash = String::new();
    while let Some(row) = rows.try_next().await.map_err(storage_error)? {
        let revision: i64 = row.try_get("revision").map_err(storage_error)?;
        let binding_json: String = row.try_get("binding_json").map_err(storage_error)?;
        let rollout_id: String = row.try_get("rollout_id").map_err(storage_error)?;
        let previous_hash: String = row.try_get("previous_hash").map_err(storage_error)?;
        let sha256: String = row.try_get("record_hash").map_err(storage_error)?;
        let payload: Vec<u8> = row.try_get("payload").map_err(storage_error)?;
        let payload_len: i64 = row.try_get("payload_len").map_err(storage_error)?;
        let binding: NativeCheckpointBinding =
            serde_json::from_str(&binding_json).map_err(storage_error)?;
        validate_binding(&binding).map_err(storage_error)?;
        if revision != expected_revision as i64
            || expected_revision > MAX_REVISIONS
            || previous_hash != expected_hash
            || payload.is_empty()
            || payload.len() > MAX_PAYLOAD
            || payload_len != payload.len() as i64
            || serde_json::to_string(&binding).map_err(storage_error)? != binding_json
            || record_hash(
                &binding_json,
                &rollout_id,
                expected_revision,
                &previous_hash,
                &payload,
            ) != sha256
        {
            return Err(storage_error(
                "native checkpoint chain or payload is corrupt",
            ));
        }
        if binding != session.binding || rollout_id != session.rollout_id.to_string() {
            return Err(conflict(
                "native checkpoint original binding or rollout does not match",
            ));
        }
        expected_hash = sha256.clone();
        latest = Some(StoredNativeCheckpoint {
            rollout_id: session.rollout_id,
            version: NativeCheckpointVersion {
                revision: expected_revision,
                sha256,
            },
            state: NativeCheckpointState { binding, payload },
        });
        expected_revision += 1;
    }
    match (&head, &latest) {
        (None, None) => {}
        (Some((revision, hash)), Some(record))
            if *revision == record.version.revision as i64 && hash == &record.version.sha256 => {}
        _ => {
            return Err(storage_error(
                "native checkpoint head is missing or does not match its chain",
            ));
        }
    }
    Ok(latest)
}

fn record_hash(
    binding: &str,
    rollout_id: &str,
    revision: u64,
    previous_hash: &str,
    payload: &[u8],
) -> String {
    let mut hash = Sha256::new();
    hash.update(b"hepta:thread-store:native-checkpoint:v1\0");
    hash.update(revision.to_be_bytes());
    for bytes in [
        binding.as_bytes(),
        rollout_id.as_bytes(),
        previous_hash.as_bytes(),
        payload,
    ] {
        hash.update((bytes.len() as u64).to_be_bytes());
        hash.update(bytes);
    }
    let digest = hash.finalize();
    format!("{digest:x}")
}

fn validate_binding(binding: &NativeCheckpointBinding) -> ThreadStoreResult<()> {
    if binding.generation == 0
        || [&binding.turn_id, &binding.operation_id, &binding.lease_id]
            .iter()
            .any(|value| value.is_empty() || value.len() > 512)
    {
        return Err(conflict(
            "native checkpoint requires bounded original identities and nonzero generation",
        ));
    }
    Ok(())
}

fn conflict(message: &str) -> ThreadStoreError {
    ThreadStoreError::Conflict {
        message: message.to_string(),
    }
}

fn storage_error(error: impl std::fmt::Display) -> ThreadStoreError {
    ThreadStoreError::Internal {
        message: format!("native checkpoint storage: {error}"),
    }
}

#[cfg(test)]
#[path = "native_checkpoint_tests.rs"]
mod tests;
