use std::fmt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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

use crate::ReconciliationOutcome;

pub const MAX_DURABLE_OPERATION_ROWS: i64 = 100_000;
pub const MAX_DURABLE_OUTBOX_ROWS: i64 = 100_000;
pub const MAX_DURABLE_CLAIM_BATCH: u32 = 256;
pub const MAX_DURABLE_ATTEMPTS: u32 = 32;
pub const MAX_DURABLE_LEASE_MS: i64 = 60_000;
pub const MAX_DURABLE_RETRY_DELAY_MS: i64 = 300_000;
pub const DEFAULT_BUSY_TIMEOUT_MS: u64 = 5_000;

const CRASH_AFTER_DISPATCH_DOMAIN: &[u8] = b"hepta.kernel.operations.crash-after-dispatch.v1\0";
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationIdentity {
    pub scope_id: StableId,
    pub operation_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableIntent {
    pub identity: OperationIdentity,
    pub predecessor_id: Option<StableId>,
    pub destination_id: StableId,
    pub payload_digest: Digest32,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
}

impl DurableIntent {
    pub fn validate(&self) -> Result<(), DurableOperationError> {
        if self.payload_digest.is_zero() {
            return Err(DurableOperationError::InvalidRequest(
                "payload digest must be nonzero",
            ));
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.durable-intent.v1\0".to_vec();
        push_id(&mut bytes, &self.identity.scope_id);
        push_id(&mut bytes, &self.identity.operation_id);
        match &self.predecessor_id {
            Some(value) => {
                bytes.push(1);
                push_id(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        push_id(&mut bytes, &self.destination_id);
        bytes.extend_from_slice(self.payload_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOperationState {
    Prepared,
    Dispatched,
    Indeterminate,
    Applied,
    NotApplied,
    Quarantined,
}

impl DurableOperationState {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }

    fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "dispatched" => Ok(Self::Dispatched),
            "indeterminate" => Ok(Self::Indeterminate),
            "applied" => Ok(Self::Applied),
            "not_applied" => Ok(Self::NotApplied),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown operation state: {value}"
            ))),
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Applied | Self::NotApplied | Self::Quarantined)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Queued,
    Leased,
    Indeterminate,
    Acknowledged,
    Quarantined,
}

impl DurableOutboxState {
    fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "queued" => Ok(Self::Queued),
            "leased" => Ok(Self::Leased),
            "indeterminate" => Ok(Self::Indeterminate),
            "acknowledged" => Ok(Self::Acknowledged),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown outbox state: {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationStatus {
    pub intent: DurableIntent,
    pub semantic_digest: Digest32,
    pub revision: Revision,
    pub state: DurableOperationState,
    pub dispatch_digest: Option<Digest32>,
    pub indeterminate_digest: Option<Digest32>,
    pub terminal_evidence_digest: Option<Digest32>,
    pub terminal_observer_id: Option<StableId>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOutboxStatus {
    pub identity: OperationIdentity,
    pub destination_id: StableId,
    pub payload_digest: Digest32,
    pub semantic_digest: Digest32,
    pub state: DurableOutboxState,
    pub fence: u64,
    pub attempts: u32,
    pub worker_id: Option<StableId>,
    pub claim_owner_generation: Option<Generation>,
    pub lease_until_ms: Option<i64>,
    pub next_eligible_at_ms: i64,
    pub acknowledgement_digest: Option<Digest32>,
    pub acknowledgement_watermark: Option<u64>,
    pub last_error_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchLease {
    pub identity: OperationIdentity,
    pub destination_id: StableId,
    pub payload_digest: Digest32,
    pub semantic_digest: Digest32,
    pub worker_id: StableId,
    pub owner_generation: Generation,
    pub fence: u64,
    pub attempts: u32,
    pub expires_at_ms: i64,
}

impl DispatchLease {
    pub fn dispatch_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.dispatch-attempt.v1\0".to_vec();
        push_id(&mut bytes, &self.identity.scope_id);
        push_id(&mut bytes, &self.identity.operation_id);
        push_id(&mut bytes, &self.destination_id);
        push_id(&mut bytes, &self.worker_id);
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(&self.owner_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.fence.to_be_bytes());
        bytes.extend_from_slice(&u64::from(self.attempts).to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RecoveryReport {
    pub requeued_before_dispatch: u64,
    pub marked_indeterminate_after_dispatch: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct OperationMetrics {
    pub prepared_operations: i64,
    pub dispatched_operations: i64,
    pub indeterminate_operations: i64,
    pub terminal_operations: i64,
    pub queued_outbox: i64,
    pub leased_outbox: i64,
    pub indeterminate_outbox: i64,
    pub terminal_outbox: i64,
    pub oldest_ready_age_ms: Option<i64>,
}

#[derive(Clone)]
pub struct DurableOperationStore {
    pub(crate) pool: SqlitePool,
    path: PathBuf,
}

impl fmt::Debug for DurableOperationStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableOperationStore")
            .field("path", &self.path)
            .finish_non_exhaustive()
    }
}

impl DurableOperationStore {
    pub async fn open(path: impl AsRef<Path>) -> Result<Self, DurableOperationError> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| {
                DurableOperationError::Unavailable(format!(
                    "failed to create operation-store directory: {error}"
                ))
            })?;
        }
        let options = SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_millis(DEFAULT_BUSY_TIMEOUT_MS));
        let pool = SqlitePoolOptions::new()
            .max_connections(8)
            .connect_with(options)
            .await
            .map_err(classify_sqlx_error)?;
        if let Err(error) = verify_quick_check(&pool).await {
            pool.close().await;
            return Err(error);
        }
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(DurableOperationError::Migration(error.to_string()));
        }
        if let Err(error) = verify_integrity(&pool).await {
            pool.close().await;
            return Err(error);
        }
        let store = Self { pool, path };
        store.recover_expired_leases().await?;
        Ok(store)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn prepare_intent(
        &self,
        intent: &DurableIntent,
    ) -> Result<DurableOperationStatus, DurableOperationError> {
        intent.validate()?;
        let now = now_millis()?;
        let semantic_digest = intent.semantic_digest();
        let mut tx = self.begin_immediate().await?;
        if let Some(existing) = load_operation(&mut tx, &intent.identity).await? {
            if existing.semantic_digest == semantic_digest {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(existing);
            }
            return Err(DurableOperationError::Conflict(
                intent.identity.operation_id.clone(),
            ));
        }
        enforce_prepare_capacity(&mut tx).await?;
        let revision = revision(1)?;
        sqlx::query(
            "INSERT INTO operation_ledger (
                scope_id, operation_id, predecessor_id, destination_id, payload_digest,
                semantic_digest, owner_generation, authority_epoch, revision, state,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
        )
        .bind(intent.identity.scope_id.as_str())
        .bind(intent.identity.operation_id.as_str())
        .bind(intent.predecessor_id.as_ref().map(StableId::as_str))
        .bind(intent.destination_id.as_str())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(semantic_digest.as_array().as_slice())
        .bind(u64_bytes(intent.owner_generation.get()).as_slice())
        .bind(u64_bytes(intent.authority_epoch.get()).as_slice())
        .bind(u64_bytes(revision.get()).as_slice())
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "INSERT INTO cross_owner_outbox (
                scope_id, operation_id, destination_id, payload_digest, semantic_digest,
                state, fence, attempts, next_eligible_at_ms, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?)",
        )
        .bind(intent.identity.scope_id.as_str())
        .bind(intent.identity.operation_id.as_str())
        .bind(intent.destination_id.as_str())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(semantic_digest.as_array().as_slice())
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let status = load_operation(&mut tx, &intent.identity)
            .await?
            .ok_or_else(|| {
                DurableOperationError::Corrupt("inserted operation is missing".into())
            })?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn bind_authority_epoch(
        &self,
        identity: &OperationIdentity,
        authority_epoch: Generation,
    ) -> Result<DurableOperationStatus, DurableOperationError> {
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        let operation = load_operation(&mut tx, identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        if operation.state != DurableOperationState::Prepared {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "authority_epoch_rebind",
            });
        }
        if authority_epoch < operation.intent.authority_epoch {
            return Err(DurableOperationError::StaleGeneration);
        }
        if authority_epoch == operation.intent.authority_epoch {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(operation);
        }
        let next = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET authority_epoch = ?, revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_bytes(authority_epoch.get()).as_slice())
        .bind(u64_bytes(next.get()).as_slice())
        .bind(now)
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let status = load_operation(&mut tx, identity).await?.ok_or_else(|| {
            DurableOperationError::Corrupt("operation disappeared during authority rebind".into())
        })?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn operation_status(
        &self,
        identity: &OperationIdentity,
    ) -> Result<Option<DurableOperationStatus>, DurableOperationError> {
        sqlx::query("SELECT * FROM operation_ledger WHERE scope_id = ? AND operation_id = ?")
            .bind(identity.scope_id.as_str())
            .bind(identity.operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?
            .map(decode_operation)
            .transpose()
    }

    pub async fn outbox_status(
        &self,
        identity: &OperationIdentity,
    ) -> Result<Option<DurableOutboxStatus>, DurableOperationError> {
        sqlx::query("SELECT * FROM cross_owner_outbox WHERE scope_id = ? AND operation_id = ?")
            .bind(identity.scope_id.as_str())
            .bind(identity.operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?
            .map(decode_outbox)
            .transpose()
    }

    pub async fn ready_outbox(
        &self,
        destination: &StableId,
        limit: u32,
    ) -> Result<Vec<DurableOutboxStatus>, DurableOperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(DurableOperationError::InvalidRequest(
                "claim batch must be 1..=256",
            ));
        }
        let now = now_millis()?;
        let rows = sqlx::query(
            "SELECT * FROM cross_owner_outbox
             WHERE destination_id = ? AND state = 'queued' AND next_eligible_at_ms <= ?
             ORDER BY next_eligible_at_ms, scope_id, operation_id LIMIT ?",
        )
        .bind(destination.as_str())
        .bind(now)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        rows.into_iter().map(decode_outbox).collect()
    }

    pub async fn claim_outbox(
        &self,
        identity: &OperationIdentity,
        worker_id: &StableId,
        owner_generation: Generation,
        lease_ms: i64,
    ) -> Result<DispatchLease, DurableOperationError> {
        validate_lease(lease_ms)?;
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        let outbox = load_outbox(&mut tx, identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        let operation = load_operation(&mut tx, identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        if outbox.attempts >= MAX_DURABLE_ATTEMPTS {
            quarantine_in_tx(
                &mut tx,
                identity,
                Digest32::of_bytes(b"hepta.kernel.operations.max-attempts.v1\0"),
                now,
            )
            .await?;
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Err(DurableOperationError::AttemptsExhausted);
        }
        match outbox.state {
            DurableOutboxState::Queued => {
                if outbox.next_eligible_at_ms > now {
                    return Err(DurableOperationError::Unavailable(
                        "outbox intent is not yet eligible".into(),
                    ));
                }
            }
            DurableOutboxState::Leased => {
                let until = outbox.lease_until_ms.ok_or_else(|| {
                    DurableOperationError::Corrupt("leased outbox row has no deadline".into())
                })?;
                if until > now {
                    return Err(DurableOperationError::Unavailable(
                        "outbox intent is already leased".into(),
                    ));
                }
                if matches!(
                    operation.state,
                    DurableOperationState::Dispatched | DurableOperationState::Indeterminate
                ) {
                    mark_recovery_indeterminate(&mut tx, identity, now).await?;
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Err(DurableOperationError::RequiresReconciliation);
                }
                if operation.state.is_terminal() {
                    return Err(DurableOperationError::Terminal);
                }
                if let Some(existing) = outbox.claim_owner_generation {
                    if owner_generation < existing {
                        return Err(DurableOperationError::StaleGeneration);
                    }
                }
            }
            DurableOutboxState::Indeterminate => {
                return Err(DurableOperationError::RequiresReconciliation);
            }
            DurableOutboxState::Acknowledged | DurableOutboxState::Quarantined => {
                return Err(DurableOperationError::Terminal);
            }
        }
        let fence = outbox
            .fence
            .checked_add(1)
            .ok_or(DurableOperationError::FenceOverflow)?;
        let attempts = outbox
            .attempts
            .checked_add(1)
            .ok_or(DurableOperationError::AttemptsExhausted)?;
        let lease_until = now
            .checked_add(lease_ms)
            .ok_or(DurableOperationError::InvalidRequest("lease time overflow"))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, attempts = ?,
             worker_id = ?, claim_owner_generation = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(i64_from_u64(fence, "fence")?)
        .bind(i64::from(attempts))
        .bind(worker_id.as_str())
        .bind(u64_bytes(owner_generation.get()).as_slice())
        .bind(lease_until)
        .bind(now)
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if owner_generation > operation.intent.owner_generation {
            sqlx::query(
                "UPDATE operation_ledger SET owner_generation = ?, updated_at_ms = ?
                 WHERE scope_id = ? AND operation_id = ?",
            )
            .bind(u64_bytes(owner_generation.get()).as_slice())
            .bind(now)
            .bind(identity.scope_id.as_str())
            .bind(identity.operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(DispatchLease {
            identity: identity.clone(),
            destination_id: outbox.destination_id,
            payload_digest: outbox.payload_digest,
            semantic_digest: outbox.semantic_digest,
            worker_id: worker_id.clone(),
            owner_generation,
            fence,
            attempts,
            expires_at_ms: lease_until,
        })
    }

    pub async fn mark_dispatch_started(
        &self,
        lease: &DispatchLease,
    ) -> Result<DurableOperationStatus, DurableOperationError> {
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        require_current_lease(&mut tx, lease, now).await?;
        let operation = load_operation(&mut tx, &lease.identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.identity.operation_id.clone()))?;
        let dispatch_digest = lease.dispatch_digest();
        if operation.state == DurableOperationState::Dispatched
            && operation.dispatch_digest == Some(dispatch_digest)
        {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(operation);
        }
        if operation.state != DurableOperationState::Prepared {
            if operation.state == DurableOperationState::Indeterminate {
                return Err(DurableOperationError::RequiresReconciliation);
            }
            if operation.state.is_terminal() {
                return Err(DurableOperationError::Terminal);
            }
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "dispatched",
            });
        }
        let next = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatched', revision = ?, dispatch_digest = ?,
             updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_bytes(next.get()).as_slice())
        .bind(dispatch_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.identity.scope_id.as_str())
        .bind(lease.identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let status = load_operation(&mut tx, &lease.identity)
            .await?
            .ok_or_else(|| {
                DurableOperationError::Corrupt("dispatched operation disappeared".into())
            })?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn requeue_not_attempted(
        &self,
        lease: &DispatchLease,
        reason_digest: Digest32,
        retry_after_ms: i64,
    ) -> Result<(), DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::InvalidRequest(
                "retry reason digest must be nonzero",
            ));
        }
        if !(0..=MAX_DURABLE_RETRY_DELAY_MS).contains(&retry_after_ms) {
            return Err(DurableOperationError::InvalidRequest(
                "retry delay must be 0..=300000 ms",
            ));
        }
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        require_current_lease(&mut tx, lease, now).await?;
        let operation = load_operation(&mut tx, &lease.identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.identity.operation_id.clone()))?;
        match operation.state {
            DurableOperationState::Prepared => {}
            DurableOperationState::Dispatched
                if operation.dispatch_digest == Some(lease.dispatch_digest()) =>
            {
                let next = next_revision(operation.revision)?;
                sqlx::query(
                    "UPDATE operation_ledger SET state = 'prepared', revision = ?,
                     dispatch_digest = NULL, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
                )
                .bind(u64_bytes(next.get()).as_slice())
                .bind(now)
                .bind(lease.identity.scope_id.as_str())
                .bind(lease.identity.operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            }
            DurableOperationState::Indeterminate => {
                return Err(DurableOperationError::RequiresReconciliation);
            }
            state if state.is_terminal() => return Err(DurableOperationError::Terminal),
            _ => return Err(DurableOperationError::RequiresReconciliation),
        }
        let next_eligible = now
            .checked_add(retry_after_ms)
            .ok_or(DurableOperationError::InvalidRequest("retry time overflow"))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'queued', fence = fence + 1,
             worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
             next_eligible_at_ms = ?, last_error_digest = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(next_eligible)
        .bind(reason_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.identity.scope_id.as_str())
        .bind(lease.identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn record_transport_ack(
        &self,
        lease: &DispatchLease,
        acknowledgement_digest: Digest32,
        acknowledgement_watermark: u64,
    ) -> Result<(), DurableOperationError> {
        if acknowledgement_digest.is_zero() || acknowledgement_watermark == 0 {
            return Err(DurableOperationError::InvalidRequest(
                "transport acknowledgement requires nonzero digest and watermark",
            ));
        }
        self.mark_indeterminate_internal(
            lease,
            acknowledgement_digest,
            Some((acknowledgement_digest, acknowledgement_watermark)),
        )
        .await
    }

    pub async fn mark_indeterminate(
        &self,
        lease: &DispatchLease,
        reason_digest: Digest32,
    ) -> Result<(), DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::InvalidRequest(
                "indeterminate reason digest must be nonzero",
            ));
        }
        self.mark_indeterminate_internal(lease, reason_digest, None)
            .await
    }

    async fn mark_indeterminate_internal(
        &self,
        lease: &DispatchLease,
        reason_digest: Digest32,
        acknowledgement: Option<(Digest32, u64)>,
    ) -> Result<(), DurableOperationError> {
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        require_current_lease(&mut tx, lease, now).await?;
        let operation = load_operation(&mut tx, &lease.identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.identity.operation_id.clone()))?;
        if operation.state == DurableOperationState::Indeterminate
            && operation.indeterminate_digest == Some(reason_digest)
        {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(());
        }
        if operation.state != DurableOperationState::Dispatched {
            if operation.state.is_terminal() {
                return Err(DurableOperationError::Terminal);
            }
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "indeterminate",
            });
        }
        let next = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate', revision = ?,
             indeterminate_digest = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_bytes(next.get()).as_slice())
        .bind(reason_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.identity.scope_id.as_str())
        .bind(lease.identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let ack_digest = acknowledgement.map(|value| value.0.into_array().to_vec());
        let watermark = acknowledgement.map(|value| value.1.to_be_bytes().to_vec());
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = fence + 1,
             worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
             acknowledgement_digest = COALESCE(?, acknowledgement_digest),
             acknowledgement_watermark = COALESCE(?, acknowledgement_watermark), last_error_digest = ?,
             updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(ack_digest)
        .bind(watermark)
        .bind(reason_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.identity.scope_id.as_str())
        .bind(lease.identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn observe_terminal(
        &self,
        identity: &OperationIdentity,
        observer_generation: Generation,
        observer_id: &StableId,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    ) -> Result<DurableOperationStatus, DurableOperationError> {
        if evidence_digest.is_zero() {
            return Err(DurableOperationError::InvalidRequest(
                "terminal evidence digest must be nonzero",
            ));
        }
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        let operation = load_operation(&mut tx, identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        if observer_generation < operation.intent.owner_generation {
            return Err(DurableOperationError::StaleGeneration);
        }
        let target = terminal_state(outcome);
        if operation.state == target
            && operation.terminal_evidence_digest == Some(evidence_digest)
            && operation.terminal_observer_id.as_ref() == Some(observer_id)
        {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(operation);
        }
        if operation.state.is_terminal() {
            return Err(DurableOperationError::TerminalConflict);
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: target.as_str(),
            });
        }
        let next = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = ?, revision = ?, owner_generation = ?,
             terminal_evidence_digest = ?, terminal_observer_id = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(target.as_str())
        .bind(u64_bytes(next.get()).as_slice())
        .bind(u64_bytes(observer_generation.get()).as_slice())
        .bind(evidence_digest.as_array().as_slice())
        .bind(observer_id.as_str())
        .bind(now)
        .bind(now)
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let outbox_state = if target == DurableOperationState::Quarantined {
            "quarantined"
        } else {
            "acknowledged"
        };
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = ?, fence = fence + 1,
             worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
             acknowledgement_digest = COALESCE(acknowledgement_digest, ?),
             acknowledgement_watermark = COALESCE(acknowledgement_watermark, ?),
             updated_at_ms = ?, terminal_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(outbox_state)
        .bind(evidence_digest.as_array().as_slice())
        .bind(u64_bytes(next.get()).as_slice())
        .bind(now)
        .bind(now)
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let status = load_operation(&mut tx, identity).await?.ok_or_else(|| {
            DurableOperationError::Corrupt("terminal operation disappeared".into())
        })?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn recover_expired_leases(&self) -> Result<RecoveryReport, DurableOperationError> {
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        let rows = sqlx::query(
            "SELECT o.scope_id, o.operation_id, o.state AS operation_state
             FROM cross_owner_outbox x JOIN operation_ledger o USING(scope_id, operation_id)
             WHERE x.state = 'leased' AND x.lease_until_ms <= ?",
        )
        .bind(now)
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut report = RecoveryReport::default();
        for row in rows {
            let identity = OperationIdentity {
                scope_id: stable_id(row.try_get::<String, _>("scope_id")?)?,
                operation_id: stable_id(row.try_get::<String, _>("operation_id")?)?,
            };
            let state = DurableOperationState::parse(row.try_get("operation_state")?)?;
            match state {
                DurableOperationState::Prepared => {
                    sqlx::query(
                        "UPDATE cross_owner_outbox SET state = 'queued', fence = fence + 1,
                         worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
                         updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
                    )
                    .bind(now)
                    .bind(identity.scope_id.as_str())
                    .bind(identity.operation_id.as_str())
                    .execute(&mut *tx)
                    .await
                    .map_err(classify_sqlx_error)?;
                    report.requeued_before_dispatch += 1;
                }
                DurableOperationState::Dispatched | DurableOperationState::Indeterminate => {
                    mark_recovery_indeterminate(&mut tx, &identity, now).await?;
                    report.marked_indeterminate_after_dispatch += 1;
                }
                state if state.is_terminal() => {
                    let outbox_state = if state == DurableOperationState::Quarantined {
                        "quarantined"
                    } else {
                        "acknowledged"
                    };
                    sqlx::query(
                        "UPDATE cross_owner_outbox SET state = ?, fence = fence + 1,
                         worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
                         terminal_at_ms = COALESCE(terminal_at_ms, ?), updated_at_ms = ?
                         WHERE scope_id = ? AND operation_id = ?",
                    )
                    .bind(outbox_state)
                    .bind(now)
                    .bind(now)
                    .bind(identity.scope_id.as_str())
                    .bind(identity.operation_id.as_str())
                    .execute(&mut *tx)
                    .await
                    .map_err(classify_sqlx_error)?;
                }
                _ => {}
            }
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(report)
    }

    pub async fn quarantine(
        &self,
        identity: &OperationIdentity,
        reason_digest: Digest32,
    ) -> Result<DurableOperationStatus, DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::InvalidRequest(
                "quarantine reason must be nonzero",
            ));
        }
        let now = now_millis()?;
        let mut tx = self.begin_immediate().await?;
        quarantine_in_tx(&mut tx, identity, reason_digest, now).await?;
        let status = load_operation(&mut tx, identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(status)
    }

    pub async fn metrics(&self) -> Result<OperationMetrics, DurableOperationError> {
        let now = now_millis()?;
        let row = sqlx::query(
            "SELECT
             SUM(CASE WHEN state='prepared' THEN 1 ELSE 0 END) prepared,
             SUM(CASE WHEN state='dispatched' THEN 1 ELSE 0 END) dispatched,
             SUM(CASE WHEN state='indeterminate' THEN 1 ELSE 0 END) indeterminate,
             SUM(CASE WHEN state IN ('applied','not_applied','quarantined') THEN 1 ELSE 0 END) terminal
             FROM operation_ledger",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let outbox = sqlx::query(
            "SELECT
             SUM(CASE WHEN state='queued' THEN 1 ELSE 0 END) queued,
             SUM(CASE WHEN state='leased' THEN 1 ELSE 0 END) leased,
             SUM(CASE WHEN state='indeterminate' THEN 1 ELSE 0 END) indeterminate,
             SUM(CASE WHEN state IN ('acknowledged','quarantined') THEN 1 ELSE 0 END) terminal,
             MIN(CASE WHEN state='queued' AND next_eligible_at_ms <= ? THEN next_eligible_at_ms END) oldest
             FROM cross_owner_outbox",
        )
        .bind(now)
        .fetch_one(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let oldest: Option<i64> = outbox.try_get("oldest")?;
        Ok(OperationMetrics {
            prepared_operations: row.try_get::<Option<i64>, _>("prepared")?.unwrap_or(0),
            dispatched_operations: row.try_get::<Option<i64>, _>("dispatched")?.unwrap_or(0),
            indeterminate_operations: row.try_get::<Option<i64>, _>("indeterminate")?.unwrap_or(0),
            terminal_operations: row.try_get::<Option<i64>, _>("terminal")?.unwrap_or(0),
            queued_outbox: outbox.try_get::<Option<i64>, _>("queued")?.unwrap_or(0),
            leased_outbox: outbox.try_get::<Option<i64>, _>("leased")?.unwrap_or(0),
            indeterminate_outbox: outbox
                .try_get::<Option<i64>, _>("indeterminate")?
                .unwrap_or(0),
            terminal_outbox: outbox.try_get::<Option<i64>, _>("terminal")?.unwrap_or(0),
            oldest_ready_age_ms: oldest.map(|value| now.saturating_sub(value)),
        })
    }

    pub async fn prune_terminal_outbox(
        &self,
        older_than_ms: i64,
        retain_at_least: u32,
    ) -> Result<u64, DurableOperationError> {
        if older_than_ms < 0 || i64::from(retain_at_least) > MAX_DURABLE_OUTBOX_ROWS {
            return Err(DurableOperationError::InvalidRequest(
                "invalid terminal retention policy",
            ));
        }
        let cutoff = now_millis()?.saturating_sub(older_than_ms);
        let result = sqlx::query(
            "DELETE FROM cross_owner_outbox WHERE rowid IN (
               SELECT rowid FROM cross_owner_outbox
               WHERE state IN ('acknowledged','quarantined') AND terminal_at_ms <= ?
               ORDER BY terminal_at_ms, scope_id, operation_id
               LIMIT MAX(0, (SELECT COUNT(*) FROM cross_owner_outbox
                 WHERE state IN ('acknowledged','quarantined')) - ?)
             )",
        )
        .bind(cutoff)
        .bind(i64::from(retain_at_least))
        .execute(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        Ok(result.rows_affected())
    }

    async fn begin_immediate(&self) -> Result<Transaction<'static, Sqlite>, DurableOperationError> {
        self.pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)
    }
}

