//! Async SQLite production owner for HeptaBao metadata operations.
//!
//! The JSON owner remains a bounded reference/migration oracle. This owner uses
//! WAL/FULL SQLite transactions, immutable operation identities, generation CAS,
//! append-only transitions, a reconciliation queue and terminal archival. It
//! stores no provider token or secret value.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::fs;
use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::BaoConsumptionOperationV1;
use crate::BaoConsumptionStateV1;
use crate::LeaseOperationStateV1;
use crate::LeaseOperationV1;
use crate::LeaseRegistryMigrationSnapshotV1;
use crate::SecretLeaseMetadataV1;
use crate::SecretLeaseStateV1;

const MAX_ACTIVE_OPERATIONS: i64 = 65_536;
const MAX_RECONCILIATION_ROWS: i64 = 65_536;
const MAX_ARCHIVED_TERMINALS: i64 = 1_048_576;
const MAX_ROW_BYTES: usize = 128 * 1024;
const SCHEMA_VERSION: u32 = 2;
const RUNTIME_SAMPLE_LIMIT: usize = 256;
const MAX_RECOVERY_LEASE_MS: u64 = 5 * 60 * 1000;

// Stream the exact checkpoint preimage without allocating a copy of owner rows.
#[derive(Default)]
struct Digest32Builder(Sha256);
impl Digest32Builder {
    fn update(&mut self, bytes: &[u8]) {
        self.0.update(bytes);
    }
    fn finish(self) -> Digest32 {
        Digest32::from_array(self.0.finalize().into())
    }
}

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoOwnerCheckpointV1 {
    pub generation: u64,
    pub state_sha256: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteConsumptionRecordV1 {
    pub operation: BaoConsumptionOperationV1,
    pub revision: u64,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteConsumptionClaimV1 {
    pub record: SqliteConsumptionRecordV1,
    pub inserted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteLeaseOperationRecordV1 {
    pub operation: LeaseOperationV1,
    pub revision: u64,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
}

#[derive(Clone, Eq, PartialEq)]
pub struct SqliteBaoOwnerImportReceiptV1 {
    pub source_revision: u64,
    pub source_sha256: [u8; 32],
    pub imported_at_unix_ms: u64,
    pub checkpoint: BaoOwnerCheckpointV1,
}

impl std::fmt::Debug for SqliteBaoOwnerImportReceiptV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SqliteBaoOwnerImportReceiptV1")
            .field("source_revision", &self.source_revision)
            .field("source_sha256", &"[SENSITIVE DIGEST]")
            .field("imported_at_unix_ms", &self.imported_at_unix_ms)
            .field("checkpoint_generation", &self.checkpoint.generation)
            .field("checkpoint_state_sha256", &"[SENSITIVE DIGEST]")
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteReconciliationClaimV1 {
    pub worker_id: String,
    pub record: SqliteConsumptionRecordV1,
    pub claim_generation: u64,
    pub claim_until_unix_ms: u64,
    pub attempt_count: u64,
}

/// A newly inserted product operation plus the same-transaction execution
/// lease that prevents a recovery worker from sealing or cancelling it while
/// the forward path is still active. Exact retries never acquire this lease.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteConsumptionExecutionClaimV1 {
    pub claim: SqliteConsumptionClaimV1,
    pub execution: Option<SqliteReconciliationClaimV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteBaoOwnerRuntimeMetricsV1 {
    pub transaction_attempts: u64,
    pub confirmed_transactions: u64,
    pub indeterminate_transactions: u64,
    pub writer_fence_events: u64,
    pub last_begin_wait_micros: u64,
    pub max_begin_wait_micros: u64,
    pub p50_begin_wait_micros: u64,
    pub p95_begin_wait_micros: u64,
    pub p99_begin_wait_micros: u64,
    pub last_commit_duration_micros: u64,
    pub max_commit_duration_micros: u64,
    pub p50_commit_duration_micros: u64,
    pub p95_commit_duration_micros: u64,
    pub p99_commit_duration_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteBaoOwnerMetricsV1 {
    pub operation_count: u64,
    pub active_consumption_count: u64,
    pub terminal_archive_count: u64,
    pub transition_count: u64,
    pub reconciliation_queue_count: u64,
    pub claimed_reconciliation_count: u64,
    pub oldest_due_reconciliation_age_ms: Option<u64>,
    pub max_reconciliation_attempts: u64,
    pub pending_by_state: BTreeMap<BaoConsumptionStateV1, u64>,
    pub pending_by_recovery_action: BTreeMap<crate::BaoConsumptionRecoveryActionV1, u64>,
    pub pending_quota_amount: u64,
    pub post_dispatch_without_receipt: u64,
    pub observer_pending: u64,
    pub settlement_pending: u64,
    pub oldest_pending_age_ms: Option<u64>,
    pub database_bytes: u64,
    pub wal_bytes: u64,
    pub shm_bytes: u64,
    pub fenced: bool,
    pub provider_dynamic_execution_blocked: bool,
    pub runtime: SqliteBaoOwnerRuntimeMetricsV1,
}

#[derive(Debug, thiserror::Error)]
pub enum SqliteBaoOwnerErrorV1 {
    #[error("invalid owner input")]
    InvalidInput,
    #[error("operation identity or semantics conflict")]
    OperationConflict,
    #[error("operation was not found")]
    OperationNotFound,
    #[error("invalid durable transition")]
    InvalidTransition,
    #[error("owner revision conflict")]
    RevisionConflict,
    #[error("provider or durable observation mismatch")]
    ObservationMismatch,
    #[error("owner capacity exceeded")]
    CapacityExceeded,
    #[error("another worker is already executing this operation")]
    WriterBusy,
    #[error("transaction commit outcome is indeterminate: {0}")]
    CommitIndeterminate(String),
    #[error("external checkpoint publication failed")]
    ExternalCheckpointUnavailable,
    #[error("reference-owner migration conflicts with existing SQLite state")]
    MigrationConflict,
    #[error("owner state is corrupt: {0}")]
    CorruptState(&'static str),
    #[error("external checkpoint does not match local authoritative state")]
    RollbackDetected,
    #[error("owner is fenced after an uncertain write")]
    Fenced,
    #[error("SQLite owner is unsupported on this platform")]
    UnsupportedPlatform,
    #[error("SQLite owner storage path violates the private-owner contract: {0}")]
    UnsafeStorage(&'static str),
    #[error("SQLite owner unavailable: {0}")]
    Storage(String),
}

#[derive(Default)]
struct SqliteBaoOwnerRuntimeMetricsOwnerV1 {
    transaction_attempts: u64,
    confirmed_transactions: u64,
    indeterminate_transactions: u64,
    writer_fence_events: u64,
    last_begin_wait_micros: u64,
    max_begin_wait_micros: u64,
    begin_wait_samples_micros: VecDeque<u64>,
    last_commit_duration_micros: u64,
    max_commit_duration_micros: u64,
    commit_duration_samples_micros: VecDeque<u64>,
}

impl SqliteBaoOwnerRuntimeMetricsOwnerV1 {
    fn record_begin_wait(&mut self, started: Instant) {
        let micros = elapsed_micros(started);
        self.last_begin_wait_micros = micros;
        self.max_begin_wait_micros = self.max_begin_wait_micros.max(micros);
        push_sample(&mut self.begin_wait_samples_micros, micros);
    }

    fn record_commit(&mut self, started: Instant, confirmed: bool) {
        self.transaction_attempts = self.transaction_attempts.saturating_add(1);
        if confirmed {
            self.confirmed_transactions = self.confirmed_transactions.saturating_add(1);
        } else {
            self.indeterminate_transactions = self.indeterminate_transactions.saturating_add(1);
            self.writer_fence_events = self.writer_fence_events.saturating_add(1);
        }
        let micros = elapsed_micros(started);
        self.last_commit_duration_micros = micros;
        self.max_commit_duration_micros = self.max_commit_duration_micros.max(micros);
        push_sample(&mut self.commit_duration_samples_micros, micros);
    }

    fn snapshot(&self) -> SqliteBaoOwnerRuntimeMetricsV1 {
        let begin = sorted_samples(&self.begin_wait_samples_micros);
        let commit = sorted_samples(&self.commit_duration_samples_micros);
        SqliteBaoOwnerRuntimeMetricsV1 {
            transaction_attempts: self.transaction_attempts,
            confirmed_transactions: self.confirmed_transactions,
            indeterminate_transactions: self.indeterminate_transactions,
            writer_fence_events: self.writer_fence_events,
            last_begin_wait_micros: self.last_begin_wait_micros,
            max_begin_wait_micros: self.max_begin_wait_micros,
            p50_begin_wait_micros: percentile(&begin, 50),
            p95_begin_wait_micros: percentile(&begin, 95),
            p99_begin_wait_micros: percentile(&begin, 99),
            last_commit_duration_micros: self.last_commit_duration_micros,
            max_commit_duration_micros: self.max_commit_duration_micros,
            p50_commit_duration_micros: percentile(&commit, 50),
            p95_commit_duration_micros: percentile(&commit, 95),
            p99_commit_duration_micros: percentile(&commit, 99),
        }
    }
}

#[derive(Clone)]
pub struct SqliteBaoOwnerV1 {
    pool: SqlitePool,
    path: Arc<PathBuf>,
    fenced: Arc<AtomicBool>,
    runtime_metrics: Arc<Mutex<SqliteBaoOwnerRuntimeMetricsOwnerV1>>,
}

struct OwnerUncertainOutcomeFence<'a> {
    owner: &'a SqliteBaoOwnerV1,
    armed: bool,
}

impl Drop for OwnerUncertainOutcomeFence<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.owner.fenced.store(true, Ordering::Release);
            if let Ok(mut metrics) = self.owner.runtime_metrics.lock() {
                metrics.writer_fence_events = metrics.writer_fence_events.saturating_add(1);
            }
        }
    }
}

impl std::fmt::Debug for SqliteBaoOwnerV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SqliteBaoOwnerV1")
            .field("fenced", &self.is_fenced())
            .finish_non_exhaustive()
    }
}

