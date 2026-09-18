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

use crate::DestinationApplyDisposition;
use crate::DestinationApplyReceipt;
use crate::DestinationOperationIdentity;
use crate::DurableOperationError;
use crate::MAX_DURABLE_PENDING_OPERATIONS;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

static DESTINATION_MIGRATOR: sqlx::migrate::Migrator =
    sqlx::migrate!("./destination_migrations");

#[derive(Clone)]
pub struct DestinationDedupeStore {
    pool: SqlitePool,
    standalone_path: Option<PathBuf>,
}

impl DestinationDedupeStore {
    /// Standalone qualification/store mode. Product owners should normally add
    /// the table to their own migration lineage and call `from_migrated_pool`.
    pub async fn open_standalone(path: &Path) -> Result<Self, DurableOperationError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
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
            .map_err(sqlx_error)?;
        if let Err(error) = DESTINATION_MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(DurableOperationError::Corrupt(format!(
                "destination dedupe migration failed: {error}"
            )));
        }
        verify_table(&pool).await?;
        Ok(Self {
            pool,
            standalone_path: Some(path.to_path_buf()),
        })
    }

    /// Bind the dedupe component to a destination owner's already-migrated pool.
    /// The owner must install the exact `destination_operation_dedupe` schema in
    /// its own migration lineage. This preserves owner data authority and lets
    /// the domain mutation use the same SQLite transaction as the dedupe row.
    pub async fn from_migrated_pool(pool: SqlitePool) -> Result<Self, DurableOperationError> {
        verify_table(&pool).await?;
        Ok(Self {
            pool,
            standalone_path: None,
        })
    }

    pub fn standalone_path(&self) -> Option<&Path> {
        self.standalone_path.as_deref()
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    /// Acquire the destination write lock and determine whether the exact
    /// semantic identity is already applied. The returned transaction remains
    /// open so the destination owner can mutate its domain tables and then call
    /// `commit_applied`; both writes commit or roll back together.
    pub async fn begin_apply(
        &self,
        identity: &DestinationOperationIdentity,
    ) -> Result<DestinationApplyStart, DurableOperationError> {
        identity.validate()?;
        let semantic_digest = identity.semantic_digest();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        if let Some(row) = sqlx::query(
            "SELECT destination, scope_id, operation_id, semantic_digest, payload_digest,
                    outcome_digest, applied_at_ms
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(identity.destination.as_str())
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        {
            let receipt = decode_receipt(&row)?;
            if receipt.semantic_digest != semantic_digest
                || receipt.identity.payload_digest != identity.payload_digest
            {
                return Err(DurableOperationError::Conflict(identity.operation_id.clone()));
            }
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(DestinationApplyStart::AlreadyApplied(receipt));
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM destination_operation_dedupe")
            .fetch_one(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        if count >= MAX_DURABLE_PENDING_OPERATIONS {
            return Err(DurableOperationError::Capacity);
        }
        Ok(DestinationApplyStart::Apply(DestinationApplyTransaction {
            tx: Some(tx),
            identity: identity.clone(),
            semantic_digest,
        }))
    }

    pub async fn observe(
        &self,
        identity: &DestinationOperationIdentity,
    ) -> Result<Option<DestinationApplyReceipt>, DurableOperationError> {
        identity.validate()?;
        let row = sqlx::query(
            "SELECT destination, scope_id, operation_id, semantic_digest, payload_digest,
                    outcome_digest, applied_at_ms
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(identity.destination.as_str())
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(sqlx_error)?;
        row.map(|row| decode_receipt(&row)).transpose()
    }
}

pub enum DestinationApplyStart {
    AlreadyApplied(DestinationApplyReceipt),
    Apply(DestinationApplyTransaction),
}

impl DestinationApplyStart {
    pub const fn disposition(&self) -> DestinationApplyDisposition {
        match self {
            Self::AlreadyApplied(_) => DestinationApplyDisposition::AlreadyApplied,
            Self::Apply(_) => DestinationApplyDisposition::Applied,
        }
    }
}

/// Destination-owned transaction. Domain SQL performed through `transaction`
/// and the dedupe receipt written by `commit_applied` are one atomic commit.
pub struct DestinationApplyTransaction {
    tx: Option<Transaction<'static, Sqlite>>,
    identity: DestinationOperationIdentity,
    semantic_digest: Digest32,
}

impl DestinationApplyTransaction {
    pub fn transaction(&mut self) -> Result<&mut Transaction<'static, Sqlite>, DurableOperationError> {
        self.tx.as_mut().ok_or_else(|| {
            DurableOperationError::Unavailable("destination transaction already completed".to_owned())
        })
    }

    pub fn identity(&self) -> &DestinationOperationIdentity {
        &self.identity
    }

    pub async fn commit_applied(
        mut self,
        outcome_digest: Digest32,
    ) -> Result<DestinationApplyReceipt, DurableOperationError> {
        if outcome_digest.is_zero() {
            return Err(DurableOperationError::Invalid("destination outcome digest"));
        }
        let applied_at = now_millis()?;
        let mut tx = self.tx.take().ok_or_else(|| {
            DurableOperationError::Unavailable("destination transaction already completed".to_owned())
        })?;
        sqlx::query(
            "INSERT INTO destination_operation_dedupe (
                destination, scope_id, operation_id, semantic_digest, payload_digest,
                outcome_digest, applied_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.identity.destination.as_str())
        .bind(self.identity.scope_id.as_str())
        .bind(self.identity.operation_id.as_str())
        .bind(self.semantic_digest.as_array().as_slice())
        .bind(self.identity.payload_digest.as_array().as_slice())
        .bind(outcome_digest.as_array().as_slice())
        .bind(applied_at)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(DestinationApplyReceipt {
            identity: self.identity,
            semantic_digest: self.semantic_digest,
            outcome_digest,
            applied_at_unix_ms: to_u64(applied_at)?,
        })
    }

    pub async fn rollback(mut self) -> Result<(), DurableOperationError> {
        let tx = self.tx.take().ok_or_else(|| {
            DurableOperationError::Unavailable("destination transaction already completed".to_owned())
        })?;
        tx.rollback().await.map_err(sqlx_error)
    }
}

async fn verify_table(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name = 'destination_operation_dedupe'",
    )
    .fetch_one(pool)
    .await
    .map_err(sqlx_error)?;
    if count != 1 {
        return Err(DurableOperationError::Corrupt(
            "destination_operation_dedupe table is missing".to_owned(),
        ));
    }
    let quick: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_all(pool)
        .await
        .map_err(sqlx_error)?;
    if quick.as_slice() != ["ok"] {
        return Err(DurableOperationError::Corrupt(format!(
            "destination quick_check failed: {}",
            quick.join("; ")
        )));
    }
    Ok(())
}

fn decode_receipt(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<DestinationApplyReceipt, DurableOperationError> {
    let destination = parse_id(row.try_get("destination").map_err(sqlx_error)?)?;
    let scope_id = parse_id(row.try_get("scope_id").map_err(sqlx_error)?)?;
    let operation_id = parse_id(row.try_get("operation_id").map_err(sqlx_error)?)?;
    let payload_digest = decode_digest(row.try_get("payload_digest").map_err(sqlx_error)?)?;
    Ok(DestinationApplyReceipt {
        identity: DestinationOperationIdentity {
            destination,
            scope_id,
            operation_id,
            payload_digest,
        },
        semantic_digest: decode_digest(row.try_get("semantic_digest").map_err(sqlx_error)?)?,
        outcome_digest: decode_digest(row.try_get("outcome_digest").map_err(sqlx_error)?)?,
        applied_at_unix_ms: to_u64(row.try_get("applied_at_ms").map_err(sqlx_error)?)?,
    })
}

fn decode_digest(value: Vec<u8>) -> Result<Digest32, DurableOperationError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| DurableOperationError::Corrupt("invalid digest width".to_owned()))?;
    Ok(Digest32::from_array(bytes))
}

fn parse_id(value: String) -> Result<StableId, DurableOperationError> {
    StableId::new(value).map_err(|error| DurableOperationError::Corrupt(error.to_string()))
}

fn now_millis() -> Result<i64, DurableOperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?
        .as_millis();
    i64::try_from(millis).map_err(|_| DurableOperationError::Capacity)
}

fn to_u64(value: i64) -> Result<u64, DurableOperationError> {
    u64::try_from(value).map_err(|_| DurableOperationError::Corrupt("negative integer".to_owned()))
}

fn sqlx_error(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
#[path = "destination_dedupe_tests.rs"]
mod tests;
