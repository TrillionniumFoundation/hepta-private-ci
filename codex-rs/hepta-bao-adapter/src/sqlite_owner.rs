//! Async SQLite production owner for HeptaBao metadata operations.
//!
//! The JSON owner remains a bounded reference/migration oracle. This owner uses
//! WAL/FULL SQLite transactions, immutable operation identities, generation CAS,
//! append-only transitions, a reconciliation queue and terminal archival. It
//! stores no provider token or secret value.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use codex_hepta_types::Digest32;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::BaoConsumptionOperationV1;
use crate::BaoConsumptionStateV1;
use crate::LeaseOperationStateV1;
use crate::LeaseOperationV1;
use crate::SecretLeaseMetadataV1;
use crate::SecretLeaseStateV1;

const MAX_ACTIVE_OPERATIONS: i64 = 65_536;
const MAX_RECONCILIATION_ROWS: i64 = 65_536;
const MAX_ARCHIVED_TERMINALS: i64 = 1_048_576;
const MAX_ROW_BYTES: usize = 128 * 1024;
const SCHEMA_VERSION: u32 = 1;

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteBaoOwnerMetricsV1 {
    pub operation_count: u64,
    pub active_consumption_count: u64,
    pub terminal_archive_count: u64,
    pub transition_count: u64,
    pub reconciliation_queue_count: u64,
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

#[derive(Clone)]
pub struct SqliteBaoOwnerV1 {
    pool: SqlitePool,
    path: Arc<PathBuf>,
    fenced: Arc<AtomicBool>,
}

impl std::fmt::Debug for SqliteBaoOwnerV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SqliteBaoOwnerV1")
            .field("fenced", &self.is_fenced())
            .finish_non_exhaustive()
    }
}