#[path = "sqlite_owner_archive.rs"]
mod sqlite_owner_archive;
#[path = "sqlite_owner_checkpoint.rs"]
mod sqlite_owner_checkpoint;
#[path = "sqlite_owner_consumption.rs"]
mod sqlite_owner_consumption;
#[path = "sqlite_owner_import.rs"]
mod sqlite_owner_import;
#[path = "sqlite_owner_leases.rs"]
mod sqlite_owner_leases;
#[path = "sqlite_owner_metrics.rs"]
mod sqlite_owner_metrics;
#[path = "sqlite_owner_reconciliation.rs"]
mod sqlite_owner_reconciliation;
#[path = "sqlite_owner_rows.rs"]
mod sqlite_owner_rows;
#[path = "sqlite_owner_transactions.rs"]
mod sqlite_owner_transactions;
#[path = "sqlite_owner_transitions.rs"]
mod sqlite_owner_transitions;
use sqlite_owner_rows::*;
#[path = "sqlite_owner_lease_projection.rs"]
mod sqlite_owner_lease_projection;
use sqlite_owner_lease_projection::*;
#[path = "sqlite_owner_validation.rs"]
mod sqlite_owner_validation;
pub(crate) use sqlite_owner_validation::prepare_private_storage;
pub(crate) use sqlite_owner_validation::secure_database_file;
use sqlite_owner_validation::*;
#[path = "sqlite_owner_encoding.rs"]
mod sqlite_owner_encoding;
use sqlite_owner_encoding::*;

