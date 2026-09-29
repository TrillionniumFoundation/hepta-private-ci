#!/usr/bin/env python3
"""Install a durable, leased runtime.codex thread-cleanup obligation queue."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and migrated marker both absent")


def write_store() -> None:
    target = ROOT / "codex-rs/hepta-infer-worker-host/src/native_cleanup_store.rs"
    if target.exists() and "pub(crate) struct NativeCleanupStore" in target.read_text(encoding="utf-8"):
        return
    target.write_text(r'''//! Durable obligations for App Server ephemeral-thread cleanup.
//!
//! A row is created immediately after thread/start is observed. Before the
//! physical turn effect becomes possible the row is moved to `effect_possible`;
//! recovery never unsubscribes that state. Only a proved pre-effect stop or a
//! durably committed terminal/rejection makes an obligation cleanable.

use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

const CLEANUP_STORE_SCHEMA_VERSION: i64 = 1;
const MAX_CLEANUP_OBLIGATIONS: i64 = 65_536;
const MAX_CLEANUP_BATCH: usize = 32;
const MAX_CLEANUP_ATTEMPTS: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CleanupState {
    Prepared,
    EffectPossible,
    TerminalDurable,
}

impl CleanupState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::EffectPossible => "effect_possible",
            Self::TerminalDurable => "terminal_durable",
        }
    }

    fn parse(value: &str) -> Result<Self, NativeCleanupStoreError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "effect_possible" => Ok(Self::EffectPossible),
            "terminal_durable" => Ok(Self::TerminalDurable),
            _ => Err(NativeCleanupStoreError::Corrupt(format!(
                "invalid cleanup state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CleanupObligation {
    pub(crate) operation_id: String,
    pub(crate) thread_id: String,
    pub(crate) session_id: String,
    pub(crate) revision: u64,
    pub(crate) state: CleanupState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CleanupClaim {
    pub(crate) operation_id: String,
    pub(crate) thread_id: String,
    pub(crate) revision: u64,
    pub(crate) fence: u64,
    pub(crate) worker_id: String,
    resume_state: CleanupState,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeCleanupBacklogMetrics {
    pub pending_pre_effect: u64,
    pub unknown_history_retained: u64,
    pub terminal_cleanup_pending: u64,
    pub actively_cleaning: u64,
    pub oldest_pending_age_ms: u64,
}

#[derive(Debug)]
pub(crate) enum NativeCleanupStoreError {
    Invalid(&'static str),
    Conflict(String),
    Capacity,
    Unavailable(String),
    Corrupt(String),
}

impl fmt::Display for NativeCleanupStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NativeCleanupStoreError {}

#[derive(Clone)]
pub(crate) struct NativeCleanupStore {
    pool: SqlitePool,
    path: PathBuf,
    owner_id: String,
    owner_generation: u64,
}

impl fmt::Debug for NativeCleanupStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeCleanupStore")
            .field("path", &self.path)
            .field("owner_id", &self.owner_id)
            .field("owner_generation", &self.owner_generation)
            .finish_non_exhaustive()
    }
}

impl NativeCleanupStore {
    pub(crate) async fn open(
        path: &Path,
        owner_id: String,
        owner_generation: u64,
    ) -> Result<Self, NativeCleanupStoreError> {
        if !path.is_absolute()
            || owner_id.is_empty()
            || owner_id.len() > 128
            || owner_generation == 0
        {
            return Err(NativeCleanupStoreError::Invalid("cleanup store identity"));
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| {
                NativeCleanupStoreError::Unavailable(format!(
                    "create cleanup store parent: {error}"
                ))
            })?;
        }
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(cleanup_sqlx)?;
        let store = Self {
            pool,
            path: path.to_path_buf(),
            owner_id,
            owner_generation,
        };
        if let Err(error) = store.initialize().await {
            store.pool.close().await;
            return Err(error);
        }
        Ok(store)
    }

    async fn initialize(&self) -> Result<(), NativeCleanupStoreError> {
        let quick: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(&self.pool)
            .await
            .map_err(cleanup_sqlx)?;
        if quick != "ok" {
            return Err(NativeCleanupStoreError::Corrupt(format!(
                "cleanup quick_check: {quick}"
            )));
        }
        for statement in [
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_cleanup_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                owner_id TEXT NOT NULL,
                owner_generation INTEGER NOT NULL,
                store_revision INTEGER NOT NULL CHECK (store_revision > 0)
            ) STRICT"#,
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_cleanup_obligations (
                operation_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('prepared', 'effect_possible', 'terminal_durable', 'cleaning')),
                resume_state TEXT CHECK (resume_state IN ('prepared', 'terminal_durable')),
                revision INTEGER NOT NULL CHECK (revision > 0),
                fence INTEGER NOT NULL CHECK (fence >= 0),
                attempts INTEGER NOT NULL CHECK (attempts >= 0),
                worker_id TEXT,
                lease_until_ms INTEGER,
                last_error TEXT,
                created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
                updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
                CHECK ((state = 'cleaning') = (resume_state IS NOT NULL)),
                CHECK ((state = 'cleaning') = (worker_id IS NOT NULL)),
                CHECK ((state = 'cleaning') = (lease_until_ms IS NOT NULL))
            ) STRICT"#,
            "CREATE INDEX IF NOT EXISTS runtime_codex_cleanup_ready_idx ON runtime_codex_cleanup_obligations(state, updated_at_ms, operation_id)",
            "CREATE INDEX IF NOT EXISTS runtime_codex_cleanup_lease_idx ON runtime_codex_cleanup_obligations(state, lease_until_ms)",
        ] {
            sqlx::query(statement)
                .execute(&self.pool)
                .await
                .map_err(cleanup_sqlx)?;
        }
        let generation = cleanup_i64(self.owner_generation, "owner generation")?;
        sqlx::query(
            r#"INSERT OR IGNORE INTO runtime_codex_cleanup_meta
               (singleton, schema_version, owner_id, owner_generation, store_revision)
               VALUES (1, ?, ?, ?, 1)"#,
        )
        .bind(CLEANUP_STORE_SCHEMA_VERSION)
        .bind(&self.owner_id)
        .bind(generation)
        .execute(&self.pool)
        .await
        .map_err(cleanup_sqlx)?;
        let row = sqlx::query(
            "SELECT schema_version, owner_id, owner_generation, store_revision FROM runtime_codex_cleanup_meta WHERE singleton = 1",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(cleanup_sqlx)?;
        let schema: i64 = row.try_get("schema_version").map_err(cleanup_sqlx)?;
        let owner: String = row.try_get("owner_id").map_err(cleanup_sqlx)?;
        let persisted_generation: i64 = row.try_get("owner_generation").map_err(cleanup_sqlx)?;
        let revision: i64 = row.try_get("store_revision").map_err(cleanup_sqlx)?;
        if schema != CLEANUP_STORE_SCHEMA_VERSION
            || owner != self.owner_id
            || persisted_generation != generation
            || revision <= 0
        {
            return Err(NativeCleanupStoreError::Corrupt(
                "cleanup store identity mismatch".to_string(),
            ));
        }
        self.recover_expired(cleanup_now_ms()?).await?;
        Ok(())
    }

    pub(crate) async fn enqueue(
        &self,
        operation_id: String,
        thread_id: String,
        session_id: String,
    ) -> Result<CleanupObligation, NativeCleanupStoreError> {
        validate_cleanup_id(&operation_id)?;
        validate_cleanup_id(&thread_id)?;
        validate_cleanup_id(&session_id)?;
        let now = cleanup_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        if let Some(existing) = load_obligation(&mut tx, &operation_id).await? {
            if existing.thread_id != thread_id || existing.session_id != session_id {
                return Err(NativeCleanupStoreError::Conflict(format!(
                    "cleanup operation {operation_id} is already bound to another thread"
                )));
            }
            tx.commit().await.map_err(cleanup_sqlx)?;
            return Ok(existing);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM runtime_codex_cleanup_obligations")
            .fetch_one(&mut *tx)
            .await
            .map_err(cleanup_sqlx)?;
        if count >= MAX_CLEANUP_OBLIGATIONS {
            return Err(NativeCleanupStoreError::Capacity);
        }
        sqlx::query(
            r#"INSERT INTO runtime_codex_cleanup_obligations
               (operation_id, thread_id, session_id, state, revision, fence, attempts, created_at_ms, updated_at_ms)
               VALUES (?, ?, ?, 'prepared', 1, 0, 0, ?, ?)"#,
        )
        .bind(&operation_id)
        .bind(&thread_id)
        .bind(&session_id)
        .bind(cleanup_i64(now, "created time")?)
        .bind(cleanup_i64(now, "updated time")?)
        .execute(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        advance_cleanup_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(CleanupObligation {
            operation_id,
            thread_id,
            session_id,
            revision: 1,
            state: CleanupState::Prepared,
        })
    }

    pub(crate) async fn mark_effect_possible(
        &self,
        obligation: &CleanupObligation,
    ) -> Result<CleanupObligation, NativeCleanupStoreError> {
        self.transition(obligation, CleanupState::EffectPossible).await
    }

    pub(crate) async fn mark_terminal_durable(
        &self,
        obligation: &CleanupObligation,
    ) -> Result<CleanupObligation, NativeCleanupStoreError> {
        self.transition(obligation, CleanupState::TerminalDurable).await
    }

    async fn transition(
        &self,
        obligation: &CleanupObligation,
        target: CleanupState,
    ) -> Result<CleanupObligation, NativeCleanupStoreError> {
        let legal = matches!(
            (obligation.state, target),
            (CleanupState::Prepared, CleanupState::EffectPossible)
                | (CleanupState::Prepared, CleanupState::TerminalDurable)
                | (CleanupState::EffectPossible, CleanupState::TerminalDurable)
        );
        if !legal {
            if obligation.state == target {
                return Ok(obligation.clone());
            }
            return Err(NativeCleanupStoreError::Conflict(format!(
                "illegal cleanup transition {:?} -> {:?}",
                obligation.state, target
            )));
        }
        let next = obligation
            .revision
            .checked_add(1)
            .ok_or(NativeCleanupStoreError::Capacity)?;
        let now = cleanup_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let rows = sqlx::query(
            r#"UPDATE runtime_codex_cleanup_obligations
               SET state = ?, revision = ?, updated_at_ms = ?
               WHERE operation_id = ? AND revision = ? AND state = ?"#,
        )
        .bind(target.as_str())
        .bind(cleanup_i64(next, "next cleanup revision")?)
        .bind(cleanup_i64(now, "updated time")?)
        .bind(&obligation.operation_id)
        .bind(cleanup_i64(obligation.revision, "expected cleanup revision")?)
        .bind(obligation.state.as_str())
        .execute(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        if rows.rows_affected() != 1 {
            return Err(NativeCleanupStoreError::Conflict(
                "cleanup transition CAS failed".to_string(),
            ));
        }
        advance_cleanup_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(CleanupObligation {
            operation_id: obligation.operation_id.clone(),
            thread_id: obligation.thread_id.clone(),
            session_id: obligation.session_id.clone(),
            revision: next,
            state: target,
        })
    }

    pub(crate) async fn claim_exact(
        &self,
        obligation: &CleanupObligation,
        worker_id: String,
        lease: Duration,
    ) -> Result<Option<CleanupClaim>, NativeCleanupStoreError> {
        validate_cleanup_id(&worker_id)?;
        let now = cleanup_now_ms()?;
        let lease_until = now
            .checked_add(u64::try_from(lease.as_millis()).map_err(|_| NativeCleanupStoreError::Capacity)?)
            .ok_or(NativeCleanupStoreError::Capacity)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        recover_expired_tx(&mut tx, now).await?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let Some(current) = load_obligation(&mut tx, &obligation.operation_id).await? else {
            tx.commit().await.map_err(cleanup_sqlx)?;
            return Ok(None);
        };
        if current.revision != obligation.revision
            || current.thread_id != obligation.thread_id
            || current.session_id != obligation.session_id
        {
            return Err(NativeCleanupStoreError::Conflict(
                "cleanup exact claim binding changed".to_string(),
            ));
        }
        if !matches!(current.state, CleanupState::Prepared | CleanupState::TerminalDurable) {
            tx.commit().await.map_err(cleanup_sqlx)?;
            return Ok(None);
        }
        let row = sqlx::query(
            "SELECT fence, attempts FROM runtime_codex_cleanup_obligations WHERE operation_id = ?",
        )
        .bind(&current.operation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        let fence = cleanup_u64(row.try_get::<i64, _>("fence").map_err(cleanup_sqlx)?, "cleanup fence")?
            .checked_add(1)
            .ok_or(NativeCleanupStoreError::Capacity)?;
        let attempts = cleanup_u32(row.try_get::<i64, _>("attempts").map_err(cleanup_sqlx)?, "cleanup attempts")?;
        if attempts >= MAX_CLEANUP_ATTEMPTS {
            return Err(NativeCleanupStoreError::Capacity);
        }
        let next_revision = current.revision.checked_add(1).ok_or(NativeCleanupStoreError::Capacity)?;
        let rows = sqlx::query(
            r#"UPDATE runtime_codex_cleanup_obligations
               SET state = 'cleaning', resume_state = ?, revision = ?, fence = ?, attempts = ?,
                   worker_id = ?, lease_until_ms = ?, last_error = NULL, updated_at_ms = ?
               WHERE operation_id = ? AND revision = ? AND state = ?"#,
        )
        .bind(current.state.as_str())
        .bind(cleanup_i64(next_revision, "claimed cleanup revision")?)
        .bind(cleanup_i64(fence, "cleanup fence")?)
        .bind(i64::from(attempts + 1))
        .bind(&worker_id)
        .bind(cleanup_i64(lease_until, "cleanup lease")?)
        .bind(cleanup_i64(now, "updated time")?)
        .bind(&current.operation_id)
        .bind(cleanup_i64(current.revision, "expected cleanup revision")?)
        .bind(current.state.as_str())
        .execute(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        if rows.rows_affected() != 1 {
            return Err(NativeCleanupStoreError::Conflict(
                "cleanup claim CAS failed".to_string(),
            ));
        }
        advance_cleanup_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(Some(CleanupClaim {
            operation_id: current.operation_id,
            thread_id: current.thread_id,
            revision: next_revision,
            fence,
            worker_id,
            resume_state: current.state,
        }))
    }

    pub(crate) async fn claim_ready(
        &self,
        worker_id: String,
        lease: Duration,
        limit: usize,
    ) -> Result<Vec<CleanupClaim>, NativeCleanupStoreError> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let limit = limit.min(MAX_CLEANUP_BATCH);
        let rows = sqlx::query(
            r#"SELECT operation_id FROM runtime_codex_cleanup_obligations
               WHERE state IN ('prepared', 'terminal_durable')
               ORDER BY updated_at_ms, operation_id LIMIT ?"#,
        )
        .bind(i64::try_from(limit).map_err(|_| NativeCleanupStoreError::Capacity)?)
        .fetch_all(&self.pool)
        .await
        .map_err(cleanup_sqlx)?;
        let mut claims = Vec::with_capacity(rows.len());
        for row in rows {
            let operation_id: String = row.try_get("operation_id").map_err(cleanup_sqlx)?;
            let Some(obligation) = self.obligation(&operation_id).await? else {
                continue;
            };
            if let Some(claim) = self
                .claim_exact(&obligation, worker_id.clone(), lease)
                .await?
            {
                claims.push(claim);
            }
        }
        Ok(claims)
    }

    pub(crate) async fn complete(
        &self,
        claim: &CleanupClaim,
    ) -> Result<(), NativeCleanupStoreError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let rows = sqlx::query(
            r#"DELETE FROM runtime_codex_cleanup_obligations
               WHERE operation_id = ? AND state = 'cleaning' AND revision = ? AND fence = ? AND worker_id = ?"#,
        )
        .bind(&claim.operation_id)
        .bind(cleanup_i64(claim.revision, "cleanup revision")?)
        .bind(cleanup_i64(claim.fence, "cleanup fence")?)
        .bind(&claim.worker_id)
        .execute(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        if rows.rows_affected() != 1 {
            return Err(NativeCleanupStoreError::Conflict(
                "cleanup completion CAS failed".to_string(),
            ));
        }
        advance_cleanup_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(())
    }

    pub(crate) async fn fail(
        &self,
        claim: &CleanupClaim,
        error: &str,
    ) -> Result<(), NativeCleanupStoreError> {
        let next = claim.revision.checked_add(1).ok_or(NativeCleanupStoreError::Capacity)?;
        let now = cleanup_now_ms()?;
        let error: String = error.chars().take(512).collect();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let rows = sqlx::query(
            r#"UPDATE runtime_codex_cleanup_obligations
               SET state = ?, resume_state = NULL, revision = ?, worker_id = NULL,
                   lease_until_ms = NULL, last_error = ?, updated_at_ms = ?
               WHERE operation_id = ? AND state = 'cleaning' AND revision = ? AND fence = ? AND worker_id = ?"#,
        )
        .bind(claim.resume_state.as_str())
        .bind(cleanup_i64(next, "failed cleanup revision")?)
        .bind(error)
        .bind(cleanup_i64(now, "updated time")?)
        .bind(&claim.operation_id)
        .bind(cleanup_i64(claim.revision, "cleanup revision")?)
        .bind(cleanup_i64(claim.fence, "cleanup fence")?)
        .bind(&claim.worker_id)
        .execute(&mut *tx)
        .await
        .map_err(cleanup_sqlx)?;
        if rows.rows_affected() != 1 {
            return Err(NativeCleanupStoreError::Conflict(
                "cleanup failure CAS failed".to_string(),
            ));
        }
        advance_cleanup_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(())
    }

    pub(crate) async fn obligation(
        &self,
        operation_id: &str,
    ) -> Result<Option<CleanupObligation>, NativeCleanupStoreError> {
        let mut connection = self.pool.acquire().await.map_err(cleanup_sqlx)?;
        load_obligation_connection(&mut connection, operation_id).await
    }

    pub(crate) async fn metrics(&self) -> Result<NativeCleanupBacklogMetrics, NativeCleanupStoreError> {
        let row = sqlx::query(
            r#"SELECT
                SUM(CASE WHEN state = 'prepared' THEN 1 ELSE 0 END) AS prepared,
                SUM(CASE WHEN state = 'effect_possible' THEN 1 ELSE 0 END) AS effect_possible,
                SUM(CASE WHEN state = 'terminal_durable' THEN 1 ELSE 0 END) AS terminal_durable,
                SUM(CASE WHEN state = 'cleaning' THEN 1 ELSE 0 END) AS cleaning,
                MIN(created_at_ms) AS oldest
               FROM runtime_codex_cleanup_obligations"#,
        )
        .fetch_one(&self.pool)
        .await
        .map_err(cleanup_sqlx)?;
        let now = cleanup_now_ms()?;
        let count = |name: &str| -> Result<u64, NativeCleanupStoreError> {
            let value: Option<i64> = row.try_get(name).map_err(cleanup_sqlx)?;
            cleanup_u64(value.unwrap_or(0), "cleanup metric")
        };
        let oldest: Option<i64> = row.try_get("oldest").map_err(cleanup_sqlx)?;
        let oldest_pending_age_ms = oldest
            .map(|value| cleanup_u64(value, "oldest cleanup time"))
            .transpose()?
            .map_or(0, |value| now.saturating_sub(value));
        Ok(NativeCleanupBacklogMetrics {
            pending_pre_effect: count("prepared")?,
            unknown_history_retained: count("effect_possible")?,
            terminal_cleanup_pending: count("terminal_durable")?,
            actively_cleaning: count("cleaning")?,
            oldest_pending_age_ms,
        })
    }

    async fn recover_expired(&self, now: u64) -> Result<(), NativeCleanupStoreError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(cleanup_sqlx)?;
        let store_revision = cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let changed = recover_expired_tx(&mut tx, now).await?;
        if changed != 0 {
            advance_cleanup_store_revision(&mut tx, store_revision).await?;
        }
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(())
    }
}

async fn load_obligation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<CleanupObligation>, NativeCleanupStoreError> {
    let row = sqlx::query(
        "SELECT operation_id, thread_id, session_id, state, revision FROM runtime_codex_cleanup_obligations WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(cleanup_sqlx)?;
    row.map(decode_obligation).transpose()
}

async fn load_obligation_connection(
    connection: &mut sqlx::pool::PoolConnection<Sqlite>,
    operation_id: &str,
) -> Result<Option<CleanupObligation>, NativeCleanupStoreError> {
    let row = sqlx::query(
        "SELECT operation_id, thread_id, session_id, state, revision FROM runtime_codex_cleanup_obligations WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **connection)
    .await
    .map_err(cleanup_sqlx)?;
    row.map(decode_obligation).transpose()
}

fn decode_obligation(row: sqlx::sqlite::SqliteRow) -> Result<CleanupObligation, NativeCleanupStoreError> {
    let state: String = row.try_get("state").map_err(cleanup_sqlx)?;
    if state == "cleaning" {
        return Err(NativeCleanupStoreError::Conflict(
            "cleanup obligation is currently leased".to_string(),
        ));
    }
    Ok(CleanupObligation {
        operation_id: row.try_get("operation_id").map_err(cleanup_sqlx)?,
        thread_id: row.try_get("thread_id").map_err(cleanup_sqlx)?,
        session_id: row.try_get("session_id").map_err(cleanup_sqlx)?,
        revision: cleanup_u64(row.try_get::<i64, _>("revision").map_err(cleanup_sqlx)?, "cleanup revision")?,
        state: CleanupState::parse(&state)?,
    })
}

async fn recover_expired_tx(
    tx: &mut Transaction<'_, Sqlite>,
    now: u64,
) -> Result<u64, NativeCleanupStoreError> {
    let rows = sqlx::query(
        r#"UPDATE runtime_codex_cleanup_obligations
           SET state = resume_state, resume_state = NULL, revision = revision + 1,
               worker_id = NULL, lease_until_ms = NULL,
               last_error = 'cleanup lease expired', updated_at_ms = ?
           WHERE state = 'cleaning' AND lease_until_ms <= ?"#,
    )
    .bind(cleanup_i64(now, "recovery time")?)
    .bind(cleanup_i64(now, "recovery deadline")?)
    .execute(&mut **tx)
    .await
    .map_err(cleanup_sqlx)?;
    Ok(rows.rows_affected())
}

async fn cleanup_store_revision(
    tx: &mut Transaction<'_, Sqlite>,
    owner_id: &str,
    owner_generation: u64,
) -> Result<u64, NativeCleanupStoreError> {
    let row = sqlx::query(
        "SELECT schema_version, owner_id, owner_generation, store_revision FROM runtime_codex_cleanup_meta WHERE singleton = 1",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(cleanup_sqlx)?;
    let schema: i64 = row.try_get("schema_version").map_err(cleanup_sqlx)?;
    let owner: String = row.try_get("owner_id").map_err(cleanup_sqlx)?;
    let generation: i64 = row.try_get("owner_generation").map_err(cleanup_sqlx)?;
    if schema != CLEANUP_STORE_SCHEMA_VERSION
        || owner != owner_id
        || generation != cleanup_i64(owner_generation, "owner generation")?
    {
        return Err(NativeCleanupStoreError::Conflict(
            "cleanup store owner fence changed".to_string(),
        ));
    }
    cleanup_u64(row.try_get::<i64, _>("store_revision").map_err(cleanup_sqlx)?, "store revision")
}

async fn advance_cleanup_store_revision(
    tx: &mut Transaction<'_, Sqlite>,
    expected: u64,
) -> Result<(), NativeCleanupStoreError> {
    let next = expected.checked_add(1).ok_or(NativeCleanupStoreError::Capacity)?;
    let rows = sqlx::query(
        "UPDATE runtime_codex_cleanup_meta SET store_revision = ? WHERE singleton = 1 AND store_revision = ?",
    )
    .bind(cleanup_i64(next, "next store revision")?)
    .bind(cleanup_i64(expected, "expected store revision")?)
    .execute(&mut **tx)
    .await
    .map_err(cleanup_sqlx)?;
    if rows.rows_affected() != 1 {
        return Err(NativeCleanupStoreError::Conflict(
            "cleanup store revision CAS failed".to_string(),
        ));
    }
    Ok(())
}

fn validate_cleanup_id(value: &str) -> Result<(), NativeCleanupStoreError> {
    if value.is_empty() || value.len() > 256 || value.as_bytes().contains(&0) {
        Err(NativeCleanupStoreError::Invalid("cleanup identity"))
    } else {
        Ok(())
    }
}

fn cleanup_now_ms() -> Result<u64, NativeCleanupStoreError> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| NativeCleanupStoreError::Unavailable("clock precedes Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(value).map_err(|_| NativeCleanupStoreError::Capacity)
}

fn cleanup_i64(value: u64, label: &'static str) -> Result<i64, NativeCleanupStoreError> {
    i64::try_from(value)
        .map_err(|_| NativeCleanupStoreError::Corrupt(format!("{label} exceeds SQLite i64")))
}

fn cleanup_u64(value: i64, label: &'static str) -> Result<u64, NativeCleanupStoreError> {
    u64::try_from(value)
        .map_err(|_| NativeCleanupStoreError::Corrupt(format!("{label} is negative")))
}

fn cleanup_u32(value: i64, label: &'static str) -> Result<u32, NativeCleanupStoreError> {
    u32::try_from(value)
        .map_err(|_| NativeCleanupStoreError::Corrupt(format!("{label} is out of range")))
}

fn cleanup_sqlx(error: sqlx::Error) -> NativeCleanupStoreError {
    NativeCleanupStoreError::Unavailable(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn durable_states_and_leases_survive_reopen() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("cleanup.sqlite3");
        let store = NativeCleanupStore::open(&path, "agent:test".to_string(), 7)
            .await
            .expect("open");
        let prepared = store
            .enqueue(
                "operation:test".to_string(),
                "thread:test".to_string(),
                "session:test".to_string(),
            )
            .await
            .expect("enqueue");
        let effect = store
            .mark_effect_possible(&prepared)
            .await
            .expect("effect possible");
        drop(store);

        let store = NativeCleanupStore::open(&path, "agent:test".to_string(), 7)
            .await
            .expect("reopen");
        assert_eq!(
            store
                .obligation("operation:test")
                .await
                .expect("load")
                .expect("present"),
            effect
        );
        assert!(store
            .claim_exact(&effect, "worker:test".to_string(), Duration::from_secs(1))
            .await
            .expect("claim unknown")
            .is_none());
        let terminal = store
            .mark_terminal_durable(&effect)
            .await
            .expect("terminal");
        let claim = store
            .claim_exact(&terminal, "worker:test".to_string(), Duration::from_secs(1))
            .await
            .expect("claim")
            .expect("leased");
        store.complete(&claim).await.expect("complete");
        assert!(store
            .obligation("operation:test")
            .await
            .expect("load absent")
            .is_none());
    }
}
''', encoding="utf-8")


def library(text: str) -> str:
    if "mod native_cleanup_store;" not in text:
        text = text.replace(
            "mod native_deadline;\n",
            "mod native_deadline;\nmod native_cleanup_store;\n",
            1,
        )
    if "NativeCleanupBacklogMetrics" not in text:
        text = text.replace(
            "pub use native_thread_lifecycle::NativeCleanupMetrics;\n",
            "pub use native_cleanup_store::NativeCleanupBacklogMetrics;\npub use native_thread_lifecycle::NativeCleanupMetrics;\n",
            1,
        )
    return text


def lifecycle(_text: str) -> str:
    return r'''//! Durable cleanup for prepared/settled ephemeral threads. Unknown effects retain
//! their history: neither Drop nor disconnect is a terminal observation.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::ThreadUnsubscribeResponse;
use tokio::time::Instant;

use crate::native_cleanup_store::CleanupObligation;
use crate::native_cleanup_store::NativeCleanupStore;
use crate::native_app_server::Result;

static CLEANUP_ATTEMPTS: AtomicU64 = AtomicU64::new(0);
static CLEANUP_FAILURES: AtomicU64 = AtomicU64::new(0);
static UNKNOWN_RETAINED: AtomicU64 = AtomicU64::new(0);
static DROP_CLEANUPS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(32);

/// Process-local diagnostics. Durable backlog metrics are owned by
/// `NativeCleanupStore` and are the capacity/recovery source of truth.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeCleanupMetrics {
    pub attempted: u64,
    pub failed_or_orphaned: u64,
    pub unknown_history_retained: u64,
}

pub fn native_cleanup_metrics() -> NativeCleanupMetrics {
    NativeCleanupMetrics {
        attempted: CLEANUP_ATTEMPTS.load(Ordering::Relaxed),
        failed_or_orphaned: CLEANUP_FAILURES.load(Ordering::Relaxed),
        unknown_history_retained: UNKNOWN_RETAINED.load(Ordering::Relaxed),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Phase {
    Prepared,
    EffectPossible,
    TerminalDurable,
    CleanupRequested,
}

pub(crate) struct NativeThreadGuard {
    handle: RemoteAppServerRequestHandle,
    store: NativeCleanupStore,
    obligation: CleanupObligation,
    phase: Phase,
}

impl NativeThreadGuard {
    pub(crate) async fn create(
        store: NativeCleanupStore,
        handle: RemoteAppServerRequestHandle,
        operation_id: String,
        thread_id: String,
        session_id: String,
    ) -> Result<Self> {
        let obligation = store
            .enqueue(operation_id, thread_id, session_id)
            .await?;
        let phase = match obligation.state {
            crate::native_cleanup_store::CleanupState::Prepared => Phase::Prepared,
            crate::native_cleanup_store::CleanupState::EffectPossible => Phase::EffectPossible,
            crate::native_cleanup_store::CleanupState::TerminalDurable => Phase::TerminalDurable,
        };
        Ok(Self {
            handle,
            store,
            obligation,
            phase,
        })
    }

    pub(crate) async fn recover_pending(
        store: &NativeCleanupStore,
        handle: RemoteAppServerRequestHandle,
        deadline: Instant,
    ) -> Result<()> {
        let worker_id = format!("recovery:{}", std::process::id());
        let claims = store
            .claim_ready(worker_id, Duration::from_secs(10), 16)
            .await?;
        for claim in claims {
            if Instant::now() >= deadline {
                store.fail(&claim, "cleanup recovery budget elapsed").await?;
                break;
            }
            cleanup_claim(store.clone(), handle.clone(), claim, deadline).await;
        }
        Ok(())
    }

    pub(crate) async fn effect_entered(&mut self) -> Result<()> {
        self.obligation = self.store.mark_effect_possible(&self.obligation).await?;
        self.phase = Phase::EffectPossible;
        Ok(())
    }

    // Called only AFTER settle_native/reject_native_before_start or a proved
    // cross-owner pre-effect abort durably committed the matching record.
    pub(crate) async fn terminal_persisted(&mut self) -> Result<()> {
        self.obligation = self
            .store
            .mark_terminal_durable(&self.obligation)
            .await?;
        self.phase = Phase::TerminalDurable;
        Ok(())
    }

    pub(crate) async fn cleanup(&mut self) {
        if !matches!(self.phase, Phase::Prepared | Phase::TerminalDurable) {
            return;
        }
        let worker_id = format!("inline:{}", std::process::id());
        let claim = match self
            .store
            .claim_exact(&self.obligation, worker_id, Duration::from_secs(10))
            .await
        {
            Ok(Some(claim)) => claim,
            Ok(None) => return,
            Err(_) => {
                CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                return;
            }
        };
        self.phase = Phase::CleanupRequested;
        cleanup_claim(
            self.store.clone(),
            self.handle.clone(),
            claim,
            Instant::now() + Duration::from_secs(5),
        )
        .await;
    }
}

impl Drop for NativeThreadGuard {
    fn drop(&mut self) {
        match self.phase {
            Phase::CleanupRequested => {}
            Phase::EffectPossible => {
                UNKNOWN_RETAINED.fetch_add(1, Ordering::Relaxed);
            }
            Phase::Prepared | Phase::TerminalDurable => {
                let Ok(runtime) = tokio::runtime::Handle::try_current() else {
                    CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                    return;
                };
                let Ok(permit) = DROP_CLEANUPS.try_acquire() else {
                    CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                    return;
                };
                let store = self.store.clone();
                let handle = self.handle.clone();
                let obligation = self.obligation.clone();
                runtime.spawn(async move {
                    let worker_id = format!("drop:{}", std::process::id());
                    match store
                        .claim_exact(&obligation, worker_id, Duration::from_secs(10))
                        .await
                    {
                        Ok(Some(claim)) => {
                            cleanup_claim(
                                store,
                                handle,
                                claim,
                                Instant::now() + Duration::from_secs(5),
                            )
                            .await;
                        }
                        Ok(None) => {}
                        Err(_) => {
                            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                    drop(permit);
                });
            }
        }
    }
}

async fn cleanup_claim(
    store: NativeCleanupStore,
    handle: RemoteAppServerRequestHandle,
    claim: crate::native_cleanup_store::CleanupClaim,
    deadline: Instant,
) {
    CLEANUP_ATTEMPTS.fetch_add(1, Ordering::Relaxed);
    let request = handle.request_typed::<ThreadUnsubscribeResponse>(
        ClientRequest::ThreadUnsubscribe {
            request_id: RequestId::String(format!(
                "hepta-cleanup:{}:{}",
                claim.fence, claim.operation_id
            )),
            params: ThreadUnsubscribeParams {
                thread_id: claim.thread_id.clone(),
            },
        },
    );
    let response = tokio::time::timeout_at(
        deadline.min(Instant::now() + Duration::from_secs(5)),
        request,
    )
    .await;
    match response {
        Ok(Ok(_)) => {
            if store.complete(&claim).await.is_err() {
                CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            }
        }
        Ok(Err(error)) => {
            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            let _ = store.fail(&claim, &error.to_string()).await;
        }
        Err(_) => {
            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            let _ = store.fail(&claim, "thread unsubscribe timed out").await;
        }
    }
}
'''


def execution(text: str) -> str:
    old = '''        let mut thread_guard = crate::native_thread_lifecycle::NativeThreadGuard::new(
            client.request_handle(),
            started.thread.id.clone(),
        );
'''
    new = '''        let cleanup_root = self
            .config
            .agentd_socket
            .parent()
            .ok_or("Agentd socket omitted its exact-generation run root")?;
        let cleanup_store = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup store open",
            crate::native_cleanup_store::NativeCleanupStore::open(
                &cleanup_root.join("runtime-codex-cleanup-v1.sqlite3"),
                self.config.agent_id.to_string(),
                self.config.generation,
            ),
        )
        .await?;
        let recovery_budget = execution_clock
            .remaining(unix_time_ms()?)?
            .min(Duration::from_millis(500));
        crate::native_thread_lifecycle::NativeThreadGuard::recover_pending(
            &cleanup_store,
            client.request_handle(),
            Instant::now() + recovery_budget,
        )
        .await?;
        let cleanup_operation_id = format!(
            "native:{}",
            Digest32::of_bytes(request_id.as_bytes())
        );
        let mut thread_guard = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup obligation enqueue",
            crate::native_thread_lifecycle::NativeThreadGuard::create(
                cleanup_store,
                client.request_handle(),
                cleanup_operation_id,
                started.thread.id.clone(),
                started.thread.session_id.clone(),
            ),
        )
        .await?;
'''
    text = replace_once(text, old, new, '"durable cleanup obligation enqueue"')

    old = '''            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let entered_use = verified_use.enter(&authority_binding)?;
'''
    new = '''            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            thread_guard.effect_entered().await?;
            let entered_use = verified_use.enter(&authority_binding)?;
'''
    text = replace_once(text, old, new, "thread_guard.effect_entered().await?")

    old = '''                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(error);
'''
    new = '''                stopped?;
                thread_guard.terminal_persisted().await?;
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(error);
'''
    text = replace_once(text, old, new, "stopped?;\n                thread_guard.terminal_persisted().await?")

    text = text.replace(
        '''        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let attempt = attempt.enter_effect();
''',
        '''        drop(pre_effect_abort);
        let attempt = attempt.enter_effect();
''',
        1,
    )

    old = '''                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        thread_guard.cleanup().await;
'''
    new = '''                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        thread_guard.terminal_persisted().await?;
                        thread_guard.cleanup().await;
'''
    text = replace_once(text, old, new, "thread_guard.terminal_persisted().await?;\n                        thread_guard.cleanup")

    text = text.replace(
        "            thread_guard.terminal_persisted();\n",
        "            thread_guard.terminal_persisted().await?;\n",
        1,
    )
    return text


def main() -> None:
    write_store()
    rewrite("codex-rs/hepta-infer-worker-host/src/lib.rs", library)
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/native_thread_lifecycle.rs",
        lifecycle,
    )
    rewrite("codex-rs/hepta-infer-worker-host/src/native_execution.rs", execution)


if __name__ == "__main__":
    main()