impl SqliteBaoOwnerV1 {
    pub async fn open(
        path: &Path,
        external_checkpoint: Option<BaoOwnerCheckpointV1>,
    ) -> Result<Self, SqliteBaoOwnerErrorV1> {
        prepare_private_storage(path)?;
        let pool = codex_state_sqlite::open_durable_authority_pool(path)
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

    pub async fn claim_consumption(
        &self,
        mut operation: BaoConsumptionOperationV1,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionClaimV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_consumption_input(&operation)?;
        if operation.state != BaoConsumptionStateV1::Claimed
            || operation.reservation_id.is_some()
            || operation.receipt.is_some()
            || operation.has_terminal_fields()
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, now_unix_ms).await?;
        if let Some(existing) = load_consumption_any_tx(&mut tx, &operation.operation_id).await? {
            if existing.operation.same_identity(&operation) {
                tx.rollback().await.map_err(storage)?;
                return Ok(SqliteConsumptionClaimV1 {
                    record: existing,
                    inserted: false,
                });
            }
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if operation_identity_exists(&mut tx, &operation.operation_id).await? {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        let active: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_consumption")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if active >= MAX_ACTIVE_OPERATIONS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let revision = next_revision(&mut tx).await?;
        operation.created_revision = revision;
        operation.updated_revision = revision;
        validate_consumption_input(&operation)?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_operation
             (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
              updated_at_unix_ms, terminal)
             VALUES (?, 'consumption', 'read', ?, ?, ?, 0)",
        )
        .bind(&operation.operation_id)
        .bind(operation.semantic_sha256.as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_consumption(
            &mut tx,
            &operation,
            revision,
            now_unix_ms,
            now_unix_ms,
            &row_json,
        )
        .await?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            None,
            state_text(operation.state),
            Digest32::of_bytes(&row_json).into_array(),
            now_unix_ms,
        )
        .await?;
        upsert_reconciliation(
            &mut tx,
            &operation.operation_id,
            operation.state,
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionClaimV1 {
            record: SqliteConsumptionRecordV1 {
                operation,
                revision,
                created_at_unix_ms: now_unix_ms,
                updated_at_unix_ms: now_unix_ms,
            },
            inserted: true,
        })
    }

    pub async fn consumption_result(
        &self,
        operation_id: &str,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(operation_id)?;
        load_consumption_any_pool(&self.pool, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)
    }

    /// Generation-fenced generic transition used by the registered host.
    /// Exact duplicate state is a no-op; changed identity or terminal evidence
    /// conflicts even when the requested state name is the same.
    pub async fn transition_consumption(
        &self,
        operation_id: &str,
        expected_revision: u64,
        mut next: BaoConsumptionOperationV1,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        validate_consumption_input(&next)?;
        if next.operation_id != operation_id
            || expected_revision == 0
            || evidence_sha256 == [0; 32]
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_consumption_current_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation == next {
            let existing_evidence = establishing_transition_evidence_tx(
                &mut tx,
                operation_id,
                state_text(current.operation.state),
            )
            .await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        if !current.operation.same_identity(&next)
            || (current.operation.reservation_id.is_some()
                && current.operation.reservation_id != next.reservation_id)
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if current.operation.receipt.is_some() && current.operation.receipt != next.receipt {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        if !current.operation.state.allows_transition_to(next.state)
            || current.operation.terminal_fields_differ(&next)
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        let revision = next_revision(&mut tx).await?;
        next.created_revision = current.operation.created_revision.max(1);
        next.updated_revision = revision;
        validate_consumption_input(&next)?;
        let row_json = encode_row(&next)?;
        let terminal = matches!(
            next.state,
            BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
        );
        let changed = sqlx::query(
            "UPDATE bao_consumption SET
             state = ?, reservation_id = ?, terminal_kind = ?, terminal_code = ?,
             terminal_evidence_sha256 = ?, terminal_observed_cost = ?, row_json = ?,
             owner_revision = ?, updated_at_unix_ms = ?
             WHERE operation_id = ? AND owner_revision = ?",
        )
        .bind(state_text(next.state))
        .bind(next.reservation_id.as_deref())
        .bind(next.terminal_kind.as_deref())
        .bind(next.terminal_code.as_deref())
        .bind(next.terminal_evidence_sha256.map(|value| value.to_vec()))
        .bind(
            next.terminal_observed_cost
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .bind(u64_bytes(revision).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(operation_id)
        .bind(u64_bytes(expected_revision).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query(
            "UPDATE bao_operation SET updated_at_unix_ms = ?, terminal = ?
             WHERE operation_id = ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(if terminal { 1_i64 } else { 0_i64 })
        .bind(operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some(state_text(current.operation.state)),
            state_text(next.state),
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        if terminal {
            sqlx::query("DELETE FROM bao_reconciliation_queue WHERE operation_id = ?")
                .bind(operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
        } else {
            upsert_reconciliation(&mut tx, operation_id, next.state, now_unix_ms).await?;
        }
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionRecordV1 {
            operation: next,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn mark_consumption_reserved(
        &self,
        operation_id: &str,
        expected_revision: u64,
        reservation_id: String,
        reservation_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(&reservation_id)?;
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next
            .reservation_id
            .as_ref()
            .is_some_and(|value| value != &reservation_id)
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        next.reservation_id = Some(reservation_id);
        next.state = BaoConsumptionStateV1::Reserved;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            reservation_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_dispatch_fenced(
        &self,
        operation_id: &str,
        expected_revision: u64,
        dispatch_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next.reservation_id.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        next.state = BaoConsumptionStateV1::DispatchFenced;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            dispatch_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn prepare_consumption_delivery(
        &self,
        operation_id: &str,
        expected_revision: u64,
        receipt: crate::BaoSecretReceipt,
        preparation_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if receipt.request_sha256 != next.request_sha256 {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        next.receipt = Some(receipt);
        next.state = BaoConsumptionStateV1::DeliveryPrepared;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            preparation_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_indeterminate(
        &self,
        operation_id: &str,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.state = BaoConsumptionStateV1::Indeterminate;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_succeeded(
        &self,
        operation_id: &str,
        expected_revision: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        let receipt = next
            .receipt
            .as_ref()
            .ok_or(SqliteBaoOwnerErrorV1::InvalidTransition)?;
        let terminal = receipt
            .evidence_digest()
            .map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)?;
        next.terminal_kind = Some("success".to_owned());
        next.terminal_code = None;
        next.terminal_evidence_sha256 = Some(terminal);
        next.terminal_observed_cost = Some(next.amount);
        next.state = BaoConsumptionStateV1::ConsumerSucceeded;
        self.transition_consumption(operation_id, expected_revision, next, terminal, now_unix_ms)
            .await
    }

    pub async fn mark_consumption_provider_failed(
        &self,
        operation_id: &str,
        expected_revision: u64,
        error_code: String,
        terminal_evidence_sha256: [u8; 32],
        observed_cost: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] || observed_cost == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.terminal_kind = Some("provider_failure".to_owned());
        next.terminal_code = Some(error_code);
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(observed_cost);
        next.state = BaoConsumptionStateV1::ProviderFailed;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn mark_consumption_not_applied(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        if next.receipt.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        next.terminal_kind = Some("consumer_not_applied".to_owned());
        next.terminal_code = Some("consumer_not_applied".to_owned());
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(0);
        next.state = BaoConsumptionStateV1::ConsumerNotApplied;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn settle_consumption_terminal(
        &self,
        operation_id: &str,
        expected_revision: u64,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        let current = self.consumption_result(operation_id).await?;
        if matches!(
            current.operation.state,
            BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
        ) {
            return Ok(current);
        }
        let mut next = current.operation;
        let evidence = next
            .terminal_evidence_sha256
            .ok_or(SqliteBaoOwnerErrorV1::InvalidTransition)?;
        next.state = match next.state {
            BaoConsumptionStateV1::ConsumerSucceeded => BaoConsumptionStateV1::Succeeded,
            BaoConsumptionStateV1::ConsumerNotApplied | BaoConsumptionStateV1::ProviderFailed => {
                BaoConsumptionStateV1::Failed
            }
            _ => return Err(SqliteBaoOwnerErrorV1::InvalidTransition),
        };
        self.transition_consumption(operation_id, expected_revision, next, evidence, now_unix_ms)
            .await
    }

    pub async fn abort_consumption_before_reservation(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.abort_consumption(
            operation_id,
            expected_revision,
            "aborted_before_reservation",
            "no_reservation",
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn abort_consumption_before_dispatch(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_code: &str,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if !matches!(
            terminal_code,
            "reservation_cancelled" | "reservation_released" | "reservation_expired"
        ) {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        self.abort_consumption(
            operation_id,
            expected_revision,
            "aborted_before_dispatch",
            terminal_code,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    async fn abort_consumption(
        &self,
        operation_id: &str,
        expected_revision: u64,
        terminal_kind: &str,
        terminal_code: &str,
        terminal_evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        if terminal_evidence_sha256 == [0; 32] {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let current = self.consumption_result(operation_id).await?;
        let mut next = current.operation;
        next.terminal_kind = Some(terminal_kind.to_owned());
        next.terminal_code = Some(terminal_code.to_owned());
        next.terminal_evidence_sha256 = Some(terminal_evidence_sha256);
        next.terminal_observed_cost = Some(0);
        next.state = BaoConsumptionStateV1::Failed;
        self.transition_consumption(
            operation_id,
            expected_revision,
            next,
            terminal_evidence_sha256,
            now_unix_ms,
        )
        .await
    }

    pub async fn claim_lease_operation(
        &self,
        operation: LeaseOperationV1,
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_lease_operation(&operation)?;
        if operation.state != LeaseOperationStateV1::Prepared || now_unix_ms == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, now_unix_ms).await?;
        if let Some(existing) = load_lease_operation_tx(&mut tx, &operation.operation_id).await? {
            if same_lease_operation_claim_identity(&existing.operation, &operation) {
                tx.rollback().await.map_err(storage)?;
                return Ok(existing);
            }
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if operation_identity_exists(&mut tx, &operation.operation_id).await? {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_lease_operation")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if count >= MAX_ACTIVE_OPERATIONS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let revision = next_revision(&mut tx).await?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_operation
             (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
              updated_at_unix_ms, terminal)
             VALUES (?, 'lease', ?, ?, ?, ?, 0)",
        )
        .bind(&operation.operation_id)
        .bind(format!("{:?}", operation.kind).to_ascii_lowercase())
        .bind(operation.semantic_sha256.as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        sqlx::query(
            "INSERT INTO bao_lease_operation
             (operation_id, operation_kind, lease_id, expected_generation,
              resulting_generation, state, row_json, terminal_result_sha256)
             VALUES (?, ?, ?, ?, NULL, 'prepared', ?, NULL)",
        )
        .bind(&operation.operation_id)
        .bind(lease_operation_kind_text(operation.kind))
        .bind(operation.lease_id.as_deref())
        .bind(
            operation
                .expected_generation
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            None,
            "prepared",
            Digest32::of_bytes(&row_json).into_array(),
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: now_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn mark_lease_operation_unknown(
        &self,
        operation_id: &str,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        if expected_revision == 0 || evidence_sha256 == [0; 32] || now_unix_ms == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_lease_operation_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation.state == LeaseOperationStateV1::Unknown {
            let existing_evidence = latest_transition_evidence_tx(&mut tx, operation_id).await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        if current.operation.state != LeaseOperationStateV1::Prepared {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        let mut operation = current.operation.clone();
        operation.state = LeaseOperationStateV1::Unknown;
        let row_json = encode_row(&operation)?;
        let revision = next_revision(&mut tx).await?;
        let changed = sqlx::query(
            "UPDATE bao_lease_operation SET state = 'unknown', row_json = ?
             WHERE operation_id = ? AND state = 'prepared' AND terminal_result_sha256 IS NULL",
        )
        .bind(&row_json)
        .bind(operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query("UPDATE bao_operation SET updated_at_unix_ms = ? WHERE operation_id = ?")
            .bind(u64_bytes(now_unix_ms).as_slice())
            .bind(operation_id)
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some("prepared"),
            "unknown",
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn apply_lease_operation(
        &self,
        operation: LeaseOperationV1,
        lease: Option<SecretLeaseMetadataV1>,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_lease_operation(&operation)?;
        if !matches!(
            operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        ) || expected_revision == 0
            || evidence_sha256 == [0; 32]
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        if operation.state == LeaseOperationStateV1::Applied && lease.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_lease_operation_tx(&mut tx, &operation.operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation == operation {
            let existing_evidence =
                latest_transition_evidence_tx(&mut tx, &operation.operation_id).await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        let lease_identity_matches = match current.operation.kind {
            crate::LeaseOperationKindV1::Issue => {
                current.operation.lease_id.is_none()
                    && match operation.state {
                        LeaseOperationStateV1::Applied => operation.lease_id.is_some(),
                        LeaseOperationStateV1::Denied => operation.lease_id.is_none(),
                        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown => false,
                    }
            }
            crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
                current.operation.lease_id == operation.lease_id
            }
        };
        if current.operation.semantic_sha256 != operation.semantic_sha256
            || current.operation.kind != operation.kind
            || current.operation.expected_generation != operation.expected_generation
            || !lease_identity_matches
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if matches!(
            current.operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        ) {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        if let Some(lease) = lease.as_ref() {
            validate_lease(lease)?;
            apply_lease_projection(&mut tx, &current.operation, lease, now_unix_ms).await?;
        }
        let revision = next_revision(&mut tx).await?;
        let row_json = encode_row(&operation)?;
        let terminal_result = Digest32::of_bytes(&row_json).into_array();
        let changed = sqlx::query(
            "UPDATE bao_lease_operation
             SET state = ?, resulting_generation = ?, row_json = ?,
                 terminal_result_sha256 = ?
             WHERE operation_id = ? AND terminal_result_sha256 IS NULL",
        )
        .bind(lease_operation_state_text(operation.state))
        .bind(
            operation
                .resulting_generation
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .bind(terminal_result.as_slice())
        .bind(&operation.operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query(
            "UPDATE bao_operation SET terminal = 1, updated_at_unix_ms = ?
             WHERE operation_id = ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(&operation.operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            Some(lease_operation_state_text(current.operation.state)),
            lease_operation_state_text(operation.state),
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn lease(
        &self,
        lease_id: &str,
    ) -> Result<Option<SecretLeaseMetadataV1>, SqliteBaoOwnerErrorV1> {
        validate_identifier(lease_id)?;
        let row: Option<Vec<u8>> =
            sqlx::query_scalar("SELECT row_json FROM bao_lease WHERE lease_id = ?")
                .bind(lease_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(storage)?;
        row.map(|bytes| decode_row(&bytes)).transpose()
    }

    pub async fn due_reconciliation(
        &self,
        now_unix_ms: u64,
        limit: u32,
    ) -> Result<Vec<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
        if now_unix_ms == 0 || limit == 0 || limit > 1024 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT operation_id FROM bao_reconciliation_queue
             WHERE next_attempt_at_unix_ms <= ?
             ORDER BY next_attempt_at_unix_ms, operation_id LIMIT ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut rows = Vec::with_capacity(ids.len());
        for id in ids {
            rows.push(load_consumption_current_tx(&mut tx, &id).await?.ok_or(
                SqliteBaoOwnerErrorV1::CorruptState("reconciliation row is missing"),
            )?);
        }
        tx.commit().await.map_err(storage)?;
        Ok(rows)
    }

    pub async fn record_reconciliation_failure(
        &self,
        operation_id: &str,
        expected_revision: u64,
        observed_at_unix_ms: u64,
        next_attempt_at_unix_ms: u64,
        error_sha256: [u8; 32],
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        if expected_revision == 0
            || observed_at_unix_ms == 0
            || next_attempt_at_unix_ms < observed_at_unix_ms
            || error_sha256 == [0; 32]
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, observed_at_unix_ms).await?;
        let current = load_consumption_current_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.revision != expected_revision
            || matches!(
                current.operation.state,
                BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
            )
        {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_reconciliation_queue")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        let exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM bao_reconciliation_queue WHERE operation_id = ?)",
        )
        .bind(operation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if !exists && count >= MAX_RECONCILIATION_ROWS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let attempts = reconciliation_attempts(&mut tx, operation_id)
            .await?
            .checked_add(1)
            .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
        let revision = next_revision(&mut tx).await?;
        let mut operation = current.operation.clone();
        operation.updated_revision = revision;
        validate_consumption_input(&operation)?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_reconciliation_queue
             (operation_id, reason, next_attempt_at_unix_ms, attempt_count, last_error_sha256)
             VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(operation_id) DO UPDATE SET
             reason = excluded.reason,
             next_attempt_at_unix_ms = excluded.next_attempt_at_unix_ms,
             attempt_count = excluded.attempt_count,
             last_error_sha256 = excluded.last_error_sha256",
        )
        .bind(operation_id)
        .bind(state_text(current.operation.state))
        .bind(u64_bytes(next_attempt_at_unix_ms).as_slice())
        .bind(u64_bytes(attempts).as_slice())
        .bind(error_sha256.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        let changed = sqlx::query(
            "UPDATE bao_consumption SET row_json = ?, owner_revision = ?, updated_at_unix_ms = ?
             WHERE operation_id = ? AND owner_revision = ?",
        )
        .bind(&row_json)
        .bind(u64_bytes(revision).as_slice())
        .bind(u64_bytes(observed_at_unix_ms).as_slice())
        .bind(operation_id)
        .bind(u64_bytes(expected_revision).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query("UPDATE bao_operation SET updated_at_unix_ms = ? WHERE operation_id = ?")
            .bind(u64_bytes(observed_at_unix_ms).as_slice())
            .bind(operation_id)
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some(state_text(current.operation.state)),
            state_text(current.operation.state),
            error_sha256,
            observed_at_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, observed_at_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: observed_at_unix_ms,
        })
    }

    pub async fn archive_terminal_before(
        &self,
        cutoff_unix_ms: u64,
        limit: u32,
        archived_at_unix_ms: u64,
    ) -> Result<u32, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        if cutoff_unix_ms == 0 || archived_at_unix_ms < cutoff_unix_ms || limit == 0 || limit > 4096
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, archived_at_unix_ms).await?;
        let archived: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_terminal_archive")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if archived >= MAX_ARCHIVED_TERMINALS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let rows = sqlx::query(
            "SELECT operation_id, semantic_sha256, terminal_kind, terminal_code,
                    terminal_evidence_sha256, terminal_observed_cost, row_json,
                    owner_revision, created_at_unix_ms, updated_at_unix_ms
             FROM bao_consumption
             WHERE state IN ('succeeded', 'failed') AND updated_at_unix_ms < ?
             ORDER BY updated_at_unix_ms, operation_id LIMIT ?",
        )
        .bind(u64_bytes(cutoff_unix_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut count = 0_u32;
        let mut latest_revision = meta_revision(&mut tx).await?;
        for row in rows {
            if archived + i64::from(count) >= MAX_ARCHIVED_TERMINALS {
                return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
            }
            let operation_id: String = row.try_get("operation_id").map_err(storage)?;
            let row_json: Vec<u8> = row.try_get("row_json").map_err(storage)?;
            let decoded: BaoConsumptionOperationV1 = decode_row(&row_json)?;
            let kind = decoded
                .terminal_kind
                .as_deref()
                .ok_or(SqliteBaoOwnerErrorV1::CorruptState("terminal kind missing"))?;
            let evidence =
                decoded
                    .terminal_evidence_sha256
                    .ok_or(SqliteBaoOwnerErrorV1::CorruptState(
                        "terminal evidence missing",
                    ))?;
            let cost = decoded
                .terminal_observed_cost
                .ok_or(SqliteBaoOwnerErrorV1::CorruptState("terminal cost missing"))?;
            sqlx::query(
                "INSERT INTO bao_terminal_archive
                 (operation_id, semantic_sha256, terminal_kind, terminal_code,
                  terminal_evidence_sha256, terminal_observed_cost, row_json,
                  owner_revision, created_at_unix_ms, updated_at_unix_ms,
                  archived_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&operation_id)
            .bind(decoded.semantic_sha256.as_slice())
            .bind(kind)
            .bind(decoded.terminal_code.as_deref())
            .bind(evidence.as_slice())
            .bind(u64_bytes(cost).as_slice())
            .bind(&row_json)
            .bind(
                row.try_get::<Vec<u8>, _>("owner_revision")
                    .map_err(storage)?,
            )
            .bind(
                row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                    .map_err(storage)?,
            )
            .bind(
                row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )
            .bind(u64_bytes(archived_at_unix_ms).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
            sqlx::query("DELETE FROM bao_reconciliation_queue WHERE operation_id = ?")
                .bind(&operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
            sqlx::query("DELETE FROM bao_consumption WHERE operation_id = ?")
                .bind(&operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
            latest_revision = latest_revision
                .checked_add(1)
                .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            insert_transition(
                &mut tx,
                latest_revision,
                &operation_id,
                Some(state_text(decoded.state)),
                "archived",
                evidence,
                archived_at_unix_ms,
            )
            .await?;
            count += 1;
        }
        if count != 0 {
            write_meta(&mut tx, latest_revision, archived_at_unix_ms).await?;
        }
        self.commit(tx).await?;
        Ok(count)
    }

    pub async fn checkpoint(&self) -> Result<BaoOwnerCheckpointV1, SqliteBaoOwnerErrorV1> {
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let generation = meta_revision(&mut tx).await?;
        let time_frontier_unix_ms = meta_time_frontier(&mut tx).await?;
        let mut bytes = b"hepta.bao.sqlite-owner-checkpoint.v1\0".to_vec();
        bytes.extend_from_slice(&generation.to_be_bytes());
        bytes.extend_from_slice(&time_frontier_unix_ms.to_be_bytes());
        append_query_rows_tx(
            &mut tx,
            "SELECT operation_id, domain, kind, semantic_sha256, updated_at_unix_ms, terminal
             FROM bao_operation ORDER BY operation_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT operation_id, owner_revision, state, row_json
             FROM bao_consumption ORDER BY operation_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT lease_id, generation, state, row_json FROM bao_lease ORDER BY lease_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT operation_id, operation_kind, COALESCE(lease_id, ''),
                    COALESCE(expected_generation, x''),
                    COALESCE(resulting_generation, x''), state, row_json,
                    COALESCE(terminal_result_sha256, x'')
             FROM bao_lease_operation ORDER BY operation_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT operation_id, reason, next_attempt_at_unix_ms, attempt_count,
                    COALESCE(last_error_sha256, x'')
             FROM bao_reconciliation_queue ORDER BY operation_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT operation_id, owner_revision, row_json, archived_at_unix_ms
             FROM bao_terminal_archive ORDER BY operation_id",
            &mut bytes,
        )
        .await?;
        append_query_rows_tx(
            &mut tx,
            "SELECT sequence, revision, operation_id, COALESCE(from_state, ''),
                    to_state, evidence_sha256, observed_at_unix_ms
             FROM bao_transition ORDER BY sequence",
            &mut bytes,
        )
        .await?;
        tx.commit().await.map_err(storage)?;
        Ok(BaoOwnerCheckpointV1 {
            generation,
            state_sha256: Digest32::of_bytes(&bytes).into_array(),
        })
    }

    pub async fn metrics(
        &self,
        now_unix_ms: u64,
    ) -> Result<SqliteBaoOwnerMetricsV1, SqliteBaoOwnerErrorV1> {
        if now_unix_ms == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let operation_count = count_tx(&mut tx, "bao_operation").await?;
        let active_consumption_count = count_tx(&mut tx, "bao_consumption").await?;
        let terminal_archive_count = count_tx(&mut tx, "bao_terminal_archive").await?;
        let transition_count = count_tx(&mut tx, "bao_transition").await?;
        let reconciliation_queue_count = count_tx(&mut tx, "bao_reconciliation_queue").await?;
        let rows = sqlx::query(
            "SELECT row_json, updated_at_unix_ms FROM bao_consumption
             WHERE state NOT IN ('succeeded', 'failed')
             ORDER BY updated_at_unix_ms, operation_id",
        )
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut pending_by_state = BTreeMap::new();
        let mut pending_by_recovery_action = BTreeMap::new();
        let mut pending_quota_amount = 0_u64;
        let mut post_dispatch_without_receipt = 0_u64;
        let mut observer_pending = 0_u64;
        let mut settlement_pending = 0_u64;
        let mut oldest_pending_at = None::<u64>;
        for row in rows {
            let operation: BaoConsumptionOperationV1 =
                decode_row(&row.try_get::<Vec<u8>, _>("row_json").map_err(storage)?)?;
            validate_consumption_stored(&operation)?;
            if operation.state.is_terminal() {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "terminal row returned by pending query",
                ));
            }
            *pending_by_state.entry(operation.state).or_insert(0) += 1;
            *pending_by_recovery_action
                .entry(operation.state.recovery_action())
                .or_insert(0) += 1;
            if operation.reservation_id.is_some() {
                pending_quota_amount = pending_quota_amount
                    .checked_add(operation.amount)
                    .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            }
            if operation.state.has_dispatch_fence() && operation.receipt.is_none() {
                post_dispatch_without_receipt += 1;
            }
            if matches!(
                operation.state,
                BaoConsumptionStateV1::DispatchFenced
                    | BaoConsumptionStateV1::DeliveryPrepared
                    | BaoConsumptionStateV1::Indeterminate
            ) {
                observer_pending += 1;
            }
            if matches!(
                operation.state.phase(),
                crate::BaoConsumptionPhaseV1::TerminalEvidence
            ) {
                settlement_pending += 1;
            }
            let updated_at = fixed_u64(
                &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )?;
            oldest_pending_at =
                Some(oldest_pending_at.map_or(updated_at, |oldest| oldest.min(updated_at)));
        }
        tx.commit().await.map_err(storage)?;
        let oldest_pending_age_ms =
            oldest_pending_at.map(|value| now_unix_ms.saturating_sub(value));
        let database_bytes = metadata_len(self.path.as_path())?;
        let wal_bytes = metadata_len(&sidecar_path(self.path.as_path(), "-wal"))?;
        let shm_bytes = metadata_len(&sidecar_path(self.path.as_path(), "-shm"))?;
        Ok(SqliteBaoOwnerMetricsV1 {
            operation_count,
            active_consumption_count,
            terminal_archive_count,
            transition_count,
            reconciliation_queue_count,
            pending_by_state,
            pending_by_recovery_action,
            pending_quota_amount,
            post_dispatch_without_receipt,
            observer_pending,
            settlement_pending,
            oldest_pending_age_ms,
            database_bytes,
            wal_bytes,
            shm_bytes,
            fenced: self.is_fenced(),
            provider_dynamic_execution_blocked: true,
        })
    }

    fn ensure_writable(&self) -> Result<(), SqliteBaoOwnerErrorV1> {
        if self.is_fenced() {
            Err(SqliteBaoOwnerErrorV1::Fenced)
        } else {
            Ok(())
        }
    }

    async fn commit(&self, tx: Transaction<'static, Sqlite>) -> Result<(), SqliteBaoOwnerErrorV1> {
        if let Err(error) = tx.commit().await {
            self.fenced.store(true, Ordering::Release);
            return Err(SqliteBaoOwnerErrorV1::Storage(error.to_string()));
        }
        Ok(())
    }
}

async fn begin(pool: &SqlitePool) -> Result<Transaction<'static, Sqlite>, SqliteBaoOwnerErrorV1> {
    pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)
}

async fn verify_schema(pool: &SqlitePool) -> Result<(), SqliteBaoOwnerErrorV1> {
    let reference = codex_state_sqlite::open_schema_reference_pool()
        .await
        .map_err(storage)?;
    let result = async {
        MIGRATOR.run(&reference).await.map_err(storage)?;
        let query = "SELECT type, name, tbl_name, sql FROM sqlite_schema
                     WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL
                     ORDER BY type, name";
        let expected = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(&reference)
            .await
            .map_err(storage)?;
        let actual = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(pool)
            .await
            .map_err(storage)?;
        if actual != expected {
            return Err(SqliteBaoOwnerErrorV1::CorruptState(
                "live owner schema differs from compiled migrations",
            ));
        }
        Ok(())
    }
    .await;
    reference.close().await;
    result
}

async fn advance_time(
    tx: &mut Transaction<'_, Sqlite>,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    if now_unix_ms == 0 {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    let frontier: Vec<u8> =
        sqlx::query_scalar("SELECT time_frontier_unix_ms FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    if now_unix_ms < fixed_u64_allow_zero(&frontier)? {
        return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
    }
    Ok(())
}

async fn meta_revision(tx: &mut Transaction<'_, Sqlite>) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> =
        sqlx::query_scalar("SELECT revision FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    fixed_u64(&value)
}

async fn meta_time_frontier(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> =
        sqlx::query_scalar("SELECT time_frontier_unix_ms FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    fixed_u64_allow_zero(&value)
}

async fn next_revision(tx: &mut Transaction<'_, Sqlite>) -> Result<u64, SqliteBaoOwnerErrorV1> {
    meta_revision(tx)
        .await?
        .checked_add(1)
        .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)
}

async fn write_meta(
    tx: &mut Transaction<'_, Sqlite>,
    revision: u64,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "UPDATE bao_owner_meta SET revision = ?, time_frontier_unix_ms = ?
         WHERE singleton = 1",
    )
    .bind(u64_bytes(revision).as_slice())
    .bind(u64_bytes(now_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

async fn operation_identity_exists(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<bool, SqliteBaoOwnerErrorV1> {
    sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM bao_operation WHERE operation_id = ?)")
        .bind(operation_id)
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)
}

async fn insert_consumption(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &BaoConsumptionOperationV1,
    revision: u64,
    created_at_unix_ms: u64,
    updated_at_unix_ms: u64,
    row_json: &[u8],
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "INSERT INTO bao_consumption
         (operation_id, semantic_sha256, effect_sha256, request_sha256,
          consumer_id, consumer_configuration_sha256, amount, state,
          reservation_id, terminal_kind, terminal_code, terminal_evidence_sha256,
          terminal_observed_cost, row_json, owner_revision,
          created_at_unix_ms, updated_at_unix_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&operation.operation_id)
    .bind(operation.semantic_sha256.as_slice())
    .bind(operation.effect_sha256.as_slice())
    .bind(operation.request_sha256.as_slice())
    .bind(&operation.consumer_id)
    .bind(operation.consumer_configuration_sha256.as_slice())
    .bind(u64_bytes(operation.amount).as_slice())
    .bind(state_text(operation.state))
    .bind(operation.reservation_id.as_deref())
    .bind(operation.terminal_kind.as_deref())
    .bind(operation.terminal_code.as_deref())
    .bind(
        operation
            .terminal_evidence_sha256
            .map(|value| value.to_vec()),
    )
    .bind(
        operation
            .terminal_observed_cost
            .map(|value| u64_bytes(value).to_vec()),
    )
    .bind(row_json)
    .bind(u64_bytes(revision).as_slice())
    .bind(u64_bytes(created_at_unix_ms).as_slice())
    .bind(u64_bytes(updated_at_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

async fn load_consumption_current_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT row_json, owner_revision, created_at_unix_ms, updated_at_unix_ms
         FROM bao_consumption WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

async fn load_consumption_current_pool(
    pool: &SqlitePool,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT row_json, owner_revision, created_at_unix_ms, updated_at_unix_ms
         FROM bao_consumption WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(pool)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

async fn load_consumption_any_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    if let Some(current) = load_consumption_current_tx(tx, operation_id).await? {
        return Ok(Some(current));
    }
    let row = sqlx::query(
        "SELECT row_json, owner_revision, created_at_unix_ms, updated_at_unix_ms
         FROM bao_terminal_archive WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

async fn load_consumption_any_pool(
    pool: &SqlitePool,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    if let Some(current) = load_consumption_current_pool(pool, operation_id).await? {
        return Ok(Some(current));
    }
    let row = sqlx::query(
        "SELECT row_json, owner_revision, created_at_unix_ms, updated_at_unix_ms
         FROM bao_terminal_archive WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(pool)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

fn consumption_record(
    row: sqlx::sqlite::SqliteRow,
) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
    let bytes: Vec<u8> = row.try_get("row_json").map_err(storage)?;
    let operation: BaoConsumptionOperationV1 = decode_row(&bytes)?;
    validate_consumption_stored(&operation)?;
    let revision = fixed_u64(
        &row.try_get::<Vec<u8>, _>("owner_revision")
            .map_err(storage)?,
    )?;
    if operation.created_revision == 0
        || operation.updated_revision != revision
        || operation.created_revision > operation.updated_revision
    {
        return Err(SqliteBaoOwnerErrorV1::CorruptState(
            "consumption revision lineage is invalid",
        ));
    }
    Ok(SqliteConsumptionRecordV1 {
        operation,
        revision,
        created_at_unix_ms: fixed_u64(
            &row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                .map_err(storage)?,
        )?,
        updated_at_unix_ms: fixed_u64(
            &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                .map_err(storage)?,
        )?,
    })
}

async fn load_lease_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteLeaseOperationRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT l.row_json, o.created_at_unix_ms, o.updated_at_unix_ms,
                t.revision AS owner_revision
         FROM bao_lease_operation l
         JOIN bao_operation o ON o.operation_id = l.operation_id
         JOIN bao_transition t ON t.operation_id = l.operation_id
         WHERE l.operation_id = ? ORDER BY t.sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(|row| {
        let operation = decode_row::<LeaseOperationV1>(
            &row.try_get::<Vec<u8>, _>("row_json").map_err(storage)?,
        )?;
        validate_lease_operation(&operation)?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision: fixed_u64(
                &row.try_get::<Vec<u8>, _>("owner_revision")
                    .map_err(storage)?,
            )?,
            created_at_unix_ms: fixed_u64(
                &row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                    .map_err(storage)?,
            )?,
            updated_at_unix_ms: fixed_u64(
                &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )?,
        })
    })
    .transpose()
}

async fn apply_lease_projection(
    tx: &mut Transaction<'_, Sqlite>,
    current_operation: &LeaseOperationV1,
    lease: &SecretLeaseMetadataV1,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let existing =
        sqlx::query("SELECT generation, state, row_json FROM bao_lease WHERE lease_id = ?")
            .bind(&lease.lease_id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(storage)?;
    let row_json = encode_row(lease)?;
    match existing {
        None => {
            if current_operation.expected_generation.is_some() || lease.generation != 1 {
                return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
            }
            sqlx::query(
                "INSERT INTO bao_lease (lease_id, generation, state, row_json, updated_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?)",
            )
            .bind(&lease.lease_id)
            .bind(u64_bytes(lease.generation).as_slice())
            .bind(lease_state_text(lease.state))
            .bind(&row_json)
            .bind(u64_bytes(now_unix_ms).as_slice())
            .execute(&mut **tx)
            .await
            .map_err(map_write_error)?;
        }
        Some(row) => {
            let generation = fixed_u64(&row.try_get::<Vec<u8>, _>("generation").map_err(storage)?)?;
            let state: String = row.try_get("state").map_err(storage)?;
            if current_operation.expected_generation != Some(generation)
                || lease.generation <= generation
                || (matches!(state.as_str(), "revoked" | "expired")
                    && lease_state_text(lease.state) != state)
            {
                return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
            }
            let changed = sqlx::query(
                "UPDATE bao_lease SET generation = ?, state = ?, row_json = ?,
                 updated_at_unix_ms = ? WHERE lease_id = ? AND generation = ?",
            )
            .bind(u64_bytes(lease.generation).as_slice())
            .bind(lease_state_text(lease.state))
            .bind(&row_json)
            .bind(u64_bytes(now_unix_ms).as_slice())
            .bind(&lease.lease_id)
            .bind(u64_bytes(generation).as_slice())
            .execute(&mut **tx)
            .await
            .map_err(map_write_error)?
            .rows_affected();
            if changed != 1 {
                return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
            }
        }
    }
    Ok(())
}

async fn establishing_transition_evidence_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    state: &str,
) -> Result<[u8; 32], SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> = sqlx::query_scalar(
        "SELECT evidence_sha256 FROM bao_transition
         WHERE operation_id = ? AND to_state = ?
           AND (from_state IS NULL OR from_state != to_state)
         ORDER BY sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .bind(state)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid transition evidence"))
}

async fn latest_transition_evidence_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<[u8; 32], SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> = sqlx::query_scalar(
        "SELECT evidence_sha256 FROM bao_transition
         WHERE operation_id = ? ORDER BY sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid transition evidence"))
}

async fn insert_transition(
    tx: &mut Transaction<'_, Sqlite>,
    revision: u64,
    operation_id: &str,
    from_state: Option<&str>,
    to_state: &str,
    evidence_sha256: [u8; 32],
    observed_at_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "INSERT INTO bao_transition
         (revision, operation_id, from_state, to_state, evidence_sha256, observed_at_unix_ms)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(u64_bytes(revision).as_slice())
    .bind(operation_id)
    .bind(from_state)
    .bind(to_state)
    .bind(evidence_sha256.as_slice())
    .bind(u64_bytes(observed_at_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

async fn upsert_reconciliation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    state: BaoConsumptionStateV1,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_reconciliation_queue")
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)?;
    let exists: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM bao_reconciliation_queue WHERE operation_id = ?)",
    )
    .bind(operation_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    if !exists && count >= MAX_RECONCILIATION_ROWS {
        return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
    }
    sqlx::query(
        "INSERT INTO bao_reconciliation_queue
         (operation_id, reason, next_attempt_at_unix_ms, attempt_count, last_error_sha256)
         VALUES (?, ?, ?, ?, NULL)
         ON CONFLICT(operation_id) DO UPDATE SET
         reason = excluded.reason,
         next_attempt_at_unix_ms = excluded.next_attempt_at_unix_ms,
         attempt_count = excluded.attempt_count,
         last_error_sha256 = NULL",
    )
    .bind(operation_id)
    .bind(state_text(state))
    .bind(u64_bytes(now_unix_ms).as_slice())
    .bind(u64_bytes(0).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

async fn reconciliation_attempts(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Option<Vec<u8>> = sqlx::query_scalar(
        "SELECT attempt_count FROM bao_reconciliation_queue WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .map(|value| fixed_u64_allow_zero(&value))
        .transpose()
        .map(|value| value.unwrap_or(0))
}

async fn count_tx(
    tx: &mut Transaction<'_, Sqlite>,
    table: &str,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let query = match table {
        "bao_operation" => "SELECT COUNT(*) FROM bao_operation",
        "bao_consumption" => "SELECT COUNT(*) FROM bao_consumption",
        "bao_terminal_archive" => "SELECT COUNT(*) FROM bao_terminal_archive",
        "bao_transition" => "SELECT COUNT(*) FROM bao_transition",
        "bao_reconciliation_queue" => "SELECT COUNT(*) FROM bao_reconciliation_queue",
        _ => return Err(SqliteBaoOwnerErrorV1::InvalidInput),
    };
    let value: i64 = sqlx::query_scalar(query)
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)?;
    u64::try_from(value).map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("negative count"))
}

async fn append_query_rows_tx(
    tx: &mut Transaction<'_, Sqlite>,
    query: &'static str,
    bytes: &mut Vec<u8>,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let rows = sqlx::query(query)
        .fetch_all(&mut **tx)
        .await
        .map_err(storage)?;
    for row in rows {
        bytes.extend_from_slice(&u64::try_from(row.len()).unwrap_or(u64::MAX).to_be_bytes());
        for index in 0..row.len() {
            if let Ok(value) = row.try_get::<Vec<u8>, _>(index) {
                append_value(bytes, &value);
            } else if let Ok(value) = row.try_get::<String, _>(index) {
                append_value(bytes, value.as_bytes());
            } else if let Ok(value) = row.try_get::<i64, _>(index) {
                append_value(bytes, &value.to_be_bytes());
            } else {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "unsupported checkpoint column",
                ));
            }
        }
    }
    Ok(())
}

#[cfg(unix)]
fn prepare_private_storage(path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    if !parent.exists() {
        let mut builder = fs::DirBuilder::new();
        builder.mode(0o700).recursive(true);
        builder.create(parent).map_err(storage)?;
    }
    let parent_metadata = fs::symlink_metadata(parent).map_err(storage)?;
    if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "parent must be a real directory",
        ));
    }
    if parent_metadata.mode() & 0o077 != 0
        || parent_metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "parent must be owner-only and owner-owned",
        ));
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink()
                || !metadata.is_file()
                || metadata.nlink() != 1
                || metadata.uid() != rustix::process::geteuid().as_raw()
            {
                return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
                    "database must be an owner-owned single-link regular file",
                ));
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(storage(error)),
    }
    Ok(())
}

#[cfg(not(unix))]
fn prepare_private_storage(_path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    Err(SqliteBaoOwnerErrorV1::UnsupportedPlatform)
}

#[cfg(unix)]
fn secure_database_file(path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let metadata = fs::symlink_metadata(path).map_err(storage)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "database identity changed while opening",
        ));
    }
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(storage)?;
    let secured = fs::metadata(path).map_err(storage)?;
    if secured.mode() & 0o077 != 0 {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "database permissions are not owner-only",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn secure_database_file(_path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    Err(SqliteBaoOwnerErrorV1::UnsupportedPlatform)
}

fn sidecar_path(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

fn metadata_len(path: &Path) -> Result<u64, SqliteBaoOwnerErrorV1> {
    match fs::metadata(path) {
        Ok(metadata) => Ok(metadata.len()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
        Err(error) => Err(storage(error)),
    }
}

fn append_value(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn validate_consumption_input(
    row: &BaoConsumptionOperationV1,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    row.validate_for_persistence()
        .map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)
}

fn validate_consumption_stored(
    row: &BaoConsumptionOperationV1,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    row.validate_for_persistence()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid persisted consumption row"))
}

fn validate_lease_operation(operation: &LeaseOperationV1) -> Result<(), SqliteBaoOwnerErrorV1> {
    validate_identifier(&operation.operation_id)?;
    if operation.semantic_sha256 == [0; 32]
        || operation
            .lease_id
            .as_deref()
            .is_some_and(|value| validate_identifier(value).is_err())
        || operation.expected_generation == Some(0)
        || operation.resulting_generation == Some(0)
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    match operation.kind {
        crate::LeaseOperationKindV1::Issue => {
            if operation.expected_generation.is_some() {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
        crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
            if operation.lease_id.is_none() || operation.expected_generation.is_none() {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
    }
    let terminal = matches!(
        operation.state,
        LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
    );
    if terminal != operation.result_observation.is_some()
        || (!terminal
            && (operation.result_lease.is_some()
                || operation.observed_at_unix_ms.is_some()
                || operation.resulting_generation.is_some()))
        || (operation.state == LeaseOperationStateV1::Applied && operation.result_lease.is_none())
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    if let Some(snapshot) = operation.result_lease.as_ref() {
        validate_lease(snapshot)?;
        if operation.lease_id.as_deref() != Some(snapshot.lease_id.as_str())
            || operation.resulting_generation != Some(snapshot.generation)
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
    }
    if let (Some(expected), Some(resulting)) = (
        operation.expected_generation,
        operation.resulting_generation,
    ) && resulting <= expected
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    match operation.result_observation.as_ref() {
        Some(crate::ProviderLeaseObservationV1::Unknown) => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(
            crate::ProviderLeaseObservationV1::Denied
            | crate::ProviderLeaseObservationV1::NotApplied,
        ) if operation.state != LeaseOperationStateV1::Denied => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(
            crate::ProviderLeaseObservationV1::IssueApplied { .. }
            | crate::ProviderLeaseObservationV1::RenewApplied { .. }
            | crate::ProviderLeaseObservationV1::RevokeApplied { .. },
        ) if operation.state != LeaseOperationStateV1::Applied => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(_) | None => {}
    }
    encode_row(operation).map(|_| ())
}

fn validate_lease(lease: &SecretLeaseMetadataV1) -> Result<(), SqliteBaoOwnerErrorV1> {
    validate_identifier(&lease.lease_id)?;
    validate_identifier(&lease.secret_reference_id)?;
    validate_identifier(&lease.consumer_id)?;
    if lease.scope_sha256 == [0; 32]
        || lease.provider_metadata_sha256 == [0; 32]
        || lease.generation == 0
        || lease.expires_at_unix_ms <= lease.issued_at_unix_ms
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    encode_row(lease).map(|_| ())
}

fn same_lease_operation_claim_identity(
    current: &LeaseOperationV1,
    requested: &LeaseOperationV1,
) -> bool {
    if current.operation_id != requested.operation_id
        || current.kind != requested.kind
        || current.semantic_sha256 != requested.semantic_sha256
        || current.expected_generation != requested.expected_generation
    {
        return false;
    }
    match requested.kind {
        crate::LeaseOperationKindV1::Issue => requested.lease_id.is_none(),
        crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
            current.lease_id == requested.lease_id
        }
    }
}

fn validate_identifier(value: &str) -> Result<(), SqliteBaoOwnerErrorV1> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        Err(SqliteBaoOwnerErrorV1::InvalidInput)
    } else {
        Ok(())
    }
}

fn lease_operation_kind_text(kind: crate::LeaseOperationKindV1) -> &'static str {
    match kind {
        crate::LeaseOperationKindV1::Issue => "issue",
        crate::LeaseOperationKindV1::Renew => "renew",
        crate::LeaseOperationKindV1::Revoke => "revoke",
    }
}

fn state_text(state: BaoConsumptionStateV1) -> &'static str {
    match state {
        BaoConsumptionStateV1::Claimed => "claimed",
        BaoConsumptionStateV1::Reserved => "reserved",
        BaoConsumptionStateV1::DispatchFenced => "dispatch_fenced",
        BaoConsumptionStateV1::DeliveryPrepared => "delivery_prepared",
        BaoConsumptionStateV1::ConsumerSucceeded => "consumer_succeeded",
        BaoConsumptionStateV1::ConsumerNotApplied => "consumer_not_applied",
        BaoConsumptionStateV1::ProviderFailed => "provider_failed",
        BaoConsumptionStateV1::Indeterminate => "indeterminate",
        BaoConsumptionStateV1::Succeeded => "succeeded",
        BaoConsumptionStateV1::Failed => "failed",
        BaoConsumptionStateV1::DispatchAttempted => "dispatch_attempted",
    }
}

fn lease_operation_state_text(state: LeaseOperationStateV1) -> &'static str {
    match state {
        LeaseOperationStateV1::Prepared => "prepared",
        LeaseOperationStateV1::Unknown => "unknown",
        LeaseOperationStateV1::Applied => "applied",
        LeaseOperationStateV1::Denied => "denied",
    }
}

fn lease_state_text(state: SecretLeaseStateV1) -> &'static str {
    match state {
        SecretLeaseStateV1::Active => "active",
        SecretLeaseStateV1::RenewUnknown => "renew_unknown",
        SecretLeaseStateV1::RevokeUnknown => "revoke_unknown",
        SecretLeaseStateV1::Revoked => "revoked",
        SecretLeaseStateV1::Expired => "expired",
    }
}

fn encode_row(value: &impl Serialize) -> Result<Vec<u8>, SqliteBaoOwnerErrorV1> {
    let bytes = serde_json::to_vec(value).map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)?;
    if bytes.len() > MAX_ROW_BYTES {
        return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
    }
    Ok(bytes)
}

fn decode_row<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, SqliteBaoOwnerErrorV1> {
    if bytes.len() > MAX_ROW_BYTES {
        return Err(SqliteBaoOwnerErrorV1::CorruptState(
            "row exceeds encoded bound",
        ));
    }
    serde_json::from_slice(bytes)
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("row JSON is invalid"))
}

fn fixed_u64(value: &[u8]) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value = fixed_u64_allow_zero(value)?;
    if value == 0 {
        Err(SqliteBaoOwnerErrorV1::CorruptState("zero monotonic value"))
    } else {
        Ok(value)
    }
}

fn fixed_u64_allow_zero(value: &[u8]) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid fixed-width u64"))?;
    Ok(u64::from_be_bytes(bytes))
}

fn u64_bytes(value: u64) -> [u8; 8] {
    value.to_be_bytes()
}

fn storage(error: impl ToString) -> SqliteBaoOwnerErrorV1 {
    SqliteBaoOwnerErrorV1::Storage(error.to_string())
}

fn map_write_error(error: sqlx::Error) -> SqliteBaoOwnerErrorV1 {
    if error
        .as_database_error()
        .is_some_and(sqlx::error::DatabaseError::is_unique_violation)
    {
        SqliteBaoOwnerErrorV1::OperationConflict
    } else {
        storage(error)
    }
}

#[cfg(all(test, unix))]
#[path = "sqlite_owner_tests.rs"]
mod tests;
