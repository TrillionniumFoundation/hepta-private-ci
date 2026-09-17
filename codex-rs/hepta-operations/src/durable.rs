use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
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

use crate::ReconciliationOutcome;

const OPERATIONS_DB_FILENAME: &str = "hepta_operations_1.sqlite";
const OPERATIONS_SCHEMA_VERSION: i64 = 1;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

pub const MAX_DURABLE_OPERATION_RECORDS: i64 = 100_000;
pub const MAX_OPERATION_CLAIM_BATCH: u32 = 256;
pub const MAX_OPERATION_ATTEMPTS: u32 = 32;
pub const MAX_OPERATION_LEASE_MS: i64 = 60_000;

const REQUIRED_SCHEMA_OBJECTS: &[(&str, &str)] = &[
    ("operations_meta", "table"),
    ("operations_meta_no_update", "trigger"),
    ("operations_meta_no_delete", "trigger"),
    ("operation_ledger", "table"),
    ("operation_ledger_identity_immutable", "trigger"),
    ("operation_ledger_state_updated", "index"),
    ("cross_owner_outbox", "table"),
    ("cross_owner_outbox_identity_immutable", "trigger"),
    ("cross_owner_outbox_destination_operation", "index"),
    ("cross_owner_outbox_ready", "index"),
    ("destination_operation_dedup", "table"),
    ("destination_operation_dedup_no_update", "trigger"),
    ("destination_operation_dedup_recorded", "index"),
];

