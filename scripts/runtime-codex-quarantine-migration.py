#!/usr/bin/env python3
"""Install the durable runtime.codex quarantine owner and unknown-outcome write.

The protocol verifier remains pure. This migration adds a SQLite WAL store that
atomically records unknown effects, CAS-advances signer frontiers/nonces, and
commits a signed resolution against the exact quarantine record. The live
turn/start unknown paths write the record before returning an indeterminate
output to their caller.
"""

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
    raise RuntimeError(f"{marker}: neither legacy block nor migrated marker found")


def cargo(text: str) -> str:
    line = "sqlx = { workspace = true }"
    if line not in text:
        marker = "sha2 = { workspace = true }\n"
        if marker not in text:
            raise RuntimeError("worker-host sha2 dependency marker missing")
        text = text.replace(marker, marker + line + "\n", 1)
    return text


def quarantine_module(text: str) -> str:
    if "pub struct DurableQuarantineStore" in text:
        return text
    marker = "#[cfg(test)]\nmod tests {"
    if marker not in text:
        raise RuntimeError("quarantine test-module marker missing")
    durable = r'''
const DURABLE_QUARANTINE_STORE_SCHEMA_VERSION: i64 = 1;
const MAX_ACTIVE_QUARANTINES: i64 = 65_536;
const MAX_QUARANTINE_RECORD_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuarantineRecordDisposition {
    Inserted,
    Updated,
    Existing,
}

#[derive(Debug)]
pub enum DurableQuarantineError {
    Protocol(QuarantineProtocolError),
    InvalidStore(&'static str),
    Conflict(String),
    Capacity,
    Unavailable(String),
    Corrupt(String),
}

impl fmt::Display for DurableQuarantineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableQuarantineError {}

impl From<QuarantineProtocolError> for DurableQuarantineError {
    fn from(value: QuarantineProtocolError) -> Self {
        Self::Protocol(value)
    }
}

#[derive(Clone)]
pub struct DurableQuarantineStore {
    pool: sqlx::SqlitePool,
    path: std::path::PathBuf,
    owner_id: String,
    owner_generation: u64,
}

impl fmt::Debug for DurableQuarantineStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableQuarantineStore")
            .field("path", &self.path)
            .field("owner_id", &self.owner_id)
            .field("owner_generation", &self.owner_generation)
            .finish_non_exhaustive()
    }
}

impl DurableQuarantineStore {
    pub async fn open(
        path: &std::path::Path,
        owner_id: String,
        owner_generation: u64,
    ) -> Result<Self, DurableQuarantineError> {
        use sqlx::sqlite::SqliteConnectOptions;
        use sqlx::sqlite::SqliteJournalMode;
        use sqlx::sqlite::SqlitePoolOptions;
        use sqlx::sqlite::SqliteSynchronous;

        if !path.is_absolute() || !valid_identifier(&owner_id) || owner_generation == 0 {
            return Err(DurableQuarantineError::InvalidStore(
                "invalid quarantine store identity",
            ));
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| {
                DurableQuarantineError::Unavailable(format!(
                    "create quarantine store parent: {error}"
                ))
            })?;
        }
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(std::time::Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(quarantine_sqlx)?;
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

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    async fn initialize(&self) -> Result<(), DurableQuarantineError> {
        let quick: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(&self.pool)
            .await
            .map_err(quarantine_sqlx)?;
        if quick != "ok" {
            return Err(DurableQuarantineError::Corrupt(format!(
                "quarantine quick_check: {quick}"
            )));
        }
        for statement in [
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_quarantine_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                owner_id TEXT NOT NULL,
                owner_generation INTEGER NOT NULL,
                store_revision INTEGER NOT NULL CHECK (store_revision > 0)
            ) STRICT"#,
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_quarantined_effects (
                operation_id TEXT PRIMARY KEY,
                quarantine_revision INTEGER NOT NULL CHECK (quarantine_revision > 0),
                record_sha256 BLOB NOT NULL CHECK (length(record_sha256) = 32),
                record_json BLOB NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('active', 'resolved')),
                resolution_sequence INTEGER,
                resolution_json BLOB,
                created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
                updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms)
            ) STRICT"#,
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_quarantine_frontiers (
                signer_id TEXT NOT NULL,
                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                verifying_key BLOB NOT NULL CHECK (length(verifying_key) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence >= 0),
                state_sha256 BLOB NOT NULL CHECK (length(state_sha256) = 32),
                PRIMARY KEY (signer_id, authority_epoch)
            ) STRICT"#,
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_quarantine_nonces (
                signer_id TEXT NOT NULL,
                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                nonce BLOB NOT NULL CHECK (length(nonce) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence > 0),
                PRIMARY KEY (signer_id, authority_epoch, nonce),
                UNIQUE (signer_id, authority_epoch, resolution_sequence),
                FOREIGN KEY (signer_id, authority_epoch)
                    REFERENCES runtime_codex_quarantine_frontiers(signer_id, authority_epoch)
                    ON DELETE RESTRICT
            ) STRICT"#,
            "CREATE INDEX IF NOT EXISTS runtime_codex_quarantine_active_idx ON runtime_codex_quarantined_effects(state, updated_at_ms, operation_id)",
        ] {
            sqlx::query(statement)
                .execute(&self.pool)
                .await
                .map_err(quarantine_sqlx)?;
        }
        let owner_generation = quarantine_i64(self.owner_generation, "owner generation")?;
        sqlx::query(
            r#"INSERT OR IGNORE INTO runtime_codex_quarantine_meta
               (singleton, schema_version, owner_id, owner_generation, store_revision)
               VALUES (1, ?, ?, ?, 1)"#,
        )
        .bind(DURABLE_QUARANTINE_STORE_SCHEMA_VERSION)
        .bind(&self.owner_id)
        .bind(owner_generation)
        .execute(&self.pool)
        .await
        .map_err(quarantine_sqlx)?;
        let row = sqlx::query(
            "SELECT schema_version, owner_id, owner_generation, store_revision FROM runtime_codex_quarantine_meta WHERE singleton = 1",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(quarantine_sqlx)?;
        use sqlx::Row;
        let schema_version: i64 = row.try_get("schema_version").map_err(quarantine_sqlx)?;
        let owner_id: String = row.try_get("owner_id").map_err(quarantine_sqlx)?;
        let persisted_generation: i64 = row
            .try_get("owner_generation")
            .map_err(quarantine_sqlx)?;
        let store_revision: i64 = row.try_get("store_revision").map_err(quarantine_sqlx)?;
        if schema_version != DURABLE_QUARANTINE_STORE_SCHEMA_VERSION
            || owner_id != self.owner_id
            || persisted_generation != owner_generation
            || store_revision <= 0
        {
            return Err(DurableQuarantineError::Corrupt(
                "quarantine store identity or revision mismatch".to_string(),
            ));
        }
        Ok(())
    }

    pub async fn record_unknown(
        &self,
        quarantine: &QuarantinedEffectV1,
    ) -> Result<QuarantineRecordDisposition, DurableQuarantineError> {
        use sqlx::Row;
        quarantine.validate()?;
        let record_json = serde_json::to_vec(quarantine)
            .map_err(|_| DurableQuarantineError::Protocol(QuarantineProtocolError::EncodingFailed))?;
        if record_json.len() > MAX_QUARANTINE_RECORD_BYTES {
            return Err(DurableQuarantineError::Capacity);
        }
        let record_sha256 = quarantine.record_sha256()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(quarantine_sqlx)?;
        let store_revision = quarantine_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let existing = sqlx::query(
            "SELECT quarantine_revision, record_sha256, record_json, state FROM runtime_codex_quarantined_effects WHERE operation_id = ?",
        )
        .bind(&quarantine.operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        let now = quarantine_now_ms()?;
        let disposition = if let Some(row) = existing {
            let state: String = row.try_get("state").map_err(quarantine_sqlx)?;
            let existing_sha = quarantine_digest(
                row.try_get::<Vec<u8>, _>("record_sha256")
                    .map_err(quarantine_sqlx)?,
                "quarantine record digest",
            )?;
            if existing_sha == record_sha256 {
                tx.commit().await.map_err(quarantine_sqlx)?;
                return Ok(QuarantineRecordDisposition::Existing);
            }
            if state != "active" {
                return Err(DurableQuarantineError::Conflict(format!(
                    "resolved quarantine {} cannot be replaced",
                    quarantine.operation_id
                )));
            }
            let existing_json: Vec<u8> = row.try_get("record_json").map_err(quarantine_sqlx)?;
            let previous: QuarantinedEffectV1 = serde_json::from_slice(&existing_json).map_err(|error| {
                DurableQuarantineError::Corrupt(format!("decode existing quarantine: {error}"))
            })?;
            if !same_quarantine_identity(&previous, quarantine)
                || quarantine.quarantine_revision <= previous.quarantine_revision
                || quarantine.reconciliation_attempts < previous.reconciliation_attempts
                || quarantine.last_reconciled_unix_ms < previous.last_reconciled_unix_ms
            {
                return Err(DurableQuarantineError::Conflict(format!(
                    "quarantine {} update is not a monotonic exact-binding reconciliation",
                    quarantine.operation_id
                )));
            }
            let rows = sqlx::query(
                r#"UPDATE runtime_codex_quarantined_effects
                   SET quarantine_revision = ?, record_sha256 = ?, record_json = ?, updated_at_ms = ?
                   WHERE operation_id = ? AND state = 'active' AND quarantine_revision = ?"#,
            )
            .bind(quarantine_i64(quarantine.quarantine_revision, "quarantine revision")?)
            .bind(record_sha256.as_slice())
            .bind(&record_json)
            .bind(quarantine_i64(now, "updated time")?)
            .bind(&quarantine.operation_id)
            .bind(quarantine_i64(previous.quarantine_revision, "previous quarantine revision")?)
            .execute(&mut *tx)
            .await
            .map_err(quarantine_sqlx)?;
            if rows.rows_affected() != 1 {
                return Err(DurableQuarantineError::Conflict(
                    "quarantine update CAS failed".to_string(),
                ));
            }
            QuarantineRecordDisposition::Updated
        } else {
            let active: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM runtime_codex_quarantined_effects WHERE state = 'active'",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(quarantine_sqlx)?;
            if active >= MAX_ACTIVE_QUARANTINES {
                return Err(DurableQuarantineError::Capacity);
            }
            sqlx::query(
                r#"INSERT INTO runtime_codex_quarantined_effects
                   (operation_id, quarantine_revision, record_sha256, record_json, state, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, 'active', ?, ?)"#,
            )
            .bind(&quarantine.operation_id)
            .bind(quarantine_i64(quarantine.quarantine_revision, "quarantine revision")?)
            .bind(record_sha256.as_slice())
            .bind(&record_json)
            .bind(quarantine_i64(now, "created time")?)
            .bind(quarantine_i64(now, "updated time")?)
            .execute(&mut *tx)
            .await
            .map_err(quarantine_sqlx)?;
            QuarantineRecordDisposition::Inserted
        };
        advance_quarantine_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(quarantine_sqlx)?;
        Ok(disposition)
    }

    pub async fn active(
        &self,
        operation_id: &str,
    ) -> Result<Option<QuarantinedEffectV1>, DurableQuarantineError> {
        require_identifier(operation_id)?;
        let value: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT record_json FROM runtime_codex_quarantined_effects WHERE operation_id = ? AND state = 'active'",
        )
        .bind(operation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(quarantine_sqlx)?;
        value
            .map(|bytes| {
                serde_json::from_slice::<QuarantinedEffectV1>(&bytes)
                    .map_err(|error| DurableQuarantineError::Corrupt(format!("decode quarantine: {error}")))
                    .and_then(|record| {
                        record.validate()?;
                        Ok(record)
                    })
            })
            .transpose()
    }

    pub async fn verify_and_commit_resolution(
        &self,
        signer_id: String,
        verifying_key: [u8; 32],
        signed: &SignedQuarantineResolutionV1,
        now_unix_ms: u64,
    ) -> Result<VerifiedQuarantineResolutionV1, DurableQuarantineError> {
        use sqlx::Row;
        require_identifier(&signer_id)?;
        let operation_id = signed.resolution.operation_id.clone();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(quarantine_sqlx)?;
        let store_revision = quarantine_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
        let record_row = sqlx::query(
            "SELECT quarantine_revision, record_sha256, record_json, state FROM runtime_codex_quarantined_effects WHERE operation_id = ?",
        )
        .bind(&operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?
        .ok_or_else(|| DurableQuarantineError::Conflict(format!("quarantine {operation_id} is absent")))?;
        let state: String = record_row.try_get("state").map_err(quarantine_sqlx)?;
        if state != "active" {
            return Err(DurableQuarantineError::Conflict(format!(
                "quarantine {operation_id} is already resolved"
            )));
        }
        let record_json: Vec<u8> = record_row.try_get("record_json").map_err(quarantine_sqlx)?;
        let quarantine: QuarantinedEffectV1 = serde_json::from_slice(&record_json).map_err(|error| {
            DurableQuarantineError::Corrupt(format!("decode quarantine before resolution: {error}"))
        })?;
        quarantine.validate()?;
        let persisted_record_sha = quarantine_digest(
            record_row
                .try_get::<Vec<u8>, _>("record_sha256")
                .map_err(quarantine_sqlx)?,
            "persisted quarantine digest",
        )?;
        if persisted_record_sha != quarantine.record_sha256()? {
            return Err(DurableQuarantineError::Corrupt(
                "persisted quarantine digest mismatch".to_string(),
            ));
        }

        let frontier_row = sqlx::query(
            r#"SELECT verifying_key, resolution_sequence, state_sha256
               FROM runtime_codex_quarantine_frontiers
               WHERE signer_id = ? AND authority_epoch = ?"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(quarantine.authority_epoch, "authority epoch")?)
        .fetch_optional(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        let current_sequence = if let Some(row) = frontier_row {
            let persisted_key = quarantine_digest(
                row.try_get::<Vec<u8>, _>("verifying_key")
                    .map_err(quarantine_sqlx)?,
                "quarantine verifying key",
            )?;
            if persisted_key != verifying_key {
                return Err(DurableQuarantineError::Conflict(
                    "quarantine signer key changed within an authority epoch".to_string(),
                ));
            }
            quarantine_u64(
                row.try_get::<i64, _>("resolution_sequence")
                    .map_err(quarantine_sqlx)?,
                "resolution sequence",
            )?
        } else {
            0
        };
        let nonce_rows = sqlx::query(
            r#"SELECT nonce FROM runtime_codex_quarantine_nonces
               WHERE signer_id = ? AND authority_epoch = ? ORDER BY nonce"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(quarantine.authority_epoch, "authority epoch")?)
        .fetch_all(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        if nonce_rows.len() > MAX_USED_NONCES {
            return Err(DurableQuarantineError::Capacity);
        }
        let mut used_nonces = BTreeSet::new();
        for row in nonce_rows {
            used_nonces.insert(quarantine_digest(
                row.try_get::<Vec<u8>, _>("nonce").map_err(quarantine_sqlx)?,
                "quarantine nonce",
            )?);
        }
        let mut verifier = QuarantineResolutionVerifier::new(
            signer_id.clone(),
            verifying_key,
            quarantine.authority_epoch,
            current_sequence,
            used_nonces,
        )?;
        let verified = verifier.verify(signed, &quarantine, now_unix_ms)?;
        let frontier = verifier.frontier();
        let resolution_json = serde_json::to_vec(signed)
            .map_err(|_| DurableQuarantineError::Protocol(QuarantineProtocolError::EncodingFailed))?;
        sqlx::query(
            r#"INSERT INTO runtime_codex_quarantine_frontiers
               (signer_id, authority_epoch, verifying_key, resolution_sequence, state_sha256)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(signer_id, authority_epoch) DO UPDATE SET
                   verifying_key = excluded.verifying_key,
                   resolution_sequence = excluded.resolution_sequence,
                   state_sha256 = excluded.state_sha256
               WHERE runtime_codex_quarantine_frontiers.resolution_sequence < excluded.resolution_sequence
                 AND runtime_codex_quarantine_frontiers.verifying_key = excluded.verifying_key"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(frontier.authority_epoch, "frontier authority epoch")?)
        .bind(verifying_key.as_slice())
        .bind(quarantine_i64(frontier.resolution_sequence, "frontier sequence")?)
        .bind(frontier.state_sha256.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        sqlx::query(
            r#"INSERT INTO runtime_codex_quarantine_nonces
               (signer_id, authority_epoch, nonce, resolution_sequence)
               VALUES (?, ?, ?, ?)"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(frontier.authority_epoch, "nonce authority epoch")?)
        .bind(signed.resolution.nonce.as_slice())
        .bind(quarantine_i64(frontier.resolution_sequence, "nonce sequence")?)
        .execute(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        let rows = sqlx::query(
            r#"UPDATE runtime_codex_quarantined_effects
               SET state = 'resolved', resolution_sequence = ?, resolution_json = ?, updated_at_ms = ?
               WHERE operation_id = ? AND state = 'active' AND quarantine_revision = ? AND record_sha256 = ?"#,
        )
        .bind(quarantine_i64(frontier.resolution_sequence, "resolution sequence")?)
        .bind(&resolution_json)
        .bind(quarantine_i64(now_unix_ms, "resolution time")?)
        .bind(&operation_id)
        .bind(quarantine_i64(quarantine.quarantine_revision, "quarantine revision")?)
        .bind(persisted_record_sha.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        if rows.rows_affected() != 1 {
            return Err(DurableQuarantineError::Conflict(
                "quarantine resolution CAS failed".to_string(),
            ));
        }
        advance_quarantine_store_revision(&mut tx, store_revision).await?;
        tx.commit().await.map_err(quarantine_sqlx)?;
        Ok(verified)
    }
}

fn same_quarantine_identity(left: &QuarantinedEffectV1, right: &QuarantinedEffectV1) -> bool {
    left.operation_id == right.operation_id
        && left.source_admission_sha256 == right.source_admission_sha256
        && left.request_sha256 == right.request_sha256
        && left.payload_sha256 == right.payload_sha256
        && left.local_dispatch_sha256 == right.local_dispatch_sha256
        && left.agent_run_id == right.agent_run_id
        && left.agent_dispatch_sha256 == right.agent_dispatch_sha256
        && left.authority_epoch == right.authority_epoch
        && left.agent_generation == right.agent_generation
        && left.app_server_session_id == right.app_server_session_id
        && left.codex_home_sha256 == right.codex_home_sha256
        && left.thread_id == right.thread_id
        && left.client_user_message_id == right.client_user_message_id
        && left.user_input_sha256 == right.user_input_sha256
        && left.model_id == right.model_id
        && left.provider_id == right.provider_id
}

async fn quarantine_store_revision(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    owner_id: &str,
    owner_generation: u64,
) -> Result<u64, DurableQuarantineError> {
    use sqlx::Row;
    let row = sqlx::query(
        "SELECT schema_version, owner_id, owner_generation, store_revision FROM runtime_codex_quarantine_meta WHERE singleton = 1",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(quarantine_sqlx)?;
    let schema_version: i64 = row.try_get("schema_version").map_err(quarantine_sqlx)?;
    let persisted_owner: String = row.try_get("owner_id").map_err(quarantine_sqlx)?;
    let persisted_generation: i64 = row
        .try_get("owner_generation")
        .map_err(quarantine_sqlx)?;
    if schema_version != DURABLE_QUARANTINE_STORE_SCHEMA_VERSION
        || persisted_owner != owner_id
        || persisted_generation != quarantine_i64(owner_generation, "owner generation")?
    {
        return Err(DurableQuarantineError::Conflict(
            "quarantine store owner fence changed".to_string(),
        ));
    }
    quarantine_u64(
        row.try_get::<i64, _>("store_revision")
            .map_err(quarantine_sqlx)?,
        "store revision",
    )
}

async fn advance_quarantine_store_revision(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    expected: u64,
) -> Result<(), DurableQuarantineError> {
    let next = expected
        .checked_add(1)
        .ok_or(DurableQuarantineError::Capacity)?;
    let rows = sqlx::query(
        "UPDATE runtime_codex_quarantine_meta SET store_revision = ? WHERE singleton = 1 AND store_revision = ?",
    )
    .bind(quarantine_i64(next, "next store revision")?)
    .bind(quarantine_i64(expected, "expected store revision")?)
    .execute(&mut **tx)
    .await
    .map_err(quarantine_sqlx)?;
    if rows.rows_affected() != 1 {
        return Err(DurableQuarantineError::Conflict(
            "quarantine store revision CAS failed".to_string(),
        ));
    }
    Ok(())
}

fn quarantine_digest(value: Vec<u8>, label: &'static str) -> Result<[u8; 32], DurableQuarantineError> {
    value
        .try_into()
        .map_err(|_| DurableQuarantineError::Corrupt(format!("invalid {label} length")))
}

fn quarantine_i64(value: u64, label: &'static str) -> Result<i64, DurableQuarantineError> {
    i64::try_from(value)
        .map_err(|_| DurableQuarantineError::Corrupt(format!("{label} exceeds SQLite i64")))
}

fn quarantine_u64(value: i64, label: &'static str) -> Result<u64, DurableQuarantineError> {
    u64::try_from(value)
        .map_err(|_| DurableQuarantineError::Corrupt(format!("{label} is negative")))
}

fn quarantine_now_ms() -> Result<u64, DurableQuarantineError> {
    let value = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| DurableQuarantineError::Unavailable("clock precedes Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(value).map_err(|_| DurableQuarantineError::Capacity)
}

fn quarantine_sqlx(error: sqlx::Error) -> DurableQuarantineError {
    DurableQuarantineError::Unavailable(error.to_string())
}

#[cfg(test)]
mod durable_store_tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    fn digest(byte: u8) -> [u8; 32] {
        [byte; 32]
    }

    fn record() -> QuarantinedEffectV1 {
        QuarantinedEffectV1 {
            schema_version: 1,
            quarantine_revision: 11,
            operation_id: "operation:durable".to_string(),
            source_admission_sha256: digest(1),
            request_sha256: digest(2),
            payload_sha256: digest(3),
            local_dispatch_sha256: digest(4),
            local_dispatch_revision: 7,
            agent_run_id: "run:durable".to_string(),
            agent_revision: 9,
            agent_dispatch_sha256: digest(4),
            authority_epoch: 12,
            revocation_revision: 18,
            revocation_head_sha256: digest(5),
            authority_witness_sha256: digest(6),
            agent_generation: 3,
            app_server_session_id: "session:durable".to_string(),
            app_server_version: "app-server-test".to_string(),
            codex_home_sha256: digest(7),
            connection_id: 55,
            thread_id: "thread:durable".to_string(),
            turn_id: None,
            client_user_message_id: "message:durable".to_string(),
            user_input_sha256: digest(8),
            model_id: "model:test".to_string(),
            provider_id: "provider:test".to_string(),
            first_unknown_unix_ms: 1_000,
            last_reconciled_unix_ms: 2_000,
            reconciliation_attempts: 1,
            evidence_sha256: BTreeSet::from([digest(9), digest(10)]),
            reason_code: "TURN_START_UNKNOWN".to_string(),
            redacted_diagnostic: "unknown acknowledgement".to_string(),
        }
    }

    #[tokio::test]
    async fn durable_record_and_resolution_survive_reopen() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("quarantine.sqlite3");
        let store = DurableQuarantineStore::open(&path, "agent:test".to_string(), 3)
            .await
            .expect("open store");
        let quarantine = record();
        assert_eq!(
            store.record_unknown(&quarantine).await.expect("record"),
            QuarantineRecordDisposition::Inserted
        );
        store.close().await;

        let store = DurableQuarantineStore::open(&path, "agent:test".to_string(), 3)
            .await
            .expect("reopen store");
        assert_eq!(
            store.active(&quarantine.operation_id).await.expect("load"),
            Some(quarantine.clone())
        );
        let key = SigningKey::from_bytes(&rand::random());
        let mut resolution = QuarantineResolutionV1 {
            schema_version: 1,
            signer_id: "independent-quarantine-authority".to_string(),
            resolution_id: "resolution:durable".to_string(),
            operation_id: quarantine.operation_id.clone(),
            quarantine_revision: quarantine.quarantine_revision,
            quarantine_record_sha256: quarantine.record_sha256().expect("record digest"),
            request_sha256: quarantine.request_sha256,
            dispatch_sha256: quarantine.local_dispatch_sha256,
            evidence_set_sha256: quarantine.evidence_set_sha256().expect("evidence digest"),
            authority_epoch: quarantine.authority_epoch,
            resolution_sequence: 1,
            nonce: rand::random(),
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 60_000,
            disposition: QuarantineResolutionDispositionV1::AbandonWithoutReplay,
            terminal: None,
            new_operation_constraints: None,
            reason_code: "DUAL_OPERATOR_REVIEW".to_string(),
        };
        let signature = key
            .sign(&resolution.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        let signed = SignedQuarantineResolutionV1 {
            resolution: resolution.clone(),
            signature,
        };
        store
            .verify_and_commit_resolution(
                resolution.signer_id.clone(),
                key.verifying_key().to_bytes(),
                &signed,
                2_000,
            )
            .await
            .expect("resolve");
        assert!(store
            .active(&quarantine.operation_id)
            .await
            .expect("load resolved")
            .is_none());
        resolution.resolution_id = "resolution:replay".to_string();
        assert!(store
            .verify_and_commit_resolution(
                resolution.signer_id.clone(),
                key.verifying_key().to_bytes(),
                &signed,
                2_000,
            )
            .await
            .is_err());
    }
}

'''
    return text.replace(marker, durable + marker, 1)


