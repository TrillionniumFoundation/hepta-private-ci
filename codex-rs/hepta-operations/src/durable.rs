//! Durable kernel.operations owner.
//!
//! This store is intentionally separate from the in-memory reference model.
//! SQLite owns crash/reopen durability and writer serialization; the transition
//! semantics remain the same: dispatch acknowledgement is never terminal and an
//! indeterminate operation remains queryable until a generation-fenced terminal
//! observation is committed.

use std::path::Path;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::MAX_MODEL_OPERATION_RECORDS;
use crate::OperationError;
use crate::OperationKey;
use crate::OperationRecord;
use crate::OperationState;
use crate::ReconciliationOutcome;

#[path = "durable_outbox.rs"]
mod durable_outbox;

pub use durable_outbox::DurableOutboxRecord;
pub use durable_outbox::DurableOutboxState;
pub use durable_outbox::MAX_DURABLE_OUTBOX_PAYLOAD_BYTES;

const SCHEMA_VERSION: i64 = 2;
const MAX_DURABLE_OPERATION_RECORDS: i64 = MAX_MODEL_OPERATION_RECORDS as i64;

const SELECT_RECORD: &str = r#"
SELECT operation_id, payload_digest, destination_id, context_digest,
       owner_generation, revision, state,
       authority_evidence_digest, authority_generation, dispatch_digest,
       indeterminate_reason_digest, terminal_evidence_digest
FROM hepta_operation_ledger_v1
WHERE operation_id = ?
"#;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationBinding {
    pub key: OperationKey,
    pub destination_id: StableId,
    pub context_digest: Digest32,
}