#[derive(Debug, thiserror::Error)]
pub enum DurableOperationError {
    #[error("invalid durable operation request: {0}")]
    Invalid(&'static str),
    #[error("durable operation identity conflict: {0}")]
    Conflict(StableId),
    #[error("durable operation is missing: {0}")]
    Missing(StableId),
    #[error("durable operation store capacity exceeded")]
    Capacity,
    #[error("dispatch lease is stale")]
    StaleLease,
    #[error("operation crossed an effect boundary and requires reconciliation")]
    ReconciliationRequired,
    #[error("durable operation is unavailable in its current state")]
    UnavailableState,
    #[error("durable operation store is corrupt: {0}")]
    Corrupt(String),
    #[error("durable operation store is unavailable: {0}")]
    Unavailable(String),
    #[error("final-use authority rejected the dispatch: {0}")]
    Authority(#[from] FinalUseError),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrepareOperationIntent {
    pub scope: StableId,
    pub operation_id: StableId,
    pub predecessor_digest: Option<Digest32>,
    pub payload_digest: Digest32,
    pub destination: StableId,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
}

impl PrepareOperationIntent {
    pub fn semantic_digest(&self) -> Result<Digest32, DurableOperationError> {
        self.validate()?;
        let mut bytes = b"hepta.kernel.operations.intent.v1\0".to_vec();
        append_stable_id(&mut bytes, &self.scope);
        append_stable_id(&mut bytes, &self.operation_id);
        match self.predecessor_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(self.payload_digest.as_array());
        append_stable_id(&mut bytes, &self.destination);
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), DurableOperationError> {
        if self.payload_digest.is_zero() {
            return Err(DurableOperationError::Invalid("payload digest is zero"));
        }
        if self.predecessor_digest.is_some_and(Digest32::is_zero) {
            return Err(DurableOperationError::Invalid(
                "predecessor digest is zero",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOperationState {
    Pending,
    Dispatched,
    Indeterminate,
    Applied,
    NotApplied,
    Quarantined,
}

impl DurableOperationState {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(Self::Applied | Self::NotApplied | Self::Quarantined, self)
    }

    fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "pending" => Ok(Self::Pending),
            "dispatched" => Ok(Self::Dispatched),
            "indeterminate" => Ok(Self::Indeterminate),
            "applied" => Ok(Self::Applied),
            "not_applied" => Ok(Self::NotApplied),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown operation state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub scope: StableId,
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub predecessor_digest: Option<Digest32>,
    pub payload_digest: Digest32,
    pub destination: StableId,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
    pub revision: Revision,
    pub state: DurableOperationState,
    pub dispatch_digest: Option<Digest32>,
    pub indeterminate_digest: Option<Digest32>,
    pub terminal_evidence_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

impl DurableOperationRecord {
    pub fn final_use_binding(&self) -> FinalUseBinding {
        FinalUseBinding {
            subject_id: self.operation_id.as_str().to_string(),
            destination_id: self.destination.as_str().to_string(),
            request_sha256: self.semantic_digest.into_array(),
            scope_sha256: Digest32::of_bytes(self.scope.as_str().as_bytes()).into_array(),
            payload_sha256: self.payload_digest.into_array(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Queued,
    Leased,
    Acknowledged,
    Indeterminate,
    Settled,
    Quarantined,
}

impl DurableOutboxState {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::Acknowledged => "acknowledged",
            Self::Indeterminate => "indeterminate",
            Self::Settled => "settled",
            Self::Quarantined => "quarantined",
        }
    }

    fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "queued" => Ok(Self::Queued),
            "leased" => Ok(Self::Leased),
            "acknowledged" => Ok(Self::Acknowledged),
            "indeterminate" => Ok(Self::Indeterminate),
            "settled" => Ok(Self::Settled),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown outbox state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOutboxStatus {
    pub scope: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub semantic_digest: Digest32,
    pub state: DurableOutboxState,
    pub fence: u64,
    pub attempts: u32,
    pub available_at_ms: i64,
    pub worker_id: Option<StableId>,
    pub lease_until_ms: Option<i64>,
    pub claim_generation: Option<Generation>,
    pub acknowledgement_digest: Option<Digest32>,
    pub last_error_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchLease {
    pub scope: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub semantic_digest: Digest32,
    pub payload_digest: Digest32,
    pub worker_id: StableId,
    pub owner_generation: Generation,
    pub fence: u64,
    pub expires_at_ms: i64,
    pub attempts: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationReceipt {
    pub destination: StableId,
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub outcome: ReconciliationOutcome,
    pub evidence_digest: Digest32,
    pub recorded_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationsMetrics {
    pub total_operations: u64,
    pub pending_operations: u64,
    pub unresolved_operations: u64,
    pub terminal_operations: u64,
    pub queued_outbox: u64,
    pub leased_outbox: u64,
    pub acknowledged_outbox: u64,
    pub indeterminate_outbox: u64,
    pub total_attempts: u64,
    pub oldest_unresolved_age_ms: u64,
}

#[derive(Clone)]
pub struct DurableOperationStore {
    pool: SqlitePool,
    path: PathBuf,
}

impl DurableOperationStore {
    pub async fn open(sqlite: &SqliteConfig) -> Result<Self, DurableOperationError> {
        let path = sqlite.home().join(OPERATIONS_DB_FILENAME);
        let pool = sqlite
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(DurableOperationError::Corrupt(format!(
                "migration verification failed: {error}"
            )));
        }
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub async fn open_existing_read_only(
        sqlite: &SqliteConfig,
    ) -> Result<Self, DurableOperationError> {
        let path = sqlite.home().join(OPERATIONS_DB_FILENAME);
        let pool = sqlite
            .open_read_only_pool(&path)
            .await
            .map_err(unavailable)?;
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn prepare_intent(
        &self,
        request: &PrepareOperationIntent,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        request.validate()?;
        let semantic_digest = request.semantic_digest()?;
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        if let Some(existing) = load_operation_tx(&mut tx, &request.scope, &request.operation_id).await?
        {
            if existing.semantic_digest != semantic_digest
                || existing.predecessor_digest != request.predecessor_digest
                || existing.payload_digest != request.payload_digest
                || existing.destination != request.destination
            {
                return Err(DurableOperationError::Conflict(request.operation_id.clone()));
            }
            let outbox = load_outbox_tx(&mut tx, &request.scope, &request.operation_id)
                .await?
                .ok_or_else(|| {
                    DurableOperationError::Corrupt(
                        "operation exists without its atomic outbox row".to_string(),
                    )
                })?;
            if outbox.semantic_digest != semantic_digest || outbox.destination != request.destination {
                return Err(DurableOperationError::Corrupt(
                    "operation/outbox semantic identity mismatch".to_string(),
                ));
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operation_ledger")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        if count >= MAX_DURABLE_OPERATION_RECORDS {
            return Err(DurableOperationError::Capacity);
        }
        let revision = first_revision();
        sqlx::query(
            "INSERT INTO operation_ledger
            (scope, operation_id, semantic_digest, predecessor_digest, payload_digest,
             destination, owner_generation, authority_epoch, revision, state,
             created_at_ms, updated_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        )
        .bind(request.scope.as_str())
        .bind(request.operation_id.as_str())
        .bind(blob(semantic_digest))
        .bind(optional_blob(request.predecessor_digest))
        .bind(blob(request.payload_digest))
        .bind(request.destination.as_str())
        .bind(u64_blob(request.owner_generation.get()))
        .bind(u64_blob(request.authority_epoch.get()))
        .bind(u64_blob(revision.get()))
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "INSERT INTO cross_owner_outbox
            (scope, operation_id, destination, semantic_digest, state, fence, attempts,
             available_at_ms, created_at_ms, updated_at_ms)
            VALUES (?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?)",
        )
        .bind(request.scope.as_str())
        .bind(request.operation_id.as_str())
        .bind(request.destination.as_str())
        .bind(blob(semantic_digest))
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let record = load_operation_tx(&mut tx, &request.scope, &request.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(request.operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn get_operation(
        &self,
        scope: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DurableOperationRecord>, DurableOperationError> {
        sqlx::query(OPERATION_SELECT)
            .bind(scope.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(unavailable)?
            .map(decode_operation)
            .transpose()
    }

    pub async fn outbox_status(
        &self,
        scope: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DurableOutboxStatus>, DurableOperationError> {
        sqlx::query(OUTBOX_SELECT)
            .bind(scope.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(unavailable)?
            .map(decode_outbox)
            .transpose()
    }

    pub async fn pending_outbox(
        &self,
        limit: u32,
    ) -> Result<Vec<DurableOutboxStatus>, DurableOperationError> {
        validate_limit(limit)?;
        let now = now_millis()?;
        let rows = sqlx::query(
            "SELECT x.* FROM cross_owner_outbox x
             JOIN operation_ledger o ON o.scope = x.scope AND o.operation_id = x.operation_id
             WHERE o.state = 'pending' AND x.available_at_ms <= ?
             AND (x.state = 'queued' OR (x.state = 'leased' AND x.lease_until_ms <= ?))
             ORDER BY x.available_at_ms, x.destination, x.operation_id LIMIT ?",
        )
        .bind(now)
        .bind(now)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.into_iter().map(decode_outbox).collect()
    }

    pub async fn unresolved_operations(
        &self,
        limit: u32,
    ) -> Result<Vec<DurableOperationRecord>, DurableOperationError> {
        validate_limit(limit)?;
        let rows = sqlx::query(
            "SELECT * FROM operation_ledger
             WHERE state IN ('dispatched', 'indeterminate')
             ORDER BY updated_at_ms, scope, operation_id LIMIT ?",
        )
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.into_iter().map(decode_operation).collect()
    }

    pub async fn claim_outbox(
        &self,
        scope: &StableId,
        operation_id: &StableId,
        worker_id: &StableId,
        owner_generation: Generation,
        lease_ms: i64,
    ) -> Result<DispatchLease, DurableOperationError> {
        validate_lease_duration(lease_ms)?;
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let mut operation = load_operation_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let outbox = load_outbox_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if operation.state != DurableOperationState::Pending {
            return Err(DurableOperationError::ReconciliationRequired);
        }
        match outbox.state {
            DurableOutboxState::Queued => {
                if outbox.available_at_ms > now {
                    return Err(DurableOperationError::UnavailableState);
                }
            }
            DurableOutboxState::Leased => {
                if outbox.lease_until_ms.is_some_and(|until| until > now) {
                    return Err(DurableOperationError::StaleLease);
                }
            }
            DurableOutboxState::Acknowledged
            | DurableOutboxState::Indeterminate
            | DurableOutboxState::Settled
            | DurableOutboxState::Quarantined => {
                return Err(DurableOperationError::UnavailableState);
            }
        }
        if owner_generation < operation.owner_generation {
            return Err(DurableOperationError::StaleLease);
        }
        if outbox.attempts >= MAX_OPERATION_ATTEMPTS {
            quarantine_attempt_limit(&mut tx, &operation, now).await?;
            tx.commit().await.map_err(unavailable)?;
            return Err(DurableOperationError::UnavailableState);
        }
        if owner_generation > operation.owner_generation {
            let revision = operation
                .revision
                .next()
                .map_err(|_| DurableOperationError::Conflict(operation_id.clone()))?;
            sqlx::query(
                "UPDATE operation_ledger SET owner_generation = ?, revision = ?, updated_at_ms = ?
                 WHERE scope = ? AND operation_id = ?",
            )
            .bind(u64_blob(owner_generation.get()))
            .bind(u64_blob(revision.get()))
            .bind(now)
            .bind(scope.as_str())
            .bind(operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
            operation.owner_generation = owner_generation;
            operation.revision = revision;
            operation.updated_at_ms = now;
        }
        let fence = outbox
            .fence
            .checked_add(1)
            .filter(|value| *value <= i64::MAX as u64)
            .ok_or_else(|| DurableOperationError::Conflict(operation_id.clone()))?;
        let attempts = outbox
            .attempts
            .checked_add(1)
            .ok_or_else(|| DurableOperationError::Conflict(operation_id.clone()))?;
        let expires_at_ms = now
            .checked_add(lease_ms)
            .ok_or(DurableOperationError::Invalid("lease deadline overflow"))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, attempts = ?,
             worker_id = ?, lease_until_ms = ?, claim_generation = ?, updated_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(i64::try_from(fence).map_err(|_| DurableOperationError::Invalid("fence overflow"))?)
        .bind(i64::from(attempts))
        .bind(worker_id.as_str())
        .bind(expires_at_ms)
        .bind(u64_blob(owner_generation.get()))
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(DispatchLease {
            scope: scope.clone(),
            operation_id: operation_id.clone(),
            destination: operation.destination,
            semantic_digest: operation.semantic_digest,
            payload_digest: operation.payload_digest,
            worker_id: worker_id.clone(),
            owner_generation,
            fence,
            expires_at_ms,
            attempts,
        })
    }

    pub async fn renew_outbox_lease(
        &self,
        lease: &DispatchLease,
        lease_ms: i64,
    ) -> Result<DispatchLease, DurableOperationError> {
        validate_lease_duration(lease_ms)?;
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let (operation, outbox) = require_current_lease(&mut tx, lease, now).await?;
        if operation.state != DurableOperationState::Pending {
            return Err(DurableOperationError::ReconciliationRequired);
        }
        let fence = outbox
            .fence
            .checked_add(1)
            .filter(|value| *value <= i64::MAX as u64)
            .ok_or_else(|| DurableOperationError::Conflict(lease.operation_id.clone()))?;
        let expires_at_ms = now
            .checked_add(lease_ms)
            .ok_or(DurableOperationError::Invalid("lease deadline overflow"))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET fence = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(i64::try_from(fence).map_err(|_| DurableOperationError::Invalid("fence overflow"))?)
        .bind(expires_at_ms)
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(DispatchLease {
            fence,
            expires_at_ms,
            ..lease.clone()
        })
    }

    pub async fn retry_outbox(
        &self,
        lease: &DispatchLease,
        delay_ms: i64,
        reason_digest: Digest32,
    ) -> Result<(), DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::Invalid("retry reason digest is zero"));
        }
        if !(0..=MAX_OPERATION_LEASE_MS).contains(&delay_ms) {
            return Err(DurableOperationError::Invalid("retry delay is outside bounds"));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let (operation, outbox) = require_current_lease(&mut tx, lease, now).await?;
        if operation.state != DurableOperationState::Pending {
            return Err(DurableOperationError::ReconciliationRequired);
        }
        let fence = outbox
            .fence
            .checked_add(1)
            .filter(|value| *value <= i64::MAX as u64)
            .ok_or_else(|| DurableOperationError::Conflict(lease.operation_id.clone()))?;
        let available_at_ms = now
            .checked_add(delay_ms)
            .ok_or(DurableOperationError::Invalid("retry deadline overflow"))?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'queued', fence = ?, worker_id = NULL,
             lease_until_ms = NULL, available_at_ms = ?, last_error_digest = ?, updated_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(i64::try_from(fence).map_err(|_| DurableOperationError::Invalid("fence overflow"))?)
        .bind(available_at_ms)
        .bind(blob(reason_digest))
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(())
    }

    pub async fn claim_final_use(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        lease: &DispatchLease,
    ) -> Result<(VerifiedUseToken, FinalUseBinding), DurableOperationError> {
        let operation = self
            .get_operation(&lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        if operation.owner_generation != lease.owner_generation
            || operation.semantic_digest != lease.semantic_digest
            || operation.destination != lease.destination
        {
            return Err(DurableOperationError::StaleLease);
        }
        let binding = operation.final_use_binding();
        let token = authority.claim(signed, &binding)?;
        let authority_epoch = Generation::new(signed.grant.authority_epoch)
            .map_err(|_| DurableOperationError::Invalid("authority epoch is zero"))?;
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let (current, _) = require_current_lease(&mut tx, lease, now).await?;
        if current.state != DurableOperationState::Pending {
            return Err(DurableOperationError::ReconciliationRequired);
        }
        if current.authority_epoch != authority_epoch {
            let revision = current
                .revision
                .next()
                .map_err(|_| DurableOperationError::Conflict(lease.operation_id.clone()))?;
            sqlx::query(
                "UPDATE operation_ledger SET authority_epoch = ?, revision = ?, updated_at_ms = ?
                 WHERE scope = ? AND operation_id = ?",
            )
            .bind(u64_blob(authority_epoch.get()))
            .bind(u64_blob(revision.get()))
            .bind(now)
            .bind(lease.scope.as_str())
            .bind(lease.operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        }
        tx.commit().await.map_err(unavailable)?;
        Ok((token, binding))
    }

    pub async fn mark_dispatched(
        &self,
        lease: &DispatchLease,
        dispatch_digest: Digest32,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        if dispatch_digest.is_zero() {
            return Err(DurableOperationError::Invalid("dispatch digest is zero"));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let operation = load_operation_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        let outbox = load_outbox_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        if operation.state == DurableOperationState::Dispatched
            && operation.dispatch_digest == Some(dispatch_digest)
            && claim_matches(&outbox, lease)
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(operation);
        }
        require_lease_values(&operation, &outbox, lease, now)?;
        if operation.state != DurableOperationState::Pending {
            return Err(DurableOperationError::ReconciliationRequired);
        }
        let revision = operation
            .revision
            .next()
            .map_err(|_| DurableOperationError::Conflict(lease.operation_id.clone()))?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatched', dispatch_digest = ?, revision = ?,
             updated_at_ms = ? WHERE scope = ? AND operation_id = ?",
        )
        .bind(blob(dispatch_digest))
        .bind(u64_blob(revision.get()))
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let record = load_operation_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn acknowledge_outbox(
        &self,
        lease: &DispatchLease,
        acknowledgement_digest: Digest32,
    ) -> Result<(), DurableOperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "acknowledgement digest is zero",
            ));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let operation = load_operation_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        let outbox = load_outbox_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        if outbox.state == DurableOutboxState::Acknowledged {
            if claim_matches(&outbox, lease)
                && outbox.acknowledgement_digest == Some(acknowledgement_digest)
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            if outbox.claim_generation != Some(lease.owner_generation) {
                return Err(DurableOperationError::StaleLease);
            }
            return Err(DurableOperationError::Conflict(lease.operation_id.clone()));
        }
        require_lease_values(&operation, &outbox, lease, now)?;
        if operation.state != DurableOperationState::Dispatched {
            return Err(DurableOperationError::UnavailableState);
        }
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'acknowledged', worker_id = NULL,
             lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(blob(acknowledgement_digest))
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(())
    }

    pub async fn mark_indeterminate(
        &self,
        lease: &DispatchLease,
        reason_digest: Digest32,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "indeterminate reason digest is zero",
            ));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let operation = load_operation_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        let outbox = load_outbox_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        if operation.state == DurableOperationState::Indeterminate
            && operation.indeterminate_digest == Some(reason_digest)
            && outbox.state == DurableOutboxState::Indeterminate
            && outbox.last_error_digest == Some(reason_digest)
            && claim_matches(&outbox, lease)
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(operation);
        }
        require_lease_values(&operation, &outbox, lease, now)?;
        if operation.state != DurableOperationState::Dispatched {
            return Err(DurableOperationError::UnavailableState);
        }
        let revision = operation
            .revision
            .next()
            .map_err(|_| DurableOperationError::Conflict(lease.operation_id.clone()))?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
             revision = ?, updated_at_ms = ? WHERE scope = ? AND operation_id = ?",
        )
        .bind(blob(reason_digest))
        .bind(u64_blob(revision.get()))
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate', worker_id = NULL,
             lease_until_ms = NULL, last_error_digest = ?, updated_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(blob(reason_digest))
        .bind(now)
        .bind(lease.scope.as_str())
        .bind(lease.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let record = load_operation_tx(&mut tx, &lease.scope, &lease.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_destination_outcome(
        &self,
        destination: &StableId,
        operation_id: &StableId,
        semantic_digest: Digest32,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    ) -> Result<DestinationReceipt, DurableOperationError> {
        if semantic_digest.is_zero() || evidence_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "destination semantic/evidence digest is zero",
            ));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        if let Some(existing) = load_destination_tx(&mut tx, destination, operation_id).await? {
            if existing.semantic_digest == semantic_digest
                && existing.outcome == outcome
                && existing.evidence_digest == evidence_digest
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        sqlx::query(
            "INSERT INTO destination_operation_dedup
             (destination, operation_id, semantic_digest, outcome, evidence_digest, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(destination.as_str())
        .bind(operation_id.as_str())
        .bind(blob(semantic_digest))
        .bind(outcome_label(outcome))
        .bind(blob(evidence_digest))
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let receipt = load_destination_tx(&mut tx, destination, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    pub async fn destination_receipt(
        &self,
        destination: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DestinationReceipt>, DurableOperationError> {
        sqlx::query(DESTINATION_SELECT)
            .bind(destination.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(unavailable)?
            .map(decode_destination)
            .transpose()
    }

    pub async fn reconcile_from_destination(
        &self,
        destination_store: &DurableOperationStore,
        scope: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        let operation = self
            .get_operation(scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let receipt = destination_store
            .destination_receipt(&operation.destination, operation_id)
            .await?
            .ok_or(DurableOperationError::UnavailableState)?;
        if receipt.semantic_digest != operation.semantic_digest {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        self.settle_from_receipt(scope, operation_id, observer_generation, &receipt)
            .await
    }

    async fn settle_from_receipt(
        &self,
        scope: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
        receipt: &DestinationReceipt,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let operation = load_operation_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if operation.owner_generation != observer_generation {
            return Err(DurableOperationError::StaleLease);
        }
        if operation.destination != receipt.destination
            || operation.semantic_digest != receipt.semantic_digest
        {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        let terminal_state = state_for_outcome(receipt.outcome);
        if operation.state.is_terminal() {
            if operation.state == terminal_state
                && operation.terminal_evidence_digest == Some(receipt.evidence_digest)
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(operation);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(DurableOperationError::UnavailableState);
        }
        let revision = operation
            .revision
            .next()
            .map_err(|_| DurableOperationError::Conflict(operation_id.clone()))?;
        sqlx::query(
            "UPDATE operation_ledger SET state = ?, terminal_evidence_digest = ?, revision = ?,
             updated_at_ms = ?, terminal_at_ms = ? WHERE scope = ? AND operation_id = ?",
        )
        .bind(terminal_state.label())
        .bind(blob(receipt.evidence_digest))
        .bind(u64_blob(revision.get()))
        .bind(now)
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'settled', worker_id = NULL,
             lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(now)
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let record = load_operation_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn metrics(&self) -> Result<OperationsMetrics, DurableOperationError> {
        let now = now_millis()?;
        let operation_row = sqlx::query(
            "SELECT COUNT(*) AS total,
             COALESCE(SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END), 0) AS pending,
             COALESCE(SUM(CASE WHEN state IN ('dispatched', 'indeterminate') THEN 1 ELSE 0 END), 0) AS unresolved,
             COALESCE(SUM(CASE WHEN state IN ('applied', 'not_applied', 'quarantined') THEN 1 ELSE 0 END), 0) AS terminal,
             MIN(CASE WHEN state IN ('dispatched', 'indeterminate') THEN updated_at_ms END) AS oldest
             FROM operation_ledger",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(unavailable)?;
        let outbox_row = sqlx::query(
            "SELECT
             COALESCE(SUM(CASE WHEN state = 'queued' THEN 1 ELSE 0 END), 0) AS queued,
             COALESCE(SUM(CASE WHEN state = 'leased' THEN 1 ELSE 0 END), 0) AS leased,
             COALESCE(SUM(CASE WHEN state = 'acknowledged' THEN 1 ELSE 0 END), 0) AS acknowledged,
             COALESCE(SUM(CASE WHEN state = 'indeterminate' THEN 1 ELSE 0 END), 0) AS indeterminate,
             COALESCE(SUM(attempts), 0) AS attempts
             FROM cross_owner_outbox",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(unavailable)?;
        let oldest: Option<i64> = operation_row.try_get("oldest").map_err(unavailable)?;
        Ok(OperationsMetrics {
            total_operations: nonnegative_u64(operation_row.try_get("total").map_err(unavailable)?)?,
            pending_operations: nonnegative_u64(operation_row.try_get("pending").map_err(unavailable)?)?,
            unresolved_operations: nonnegative_u64(operation_row.try_get("unresolved").map_err(unavailable)?)?,
            terminal_operations: nonnegative_u64(operation_row.try_get("terminal").map_err(unavailable)?)?,
            queued_outbox: nonnegative_u64(outbox_row.try_get("queued").map_err(unavailable)?)?,
            leased_outbox: nonnegative_u64(outbox_row.try_get("leased").map_err(unavailable)?)?,
            acknowledged_outbox: nonnegative_u64(
                outbox_row.try_get("acknowledged").map_err(unavailable)?,
            )?,
            indeterminate_outbox: nonnegative_u64(
                outbox_row.try_get("indeterminate").map_err(unavailable)?,
            )?,
            total_attempts: nonnegative_u64(outbox_row.try_get("attempts").map_err(unavailable)?)?,
            oldest_unresolved_age_ms: oldest
                .map(|value| now.saturating_sub(value))
                .map_or(0, |value| u64::try_from(value).unwrap_or(u64::MAX)),
        })
    }

    pub async fn prune_terminal(
        &self,
        terminal_before_ms: i64,
        limit: u32,
    ) -> Result<u64, DurableOperationError> {
        validate_limit(limit)?;
        let mut tx = begin_immediate(&self.pool).await?;
        let result = sqlx::query(
            "DELETE FROM operation_ledger WHERE (scope, operation_id) IN (
                 SELECT scope, operation_id FROM operation_ledger
                 WHERE state IN ('applied', 'not_applied', 'quarantined')
                 AND terminal_at_ms <= ? ORDER BY terminal_at_ms, scope, operation_id LIMIT ?
             )",
        )
        .bind(terminal_before_ms)
        .bind(limit)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(result.rows_affected())
    }

    pub async fn prune_destination_receipts(
        &self,
        recorded_before_ms: i64,
        limit: u32,
    ) -> Result<u64, DurableOperationError> {
        validate_limit(limit)?;
        let mut tx = begin_immediate(&self.pool).await?;
        let result = sqlx::query(
            "DELETE FROM destination_operation_dedup WHERE (destination, operation_id) IN (
                 SELECT destination, operation_id FROM destination_operation_dedup
                 WHERE recorded_at_ms <= ? ORDER BY recorded_at_ms, destination, operation_id LIMIT ?
             )",
        )
        .bind(recorded_before_ms)
        .bind(limit)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(result.rows_affected())
    }
}

const OPERATION_SELECT: &str =
    "SELECT * FROM operation_ledger WHERE scope = ? AND operation_id = ?";
const OUTBOX_SELECT: &str =
    "SELECT * FROM cross_owner_outbox WHERE scope = ? AND operation_id = ?";
const DESTINATION_SELECT: &str =
    "SELECT * FROM destination_operation_dedup WHERE destination = ? AND operation_id = ?";

async fn begin_immediate(
    pool: &SqlitePool,
) -> Result<Transaction<'_, Sqlite>, DurableOperationError> {
    pool.begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)
}

async fn load_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    scope: &StableId,
    operation_id: &StableId,
) -> Result<Option<DurableOperationRecord>, DurableOperationError> {
    sqlx::query(OPERATION_SELECT)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?
        .map(decode_operation)
        .transpose()
}

async fn load_outbox_tx(
    tx: &mut Transaction<'_, Sqlite>,
    scope: &StableId,
    operation_id: &StableId,
) -> Result<Option<DurableOutboxStatus>, DurableOperationError> {
    sqlx::query(OUTBOX_SELECT)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?
        .map(decode_outbox)
        .transpose()
}

async fn load_destination_tx(
    tx: &mut Transaction<'_, Sqlite>,
    destination: &StableId,
    operation_id: &StableId,
) -> Result<Option<DestinationReceipt>, DurableOperationError> {
    sqlx::query(DESTINATION_SELECT)
        .bind(destination.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?
        .map(decode_destination)
        .transpose()
}

async fn require_current_lease(
    tx: &mut Transaction<'_, Sqlite>,
    lease: &DispatchLease,
    now: i64,
) -> Result<(DurableOperationRecord, DurableOutboxStatus), DurableOperationError> {
    let operation = load_operation_tx(tx, &lease.scope, &lease.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
    let outbox = load_outbox_tx(tx, &lease.scope, &lease.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(lease.operation_id.clone()))?;
    require_lease_values(&operation, &outbox, lease, now)?;
    Ok((operation, outbox))
}

fn require_lease_values(
    operation: &DurableOperationRecord,
    outbox: &DurableOutboxStatus,
    lease: &DispatchLease,
    now: i64,
) -> Result<(), DurableOperationError> {
    if operation.scope != lease.scope
        || operation.operation_id != lease.operation_id
        || operation.destination != lease.destination
        || operation.semantic_digest != lease.semantic_digest
        || operation.payload_digest != lease.payload_digest
        || operation.owner_generation != lease.owner_generation
        || outbox.state != DurableOutboxState::Leased
        || outbox.worker_id.as_ref() != Some(&lease.worker_id)
        || outbox.claim_generation != Some(lease.owner_generation)
        || outbox.fence != lease.fence
        || outbox.lease_until_ms != Some(lease.expires_at_ms)
        || lease.expires_at_ms <= now
    {
        return Err(DurableOperationError::StaleLease);
    }
    Ok(())
}

fn claim_matches(outbox: &DurableOutboxStatus, lease: &DispatchLease) -> bool {
    outbox.fence == lease.fence && outbox.claim_generation == Some(lease.owner_generation)
}

async fn quarantine_attempt_limit(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &DurableOperationRecord,
    now: i64,
) -> Result<(), DurableOperationError> {
    let reason = Digest32::of_bytes(b"hepta.kernel.operations.attempt-limit.v1");
    let revision = operation
        .revision
        .next()
        .map_err(|_| DurableOperationError::Conflict(operation.operation_id.clone()))?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'quarantined', terminal_evidence_digest = ?,
         revision = ?, updated_at_ms = ?, terminal_at_ms = ? WHERE scope = ? AND operation_id = ?",
    )
    .bind(blob(reason))
    .bind(u64_blob(revision.get()))
    .bind(now)
    .bind(now)
    .bind(operation.scope.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'quarantined', worker_id = NULL,
         lease_until_ms = NULL, last_error_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope = ? AND operation_id = ?",
    )
    .bind(blob(reason))
    .bind(now)
    .bind(now)
    .bind(operation.scope.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn verify_store(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    let quick: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if quick.as_slice() != ["ok"] {
        return Err(DurableOperationError::Corrupt(format!(
            "SQLite quick_check failed: {quick:?}"
        )));
    }
    let foreign = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if !foreign.is_empty() {
        return Err(DurableOperationError::Corrupt(
            "SQLite foreign_key_check failed".to_string(),
        ));
    }
    for (name, kind) in REQUIRED_SCHEMA_OBJECTS {
        let actual: Option<String> = sqlx::query_scalar(
            "SELECT type FROM sqlite_master WHERE name = ? AND type = ?",
        )
        .bind(name)
        .bind(kind)
        .fetch_optional(pool)
        .await
        .map_err(unavailable)?;
        if actual.as_deref() != Some(*kind) {
            return Err(DurableOperationError::Corrupt(format!(
                "required schema object is missing: {kind} {name}"
            )));
        }
    }
    let version: i64 = sqlx::query_scalar(
        "SELECT schema_version FROM operations_meta WHERE singleton = 1",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if version != OPERATIONS_SCHEMA_VERSION {
        return Err(DurableOperationError::Corrupt(format!(
            "unexpected operations schema version {version}"
        )));
    }
    Ok(())
}

fn decode_operation(row: SqliteRow) -> Result<DurableOperationRecord, DurableOperationError> {
    let scope = stable_id(row.try_get("scope").map_err(unavailable)?, "scope")?;
    let operation_id = stable_id(
        row.try_get("operation_id").map_err(unavailable)?,
        "operation_id",
    )?;
    let state: String = row.try_get("state").map_err(unavailable)?;
    Ok(DurableOperationRecord {
        scope,
        operation_id,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        predecessor_digest: optional_digest(
            row.try_get("predecessor_digest").map_err(unavailable)?,
            "predecessor",
        )?,
        payload_digest: digest(row.try_get("payload_digest").map_err(unavailable)?, "payload")?,
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        owner_generation: generation(
            row.try_get("owner_generation").map_err(unavailable)?,
            "owner_generation",
        )?,
        authority_epoch: generation(
            row.try_get("authority_epoch").map_err(unavailable)?,
            "authority_epoch",
        )?,
        revision: revision(row.try_get("revision").map_err(unavailable)?)?,
        state: DurableOperationState::parse(&state)?,
        dispatch_digest: optional_digest(
            row.try_get("dispatch_digest").map_err(unavailable)?,
            "dispatch",
        )?,
        indeterminate_digest: optional_digest(
            row.try_get("indeterminate_digest").map_err(unavailable)?,
            "indeterminate",
        )?,
        terminal_evidence_digest: optional_digest(
            row.try_get("terminal_evidence_digest").map_err(unavailable)?,
            "terminal evidence",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(unavailable)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(unavailable)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(unavailable)?,
    })
}

fn decode_outbox(row: SqliteRow) -> Result<DurableOutboxStatus, DurableOperationError> {
    let state: String = row.try_get("state").map_err(unavailable)?;
    let fence: i64 = row.try_get("fence").map_err(unavailable)?;
    let attempts: i64 = row.try_get("attempts").map_err(unavailable)?;
    let worker: Option<String> = row.try_get("worker_id").map_err(unavailable)?;
    Ok(DurableOutboxStatus {
        scope: stable_id(row.try_get("scope").map_err(unavailable)?, "scope")?,
        operation_id: stable_id(
            row.try_get("operation_id").map_err(unavailable)?,
            "operation_id",
        )?,
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        state: DurableOutboxState::parse(&state)?,
        fence: u64::try_from(fence)
            .map_err(|_| DurableOperationError::Corrupt("negative outbox fence".to_string()))?,
        attempts: u32::try_from(attempts)
            .map_err(|_| DurableOperationError::Corrupt("invalid outbox attempts".to_string()))?,
        available_at_ms: row.try_get("available_at_ms").map_err(unavailable)?,
        worker_id: worker.map(|value| stable_id(value, "worker_id")).transpose()?,
        lease_until_ms: row.try_get("lease_until_ms").map_err(unavailable)?,
        claim_generation: optional_generation(
            row.try_get("claim_generation").map_err(unavailable)?,
            "claim_generation",
        )?,
        acknowledgement_digest: optional_digest(
            row.try_get("acknowledgement_digest").map_err(unavailable)?,
            "acknowledgement",
        )?,
        last_error_digest: optional_digest(
            row.try_get("last_error_digest").map_err(unavailable)?,
            "last_error",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(unavailable)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(unavailable)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(unavailable)?,
    })
}

fn decode_destination(row: SqliteRow) -> Result<DestinationReceipt, DurableOperationError> {
    let outcome: String = row.try_get("outcome").map_err(unavailable)?;
    Ok(DestinationReceipt {
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        operation_id: stable_id(
            row.try_get("operation_id").map_err(unavailable)?,
            "operation_id",
        )?,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        outcome: parse_outcome(&outcome)?,
        evidence_digest: digest(row.try_get("evidence_digest").map_err(unavailable)?, "evidence")?,
        recorded_at_ms: row.try_get("recorded_at_ms").map_err(unavailable)?,
    })
}

fn state_for_outcome(outcome: ReconciliationOutcome) -> DurableOperationState {
    match outcome {
        ReconciliationOutcome::Applied => DurableOperationState::Applied,
        ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
        ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
    }
}

fn outcome_label(outcome: ReconciliationOutcome) -> &'static str {
    match outcome {
        ReconciliationOutcome::Applied => "applied",
        ReconciliationOutcome::NotApplied => "not_applied",
        ReconciliationOutcome::Quarantined => "quarantined",
    }
}

fn parse_outcome(value: &str) -> Result<ReconciliationOutcome, DurableOperationError> {
    match value {
        "applied" => Ok(ReconciliationOutcome::Applied),
        "not_applied" => Ok(ReconciliationOutcome::NotApplied),
        "quarantined" => Ok(ReconciliationOutcome::Quarantined),
        _ => Err(DurableOperationError::Corrupt(format!(
            "unknown destination outcome {value}"
        ))),
    }
}

fn append_stable_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn blob(value: Digest32) -> Vec<u8> {
    value.into_array().to_vec()
}

fn optional_blob(value: Option<Digest32>) -> Option<Vec<u8>> {
    value.map(blob)
}

fn u64_blob(value: u64) -> Vec<u8> {
    value.to_be_bytes().to_vec()
}

fn digest(bytes: Vec<u8>, field: &str) -> Result<Digest32, DurableOperationError> {
    let array: [u8; 32] = bytes.try_into().map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} digest is not 32 bytes"))
    })?;
    let value = Digest32::from_array(array);
    if value.is_zero() {
        return Err(DurableOperationError::Corrupt(format!(
            "{field} digest is zero"
        )));
    }
    Ok(value)
}

fn optional_digest(
    bytes: Option<Vec<u8>>,
    field: &str,
) -> Result<Option<Digest32>, DurableOperationError> {
    bytes.map(|value| digest(value, field)).transpose()
}

fn decode_u64(bytes: Vec<u8>, field: &str) -> Result<u64, DurableOperationError> {
    let array: [u8; 8] = bytes.try_into().map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not an 8-byte u64"))
    })?;
    Ok(u64::from_be_bytes(array))
}

fn generation(bytes: Vec<u8>, field: &str) -> Result<Generation, DurableOperationError> {
    Generation::new(decode_u64(bytes, field)?).map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not a valid generation"))
    })
}

fn optional_generation(
    bytes: Option<Vec<u8>>,
    field: &str,
) -> Result<Option<Generation>, DurableOperationError> {
    bytes.map(|value| generation(value, field)).transpose()
}

fn revision(bytes: Vec<u8>) -> Result<Revision, DurableOperationError> {
    Revision::new(decode_u64(bytes, "revision")?).map_err(|_| {
        DurableOperationError::Corrupt("revision is not a valid monotonic value".to_string())
    })
}

fn stable_id(value: String, field: &str) -> Result<StableId, DurableOperationError> {
    StableId::new(value).map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not a valid stable identifier"))
    })
}

fn first_revision() -> Revision {
    match Revision::new(1) {
        Ok(value) => value,
        Err(error) => unreachable!("constant first revision is invalid: {error}"),
    }
}

fn validate_limit(limit: u32) -> Result<(), DurableOperationError> {
    if limit == 0 || limit > MAX_OPERATION_CLAIM_BATCH {
        return Err(DurableOperationError::Invalid("limit must be 1..=256"));
    }
    Ok(())
}

fn validate_lease_duration(lease_ms: i64) -> Result<(), DurableOperationError> {
    if !(1..=MAX_OPERATION_LEASE_MS).contains(&lease_ms) {
        return Err(DurableOperationError::Invalid(
            "lease must be 1..=60000 milliseconds",
        ));
    }
    Ok(())
}

fn now_millis() -> Result<i64, DurableOperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| DurableOperationError::Unavailable("clock predates Unix epoch".to_string()))?
        .as_millis();
    i64::try_from(millis)
        .map_err(|_| DurableOperationError::Unavailable("clock overflow".to_string()))
}

fn nonnegative_u64(value: i64) -> Result<u64, DurableOperationError> {
    u64::try_from(value)
        .map_err(|_| DurableOperationError::Corrupt("negative aggregate count".to_string()))
}

fn unavailable(error: impl std::fmt::Display) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