async fn enforce_prepare_capacity(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<(), DurableOperationError> {
    let active: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM operation_ledger WHERE state IN ('prepared','dispatched','indeterminate')",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    if active >= MAX_DURABLE_OPERATION_ROWS {
        return Err(DurableOperationError::CapacityExceeded {
            resource: "active operation ledger",
            maximum: MAX_DURABLE_OPERATION_ROWS,
        });
    }
    let outbox: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cross_owner_outbox")
        .fetch_one(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
    if outbox >= MAX_DURABLE_OUTBOX_ROWS {
        return Err(DurableOperationError::CapacityExceeded {
            resource: "cross-owner outbox",
            maximum: MAX_DURABLE_OUTBOX_ROWS,
        });
    }
    Ok(())
}

async fn require_current_lease(
    tx: &mut Transaction<'_, Sqlite>,
    lease: &DispatchLease,
    now: i64,
) -> Result<DurableOutboxStatus, DurableOperationError> {
    let status = load_outbox(tx, &lease.identity)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(lease.identity.operation_id.clone()))?;
    if status.state != DurableOutboxState::Leased
        || status.fence != lease.fence
        || status.worker_id.as_ref() != Some(&lease.worker_id)
        || status.claim_owner_generation != Some(lease.owner_generation)
        || status.lease_until_ms.is_none_or(|until| until <= now)
    {
        return Err(DurableOperationError::StaleLease);
    }
    Ok(status)
}

