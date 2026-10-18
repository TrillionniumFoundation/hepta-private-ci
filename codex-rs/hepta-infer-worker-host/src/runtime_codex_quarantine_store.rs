//! Durable quarantine records and authority resolution transactions.

use super::*;

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
        let pool = crate::sqlite::open_durable_pool(path)
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
                key_epoch INTEGER NOT NULL CHECK (key_epoch > 0),
                verifying_key BLOB NOT NULL CHECK (length(verifying_key) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence >= 0),
                state_sha256 BLOB NOT NULL CHECK (length(state_sha256) = 32),
                PRIMARY KEY (signer_id, authority_epoch, key_epoch)
            ) STRICT"#,
            r#"CREATE TABLE IF NOT EXISTS runtime_codex_quarantine_nonces (
                signer_id TEXT NOT NULL,
                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                key_epoch INTEGER NOT NULL CHECK (key_epoch > 0),
                nonce BLOB NOT NULL CHECK (length(nonce) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence > 0),
                PRIMARY KEY (signer_id, authority_epoch, key_epoch, nonce),
                UNIQUE (signer_id, authority_epoch, key_epoch, resolution_sequence),
                FOREIGN KEY (signer_id, authority_epoch, key_epoch)
                    REFERENCES runtime_codex_quarantine_frontiers(signer_id, authority_epoch, key_epoch)
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
        let persisted_generation: i64 = row.try_get("owner_generation").map_err(quarantine_sqlx)?;
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
        let record_json = serde_json::to_vec(quarantine).map_err(|_| {
            DurableQuarantineError::Protocol(QuarantineProtocolError::EncodingFailed)
        })?;
        if record_json.len() > MAX_QUARANTINE_RECORD_BYTES {
            return Err(DurableQuarantineError::Capacity);
        }
        let record_sha256 = quarantine.record_sha256()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(quarantine_sqlx)?;
        let store_revision =
            quarantine_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
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
            let previous: QuarantinedEffectV1 =
                serde_json::from_slice(&existing_json).map_err(|error| {
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
                    .map_err(|error| {
                        DurableQuarantineError::Corrupt(format!("decode quarantine: {error}"))
                    })
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
        let store_revision =
            quarantine_store_revision(&mut tx, &self.owner_id, self.owner_generation).await?;
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
        let quarantine: QuarantinedEffectV1 =
            serde_json::from_slice(&record_json).map_err(|error| {
                DurableQuarantineError::Corrupt(format!(
                    "decode quarantine before resolution: {error}"
                ))
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

        let resolution_authority_epoch = signed.resolution.resolution_authority_epoch;
        let resolution_key_epoch = signed.resolution.resolution_key_epoch;
        let frontier_row = sqlx::query(
            r#"SELECT verifying_key, resolution_sequence, state_sha256
               FROM runtime_codex_quarantine_frontiers
               WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ?"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(
            resolution_authority_epoch,
            "resolution authority epoch",
        )?)
        .bind(quarantine_i64(
            resolution_key_epoch,
            "resolution key epoch",
        )?)
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
               WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ? ORDER BY nonce"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(
            resolution_authority_epoch,
            "resolution authority epoch",
        )?)
        .bind(quarantine_i64(
            resolution_key_epoch,
            "resolution key epoch",
        )?)
        .fetch_all(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        if nonce_rows.len() > MAX_USED_NONCES {
            return Err(DurableQuarantineError::Capacity);
        }
        let mut used_nonces = BTreeSet::new();
        for row in nonce_rows {
            used_nonces.insert(quarantine_digest(
                row.try_get::<Vec<u8>, _>("nonce")
                    .map_err(quarantine_sqlx)?,
                "quarantine nonce",
            )?);
        }
        let mut verifier = QuarantineResolutionVerifier::new(
            signer_id.clone(),
            verifying_key,
            resolution_authority_epoch,
            resolution_key_epoch,
            current_sequence,
            used_nonces,
        )?;
        let verified = verifier.verify(signed, &quarantine, now_unix_ms)?;
        let frontier = verifier.frontier();
        let resolution_json = serde_json::to_vec(signed).map_err(|_| {
            DurableQuarantineError::Protocol(QuarantineProtocolError::EncodingFailed)
        })?;
        sqlx::query(
            r#"INSERT INTO runtime_codex_quarantine_frontiers
               (signer_id, authority_epoch, key_epoch, verifying_key, resolution_sequence, state_sha256)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(signer_id, authority_epoch, key_epoch) DO UPDATE SET
                   verifying_key = excluded.verifying_key,
                   resolution_sequence = excluded.resolution_sequence,
                   state_sha256 = excluded.state_sha256
               WHERE runtime_codex_quarantine_frontiers.resolution_sequence < excluded.resolution_sequence
                 AND runtime_codex_quarantine_frontiers.verifying_key = excluded.verifying_key"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(frontier.authority_epoch, "frontier authority epoch")?)
        .bind(quarantine_i64(frontier.key_epoch, "frontier key epoch")?)
        .bind(verifying_key.as_slice())
        .bind(quarantine_i64(frontier.resolution_sequence, "frontier sequence")?)
        .bind(frontier.state_sha256.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(quarantine_sqlx)?;
        sqlx::query(
            r#"INSERT INTO runtime_codex_quarantine_nonces
               (signer_id, authority_epoch, key_epoch, nonce, resolution_sequence)
               VALUES (?, ?, ?, ?, ?)"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(
            frontier.authority_epoch,
            "nonce authority epoch",
        )?)
        .bind(quarantine_i64(frontier.key_epoch, "nonce key epoch")?)
        .bind(signed.resolution.nonce.as_slice())
        .bind(quarantine_i64(
            frontier.resolution_sequence,
            "nonce sequence",
        )?)
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
    let persisted_generation: i64 = row.try_get("owner_generation").map_err(quarantine_sqlx)?;
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

fn quarantine_digest(
    value: Vec<u8>,
    label: &'static str,
) -> Result<[u8; 32], DurableQuarantineError> {
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
    async fn durable_record_and_resolution_survive_reopen() -> Result<(), Box<dyn std::error::Error>>
    {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("quarantine.sqlite3");
        let store = DurableQuarantineStore::open(&path, "agent:test".to_string(), 3).await?;
        let quarantine = record();
        assert_eq!(
            store.record_unknown(&quarantine).await?,
            QuarantineRecordDisposition::Inserted
        );
        store.close().await;

        let store = DurableQuarantineStore::open(&path, "agent:test".to_string(), 3).await?;
        assert_eq!(
            store.active(&quarantine.operation_id).await?,
            Some(quarantine.clone())
        );
        let key = SigningKey::from_bytes(&rand::random());
        let now = quarantine_now_ms()?;
        let resolution = QuarantineResolutionV1 {
            schema_version: 1,
            signer_id: "independent-quarantine-authority".to_string(),
            resolution_id: "resolution:durable".to_string(),
            operation_id: quarantine.operation_id.clone(),
            quarantine_revision: quarantine.quarantine_revision,
            quarantine_record_sha256: quarantine.record_sha256()?,
            request_sha256: quarantine.request_sha256,
            dispatch_sha256: quarantine.local_dispatch_sha256,
            evidence_set_sha256: quarantine.evidence_set_sha256()?,
            authority_epoch: quarantine.authority_epoch,
            resolution_authority_epoch: 1,
            resolution_key_epoch: 1,
            resolution_sequence: 1,
            nonce: rand::random(),
            not_before_unix_ms: now,
            expires_at_unix_ms: now + 59_000,
            disposition: QuarantineResolutionDispositionV1::AbandonWithoutReplay,
            terminal: None,
            new_operation_constraints: None,
            reason_code: "DUAL_OPERATOR_REVIEW".to_string(),
        };
        let signature = key.sign(&resolution.signing_bytes()?).to_bytes().to_vec();
        let signed = SignedQuarantineResolutionV1 {
            resolution: resolution.clone(),
            signature,
        };
        store
            .verify_and_commit_resolution(
                resolution.signer_id.clone(),
                key.verifying_key().to_bytes(),
                &signed,
                now,
            )
            .await?;
        assert!(store.active(&quarantine.operation_id).await?.is_none());
        assert!(
            store
                .verify_and_commit_resolution(
                    resolution.signer_id.clone(),
                    key.verifying_key().to_bytes(),
                    &signed,
                    now,
                )
                .await
                .is_err()
        );
        Ok(())
    }
}
