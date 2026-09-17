use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::ArmedDispatch;
use crate::DispatchClaim;
use crate::DispatchLease;
use crate::DurableOperationIntent;
use crate::DurableOperationMetrics;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOutboxRecord;
use crate::DurableOutboxState;
use crate::DurableStoreConfig;
use crate::MAX_DURABLE_CLAIM_BATCH;
use crate::MAX_DURABLE_LEASE_MS;
use crate::MAX_DURABLE_OUTBOX_ATTEMPTS;
use crate::OperationError;
use crate::ReconciliationOutcome;

const OPERATIONS_DB_FILENAME: &str = "hepta_operations_1.sqlite";
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

/// SQLite-backed owner for the durable operation journal and local outbox.
/// `prepare_intent` is the only creation path and commits both rows in one
/// `BEGIN IMMEDIATE` transaction.
#[derive(Clone)]
pub struct DurableOperationStore {
    pool: SqlitePool,
    path: PathBuf,
    config: DurableStoreConfig,
}

impl DurableOperationStore {
    pub async fn open(sqlite: &SqliteConfig) -> Result<Self, OperationError> {
        Self::open_with_config(sqlite, DurableStoreConfig::default()).await
    }

    pub async fn open_with_config(
        sqlite: &SqliteConfig,
        config: DurableStoreConfig,
    ) -> Result<Self, OperationError> {
        config.validate()?;
        let path = sqlite.home().join(OPERATIONS_DB_FILENAME);
        let pool = sqlite
            .open_durable_evidence_pool(&path)
            .await
            .map_err(storage)?;
        if let Err(error) = verify_quick_check(&pool).await {
            pool.close().await;
            return Err(error);
        }
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(OperationError::Storage(error.to_string()));
        }
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path, config })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Atomically persist one operation identity and its local outbox identity.
    /// Exact replay is idempotent. A higher writer generation may adopt the
    /// same still-live semantic intent; a lower generation is rejected.
    pub async fn prepare_intent(
        &self,
        intent: DurableOperationIntent,
    ) -> Result<DurableOperationRecord, OperationError> {
        intent.validate()?;
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        if tombstone_exists(&mut tx, &intent.scope_id, &intent.operation_id).await? {
            return Err(OperationError::TerminalPruned(intent.operation_id));
        }
        if let Some(mut existing) =
            load_operation(&mut tx, &intent.scope_id, &intent.operation_id).await?
        {
            if !same_semantics(&existing.intent, &intent) {
                return Err(OperationError::Conflict(intent.operation_id));
            }
            if intent.writer_generation < existing.intent.writer_generation {
                return Err(OperationError::StaleGeneration);
            }
            let outbox = load_outbox(
                &mut tx,
                &intent.scope_id,
                &intent.operation_id,
                &intent.destination_id,
            )
            .await?
            .ok_or_else(|| OperationError::Corrupt("operation has no local outbox row".into()))?;
            if outbox.payload_digest != intent.payload_digest {
                return Err(OperationError::Corrupt(
                    "operation/outbox payload identity mismatch".into(),
                ));
            }
            if intent.writer_generation > existing.intent.writer_generation
                && !existing.state.is_terminal()
            {
                let next = next_revision(&existing)?;
                sqlx::query(
                    "UPDATE operation_records SET writer_generation = ?, revision = ?, updated_at_ms = ?
                     WHERE scope_id = ? AND operation_id = ?",
                )
                .bind(u64_blob(intent.writer_generation.get()))
                .bind(u64_blob(next.get()))
                .bind(now)
                .bind(intent.scope_id.as_str())
                .bind(intent.operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(storage)?;
                existing = load_operation(&mut tx, &intent.scope_id, &intent.operation_id)
                    .await?
                    .ok_or_else(|| OperationError::Corrupt("operation disappeared".into()))?;
            }
            tx.commit().await.map_err(storage)?;
            return Ok(existing);
        }
        require_predecessor(&mut tx, &intent).await?;
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_records
             WHERE state NOT IN ('applied', 'not_applied', 'quarantined')",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if active >= self.config.maximum_active_operations {
            return Err(OperationError::CapacityExceeded {
                resource: "durable active operations",
                maximum: usize::try_from(self.config.maximum_active_operations)
                    .unwrap_or(usize::MAX),
            });
        }
        let outbox_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cross_owner_outbox")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if outbox_count >= self.config.maximum_outbox_rows {
            return Err(OperationError::CapacityExceeded {
                resource: "durable outbox rows",
                maximum: usize::try_from(self.config.maximum_outbox_rows).unwrap_or(usize::MAX),
            });
        }
        let predecessor = intent.expected_predecessor.as_ref().map(StableId::as_str);
        sqlx::query(
            "INSERT INTO operation_records
             (scope_id, operation_id, scope_digest, request_digest, payload_digest,
              destination_id, predecessor_operation_id, writer_generation, authority_epoch,
              revision, state, created_at_ms, updated_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        )
        .bind(intent.scope_id.as_str())
        .bind(intent.operation_id.as_str())
        .bind(intent.scope_digest.as_array().as_slice())
        .bind(intent.request_digest.as_array().as_slice())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(intent.destination_id.as_str())
        .bind(predecessor)
        .bind(u64_blob(intent.writer_generation.get()))
        .bind(u64_blob(intent.authority_epoch.get()))
        .bind(u64_blob(1))
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "INSERT INTO cross_owner_outbox
             (scope_id, operation_id, destination_id, payload_digest, state, fence,
              attempts, next_eligible_ms, created_at_ms, updated_at_ms)
             VALUES (?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?)",
        )
        .bind(intent.scope_id.as_str())
        .bind(intent.operation_id.as_str())
        .bind(intent.destination_id.as_str())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let record = load_operation(&mut tx, &intent.scope_id, &intent.operation_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("inserted operation is missing".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn operation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DurableOperationRecord>, OperationError> {
        let row = sqlx::query(
            "SELECT * FROM operation_records WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        row.map(decode_operation).transpose()
    }

    pub async fn outbox(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        destination_id: &StableId,
    ) -> Result<Option<DurableOutboxRecord>, OperationError> {
        let row = sqlx::query(
            "SELECT * FROM cross_owner_outbox
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .bind(destination_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        row.map(decode_outbox).transpose()
    }

    /// Bounded observation of rows that can be safely claimed. Indeterminate or
    /// acknowledged rows are intentionally excluded because they require
    /// reconciliation, not resend.
    pub async fn ready_outbox(
        &self,
        destination_id: &StableId,
        limit: u32,
    ) -> Result<Vec<DurableOutboxRecord>, OperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(OperationError::InvalidTransition {
                from: "ready_outbox",
                to: "invalid_batch_limit",
            });
        }
        let now = now_millis()?;
        let rows = sqlx::query(
            "SELECT * FROM cross_owner_outbox
             WHERE destination_id = ? AND next_eligible_ms <= ?
             AND (state = 'queued' OR (state = 'leased' AND lease_until_ms <= ?))
             ORDER BY next_eligible_ms, scope_id, operation_id LIMIT ?",
        )
        .bind(destination_id.as_str())
        .bind(now)
        .bind(now)
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(decode_outbox).collect()
    }

    /// Claim only a pre-dispatch row. Expired pre-dispatch leases may be taken
    /// over by the same or a higher generation. Once `arm_dispatch` succeeds the
    /// row leaves this claimable set permanently and must reconcile.
    pub async fn claim_outbox(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        destination_id: &StableId,
        worker_id: StableId,
        writer_generation: Generation,
        lease_ms: i64,
    ) -> Result<DispatchClaim, OperationError> {
        validate_lease_ms(lease_ms)?;
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let mut operation = load_operation(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        let outbox = load_outbox(&mut tx, scope_id, operation_id, destination_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        if outbox.updated_at_ms > now {
            return Err(OperationError::Unavailable(
                "clock moved behind the durable outbox watermark".into(),
            ));
        }
        if operation.state != DurableOperationState::Pending {
            return Err(OperationError::LeaseUnavailable);
        }
        if outbox.next_eligible_ms > now {
            return Err(OperationError::LeaseUnavailable);
        }
        match outbox.state {
            DurableOutboxState::Queued => {}
            DurableOutboxState::Leased
                if outbox.lease_until_ms.is_some_and(|deadline| deadline <= now) => {}
            _ => return Err(OperationError::LeaseUnavailable),
        }
        if outbox
            .claim_generation
            .is_some_and(|generation| generation > writer_generation)
            || operation.intent.writer_generation > writer_generation
        {
            return Err(OperationError::StaleGeneration);
        }
        if outbox.attempts >= MAX_DURABLE_OUTBOX_ATTEMPTS {
            quarantine_pre_dispatch(
                &mut tx,
                &operation,
                &outbox,
                writer_generation,
                Digest32::of_bytes(b"hepta.kernel.operations.outbox-attempts-exhausted.v1"),
                now,
            )
            .await?;
            tx.commit().await.map_err(storage)?;
            return Err(OperationError::LeaseUnavailable);
        }
        if writer_generation > operation.intent.writer_generation {
            let next = next_revision(&operation)?;
            sqlx::query(
                "UPDATE operation_records SET writer_generation = ?, revision = ?, updated_at_ms = ?
                 WHERE scope_id = ? AND operation_id = ?",
            )
            .bind(u64_blob(writer_generation.get()))
            .bind(u64_blob(next.get()))
            .bind(now)
            .bind(scope_id.as_str())
            .bind(operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
            operation = load_operation(&mut tx, scope_id, operation_id)
                .await?
                .ok_or_else(|| OperationError::Corrupt("operation disappeared".into()))?;
        }
        let lease_until = now
            .checked_add(lease_ms)
            .ok_or_else(|| OperationError::Unavailable("lease time overflow".into()))?;
        let new_fence = outbox
            .fence
            .checked_add(1)
            .ok_or_else(|| OperationError::Unavailable("outbox fence overflow".into()))?;
        let new_attempts = outbox
            .attempts
            .checked_add(1)
            .ok_or_else(|| OperationError::Unavailable("outbox attempts overflow".into()))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, claim_generation = ?,
             attempts = ?, worker_id = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(new_fence)?)
        .bind(u64_blob(writer_generation.get()))
        .bind(i64::from(new_attempts))
        .bind(worker_id.as_str())
        .bind(lease_until)
        .bind(now)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .bind(destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let claimed_outbox = load_outbox(&mut tx, scope_id, operation_id, destination_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("claimed outbox row disappeared".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(DispatchClaim {
            operation,
            outbox: claimed_outbox,
            lease: DispatchLease {
                scope_id: scope_id.clone(),
                operation_id: operation_id.clone(),
                destination_id: destination_id.clone(),
                worker_id,
                writer_generation,
                fence: new_fence,
                expires_at_ms: lease_until,
            },
        })
    }

    pub async fn renew_claim(
        &self,
        lease: &DispatchLease,
        lease_ms: i64,
    ) -> Result<DispatchLease, OperationError> {
        validate_lease_ms(lease_ms)?;
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let outbox = require_current_lease(&mut tx, lease, now).await?;
        let new_fence = outbox
            .fence
            .checked_add(1)
            .ok_or_else(|| OperationError::Unavailable("outbox fence overflow".into()))?;
        let lease_until = now
            .checked_add(lease_ms)
            .ok_or_else(|| OperationError::Unavailable("lease time overflow".into()))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET fence = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(new_fence)?)
        .bind(lease_until)
        .bind(now)
        .bind(lease.scope_id.as_str())
        .bind(lease.operation_id.as_str())
        .bind(lease.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(DispatchLease {
            fence: new_fence,
            expires_at_ms: lease_until,
            ..lease.clone()
        })
    }

    /// Release a claim before the external-effect boundary has been armed.
    pub async fn retry_claim(
        &self,
        lease: &DispatchLease,
        delay_ms: i64,
    ) -> Result<(), OperationError> {
        if !(0..=MAX_DURABLE_LEASE_MS).contains(&delay_ms) {
            return Err(OperationError::InvalidTransition {
                from: "leased",
                to: "invalid_retry_delay",
            });
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let outbox = require_current_lease(&mut tx, lease, now).await?;
        let next = now
            .checked_add(delay_ms)
            .ok_or_else(|| OperationError::Unavailable("retry time overflow".into()))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'queued', fence = ?, worker_id = NULL,
             lease_until_ms = NULL, next_eligible_ms = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(outbox.fence + 1)?)
        .bind(next)
        .bind(now)
        .bind(lease.scope_id.as_str())
        .bind(lease.operation_id.as_str())
        .bind(lease.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(())
    }

    /// Durably cross the point after which a crash is an unknown external
    /// effect. The outbox becomes indeterminate before the adapter is entered,
    /// so no expired-lease worker can blindly resend this attempt.
    pub async fn arm_dispatch(
        &self,
        lease: &DispatchLease,
        dispatch_digest: Digest32,
    ) -> Result<ArmedDispatch, OperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch"));
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let outbox = require_current_lease(&mut tx, lease, now).await?;
        let operation = load_operation(&mut tx, &lease.scope_id, &lease.operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(lease.operation_id.clone()))?;
        if operation.state != DurableOperationState::Pending {
            return Err(OperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "dispatched",
            });
        }
        if operation.intent.writer_generation != lease.writer_generation {
            return Err(OperationError::StaleGeneration);
        }
        let next = next_revision(&operation)?;
        sqlx::query(
            "UPDATE operation_records SET state = 'dispatched', revision = ?,
             dispatch_digest = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_blob(next.get()))
        .bind(dispatch_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.scope_id.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let armed_fence = outbox
            .fence
            .checked_add(1)
            .ok_or_else(|| OperationError::Unavailable("outbox fence overflow".into()))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = ?,
             worker_id = NULL, lease_until_ms = NULL, reason_digest = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(armed_fence)?)
        .bind(dispatch_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.scope_id.as_str())
        .bind(lease.operation_id.as_str())
        .bind(lease.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let operation = load_operation(&mut tx, &lease.scope_id, &lease.operation_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("armed operation disappeared".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(ArmedDispatch {
            operation,
            fence: armed_fence,
            worker_id: lease.worker_id.clone(),
            writer_generation: lease.writer_generation,
        })
    }

    /// Record transport acknowledgement without claiming terminal success.
    pub async fn acknowledge_dispatch(
        &self,
        armed: &ArmedDispatch,
        acknowledgement_digest: Digest32,
    ) -> Result<(), OperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox acknowledgement"));
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let outbox = require_armed_outbox(&mut tx, armed).await?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'acknowledged', fence = ?,
             acknowledgement_digest = ?, reason_digest = NULL, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(outbox.fence + 1)?)
        .bind(acknowledgement_digest.as_array().as_slice())
        .bind(now)
        .bind(armed.operation.intent.scope_id.as_str())
        .bind(armed.operation.intent.operation_id.as_str())
        .bind(armed.operation.intent.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(())
    }

    pub async fn mark_dispatch_indeterminate(
        &self,
        armed: &ArmedDispatch,
        reason_digest: Digest32,
    ) -> Result<(), OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason"));
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let outbox = require_armed_outbox(&mut tx, armed).await?;
        let operation = load_operation(
            &mut tx,
            &armed.operation.intent.scope_id,
            &armed.operation.intent.operation_id,
        )
        .await?
        .ok_or_else(|| OperationError::Missing(armed.operation.intent.operation_id.clone()))?;
        if operation.state != DurableOperationState::Dispatched {
            return Err(OperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "indeterminate",
            });
        }
        let next = next_revision(&operation)?;
        sqlx::query(
            "UPDATE operation_records SET state = 'indeterminate', revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_blob(next.get()))
        .bind(now)
        .bind(armed.operation.intent.scope_id.as_str())
        .bind(armed.operation.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET fence = ?, reason_digest = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(u64_to_i64(outbox.fence + 1)?)
        .bind(reason_digest.as_array().as_slice())
        .bind(now)
        .bind(armed.operation.intent.scope_id.as_str())
        .bind(armed.operation.intent.operation_id.as_str())
        .bind(armed.operation.intent.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(())
    }

    /// Settle a dispatched/indeterminate operation from a trusted terminal
    /// observer. A newer generation may take ownership; a stale generation may
    /// not overwrite the current writer.
    pub async fn observe_terminal(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
        acknowledgement_digest: Option<Digest32>,
    ) -> Result<DurableOperationRecord, OperationError> {
        if evidence_digest.is_zero() {
            return Err(OperationError::InvalidDigest("terminal outcome"));
        }
        if acknowledgement_digest.is_some_and(Digest32::is_zero) {
            return Err(OperationError::InvalidDigest("outbox acknowledgement"));
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let operation = load_operation(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        if observer_generation < operation.intent.writer_generation {
            return Err(OperationError::StaleGeneration);
        }
        let target = terminal_state(outcome);
        if operation.state.is_terminal() {
            if operation.state == target && operation.terminal_digest == Some(evidence_digest) {
                tx.commit().await.map_err(storage)?;
                return Ok(operation);
            }
            return Err(OperationError::Terminal);
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(OperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: target.as_str(),
            });
        }
        let next = next_revision(&operation)?;
        sqlx::query(
            "UPDATE operation_records SET state = ?, writer_generation = ?, revision = ?,
             terminal_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(target.as_str())
        .bind(u64_blob(observer_generation.get()))
        .bind(u64_blob(next.get()))
        .bind(evidence_digest.as_array().as_slice())
        .bind(now)
        .bind(now)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let outbox = load_outbox(
            &mut tx,
            scope_id,
            operation_id,
            &operation.intent.destination_id,
        )
        .await?
        .ok_or_else(|| OperationError::Corrupt("terminal operation has no outbox".into()))?;
        if !matches!(
            outbox.state,
            DurableOutboxState::Indeterminate | DurableOutboxState::Acknowledged
        ) {
            return Err(OperationError::Corrupt(
                "terminal settlement found a retryable outbox state".into(),
            ));
        }
        let outbox_state = if outcome == ReconciliationOutcome::Quarantined {
            DurableOutboxState::Quarantined
        } else {
            DurableOutboxState::Settled
        };
        let acknowledgement = acknowledgement_digest.or(outbox.acknowledgement_digest);
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = ?, fence = ?, claim_generation = ?,
             acknowledgement_digest = ?, reason_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
        )
        .bind(outbox_state.as_str())
        .bind(u64_to_i64(outbox.fence + 1)?)
        .bind(u64_blob(observer_generation.get()))
        .bind(acknowledgement.map(|digest| digest.into_array().to_vec()))
        .bind(if outcome == ReconciliationOutcome::Quarantined {
            Some(evidence_digest.into_array().to_vec())
        } else {
            None
        })
        .bind(now)
        .bind(now)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .bind(operation.intent.destination_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let settled = load_operation(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("settled operation disappeared".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(settled)
    }

    /// Explicitly quarantine an exhausted pre-dispatch operation. This path is
    /// terminal but proves no external effect; compensation remains a new
    /// operation if a domain owner later needs one.
    pub async fn quarantine_pending(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        writer_generation: Generation,
        reason_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("quarantine reason"));
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let operation = load_operation(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        if operation.state != DurableOperationState::Pending {
            return Err(OperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "quarantined",
            });
        }
        if writer_generation < operation.intent.writer_generation {
            return Err(OperationError::StaleGeneration);
        }
        let outbox = load_outbox(
            &mut tx,
            scope_id,
            operation_id,
            &operation.intent.destination_id,
        )
        .await?
        .ok_or_else(|| OperationError::Corrupt("pending operation has no outbox".into()))?;
        quarantine_pre_dispatch(
            &mut tx,
            &operation,
            &outbox,
            writer_generation,
            reason_digest,
            now,
        )
        .await?;
        let terminal = load_operation(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("quarantined operation disappeared".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(terminal)
    }

    /// Move old terminal identities into tombstones before deleting payload-free
    /// live rows. Tombstones remain authoritative for conflict/resurrection
    /// checks and are intentionally not pruned by this method.
    pub async fn prune_terminal(&self, limit: u32) -> Result<u32, OperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(OperationError::InvalidTransition {
                from: "retention",
                to: "invalid_prune_limit",
            });
        }
        let mut tx = self.begin_immediate().await?;
        let now = now_millis()?;
        let cutoff = now.saturating_sub(self.config.terminal_retention_ms);
        let mut terminal_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_records
             WHERE state IN ('applied', 'not_applied', 'quarantined')",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let rows = sqlx::query(
            "SELECT * FROM operation_records
             WHERE state IN ('applied', 'not_applied', 'quarantined')
             ORDER BY terminal_at_ms, scope_id, operation_id LIMIT ?",
        )
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut pruned = 0_u32;
        for row in rows {
            let record = decode_operation(row)?;
            let terminal_at = record
                .terminal_at_ms
                .ok_or_else(|| OperationError::Corrupt("terminal row has no timestamp".into()))?;
            if terminal_at > cutoff && terminal_count <= self.config.terminal_retained_rows {
                break;
            }
            let digest = record
                .terminal_digest
                .ok_or_else(|| OperationError::Corrupt("terminal row has no digest".into()))?;
            sqlx::query(
                "INSERT OR IGNORE INTO operation_tombstones
                 (scope_id, operation_id, scope_digest, request_digest, payload_digest,
                  destination_id, terminal_state, terminal_digest, terminal_at_ms, pruned_at_ms)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(record.intent.scope_id.as_str())
            .bind(record.intent.operation_id.as_str())
            .bind(record.intent.scope_digest.as_array().as_slice())
            .bind(record.intent.request_digest.as_array().as_slice())
            .bind(record.intent.payload_digest.as_array().as_slice())
            .bind(record.intent.destination_id.as_str())
            .bind(record.state.as_str())
            .bind(digest.as_array().as_slice())
            .bind(terminal_at)
            .bind(now)
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
            sqlx::query(
                "DELETE FROM cross_owner_outbox
                 WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
            )
            .bind(record.intent.scope_id.as_str())
            .bind(record.intent.operation_id.as_str())
            .bind(record.intent.destination_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
            sqlx::query("DELETE FROM operation_records WHERE scope_id = ? AND operation_id = ?")
                .bind(record.intent.scope_id.as_str())
                .bind(record.intent.operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(storage)?;
            terminal_count -= 1;
            pruned += 1;
        }
        tx.commit().await.map_err(storage)?;
        Ok(pruned)
    }

    pub async fn metrics(&self) -> Result<DurableOperationMetrics, OperationError> {
        let now = now_millis()?;
        let active_operations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_records
             WHERE state NOT IN ('applied', 'not_applied', 'quarantined')",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let terminal_operations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_records
             WHERE state IN ('applied', 'not_applied', 'quarantined')",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let queued_outbox = count_outbox(&self.pool, "queued").await?;
        let leased_outbox = count_outbox(&self.pool, "leased").await?;
        let acknowledged_outbox = count_outbox(&self.pool, "acknowledged").await?;
        let indeterminate_outbox = count_outbox(&self.pool, "indeterminate").await?;
        let oldest_ready: Option<i64> = sqlx::query_scalar(
            "SELECT MIN(next_eligible_ms) FROM cross_owner_outbox WHERE state = 'queued'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        let tombstones: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operation_tombstones")
            .fetch_one(&self.pool)
            .await
            .map_err(storage)?;
        Ok(DurableOperationMetrics {
            active_operations,
            terminal_operations,
            queued_outbox,
            leased_outbox,
            acknowledged_outbox,
            indeterminate_outbox,
            oldest_ready_age_ms: oldest_ready.map(|timestamp| now.saturating_sub(timestamp)),
            tombstones,
        })
    }

    async fn begin_immediate(&self) -> Result<Transaction<'static, Sqlite>, OperationError> {
        self.pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)
    }
}

async fn verify_quick_check(pool: &SqlitePool) -> Result<(), OperationError> {
    let result: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(pool)
        .await
        .map_err(storage)?;
    if result != "ok" {
        return Err(OperationError::Corrupt(format!(
            "SQLite quick_check returned {result:?}"
        )));
    }
    Ok(())
}

async fn verify_store(pool: &SqlitePool) -> Result<(), OperationError> {
    verify_quick_check(pool).await?;
    for table in [
        "operation_records",
        "cross_owner_outbox",
        "operation_tombstones",
    ] {
        let present: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
        )
        .bind(table)
        .fetch_one(pool)
        .await
        .map_err(storage)?;
        if present != 1 {
            return Err(OperationError::Corrupt(format!(
                "required table {table} is missing"
            )));
        }
    }
    let foreign_key_violation = sqlx::query("PRAGMA foreign_key_check")
        .fetch_optional(pool)
        .await
        .map_err(storage)?;
    if foreign_key_violation.is_some() {
        return Err(OperationError::Corrupt(
            "SQLite foreign_key_check reported a violation".into(),
        ));
    }
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(pool)
        .await
        .map_err(storage)?;
    if !journal.eq_ignore_ascii_case("wal") {
        return Err(OperationError::Unavailable(format!(
            "durable operation store requires WAL, found {journal}"
        )));
    }
    Ok(())
}

async fn require_predecessor(
    tx: &mut Transaction<'_, Sqlite>,
    intent: &DurableOperationIntent,
) -> Result<(), OperationError> {
    let Some(predecessor) = intent.expected_predecessor.as_ref() else {
        return Ok(());
    };
    if let Some(record) = load_operation(tx, &intent.scope_id, predecessor).await? {
        if record.state.is_terminal() {
            return Ok(());
        }
        return Err(OperationError::InvalidTransition {
            from: record.state.as_str(),
            to: "predecessor_required_terminal",
        });
    }
    if tombstone_exists(tx, &intent.scope_id, predecessor).await? {
        return Ok(());
    }
    Err(OperationError::Missing(predecessor.clone()))
}

async fn require_current_lease(
    tx: &mut Transaction<'_, Sqlite>,
    lease: &DispatchLease,
    now: i64,
) -> Result<DurableOutboxRecord, OperationError> {
    let outbox = load_outbox(
        tx,
        &lease.scope_id,
        &lease.operation_id,
        &lease.destination_id,
    )
    .await?
    .ok_or_else(|| OperationError::Missing(lease.operation_id.clone()))?;
    if outbox.state != DurableOutboxState::Leased
        || outbox.fence != lease.fence
        || outbox.worker_id.as_ref() != Some(&lease.worker_id)
        || outbox.claim_generation != Some(lease.writer_generation)
        || outbox.lease_until_ms.is_none_or(|deadline| deadline <= now)
    {
        return Err(OperationError::StaleLease);
    }
    Ok(outbox)
}

async fn require_armed_outbox(
    tx: &mut Transaction<'_, Sqlite>,
    armed: &ArmedDispatch,
) -> Result<DurableOutboxRecord, OperationError> {
    let outbox = load_outbox(
        tx,
        &armed.operation.intent.scope_id,
        &armed.operation.intent.operation_id,
        &armed.operation.intent.destination_id,
    )
    .await?
    .ok_or_else(|| OperationError::Missing(armed.operation.intent.operation_id.clone()))?;
    if outbox.state != DurableOutboxState::Indeterminate
        || outbox.fence != armed.fence
        || outbox.claim_generation != Some(armed.writer_generation)
    {
        return Err(OperationError::StaleLease);
    }
    Ok(outbox)
}

async fn quarantine_pre_dispatch(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &DurableOperationRecord,
    outbox: &DurableOutboxRecord,
    writer_generation: Generation,
    reason_digest: Digest32,
    now: i64,
) -> Result<(), OperationError> {
    let next = next_revision(operation)?;
    sqlx::query(
        "UPDATE operation_records SET state = 'quarantined', writer_generation = ?, revision = ?,
         terminal_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(u64_blob(writer_generation.get()))
    .bind(u64_blob(next.get()))
    .bind(reason_digest.as_array().as_slice())
    .bind(now)
    .bind(now)
    .bind(operation.intent.scope_id.as_str())
    .bind(operation.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'quarantined', fence = ?, claim_generation = ?,
         worker_id = NULL, lease_until_ms = NULL, reason_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
    )
    .bind(u64_to_i64(outbox.fence + 1)?)
    .bind(u64_blob(writer_generation.get()))
    .bind(reason_digest.as_array().as_slice())
    .bind(now)
    .bind(now)
    .bind(operation.intent.scope_id.as_str())
    .bind(operation.intent.operation_id.as_str())
    .bind(operation.intent.destination_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn load_operation(
    tx: &mut Transaction<'_, Sqlite>,
    scope_id: &StableId,
    operation_id: &StableId,
) -> Result<Option<DurableOperationRecord>, OperationError> {
    sqlx::query("SELECT * FROM operation_records WHERE scope_id = ? AND operation_id = ?")
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?
        .map(decode_operation)
        .transpose()
}

async fn load_outbox(
    tx: &mut Transaction<'_, Sqlite>,
    scope_id: &StableId,
    operation_id: &StableId,
    destination_id: &StableId,
) -> Result<Option<DurableOutboxRecord>, OperationError> {
    sqlx::query(
        "SELECT * FROM cross_owner_outbox
         WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
    )
    .bind(scope_id.as_str())
    .bind(operation_id.as_str())
    .bind(destination_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .map(decode_outbox)
    .transpose()
}

async fn tombstone_exists(
    tx: &mut Transaction<'_, Sqlite>,
    scope_id: &StableId,
    operation_id: &StableId,
) -> Result<bool, OperationError> {
    sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM operation_tombstones WHERE scope_id = ? AND operation_id = ?)",
    )
    .bind(scope_id.as_str())
    .bind(operation_id.as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)
}

fn decode_operation(row: SqliteRow) -> Result<DurableOperationRecord, OperationError> {
    let scope_id = stable_id(row.try_get::<String, _>("scope_id").map_err(storage)?)?;
    let operation_id = stable_id(
        row.try_get::<String, _>("operation_id")
            .map_err(storage)?,
    )?;
    let destination_id = stable_id(
        row.try_get::<String, _>("destination_id")
            .map_err(storage)?,
    )?;
    let predecessor = row
        .try_get::<Option<String>, _>("predecessor_operation_id")
        .map_err(storage)?
        .map(stable_id)
        .transpose()?;
    let writer_generation = generation(blob_u64(
        &row.try_get::<Vec<u8>, _>("writer_generation")
            .map_err(storage)?,
        "writer generation",
    )?)?;
    let authority_epoch = generation(blob_u64(
        &row.try_get::<Vec<u8>, _>("authority_epoch")
            .map_err(storage)?,
        "authority epoch",
    )?)?;
    let revision = revision(blob_u64(
        &row.try_get::<Vec<u8>, _>("revision").map_err(storage)?,
        "revision",
    )?)?;
    let state_text = row.try_get::<String, _>("state").map_err(storage)?;
    let state = DurableOperationState::parse(&state_text).ok_or_else(|| {
        OperationError::Corrupt(format!("unknown durable operation state {state_text:?}"))
    })?;
    Ok(DurableOperationRecord {
        intent: DurableOperationIntent {
            scope_id,
            operation_id,
            scope_digest: digest(
                row.try_get::<Vec<u8>, _>("scope_digest")
                    .map_err(storage)?,
                "scope digest",
            )?,
            request_digest: digest(
                row.try_get::<Vec<u8>, _>("request_digest")
                    .map_err(storage)?,
                "request digest",
            )?,
            payload_digest: digest(
                row.try_get::<Vec<u8>, _>("payload_digest")
                    .map_err(storage)?,
                "payload digest",
            )?,
            destination_id,
            expected_predecessor: predecessor,
            writer_generation,
            authority_epoch,
        },
        revision,
        state,
        dispatch_digest: optional_digest(
            row.try_get::<Option<Vec<u8>>, _>("dispatch_digest")
                .map_err(storage)?,
            "dispatch digest",
        )?,
        terminal_digest: optional_digest(
            row.try_get::<Option<Vec<u8>>, _>("terminal_digest")
                .map_err(storage)?,
            "terminal digest",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(storage)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(storage)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(storage)?,
    })
}

fn decode_outbox(row: SqliteRow) -> Result<DurableOutboxRecord, OperationError> {
    let state_text = row.try_get::<String, _>("state").map_err(storage)?;
    let state = DurableOutboxState::parse(&state_text).ok_or_else(|| {
        OperationError::Corrupt(format!("unknown durable outbox state {state_text:?}"))
    })?;
    let fence: i64 = row.try_get("fence").map_err(storage)?;
    let attempts: i64 = row.try_get("attempts").map_err(storage)?;
    Ok(DurableOutboxRecord {
        scope_id: stable_id(row.try_get::<String, _>("scope_id").map_err(storage)?)?,
        operation_id: stable_id(
            row.try_get::<String, _>("operation_id")
                .map_err(storage)?,
        )?,
        destination_id: stable_id(
            row.try_get::<String, _>("destination_id")
                .map_err(storage)?,
        )?,
        payload_digest: digest(
            row.try_get::<Vec<u8>, _>("payload_digest")
                .map_err(storage)?,
            "outbox payload digest",
        )?,
        state,
        fence: u64::try_from(fence)
            .map_err(|_| OperationError::Corrupt("negative outbox fence".into()))?,
        claim_generation: row
            .try_get::<Option<Vec<u8>>, _>("claim_generation")
            .map_err(storage)?
            .map(|bytes| blob_u64(&bytes, "claim generation").and_then(generation))
            .transpose()?,
        attempts: u32::try_from(attempts)
            .map_err(|_| OperationError::Corrupt("invalid outbox attempts".into()))?,
        worker_id: row
            .try_get::<Option<String>, _>("worker_id")
            .map_err(storage)?
            .map(stable_id)
            .transpose()?,
        lease_until_ms: row.try_get("lease_until_ms").map_err(storage)?,
        next_eligible_ms: row.try_get("next_eligible_ms").map_err(storage)?,
        acknowledgement_digest: optional_digest(
            row.try_get::<Option<Vec<u8>>, _>("acknowledgement_digest")
                .map_err(storage)?,
            "outbox acknowledgement digest",
        )?,
        reason_digest: optional_digest(
            row.try_get::<Option<Vec<u8>>, _>("reason_digest")
                .map_err(storage)?,
            "outbox reason digest",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(storage)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(storage)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(storage)?,
    })
}

fn same_semantics(left: &DurableOperationIntent, right: &DurableOperationIntent) -> bool {
    left.scope_id == right.scope_id
        && left.operation_id == right.operation_id
        && left.scope_digest == right.scope_digest
        && left.request_digest == right.request_digest
        && left.payload_digest == right.payload_digest
        && left.destination_id == right.destination_id
        && left.expected_predecessor == right.expected_predecessor
        && left.authority_epoch == right.authority_epoch
}

fn terminal_state(outcome: ReconciliationOutcome) -> DurableOperationState {
    match outcome {
        ReconciliationOutcome::Applied => DurableOperationState::Applied,
        ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
        ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
    }
}

fn next_revision(record: &DurableOperationRecord) -> Result<Revision, OperationError> {
    record
        .revision
        .next()
        .map_err(|_| OperationError::Conflict(record.intent.operation_id.clone()))
}

fn validate_lease_ms(lease_ms: i64) -> Result<(), OperationError> {
    if !(1..=MAX_DURABLE_LEASE_MS).contains(&lease_ms) {
        return Err(OperationError::InvalidTransition {
            from: "queued",
            to: "invalid_lease_duration",
        });
    }
    Ok(())
}

fn stable_id(value: String) -> Result<StableId, OperationError> {
    StableId::new(value).map_err(|error| OperationError::Corrupt(error.to_string()))
}

fn generation(value: u64) -> Result<Generation, OperationError> {
    Generation::new(value).map_err(|error| OperationError::Corrupt(error.to_string()))
}

fn revision(value: u64) -> Result<Revision, OperationError> {
    Revision::new(value).map_err(|error| OperationError::Corrupt(error.to_string()))
}

fn digest(bytes: Vec<u8>, label: &'static str) -> Result<Digest32, OperationError> {
    let array: [u8; 32] = bytes.try_into().map_err(|_| {
        OperationError::Corrupt(format!("{label} has an invalid encoded length"))
    })?;
    let digest = Digest32::from_array(array);
    if digest.is_zero() {
        return Err(OperationError::Corrupt(format!("{label} is zero")));
    }
    Ok(digest)
}

fn optional_digest(
    bytes: Option<Vec<u8>>,
    label: &'static str,
) -> Result<Option<Digest32>, OperationError> {
    bytes.map(|value| digest(value, label)).transpose()
}

fn u64_blob(value: u64) -> Vec<u8> {
    value.to_be_bytes().to_vec()
}

fn blob_u64(bytes: &[u8], label: &'static str) -> Result<u64, OperationError> {
    let array: [u8; 8] = bytes
        .try_into()
        .map_err(|_| OperationError::Corrupt(format!("{label} has an invalid encoded length")))?;
    Ok(u64::from_be_bytes(array))
}

fn u64_to_i64(value: u64) -> Result<i64, OperationError> {
    i64::try_from(value).map_err(|_| OperationError::Unavailable("outbox fence overflow".into()))
}

fn storage(error: sqlx::Error) -> OperationError {
    OperationError::Storage(error.to_string())
}

fn now_millis() -> Result<i64, OperationError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OperationError::Unavailable("clock predates Unix epoch".into()))?;
    i64::try_from(duration.as_millis())
        .map_err(|_| OperationError::Unavailable("clock exceeds SQLite integer range".into()))
}

async fn count_outbox(pool: &SqlitePool, state: &str) -> Result<i64, OperationError> {
    sqlx::query_scalar("SELECT COUNT(*) FROM cross_owner_outbox WHERE state = ?")
        .bind(state)
        .fetch_one(pool)
        .await
        .map_err(storage)
}