async fn quarantine_in_tx(
    tx: &mut Transaction<'_, Sqlite>,
    identity: &OperationIdentity,
    reason_digest: Digest32,
    now: i64,
) -> Result<(), DurableOperationError> {
    let operation = load_operation(tx, identity)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
    if operation.state == DurableOperationState::Quarantined
        && operation.terminal_evidence_digest == Some(reason_digest)
    {
        return Ok(());
    }
    if operation.state.is_terminal() {
        return Err(DurableOperationError::TerminalConflict);
    }
    let next = next_revision(operation.revision)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'quarantined', revision = ?,
         terminal_evidence_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(u64_bytes(next.get()).as_slice())
    .bind(reason_digest.as_array().as_slice())
    .bind(now)
    .bind(now)
    .bind(identity.scope_id.as_str())
    .bind(identity.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'quarantined', fence = fence + 1,
         worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
         last_error_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(reason_digest.as_array().as_slice())
    .bind(now)
    .bind(now)
    .bind(identity.scope_id.as_str())
    .bind(identity.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn mark_recovery_indeterminate(
    tx: &mut Transaction<'_, Sqlite>,
    identity: &OperationIdentity,
    now: i64,
) -> Result<(), DurableOperationError> {
    let operation = load_operation(tx, identity)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
    let reason = Digest32::of_bytes(CRASH_AFTER_DISPATCH_DOMAIN);
    if operation.state == DurableOperationState::Dispatched {
        let next = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate', revision = ?,
             indeterminate_digest = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(u64_bytes(next.get()).as_slice())
        .bind(reason.as_array().as_slice())
        .bind(now)
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .execute(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
    }
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = fence + 1,
         worker_id = NULL, claim_owner_generation = NULL, lease_until_ms = NULL,
         last_error_digest = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(reason.as_array().as_slice())
    .bind(now)
    .bind(identity.scope_id.as_str())
    .bind(identity.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn load_operation(
    tx: &mut Transaction<'_, Sqlite>,
    identity: &OperationIdentity,
) -> Result<Option<DurableOperationStatus>, DurableOperationError> {
    sqlx::query("SELECT * FROM operation_ledger WHERE scope_id = ? AND operation_id = ?")
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .map(decode_operation)
        .transpose()
}

async fn load_outbox(
    tx: &mut Transaction<'_, Sqlite>,
    identity: &OperationIdentity,
) -> Result<Option<DurableOutboxStatus>, DurableOperationError> {
    sqlx::query("SELECT * FROM cross_owner_outbox WHERE scope_id = ? AND operation_id = ?")
        .bind(identity.scope_id.as_str())
        .bind(identity.operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .map(decode_outbox)
        .transpose()
}

fn decode_operation(
    row: sqlx::sqlite::SqliteRow,
) -> Result<DurableOperationStatus, DurableOperationError> {
    let scope_id = stable_id(row.try_get::<String, _>("scope_id")?)?;
    let operation_id = stable_id(row.try_get::<String, _>("operation_id")?)?;
    let predecessor_id = row
        .try_get::<Option<String>, _>("predecessor_id")?
        .map(stable_id)
        .transpose()?;
    let destination_id = stable_id(row.try_get::<String, _>("destination_id")?)?;
    let payload_digest = digest(
        row.try_get::<Vec<u8>, _>("payload_digest")?,
        "payload_digest",
    )?;
    let semantic_digest = digest(
        row.try_get::<Vec<u8>, _>("semantic_digest")?,
        "semantic_digest",
    )?;
    let owner_generation = generation_from_blob(row.try_get::<Vec<u8>, _>("owner_generation")?)?;
    let authority_epoch = generation_from_blob(row.try_get::<Vec<u8>, _>("authority_epoch")?)?;
    let revision = revision_from_blob(row.try_get::<Vec<u8>, _>("revision")?)?;
    Ok(DurableOperationStatus {
        intent: DurableIntent {
            identity: OperationIdentity {
                scope_id,
                operation_id,
            },
            predecessor_id,
            destination_id,
            payload_digest,
            owner_generation,
            authority_epoch,
        },
        semantic_digest,
        revision,
        state: DurableOperationState::parse(row.try_get("state")?)?,
        dispatch_digest: optional_digest(row.try_get("dispatch_digest")?, "dispatch_digest")?,
        indeterminate_digest: optional_digest(
            row.try_get("indeterminate_digest")?,
            "indeterminate_digest",
        )?,
        terminal_evidence_digest: optional_digest(
            row.try_get("terminal_evidence_digest")?,
            "terminal_evidence_digest",
        )?,
        terminal_observer_id: row
            .try_get::<Option<String>, _>("terminal_observer_id")?
            .map(stable_id)
            .transpose()?,
        created_at_ms: row.try_get("created_at_ms")?,
        updated_at_ms: row.try_get("updated_at_ms")?,
        terminal_at_ms: row.try_get("terminal_at_ms")?,
    })
}

fn decode_outbox(
    row: sqlx::sqlite::SqliteRow,
) -> Result<DurableOutboxStatus, DurableOperationError> {
    Ok(DurableOutboxStatus {
        identity: OperationIdentity {
            scope_id: stable_id(row.try_get::<String, _>("scope_id")?)?,
            operation_id: stable_id(row.try_get::<String, _>("operation_id")?)?,
        },
        destination_id: stable_id(row.try_get::<String, _>("destination_id")?)?,
        payload_digest: digest(
            row.try_get::<Vec<u8>, _>("payload_digest")?,
            "payload_digest",
        )?,
        semantic_digest: digest(
            row.try_get::<Vec<u8>, _>("semantic_digest")?,
            "semantic_digest",
        )?,
        state: DurableOutboxState::parse(row.try_get("state")?)?,
        fence: u64_from_i64(row.try_get("fence")?, "fence")?,
        attempts: u32::try_from(row.try_get::<i64, _>("attempts")?)
            .map_err(|_| DurableOperationError::Corrupt("invalid outbox attempts".into()))?,
        worker_id: row
            .try_get::<Option<String>, _>("worker_id")?
            .map(stable_id)
            .transpose()?,
        claim_owner_generation: row
            .try_get::<Option<Vec<u8>>, _>("claim_owner_generation")?
            .map(generation_from_blob)
            .transpose()?,
        lease_until_ms: row.try_get("lease_until_ms")?,
        next_eligible_at_ms: row.try_get("next_eligible_at_ms")?,
        acknowledgement_digest: optional_digest(
            row.try_get("acknowledgement_digest")?,
            "acknowledgement_digest",
        )?,
        acknowledgement_watermark: row
            .try_get::<Option<Vec<u8>>, _>("acknowledgement_watermark")?
            .map(|value| u64_from_blob(value, "acknowledgement_watermark"))
            .transpose()?,
        last_error_digest: optional_digest(row.try_get("last_error_digest")?, "last_error_digest")?,
        created_at_ms: row.try_get("created_at_ms")?,
        updated_at_ms: row.try_get("updated_at_ms")?,
        terminal_at_ms: row.try_get("terminal_at_ms")?,
    })
}

async fn verify_quick_check(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    let values: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
    if values.len() != 1 || values[0] != "ok" {
        return Err(DurableOperationError::Corrupt(format!(
            "sqlite quick_check failed: {}",
            values.join("; ")
        )));
    }
    Ok(())
}

async fn verify_integrity(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    verify_quick_check(pool).await?;
    for object in [
        "operation_ledger",
        "cross_owner_outbox",
        "cross_owner_outbox_ready_idx",
        "cross_owner_outbox_terminal_idx",
    ] {
        let exists: i64 = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table','index'))",
        )
        .bind(object)
        .fetch_one(pool)
        .await
        .map_err(classify_sqlx_error)?;
        if exists != 1 {
            return Err(DurableOperationError::Corrupt(format!(
                "required sqlite object is missing: {object}"
            )));
        }
    }
    let fk_rows = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
    if !fk_rows.is_empty() {
        return Err(DurableOperationError::Corrupt(
            "sqlite foreign_key_check failed".into(),
        ));
    }
    Ok(())
}

fn terminal_state(outcome: ReconciliationOutcome) -> DurableOperationState {
    match outcome {
        ReconciliationOutcome::Applied => DurableOperationState::Applied,
        ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
        ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
    }
}

fn validate_lease(lease_ms: i64) -> Result<(), DurableOperationError> {
    if !(1..=MAX_DURABLE_LEASE_MS).contains(&lease_ms) {
        return Err(DurableOperationError::InvalidRequest(
            "lease must be 1..=60000 ms",
        ));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn stable_id(value: String) -> Result<StableId, DurableOperationError> {
    StableId::new(value).map_err(|error| {
        DurableOperationError::Corrupt(format!("invalid stored identifier: {error}"))
    })
}

fn digest(value: Vec<u8>, field: &'static str) -> Result<Digest32, DurableOperationError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| DurableOperationError::Corrupt(format!("invalid stored {field} length")))?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(DurableOperationError::Corrupt(format!(
            "stored {field} is zero"
        )));
    }
    Ok(digest)
}

fn optional_digest(
    value: Option<Vec<u8>>,
    field: &'static str,
) -> Result<Option<Digest32>, DurableOperationError> {
    value.map(|value| digest(value, field)).transpose()
}

fn u64_bytes(value: u64) -> [u8; 8] {
    value.to_be_bytes()
}

fn u64_from_blob(value: Vec<u8>, field: &'static str) -> Result<u64, DurableOperationError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| DurableOperationError::Corrupt(format!("invalid stored {field} length")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn generation_from_blob(value: Vec<u8>) -> Result<Generation, DurableOperationError> {
    Generation::new(u64_from_blob(value, "generation")?)
        .map_err(|error| DurableOperationError::Corrupt(format!("invalid generation: {error}")))
}

fn revision_from_blob(value: Vec<u8>) -> Result<Revision, DurableOperationError> {
    Revision::new(u64_from_blob(value, "revision")?)
        .map_err(|error| DurableOperationError::Corrupt(format!("invalid revision: {error}")))
}

fn revision(value: u64) -> Result<Revision, DurableOperationError> {
    Revision::new(value)
        .map_err(|error| DurableOperationError::Corrupt(format!("invalid revision: {error}")))
}

fn next_revision(value: Revision) -> Result<Revision, DurableOperationError> {
    value
        .next()
        .map_err(|_| DurableOperationError::RevisionOverflow)
}

fn i64_from_u64(value: u64, field: &'static str) -> Result<i64, DurableOperationError> {
    i64::try_from(value).map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} exceeds sqlite integer range"))
    })
}

fn u64_from_i64(value: i64, field: &'static str) -> Result<u64, DurableOperationError> {
    u64::try_from(value)
        .map_err(|_| DurableOperationError::Corrupt(format!("negative stored {field}")))
}

fn now_millis() -> Result<i64, DurableOperationError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| DurableOperationError::Unavailable("clock predates Unix epoch".into()))?;
    i64::try_from(elapsed.as_millis())
        .map_err(|_| DurableOperationError::Unavailable("clock exceeds sqlite range".into()))
}