impl DurableOperationBinding {
    fn validate(&self) -> Result<(), OperationError> {
        self.key.validate()?;
        if self.context_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation context"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub operation: OperationRecord,
    pub destination_id: StableId,
    pub context_digest: Digest32,
    pub authority_evidence_digest: Option<Digest32>,
    pub authority_generation: Option<Generation>,
    pub dispatch_digest: Option<Digest32>,
    pub indeterminate_reason_digest: Option<Digest32>,
    pub terminal_evidence_digest: Option<Digest32>,
}

#[derive(Clone, Debug)]
pub struct DurableOperationLedger {
    pool: SqlitePool,
}

impl DurableOperationLedger {
    pub async fn open(path: &Path) -> Result<Self, OperationError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|_| OperationError::StorageUnavailable)?;
        }
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(options)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;

        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS hepta_operation_ledger_schema (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                version INTEGER NOT NULL
            )
            "#,
        )
        .execute(&pool)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
        sqlx::query(
            "INSERT OR IGNORE INTO hepta_operation_ledger_schema(singleton, version) VALUES (1, ?)",
        )
        .bind(SCHEMA_VERSION)
        .execute(&pool)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
        let version =
            sqlx::query_scalar::<_, i64>("SELECT version FROM hepta_operation_ledger_schema WHERE singleton = 1")
                .fetch_one(&pool)
                .await
                .map_err(|_| OperationError::StorageUnavailable)?;
        if version != SCHEMA_VERSION {
            return Err(OperationError::CorruptStore("schema version"));
        }

        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS hepta_operation_ledger_v1 (
                operation_id TEXT PRIMARY KEY NOT NULL,
                payload_digest BLOB NOT NULL CHECK(length(payload_digest) = 32),
                destination_id TEXT NOT NULL,
                context_digest BLOB NOT NULL CHECK(length(context_digest) = 32),
                owner_generation TEXT NOT NULL,
                revision TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN (
                    'pending', 'authorized', 'dispatched', 'indeterminate',
                    'applied', 'not_applied', 'quarantined'
                )),
                authority_evidence_digest BLOB CHECK(
                    authority_evidence_digest IS NULL OR length(authority_evidence_digest) = 32
                ),
                authority_generation TEXT,
                dispatch_digest BLOB CHECK(
                    dispatch_digest IS NULL OR length(dispatch_digest) = 32
                ),
                indeterminate_reason_digest BLOB CHECK(
                    indeterminate_reason_digest IS NULL OR length(indeterminate_reason_digest) = 32
                ),
                terminal_evidence_digest BLOB CHECK(
                    terminal_evidence_digest IS NULL OR length(terminal_evidence_digest) = 32
                )
            )
            "#,
        )
        .execute(&pool)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;

        durable_outbox::initialize(&pool).await?;

        let journal_mode = sqlx::query_scalar::<_, String>("PRAGMA journal_mode")
            .fetch_one(&pool)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        if !journal_mode.eq_ignore_ascii_case("wal") {
            return Err(OperationError::CorruptStore("journal mode"));
        }
        let synchronous = sqlx::query_scalar::<_, i64>("PRAGMA synchronous")
            .fetch_one(&pool)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        if synchronous != 2 {
            return Err(OperationError::CorruptStore("synchronous mode"));
        }
        let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check")
            .fetch_one(&pool)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        if quick_check != "ok" {
            return Err(OperationError::CorruptStore("quick_check"));
        }

        Ok(Self { pool })
    }

    pub async fn begin(
        &self,
        key: OperationKey,
        owner_generation: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        let binding = DurableOperationBinding {
            context_digest: key.payload_digest,
            destination_id: StableId::new("kernel.operations.reference")
                .map_err(|_| OperationError::CorruptStore("reference destination"))?,
            key,
        };
        self.begin_bound(binding, owner_generation).await
    }

    pub async fn begin_bound(
        &self,
        binding: DurableOperationBinding,
        owner_generation: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        binding.validate()?;
        let key = binding.key.clone();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        if let Some(existing) = load_in_transaction(&mut tx, &key.id).await? {
            if existing.operation.key == key
                && existing.destination_id == binding.destination_id
                && existing.context_digest == binding.context_digest
                && existing.operation.owner_generation == owner_generation
            {
                tx.commit()
                    .await
                    .map_err(|_| OperationError::StorageUnavailable)?;
                return Ok(existing);
            }
            return Err(OperationError::Conflict(key.id));
        }
        let count = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM hepta_operation_ledger_v1")
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        if count >= MAX_DURABLE_OPERATION_RECORDS {
            return Err(OperationError::CapacityExceeded {
                resource: "durable operation ledger",
                maximum: MAX_MODEL_OPERATION_RECORDS,
            });
        }

        let record = DurableOperationRecord {
            operation: OperationRecord {
                key,
                owner_generation,
                revision: revision(1)?,
                state: OperationState::Pending,
            },
            destination_id: binding.destination_id,
            context_digest: binding.context_digest,
            authority_evidence_digest: None,
            authority_generation: None,
            dispatch_digest: None,
            indeterminate_reason_digest: None,
            terminal_evidence_digest: None,
        };
        insert_record(&mut tx, &record).await?;
        tx.commit()
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        Ok(record)
    }

    /// Persist evidence that an external kernel.authority consumer admitted the
    /// exact operation. This method does not authenticate or authorize by itself.
    /// Product hosts must call it only after their real final-use verifier has
    /// admitted the exact final payload.
    pub async fn record_authority_evidence(
        &self,
        operation_id: &StableId,
        evidence_digest: Digest32,
        authority_generation: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if evidence_digest.is_zero() {
            return Err(OperationError::InvalidDigest("authority evidence"));
        }
        self.transition(operation_id, |mut record| {
            match record.operation.state.clone() {
                OperationState::Pending => {
                    advance(&mut record.operation)?;
                    record.operation.state = OperationState::Authorized {
                        witness_digest: evidence_digest,
                        authority_generation,
                    };
                    record.authority_evidence_digest = Some(evidence_digest);
                    record.authority_generation = Some(authority_generation);
                }
                OperationState::Authorized {
                    witness_digest,
                    authority_generation: existing_generation,
                } if witness_digest == evidence_digest
                    && existing_generation == authority_generation =>
                {
                    return Ok(record);
                }
                ref state if state.is_terminal() => return Err(OperationError::Terminal),
                ref state => return invalid(state, "authorized"),
            }
            Ok(record)
        })
        .await
    }

    /// Atomically persist the admitted authority lineage and the dispatch
    /// intent before the product host crosses the real owner/effect boundary.
    /// This removes the crash window between an Authorized row and a dispatch
    /// attempt while keeping the final outcome non-terminal.
    pub async fn record_authorized_dispatch(
        &self,
        operation_id: &StableId,
        evidence_digest: Digest32,
        authority_generation: Generation,
        dispatch_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if evidence_digest.is_zero() {
            return Err(OperationError::InvalidDigest("authority evidence"));
        }
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch"));
        }
        self.transition(operation_id, |mut record| {
            match record.operation.state.clone() {
                OperationState::Pending => {
                    advance(&mut record.operation)?;
                    advance(&mut record.operation)?;
                    record.operation.state = OperationState::Dispatched { dispatch_digest };
                    record.authority_evidence_digest = Some(evidence_digest);
                    record.authority_generation = Some(authority_generation);
                    record.dispatch_digest = Some(dispatch_digest);
                }
                OperationState::Authorized {
                    witness_digest,
                    authority_generation: existing_generation,
                } if witness_digest == evidence_digest
                    && existing_generation == authority_generation =>
                {
                    advance(&mut record.operation)?;
                    record.operation.state = OperationState::Dispatched { dispatch_digest };
                    record.dispatch_digest = Some(dispatch_digest);
                }
                OperationState::Dispatched {
                    dispatch_digest: existing,
                } if existing == dispatch_digest
                    && record.authority_evidence_digest == Some(evidence_digest)
                    && record.authority_generation == Some(authority_generation) =>
                {
                    return Ok(record);
                }
                ref state if state.is_terminal() => return Err(OperationError::Terminal),
                ref state => return invalid(state, "authorized_dispatch"),
            }
            Ok(record)
        })
        .await
    }

    pub async fn record_dispatch(
        &self,
        operation_id: &StableId,
        dispatch_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch"));
        }
        self.transition(operation_id, |mut record| {
            match record.operation.state.clone() {
                OperationState::Authorized { .. } => {
                    advance(&mut record.operation)?;
                    record.operation.state = OperationState::Dispatched { dispatch_digest };
                    record.dispatch_digest = Some(dispatch_digest);
                }
                OperationState::Dispatched {
                    dispatch_digest: existing,
                } if existing == dispatch_digest => return Ok(record),
                ref state if state.is_terminal() => return Err(OperationError::Terminal),
                ref state => return invalid(state, "dispatched"),
            }
            Ok(record)
        })
        .await
    }

    pub async fn mark_indeterminate(
        &self,
        operation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason"));
        }
        self.transition(operation_id, |mut record| {
            match record.operation.state.clone() {
                OperationState::Dispatched { .. } => {
                    advance(&mut record.operation)?;
                    record.operation.state = OperationState::Indeterminate { reason_digest };
                    record.indeterminate_reason_digest = Some(reason_digest);
                }
                OperationState::Indeterminate {
                    reason_digest: existing,
                } if existing == reason_digest => return Ok(record),
                ref state if state.is_terminal() => return Err(OperationError::Terminal),
                ref state => return invalid(state, "indeterminate"),
            }
            Ok(record)
        })
        .await
    }

    pub async fn observe_terminal(
        &self,
        operation_id: &StableId,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
        observer_generation: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if outcome_digest.is_zero() {
            return Err(OperationError::InvalidDigest("terminal outcome"));
        }
        self.transition(operation_id, |mut record| {
            if observer_generation != record.operation.owner_generation {
                return Err(OperationError::StaleGeneration);
            }
            if terminal_matches(&record.operation.state, outcome, outcome_digest) {
                return Ok(record);
            }
            match record.operation.state.clone() {
                OperationState::Dispatched { .. } | OperationState::Indeterminate { .. } => {
                    advance(&mut record.operation)?;
                    record.operation.state = terminal_state(outcome, outcome_digest);
                    record.terminal_evidence_digest = Some(outcome_digest);
                }
                ref state if state.is_terminal() => return Err(OperationError::Terminal),
                ref state => return invalid(state, "terminal_observation"),
            }
            Ok(record)
        })
        .await
    }

    pub async fn get(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<DurableOperationRecord>, OperationError> {
        let row = sqlx::query(SELECT_RECORD)
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        row.map(decode_record).transpose()
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    async fn transition(
        &self,
        operation_id: &StableId,
        apply: impl FnOnce(DurableOperationRecord) -> Result<DurableOperationRecord, OperationError>,
    ) -> Result<DurableOperationRecord, OperationError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        let current = load_in_transaction(&mut tx, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        let next = apply(current)?;
        update_record(&mut tx, &next).await?;
        tx.commit()
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        Ok(next)
    }
}

async fn load_in_transaction(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<DurableOperationRecord>, OperationError> {
    let row = sqlx::query(SELECT_RECORD)
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
    row.map(decode_record).transpose()
}

async fn insert_record(
    tx: &mut Transaction<'_, Sqlite>,
    record: &DurableOperationRecord,
) -> Result<(), OperationError> {
    let columns = encoded_state(record);
    sqlx::query(
        r#"
        INSERT INTO hepta_operation_ledger_v1(
            operation_id, payload_digest, destination_id, context_digest,
            owner_generation, revision, state, authority_evidence_digest,
            authority_generation, dispatch_digest, indeterminate_reason_digest,
            terminal_evidence_digest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        "#,
    )
    .bind(record.operation.key.id.as_str())
    .bind(record.operation.key.payload_digest.as_array().to_vec())
    .bind(record.destination_id.as_str())
    .bind(record.context_digest.as_array().to_vec())
    .bind(record.operation.owner_generation.get().to_string())
    .bind(record.operation.revision.get().to_string())
    .bind(columns.state)
    .bind(columns.authority_evidence)
    .bind(columns.authority_generation)
    .bind(columns.dispatch)
    .bind(columns.indeterminate)
    .bind(columns.terminal)
    .execute(&mut **tx)
    .await
    .map_err(|_| OperationError::StorageUnavailable)?;
    Ok(())
}

async fn update_record(
    tx: &mut Transaction<'_, Sqlite>,
    record: &DurableOperationRecord,
) -> Result<(), OperationError> {
    let columns = encoded_state(record);
    let result = sqlx::query(
        r#"
        UPDATE hepta_operation_ledger_v1
        SET revision = ?, state = ?, authority_evidence_digest = ?,
            authority_generation = ?, dispatch_digest = ?,
            indeterminate_reason_digest = ?, terminal_evidence_digest = ?
        WHERE operation_id = ? AND payload_digest = ? AND destination_id = ?
          AND context_digest = ? AND owner_generation = ?
        "#,
    )
    .bind(record.operation.revision.get().to_string())
    .bind(columns.state)
    .bind(columns.authority_evidence)
    .bind(columns.authority_generation)
    .bind(columns.dispatch)
    .bind(columns.indeterminate)
    .bind(columns.terminal)
    .bind(record.operation.key.id.as_str())
    .bind(record.operation.key.payload_digest.as_array().to_vec())
    .bind(record.destination_id.as_str())
    .bind(record.context_digest.as_array().to_vec())
    .bind(record.operation.owner_generation.get().to_string())
    .execute(&mut **tx)
    .await
    .map_err(|_| OperationError::StorageUnavailable)?;
    if result.rows_affected() != 1 {
        return Err(OperationError::CorruptStore("operation update identity"));
    }
    Ok(())
}

struct EncodedState {
    state: &'static str,
    authority_evidence: Option<Vec<u8>>,
    authority_generation: Option<String>,
    dispatch: Option<Vec<u8>>,
    indeterminate: Option<Vec<u8>>,
    terminal: Option<Vec<u8>>,
}

fn encoded_state(record: &DurableOperationRecord) -> EncodedState {
    EncodedState {
        state: record.operation.state.label(),
        authority_evidence: record
            .authority_evidence_digest
            .map(|digest| digest.as_array().to_vec()),
        authority_generation: record
            .authority_generation
            .map(|generation| generation.get().to_string()),
        dispatch: record.dispatch_digest.map(|digest| digest.as_array().to_vec()),
        indeterminate: record
            .indeterminate_reason_digest
            .map(|digest| digest.as_array().to_vec()),
        terminal: record
            .terminal_evidence_digest
            .map(|digest| digest.as_array().to_vec()),
    }
}

fn decode_record(row: sqlx::sqlite::SqliteRow) -> Result<DurableOperationRecord, OperationError> {
    let operation_id = stable_id(row.try_get("operation_id").map_err(storage)?, "operation id")?;
    let payload_digest = digest_blob(row.try_get("payload_digest").map_err(storage)?, "payload digest")?;
    let destination_id = stable_id(
        row.try_get("destination_id").map_err(storage)?,
        "destination id",
    )?;
    let context_digest =
        digest_blob(row.try_get("context_digest").map_err(storage)?, "context digest")?;
    let owner_generation = generation_text(row.try_get("owner_generation").map_err(storage)?, "owner generation")?;
    let revision = revision_text(row.try_get("revision").map_err(storage)?, "revision")?;
    let state: String = row.try_get("state").map_err(storage)?;
    let authority_evidence_digest =
        optional_digest(row.try_get("authority_evidence_digest").map_err(storage)?, "authority evidence")?;
    let authority_generation = optional_generation(
        row.try_get("authority_generation").map_err(storage)?,
        "authority generation",
    )?;
    let dispatch_digest = optional_digest(row.try_get("dispatch_digest").map_err(storage)?, "dispatch digest")?;
    let indeterminate_reason_digest = optional_digest(
        row.try_get("indeterminate_reason_digest").map_err(storage)?,
        "indeterminate reason",
    )?;
    let terminal_evidence_digest =
        optional_digest(row.try_get("terminal_evidence_digest").map_err(storage)?, "terminal evidence")?;

    let operation_state = match state.as_str() {
        "pending" => OperationState::Pending,
        "authorized" => OperationState::Authorized {
            witness_digest: authority_evidence_digest
                .ok_or(OperationError::CorruptStore("authorized evidence"))?,
            authority_generation: authority_generation
                .ok_or(OperationError::CorruptStore("authorized generation"))?,
        },
        "dispatched" => OperationState::Dispatched {
            dispatch_digest: dispatch_digest
                .ok_or(OperationError::CorruptStore("dispatch evidence"))?,
        },
        "indeterminate" => OperationState::Indeterminate {
            reason_digest: indeterminate_reason_digest
                .ok_or(OperationError::CorruptStore("indeterminate evidence"))?,
        },
        "applied" => OperationState::Applied {
            outcome_digest: terminal_evidence_digest
                .ok_or(OperationError::CorruptStore("terminal evidence"))?,
        },
        "not_applied" => OperationState::NotApplied {
            outcome_digest: terminal_evidence_digest
                .ok_or(OperationError::CorruptStore("terminal evidence"))?,
        },
        "quarantined" => OperationState::Quarantined {
            reason_digest: terminal_evidence_digest
                .ok_or(OperationError::CorruptStore("terminal evidence"))?,
        },
        _ => return Err(OperationError::CorruptStore("operation state")),
    };

    if !matches!(&operation_state, OperationState::Pending)
        && (authority_evidence_digest.is_none() || authority_generation.is_none())
    {
        return Err(OperationError::CorruptStore("missing authority lineage"));
    }
    if matches!(
        &operation_state,
        OperationState::Dispatched { .. }
            | OperationState::Indeterminate { .. }
            | OperationState::Applied { .. }
            | OperationState::NotApplied { .. }
            | OperationState::Quarantined { .. }
    ) && dispatch_digest.is_none()
    {
        return Err(OperationError::CorruptStore("missing dispatch lineage"));
    }

    Ok(DurableOperationRecord {
        operation: OperationRecord {
            key: OperationKey {
                id: operation_id,
                payload_digest,
            },
            owner_generation,
            revision,
            state: operation_state,
        },
        destination_id,
        context_digest,
        authority_evidence_digest,
        authority_generation,
        dispatch_digest,
        indeterminate_reason_digest,
        terminal_evidence_digest,
    })
}

fn stable_id(value: String, field: &'static str) -> Result<StableId, OperationError> {
    StableId::new(value).map_err(|_| OperationError::CorruptStore(field))
}

fn generation_text(value: String, field: &'static str) -> Result<Generation, OperationError> {
    let value = value
        .parse::<u64>()
        .map_err(|_| OperationError::CorruptStore(field))?;
    Generation::new(value).map_err(|_| OperationError::CorruptStore(field))
}

fn revision_text(value: String, field: &'static str) -> Result<Revision, OperationError> {
    let value = value
        .parse::<u64>()
        .map_err(|_| OperationError::CorruptStore(field))?;
    Revision::new(value).map_err(|_| OperationError::CorruptStore(field))
}

fn optional_generation(
    value: Option<String>,
    field: &'static str,
) -> Result<Option<Generation>, OperationError> {
    value.map(|value| generation_text(value, field)).transpose()
}

fn digest_blob(value: Vec<u8>, field: &'static str) -> Result<Digest32, OperationError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| OperationError::CorruptStore(field))?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(OperationError::CorruptStore(field));
    }
    Ok(digest)
}

fn optional_digest(
    value: Option<Vec<u8>>,
    field: &'static str,
) -> Result<Option<Digest32>, OperationError> {
    value.map(|value| digest_blob(value, field)).transpose()
}

fn storage(_: sqlx::Error) -> OperationError {
    OperationError::StorageUnavailable
}

fn revision(value: u64) -> Result<Revision, OperationError> {
    Revision::new(value).map_err(|_| OperationError::CorruptStore("revision"))
}

fn advance(record: &mut OperationRecord) -> Result<(), OperationError> {
    record.revision = record
        .revision
        .next()
        .map_err(|_| OperationError::Conflict(record.key.id.clone()))?;
    Ok(())
}

fn terminal_state(outcome: ReconciliationOutcome, digest: Digest32) -> OperationState {
    match outcome {
        ReconciliationOutcome::Applied => OperationState::Applied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::NotApplied => OperationState::NotApplied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::Quarantined => OperationState::Quarantined {
            reason_digest: digest,
        },
    }
}

fn terminal_matches(
    state: &OperationState,
    outcome: ReconciliationOutcome,
    digest: Digest32,
) -> bool {
    matches!(
        (state, outcome),
        (
            OperationState::Applied {
                outcome_digest: existing
            },
            ReconciliationOutcome::Applied
        ) if *existing == digest
    ) || matches!(
        (state, outcome),
        (
            OperationState::NotApplied {
                outcome_digest: existing
            },
            ReconciliationOutcome::NotApplied
        ) if *existing == digest
    ) || matches!(
        (state, outcome),
        (
            OperationState::Quarantined {
                reason_digest: existing
            },
            ReconciliationOutcome::Quarantined
        ) if *existing == digest
    )
}

fn invalid<T>(state: &OperationState, to: &'static str) -> Result<T, OperationError> {
    Err(OperationError::InvalidTransition {
        from: state.label(),
        to,
    })
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