impl SqliteBaoOwnerV1 {
    pub async fn open(
        path: &Path,
        external_checkpoint: Option<BaoOwnerCheckpointV1>,
    ) -> Result<Self, SqliteBaoOwnerErrorV1> {
        prepare_private_storage(path)?;
        let pool = codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::try_from(
                path.parent()
                    .ok_or(SqliteBaoOwnerErrorV1::InvalidInput)?
                    .to_path_buf(),
            )
            .map_err(storage)?,
        )
        .open_durable_evidence_pool(path)
        .await
        .map_err(storage)?;
        let result = async {
            let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
                .fetch_one(&pool)
                .await
                .map_err(storage)?;
            if quick_check != "ok" {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "SQLite quick_check failed",
                ));
            }
            MIGRATOR.run(&pool).await.map_err(storage)?;
            secure_database_file(path)?;
            verify_schema(&pool).await?;
            let schema_version: i64 =
                sqlx::query_scalar("SELECT schema_version FROM bao_owner_meta WHERE singleton = 1")
                    .fetch_one(&pool)
                    .await
                    .map_err(storage)?;
            if schema_version != i64::from(SCHEMA_VERSION) {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "unexpected SQLite owner schema version",
                ));
            }
            let foreign_key_failures: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM pragma_foreign_key_check")
                    .fetch_one(&pool)
                    .await
                    .map_err(storage)?;
            if foreign_key_failures != 0 {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "SQLite foreign-key check failed",
                ));
            }
            Ok(())
        }
        .await;
        if let Err(error) = result {
            pool.close().await;
            return Err(error);
        }
        let owner = Self {
            pool,
            path: Arc::new(path.to_path_buf()),
            fenced: Arc::new(AtomicBool::new(false)),
            runtime_metrics: Arc::new(Mutex::new(Default::default())),
        };
        if let Some(expected) = external_checkpoint
            && owner.checkpoint().await? != expected
        {
            owner.pool.close().await;
            return Err(SqliteBaoOwnerErrorV1::RollbackDetected);
        }
        Ok(owner)
    }

    #[must_use]
    pub fn is_fenced(&self) -> bool {
        self.fenced.load(Ordering::Acquire)
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }
}
#[cfg(all(test, unix))]
#[path = "sqlite_owner_tests.rs"]
mod tests;