fn classify_sqlx_error(error: sqlx::Error) -> DurableOperationError {
    match &error {
        sqlx::Error::Database(database) if database.is_unique_violation() => {
            DurableOperationError::DatabaseConflict(error.to_string())
        }
        _ => DurableOperationError::Database(error.to_string()),
    }
}

impl From<sqlx::Error> for DurableOperationError {
    fn from(value: sqlx::Error) -> Self {
        classify_sqlx_error(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableOperationError {
    InvalidRequest(&'static str),
    Missing(StableId),
    Conflict(StableId),
    DatabaseConflict(String),
    CapacityExceeded {
        resource: &'static str,
        maximum: i64,
    },
    InvalidTransition {
        from: &'static str,
        to: &'static str,
    },
    StaleGeneration,
    StaleLease,
    RequiresReconciliation,
    AttemptsExhausted,
    FenceOverflow,
    RevisionOverflow,
    Terminal,
    TerminalConflict,
    Database(String),
    Migration(String),
    Corrupt(String),
    Unavailable(String),
}

impl fmt::Display for DurableOperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(message) => {
                write!(formatter, "invalid durable operation request: {message}")
            }
            Self::Missing(id) => write!(formatter, "durable operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "durable operation identity conflicts: {id}"),
            Self::DatabaseConflict(message) => {
                write!(formatter, "durable store conflict: {message}")
            }
            Self::CapacityExceeded { resource, maximum } => {
                write!(
                    formatter,
                    "{resource} capacity exceeded; maximum is {maximum}"
                )
            }
            Self::InvalidTransition { from, to } => {
                write!(
                    formatter,
                    "invalid durable operation transition from {from} to {to}"
                )
            }
            Self::StaleGeneration => formatter.write_str("durable operation generation is stale"),
            Self::StaleLease => formatter.write_str("durable outbox lease is stale or expired"),
            Self::RequiresReconciliation => {
                formatter.write_str("operation requires authoritative reconciliation")
            }
            Self::AttemptsExhausted => formatter.write_str("durable outbox attempts are exhausted"),
            Self::FenceOverflow => formatter.write_str("durable outbox fence overflow"),
            Self::RevisionOverflow => formatter.write_str("durable operation revision overflow"),
            Self::Terminal => formatter.write_str("durable operation is already terminal"),
            Self::TerminalConflict => formatter.write_str("terminal durable operation conflicts"),
            Self::Database(message) => write!(formatter, "durable sqlite error: {message}"),
            Self::Migration(message) => write!(formatter, "durable migration error: {message}"),
            Self::Corrupt(message) => {
                write!(formatter, "durable operation store is corrupt: {message}")
            }
            Self::Unavailable(message) => {
                write!(formatter, "durable operation store unavailable: {message}")
            }
        }
    }
}

impl std::error::Error for DurableOperationError {}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