def native_execution(text: str) -> str:
    if "persist_unknown_turn_start" in text:
        return text
    response_marker = '''        let response = timeout(
            send_budget,
            send_authorized_turn_start(&mut client, entered_use, turn_params),
        )
        .await;
'''
    response_new = '''        let app_server_session_id = started.thread.session_id.clone();
        let response = timeout(
            send_budget,
            send_authorized_turn_start(&mut client, entered_use, turn_params),
        )
        .await;
'''
    text = replace_once(text, response_marker, response_new, "app_server_session_id")

    old_blocks = [
        '''                            thread_guard.cleanup().await;
                            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                            return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                                started,
                                format!(
                                    "turn/start returned an accepted-or-unknown JSON-RPC error ({reason}); reconciliation found no exact turn; do not replay"
                                ),
                            )).await);
''',
        '''                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                        started,
                        format!(
                            "turn/start transport outcome unknown ({error}); reconciliation found no exact turn; do not replay"
                        ),
                    )).await);
''',
        '''                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                        started,
                        "turn/start timed out; reconciliation found no exact turn; do not replay"
                            .to_string(),
                    )).await);
''',
    ]
    reasons = [
        '''let unknown_reason = format!(
                                "turn/start returned an accepted-or-unknown JSON-RPC error ({reason}); reconciliation found no exact turn; do not replay"
                            );''',
        '''let unknown_reason = format!(
                        "turn/start transport outcome unknown ({error}); reconciliation found no exact turn; do not replay"
                    );''',
        '''let unknown_reason =
                        "turn/start timed out; reconciliation found no exact turn; do not replay"
                            .to_string();''',
    ]
    indents = ["                            ", "                    ", "                    "]
    for old, reason, indent in zip(old_blocks, reasons, indents):
        new = f'''{indent}{reason}
{indent}let output = reconcile_intelligence_start_unknown(
{indent}    &owner,
{indent}    intelligence,
{indent}    intelligence_revision,
{indent}    indeterminate_start_output(started, unknown_reason.clone()),
{indent})
{indent}.await;
{indent}persist_unknown_turn_start(
{indent}    self,
{indent}    control,
{indent}    request_id,
{indent}    &adapter_intent,
{indent}    request_receipt.request_digest,
{indent}    payload_digest,
{indent}    source_admission_digest,
{indent}    user_input_digest,
{indent}    authority_epoch,
{indent}    revocation_revision,
{indent}    &revocation_head_digest,
{indent}    &authority_witness,
{indent}    codex_home_digest,
{indent}    connection_id,
{indent}    &app_server_session_id,
{indent}    &app_server_version,
{indent}    intelligence,
{indent}    intelligence_revision,
{indent}    prepared_revision,
{indent}    &output,
{indent}    &unknown_reason,
{indent})
{indent}.await?;
{indent}thread_guard.cleanup().await;
{indent}let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
{indent}return Ok(output);
'''
        text = replace_once(text, old, new, "persist_unknown_turn_start(")

    helper = r'''

async fn persist_unknown_turn_start(
    driver: &AppServerModelDriver,
    control: &DurableInferenceControl,
    request_id: &str,
    adapter_intent: &CodexOperationIntent,
    request_digest: Digest32,
    payload_digest: Digest32,
    source_admission_digest: Digest32,
    user_input_digest: Digest32,
    authority_epoch: u64,
    revocation_revision: u64,
    revocation_head_digest: &str,
    authority_witness_digest: &str,
    codex_home_digest: Digest32,
    connection_id: u64,
    app_server_session_id: &str,
    app_server_version: &str,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    intelligence_revision: Option<u64>,
    prepared_revision: u64,
    output: &NativeRunOutput,
    reason: &str,
) -> Result<()> {
    use crate::runtime_codex_quarantine::DurableQuarantineStore;
    use crate::runtime_codex_quarantine::QuarantinedEffectV1;

    let now = unix_time_ms()?;
    let native_revision = control
        .native_record(request_id)
        .ok_or("native unknown outcome omitted its durable record")?
        .revision;
    let revocation_head: Digest32 = revocation_head_digest.parse()?;
    let authority_witness: Digest32 = authority_witness_digest.parse()?;
    let reason_evidence = Digest32::of_bytes(reason.as_bytes());
    let agent_run_id = intelligence
        .map(|binding| binding.run_id.clone())
        .unwrap_or_else(|| format!("local:{request_digest}"));
    let agent_revision = intelligence_revision.unwrap_or(prepared_revision);
    let mut diagnostic = String::new();
    for character in reason.chars() {
        if diagnostic.len() + character.len_utf8() > 1024 {
            break;
        }
        diagnostic.push(character);
    }
    let record = QuarantinedEffectV1 {
        schema_version: 1,
        quarantine_revision: native_revision,
        operation_id: adapter_intent.operation_id.as_str().to_string(),
        source_admission_sha256: *source_admission_digest.as_array(),
        request_sha256: *request_digest.as_array(),
        payload_sha256: *payload_digest.as_array(),
        local_dispatch_sha256: *request_digest.as_array(),
        local_dispatch_revision: prepared_revision,
        agent_run_id,
        agent_revision,
        agent_dispatch_sha256: *request_digest.as_array(),
        authority_epoch,
        revocation_revision,
        revocation_head_sha256: *revocation_head.as_array(),
        authority_witness_sha256: *authority_witness.as_array(),
        agent_generation: driver.config.generation,
        app_server_session_id: app_server_session_id.to_string(),
        app_server_version: app_server_version.to_string(),
        codex_home_sha256: *codex_home_digest.as_array(),
        connection_id,
        thread_id: output.thread_id.clone(),
        turn_id: (!output.turn_id.is_empty()).then(|| output.turn_id.clone()),
        client_user_message_id: request_id.to_string(),
        user_input_sha256: *user_input_digest.as_array(),
        model_id: output.model.clone(),
        provider_id: output.model_provider.clone(),
        first_unknown_unix_ms: now,
        last_reconciled_unix_ms: now,
        reconciliation_attempts: 1,
        evidence_sha256: std::collections::BTreeSet::from([
            *source_admission_digest.as_array(),
            *request_digest.as_array(),
            *payload_digest.as_array(),
            *authority_witness.as_array(),
            *reason_evidence.as_array(),
        ]),
        reason_code: "TURN_START_UNKNOWN".to_string(),
        redacted_diagnostic: diagnostic,
    };
    let run_root = driver
        .config
        .agentd_socket
        .parent()
        .ok_or("Agentd socket omitted its exact-generation run root")?;
    let store = DurableQuarantineStore::open(
        &run_root.join("runtime-codex-quarantine-v1.sqlite3"),
        driver.config.agent_id.to_string(),
        driver.config.generation,
    )
    .await?;
    let result = store.record_unknown(&record).await;
    store.close().await;
    result?;
    Ok(())
}
'''
    if not text.rstrip().endswith("}"):
        raise RuntimeError("native_execution.rs does not end in impl brace")
    text = text.rstrip() + helper + "\n"
    return text


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/Cargo.toml", cargo)
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
        quarantine_module,
    )
    rewrite("codex-rs/hepta-infer-worker-host/src/native_execution.rs", native_execution)


if __name__ == "__main__":
    main()
