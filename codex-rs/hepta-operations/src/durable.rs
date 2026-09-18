use std::fmt;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
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

use crate::OperationError;
use crate::ReconciliationOutcome;

const OPERATIONS_DB_FILENAME: &str = "hepta_operations_1.sqlite";
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

pub const MAX_DURABLE_ACTIVE_OPERATIONS: i64 = 100_000;
pub const MAX_DURABLE_PAYLOAD_BYTES: usize = 1_048_576;
pub const MAX_DURABLE_OUTBOX_ATTEMPTS: i64 = 16;
pub const MAX_DURABLE_OUTBOX_LEASE_MS: i64 = 60_000;
pub const MAX_DURABLE_CLAIM_BATCH: u32 = 256;
const TERMINAL_OUTBOX_RETENTION_MS: i64 = 7 * 24 * 60 * 60 * 1_000;
const TERMINAL_OUTBOX_RETAINED_ROWS: i64 = 16_384;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedIntent {
    pub operation_id: StableId,
    pub owner_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub destination: StableId,
    pub expected_predecessor: Option<Digest32>,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
}

impl PreparedIntent {
    pub fn validate(&self) -> Result<(), OperationError> {
        if self.scope_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation scope"));
        }
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation payload"));
        }
        if self.expected_predecessor.is_some_and(Digest32::is_zero) {
            return Err(OperationError::InvalidDigest("operation predecessor"));
        }
        Ok(())
    }

    /// Stable semantic identity. Runtime ownership generations and authority
    /// epochs are deliberately excluded so a fenced handoff does not invent a
    /// new operation.
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.semantic-intent.v1\0".to_vec();
        append_text(&mut bytes, &self.operation_id);
        append_text(&mut bytes, &self.owner_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        append_text(&mut bytes, &self.destination);
        match self.expected_predecessor {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
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
        matches!(self, Self::Applied | Self::NotApplied | Self::Quarantined)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub intent: PreparedIntent,
    pub semantic_digest: Digest32,
    pub revision: Revision,
    pub state: DurableOperationState,
    pub writer_fence: i64,
    pub attempts: i64,
    pub dispatch_digest: Option<Digest32>,
    pub acknowledgement_digest: Option<Digest32>,
    pub indeterminate_reason_digest: Option<Digest32>,
    pub terminal_digest: Option<Digest32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchStartDisposition {
    Started,
    AlreadyStarted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchEnvelope {
    pub operation_id: StableId,
    pub owner_id: StableId,
    pub destination: StableId,
    pub semantic_digest: Digest32,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub expected_predecessor: Option<Digest32>,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
    pub fence: i64,
    pub attempt: i64,
}

impl DispatchEnvelope {
    /// Attempt-specific digest used as the final-use request binding. A grant
    /// for an older lease/fence cannot be reused for a newer attempt.
    pub fn attempt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.dispatch-attempt.v1\0".to_vec();
        bytes.extend_from_slice(self.semantic_digest.as_array());
        bytes.extend_from_slice(&self.owner_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&self.fence.to_be_bytes());
        bytes.extend_from_slice(&self.attempt.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn final_use_binding(&self) -> FinalUseBinding {
        FinalUseBinding {
            subject_id: self.owner_id.as_str().to_owned(),
            destination_id: self.destination.as_str().to_owned(),
            request_sha256: self.attempt_digest().into_array(),
            scope_sha256: self.scope_digest.into_array(),
            payload_sha256: self.payload_digest.into_array(),
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct DispatchLease {
    envelope: DispatchEnvelope,
    payload: Vec<u8>,
    worker_id: StableId,
    expires_at_ms: i64,
}

impl fmt::Debug for DispatchLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DispatchLease")
            .field("envelope", &self.envelope)
            .field("payload_len", &self.payload.len())
            .field("worker_id", &self.worker_id)
            .field("expires_at_ms", &self.expires_at_ms)
            .finish()
    }
}

impl DispatchLease {
    pub fn envelope(&self) -> &DispatchEnvelope {
        &self.envelope
    }

    pub fn operation_id(&self) -> &StableId {
        &self.envelope.operation_id
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn worker_id(&self) -> &StableId {
        &self.worker_id
    }

    pub fn fence(&self) -> i64 {
        self.envelope.fence
    }

    pub fn expires_at_ms(&self) -> i64 {
        self.expires_at_ms
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EffectObservation {
    Terminal {
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    },
    Indeterminate {
        reason_digest: Digest32,
    },
}

#[derive(Clone)]
pub struct DurableOperationStore {
    pool: SqlitePool,
    path: PathBuf,
}

impl DurableOperationStore {
    pub async fn open(sqlite: &SqliteConfig) -> Result<Self, OperationError> {
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
        if let Err(error) = verify_schema(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }

    /// Atomically writes the authoritative ledger row and its local outbox row.
    /// Exact semantic replay returns the retained operation without requeueing a
    /// terminal or already-dispatched operation.
    pub async fn prepare_intent(
        &self,
        intent: PreparedIntent,
        payload: Vec<u8>,
    ) -> Result<DurableOperationRecord, OperationError> {
        intent.validate()?;
        validate_payload(&intent, &payload)?;
        let semantic_digest = intent.semantic_digest();
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        maintain_terminal_outbox(&mut tx, now).await?;

        if let Some(existing) = load_operation_tx(&mut tx, &intent.operation_id).await? {
            if existing.semantic_digest != semantic_digest {
                return Err(OperationError::Conflict(intent.operation_id));
            }
            tx.commit().await.map_err(storage)?;
            return Ok(existing);
        }

        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_ledger WHERE state NOT IN ('applied','not_applied','quarantined')",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if active >= MAX_DURABLE_ACTIVE_OPERATIONS {
            return Err(OperationError::CapacityExceeded {
                resource: "durable operation ledger active set",
                maximum: usize::try_from(MAX_DURABLE_ACTIVE_OPERATIONS).unwrap_or(usize::MAX),
            });
        }

        sqlx::query(
            "INSERT INTO operation_ledger (
                operation_id, owner_id, scope_digest, payload_digest, destination,
                expected_predecessor_digest, semantic_digest, owner_generation,
                authority_epoch, revision, state, writer_fence, attempts,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?)",
        )
        .bind(intent.operation_id.as_str())
        .bind(intent.owner_id.as_str())
        .bind(intent.scope_digest.as_array().as_slice())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(intent.destination.as_str())
        .bind(intent.expected_predecessor.map(|value| value.into_array().to_vec()))
        .bind(semantic_digest.as_array().as_slice())
        .bind(intent.owner_generation.get().to_be_bytes().as_slice())
        .bind(intent.authority_epoch.get().to_be_bytes().as_slice())
        .bind(1_u64.to_be_bytes().as_slice())
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;

        // Same BEGIN IMMEDIATE transaction: there is no state in which only one
        // of the authoritative intent and its source outbox is committed.
        sqlx::query(
            "INSERT INTO cross_owner_outbox (
                operation_id, destination, semantic_digest, payload_digest, payload, state,
                fence, attempts, available_at_ms, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?)",
        )
        .bind(intent.operation_id.as_str())
        .bind(intent.destination.as_str())
        .bind(semantic_digest.as_array().as_slice())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(payload)
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;

        let record = load_operation_tx(&mut tx, &intent.operation_id)
            .await?
            .ok_or_else(|| OperationError::Corrupt("prepared operation disappeared".into()))?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn get(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<DurableOperationRecord>, OperationError> {
        sqlx::query("SELECT * FROM operation_ledger WHERE operation_id = ?")
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(decode_operation)
            .transpose()
    }

    pub async fn pending_operations(
        &self,
        destination: Option<&StableId>,
        limit: u32,
    ) -> Result<Vec<DurableOperationRecord>, OperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(OperationError::InvalidRequest("claim batch must be 1..=256"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        maintain_terminal_outbox(&mut tx, now).await?;
        let destination = destination.map(StableId::as_str);
        let rows = sqlx::query(
            "SELECT operation_id FROM cross_owner_outbox
             WHERE (? IS NULL OR destination = ?)
               AND available_at_ms <= ?
               AND (state = 'queued' OR (state = 'leased' AND lease_until_ms <= ?))
             ORDER BY available_at_ms, operation_id LIMIT ?",
        )
        .bind(destination)
        .bind(destination)
        .bind(now)
        .bind(now)
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut records = Vec::with_capacity(rows.len());
        for row in rows {
            let id = StableId::new(
                row.try_get::<String, _>("operation_id")
                    .map_err(storage)?,
            )
            .map_err(|_| OperationError::Corrupt("invalid stored operation ID".into()))?;
            records.push(
                load_operation_tx(&mut tx, &id)
                    .await?
                    .ok_or_else(|| OperationError::Corrupt("outbox lost ledger parent".into()))?,
            );
        }
        tx.commit().await.map_err(storage)?;
        Ok(records)
    }

    pub async fn claim_outbox(
        &self,
        operation_id: &StableId,
        owner_generation: Generation,
        authority_epoch: Generation,
        worker_id: &StableId,
        lease_ms: i64,
    ) -> Result<DispatchLease, OperationError> {
        validate_lease_ms(lease_ms)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, operation_id).await?;
        require_owner(&record, owner_generation, authority_epoch)?;
        if record.state != DurableOperationState::Pending {
            return Err(if record.state.is_terminal() {
                OperationError::Terminal
            } else {
                OperationError::Unavailable
            });
        }
        let outbox = load_required_outbox(&mut tx, operation_id).await?;
        if now < outbox.updated_at_ms {
            return Err(OperationError::StaleLease);
        }
        let claimable = match outbox.state.as_str() {
            "queued" => outbox.available_at_ms <= now,
            "leased" => outbox.lease_until_ms.is_some_and(|until| until <= now),
            _ => false,
        };
        if !claimable {
            return Err(OperationError::Unavailable);
        }
        if outbox.attempts >= MAX_DURABLE_OUTBOX_ATTEMPTS {
            terminalize_without_effect(
                &mut tx,
                &record,
                &outbox,
                attempt_budget_digest(operation_id),
                now,
            )
            .await?;
            tx.commit().await.map_err(storage)?;
            return Err(OperationError::Unavailable);
        }
        let fence = outbox
            .fence
            .checked_add(1)
            .ok_or(OperationError::StaleLease)?;
        let attempt = outbox
            .attempts
            .checked_add(1)
            .ok_or(OperationError::StaleLease)?;
        let expires_at_ms = now
            .checked_add(lease_ms)
            .ok_or(OperationError::InvalidRequest("lease time overflow"))?;
        let revision = next_revision(record.revision, operation_id)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, attempts = ?,
                worker_id = ?, lease_until_ms = ?, updated_at_ms = ? WHERE operation_id = ?",
        )
        .bind(fence)
        .bind(attempt)
        .bind(worker_id.as_str())
        .bind(expires_at_ms)
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE operation_ledger SET writer_fence = ?, attempts = ?, revision = ?,
                updated_at_ms = ? WHERE operation_id = ?",
        )
        .bind(fence)
        .bind(attempt)
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let payload = outbox.payload;
        tx.commit().await.map_err(storage)?;
        Ok(DispatchLease {
            envelope: envelope_from(&record, fence, attempt),
            payload,
            worker_id: worker_id.clone(),
            expires_at_ms,
        })
    }

    pub async fn renew_outbox(
        &self,
        lease: &DispatchLease,
        lease_ms: i64,
    ) -> Result<DispatchLease, OperationError> {
        validate_lease_ms(lease_ms)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, lease.operation_id()).await?;
        let outbox = load_required_outbox(&mut tx, lease.operation_id()).await?;
        require_live_lease(&record, &outbox, lease, now)?;
        let fence = outbox
            .fence
            .checked_add(1)
            .ok_or(OperationError::StaleLease)?;
        let expires_at_ms = now
            .checked_add(lease_ms)
            .ok_or(OperationError::InvalidRequest("lease time overflow"))?;
        let revision = next_revision(record.revision, lease.operation_id())?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET fence = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(fence)
        .bind(expires_at_ms)
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE operation_ledger SET writer_fence = ?, revision = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(fence)
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        let mut envelope = lease.envelope.clone();
        envelope.fence = fence;
        Ok(DispatchLease {
            envelope,
            payload: lease.payload.clone(),
            worker_id: lease.worker_id.clone(),
            expires_at_ms,
        })
    }

    /// Releases only a pre-dispatch lease. Once `record_dispatch_started` has
    /// committed, retry is forbidden and reconciliation is required instead.
    pub async fn release_outbox(
        &self,
        lease: &DispatchLease,
        delay_ms: i64,
    ) -> Result<(), OperationError> {
        if !(0..=MAX_DURABLE_OUTBOX_LEASE_MS).contains(&delay_ms) {
            return Err(OperationError::InvalidRequest("retry delay must be 0..=60000 ms"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, lease.operation_id()).await?;
        let outbox = load_required_outbox(&mut tx, lease.operation_id()).await?;
        require_live_lease(&record, &outbox, lease, now)?;
        let revision = next_revision(record.revision, lease.operation_id())?;
        let fence = outbox
            .fence
            .checked_add(1)
            .ok_or(OperationError::StaleLease)?;
        if outbox.attempts >= MAX_DURABLE_OUTBOX_ATTEMPTS {
            terminalize_without_effect(
                &mut tx,
                &record,
                &outbox,
                attempt_budget_digest(lease.operation_id()),
                now,
            )
            .await?;
        } else {
            let available_at_ms = now
                .checked_add(delay_ms)
                .ok_or(OperationError::InvalidRequest("retry time overflow"))?;
            sqlx::query(
                "UPDATE cross_owner_outbox SET state = 'queued', fence = ?, worker_id = NULL,
                    lease_until_ms = NULL, available_at_ms = ?, updated_at_ms = ?
                 WHERE operation_id = ?",
            )
            .bind(fence)
            .bind(available_at_ms)
            .bind(now)
            .bind(lease.operation_id().as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
            sqlx::query(
                "UPDATE operation_ledger SET writer_fence = ?, revision = ?, updated_at_ms = ?
                 WHERE operation_id = ?",
            )
            .bind(fence)
            .bind(revision.get().to_be_bytes().as_slice())
            .bind(now)
            .bind(lease.operation_id().as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(())
    }

    /// Persist the point of no blind retry immediately before the effect
    /// boundary. A replay of this method never grants permission to invoke the
    /// effect again; callers must reconcile an already-started dispatch.
    pub async fn record_dispatch_started(
        &self,
        lease: &DispatchLease,
        dispatch_digest: Digest32,
    ) -> Result<DispatchStartDisposition, OperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, lease.operation_id()).await?;
        require_owner(
            &record,
            lease.envelope.owner_generation,
            lease.envelope.authority_epoch,
        )?;
        let outbox = load_required_outbox(&mut tx, lease.operation_id()).await?;
        if record.state == DurableOperationState::Dispatched
            && record.dispatch_digest == Some(dispatch_digest)
            && outbox.fence == lease.fence()
        {
            tx.commit().await.map_err(storage)?;
            return Ok(DispatchStartDisposition::AlreadyStarted);
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if record.state != DurableOperationState::Pending {
            return Err(OperationError::InvalidTransition {
                from: record.state.label(),
                to: "dispatched",
            });
        }
        require_live_lease(&record, &outbox, lease, now)?;
        let revision = next_revision(record.revision, lease.operation_id())?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatched', dispatch_digest = ?,
                revision = ?, updated_at_ms = ? WHERE operation_id = ?",
        )
        .bind(dispatch_digest.as_array().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'dispatched', worker_id = NULL,
                lease_until_ms = NULL, updated_at_ms = ? WHERE operation_id = ?",
        )
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(DispatchStartDisposition::Started)
    }

    /// A transport acknowledgement is evidence only. It never terminalizes the
    /// operation and cannot make a blind resend safe.
    pub async fn acknowledge_transport(
        &self,
        lease: &DispatchLease,
        acknowledgement_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox acknowledgement"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, lease.operation_id()).await?;
        require_dispatch_fence(&record, lease)?;
        if !matches!(
            record.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(if record.state.is_terminal() {
                OperationError::Terminal
            } else {
                OperationError::InvalidTransition {
                    from: record.state.label(),
                    to: "acknowledged",
                }
            });
        }
        if let Some(existing) = record.acknowledgement_digest {
            if existing == acknowledgement_digest {
                tx.commit().await.map_err(storage)?;
                return Ok(record);
            }
            return Err(OperationError::Conflict(lease.operation_id().clone()));
        }
        let outbox = load_required_outbox(&mut tx, lease.operation_id()).await?;
        if outbox.fence != lease.fence() {
            return Err(OperationError::StaleLease);
        }
        let revision = next_revision(record.revision, lease.operation_id())?;
        sqlx::query(
            "UPDATE operation_ledger SET acknowledgement_digest = ?, revision = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(acknowledgement_digest.as_array().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET acknowledgement_digest = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(acknowledgement_digest.as_array().as_slice())
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = load_required_operation(&mut tx, lease.operation_id()).await?;
        tx.commit().await.map_err(storage)?;
        Ok(updated)
    }

    pub async fn mark_indeterminate(
        &self,
        lease: &DispatchLease,
        reason_digest: Digest32,
    ) -> Result<DurableOperationRecord, OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, lease.operation_id()).await?;
        require_dispatch_fence(&record, lease)?;
        if record.state == DurableOperationState::Indeterminate
            && record.indeterminate_reason_digest == Some(reason_digest)
        {
            tx.commit().await.map_err(storage)?;
            return Ok(record);
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if record.state != DurableOperationState::Dispatched {
            return Err(OperationError::InvalidTransition {
                from: record.state.label(),
                to: "indeterminate",
            });
        }
        let outbox = load_required_outbox(&mut tx, lease.operation_id()).await?;
        if outbox.fence != lease.fence() {
            return Err(OperationError::StaleLease);
        }
        let revision = next_revision(record.revision, lease.operation_id())?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_reason_digest = ?,
                revision = ?, updated_at_ms = ? WHERE operation_id = ?",
        )
        .bind(reason_digest.as_array().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate', updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(now)
        .bind(lease.operation_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = load_required_operation(&mut tx, lease.operation_id()).await?;
        tx.commit().await.map_err(storage)?;
        Ok(updated)
    }

    /// Persist uncertainty discovered after reopening a committed dispatch.
    ///
    /// This recovery path deliberately does not require the original in-process
    /// `DispatchLease`: a crashed worker cannot possess it. The current owner
    /// generation and authority epoch are rechecked instead, and the operation
    /// remains non-dispatchable. This method never requeues or executes an
    /// effect.
    pub async fn mark_recovered_indeterminate(
        &self,
        operation_id: &StableId,
        reason_digest: Digest32,
        observer_generation: Generation,
        authority_epoch: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, operation_id).await?;
        require_owner(&record, observer_generation, authority_epoch)?;
        if record.state == DurableOperationState::Indeterminate
            && record.indeterminate_reason_digest == Some(reason_digest)
        {
            tx.commit().await.map_err(storage)?;
            return Ok(record);
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if record.state != DurableOperationState::Dispatched {
            return Err(OperationError::InvalidTransition {
                from: record.state.label(),
                to: "indeterminate",
            });
        }
        let outbox = load_required_outbox(&mut tx, operation_id).await?;
        if outbox.state != "dispatched"
            || outbox.fence != record.writer_fence
            || outbox.attempts != record.attempts
        {
            return Err(OperationError::Corrupt(
                "recovered dispatch/outbox fence mismatch".into(),
            ));
        }
        let revision = next_revision(record.revision, operation_id)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate',
                indeterminate_reason_digest = ?, revision = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(reason_digest.as_array().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate',
                worker_id = NULL, lease_until_ms = NULL, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = load_required_operation(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(updated)
    }

    pub async fn observe_terminal(
        &self,
        operation_id: &StableId,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
        observer_generation: Generation,
        authority_epoch: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if outcome_digest.is_zero() {
            return Err(OperationError::InvalidDigest("terminal outcome"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, operation_id).await?;
        require_owner(&record, observer_generation, authority_epoch)?;
        let desired = terminal_state(outcome);
        if record.state == desired && record.terminal_digest == Some(outcome_digest) {
            tx.commit().await.map_err(storage)?;
            return Ok(record);
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if !matches!(
            record.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(OperationError::InvalidTransition {
                from: record.state.label(),
                to: desired.label(),
            });
        }
        let revision = next_revision(record.revision, operation_id)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = ?, terminal_digest = ?, revision = ?,
                updated_at_ms = ?, terminal_at_ms = ? WHERE operation_id = ?",
        )
        .bind(desired.label())
        .bind(outcome_digest.as_array().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(now)
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = ?, worker_id = NULL, lease_until_ms = NULL,
                updated_at_ms = ?, terminal_at_ms = ? WHERE operation_id = ?",
        )
        .bind(desired.label())
        .bind(now)
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = load_required_operation(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(updated)
    }

    /// Transfer unresolved ownership to a strictly newer process generation and
    /// a strictly newer authority epoch. The authority owner must publish that
    /// epoch before the new writer is allowed to enter an effect boundary.
    /// A dispatched operation becomes indeterminate and is never requeued.
    pub async fn handoff_owner(
        &self,
        operation_id: &StableId,
        expected_owner_generation: Generation,
        new_owner_generation: Generation,
        new_authority_epoch: Generation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if new_owner_generation <= expected_owner_generation {
            return Err(OperationError::InvalidRequest("new owner generation must increase"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let record = load_required_operation(&mut tx, operation_id).await?;
        if record.intent.owner_generation != expected_owner_generation {
            return Err(OperationError::StaleGeneration);
        }
        if new_authority_epoch <= record.intent.authority_epoch {
            return Err(OperationError::InvalidRequest("new authority epoch must increase"));
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        let outbox = load_required_outbox(&mut tx, operation_id).await?;
        let fence = outbox
            .fence
            .checked_add(1)
            .ok_or(OperationError::StaleLease)?;
        let revision = next_revision(record.revision, operation_id)?;
        let (next_state, reason_digest) = match record.state {
            DurableOperationState::Pending => (DurableOperationState::Pending, None),
            DurableOperationState::Dispatched => (
                DurableOperationState::Indeterminate,
                Some(handoff_reason_digest(
                    operation_id,
                    expected_owner_generation,
                    new_owner_generation,
                    new_authority_epoch,
                )),
            ),
            DurableOperationState::Indeterminate => (
                DurableOperationState::Indeterminate,
                record.indeterminate_reason_digest,
            ),
            DurableOperationState::Applied
            | DurableOperationState::NotApplied
            | DurableOperationState::Quarantined => return Err(OperationError::Terminal),
        };
        sqlx::query(
            "UPDATE operation_ledger SET owner_generation = ?, authority_epoch = ?, revision = ?,
                state = ?, writer_fence = ?, indeterminate_reason_digest = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(new_owner_generation.get().to_be_bytes().as_slice())
        .bind(new_authority_epoch.get().to_be_bytes().as_slice())
        .bind(revision.get().to_be_bytes().as_slice())
        .bind(next_state.label())
        .bind(fence)
        .bind(reason_digest.map(|value| value.into_array().to_vec()))
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let outbox_state = match next_state {
            DurableOperationState::Pending => "queued",
            DurableOperationState::Indeterminate => "indeterminate",
            _ => return Err(OperationError::Corrupt("invalid handoff state".into())),
        };
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = ?, fence = ?, worker_id = NULL,
                lease_until_ms = NULL, available_at_ms = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(outbox_state)
        .bind(fence)
        .bind(now)
        .bind(now)
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = load_required_operation(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(updated)
    }

    pub async fn compact_terminal_outbox(&self) -> Result<u64, OperationError> {
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)?;
        let removed = maintain_terminal_outbox(&mut tx, now).await?;
        tx.commit().await.map_err(storage)?;
        Ok(removed)
    }

    /// One bounded vertical dispatch step. The effect closure runs synchronously
    /// under `kernel.authority`'s final-use revocation fence. This function never
    /// retries an already-started effect: callers receiving
    /// `DispatchAlreadyStarted` must reconcile instead.
    pub async fn dispatch_once(
        &self,
        lease: &DispatchLease,
        dispatch_digest: Digest32,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        effect: impl FnOnce(&DispatchEnvelope, &[u8]) -> EffectObservation,
    ) -> Result<DurableOperationRecord, OperationError> {
        if self
            .record_dispatch_started(lease, dispatch_digest)
            .await?
            == DispatchStartDisposition::AlreadyStarted
        {
            return Err(OperationError::DispatchAlreadyStarted);
        }
        let observation = execute_with_final_use(authority, grant, lease.envelope(), || {
            effect(lease.envelope(), lease.payload())
        })?;
        match observation {
            EffectObservation::Terminal {
                outcome,
                evidence_digest,
            } => {
                self.observe_terminal(
                    lease.operation_id(),
                    outcome,
                    evidence_digest,
                    lease.envelope.owner_generation,
                    lease.envelope.authority_epoch,
                )
                .await
            }
            EffectObservation::Indeterminate { reason_digest } => {
                self.mark_indeterminate(lease, reason_digest).await
            }
        }
    }
}

pub fn execute_with_final_use<T>(
    authority: &FinalUseAuthority,
    grant: &SignedFinalUseGrant,
    envelope: &DispatchEnvelope,
    effect: impl FnOnce() -> T,
) -> Result<T, OperationError> {
    let binding = envelope.final_use_binding();
    let token = authority
        .claim(grant, &binding)
        .map_err(OperationError::Authority)?;
    authority
        .with_verified_use(token, &binding, effect)
        .map_err(OperationError::Authority)
}

#[derive(Clone)]
struct OutboxRow {
    state: String,
    payload: Vec<u8>,
    fence: i64,
    attempts: i64,
    worker_id: Option<String>,
    lease_until_ms: Option<i64>,
    available_at_ms: i64,
    updated_at_ms: i64,
}

fn envelope_from(record: &DurableOperationRecord, fence: i64, attempt: i64) -> DispatchEnvelope {
    DispatchEnvelope {
        operation_id: record.intent.operation_id.clone(),
        owner_id: record.intent.owner_id.clone(),
        destination: record.intent.destination.clone(),
        semantic_digest: record.semantic_digest,
        scope_digest: record.intent.scope_digest,
        payload_digest: record.intent.payload_digest,
        expected_predecessor: record.intent.expected_predecessor,
        owner_generation: record.intent.owner_generation,
        authority_epoch: record.intent.authority_epoch,
        fence,
        attempt,
    }
}

fn require_owner(
    record: &DurableOperationRecord,
    generation: Generation,
    authority_epoch: Generation,
) -> Result<(), OperationError> {
    if record.intent.owner_generation != generation {
        return Err(OperationError::StaleGeneration);
    }
    if record.intent.authority_epoch != authority_epoch {
        return Err(OperationError::StaleAuthorityEpoch);
    }
    Ok(())
}

fn require_dispatch_fence(
    record: &DurableOperationRecord,
    lease: &DispatchLease,
) -> Result<(), OperationError> {
    require_owner(
        record,
        lease.envelope.owner_generation,
        lease.envelope.authority_epoch,
    )?;
    if record.writer_fence != lease.fence() {
        return Err(OperationError::StaleLease);
    }
    Ok(())
}

fn require_live_lease(
    record: &DurableOperationRecord,
    outbox: &OutboxRow,
    lease: &DispatchLease,
    now: i64,
) -> Result<(), OperationError> {
    require_dispatch_fence(record, lease)?;
    if record.state != DurableOperationState::Pending
        || outbox.state != "leased"
        || outbox.fence != lease.fence()
        || outbox.worker_id.as_deref() != Some(lease.worker_id.as_str())
        || outbox.lease_until_ms != Some(lease.expires_at_ms)
        || outbox.lease_until_ms.is_none_or(|until| until <= now)
        || now < outbox.updated_at_ms
    {
        return Err(OperationError::StaleLease);
    }
    Ok(())
}

fn validate_payload(intent: &PreparedIntent, payload: &[u8]) -> Result<(), OperationError> {
    if payload.is_empty() || payload.len() > MAX_DURABLE_PAYLOAD_BYTES {
        return Err(OperationError::InvalidRequest(
            "durable operation payload must be 1..=1048576 bytes",
        ));
    }
    if Digest32::of_bytes(payload) != intent.payload_digest {
        return Err(OperationError::InvalidDigest("operation payload binding"));
    }
    Ok(())
}

fn validate_lease_ms(lease_ms: i64) -> Result<(), OperationError> {
    if !(1..=MAX_DURABLE_OUTBOX_LEASE_MS).contains(&lease_ms) {
        return Err(OperationError::InvalidRequest("lease must be 1..=60000 ms"));
    }
    Ok(())
}

async fn load_required_operation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<DurableOperationRecord, OperationError> {
    load_operation_tx(tx, operation_id)
        .await?
        .ok_or_else(|| OperationError::Missing(operation_id.clone()))
}

async fn load_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<DurableOperationRecord>, OperationError> {
    sqlx::query("SELECT * FROM operation_ledger WHERE operation_id = ?")
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?
        .map(decode_operation)
        .transpose()
}

async fn load_required_outbox(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<OutboxRow, OperationError> {
    let row = sqlx::query("SELECT * FROM cross_owner_outbox WHERE operation_id = ?")
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(storage)?
        .ok_or_else(|| OperationError::Corrupt("active operation lost outbox row".into()))?;
    decode_outbox(row)
}

fn decode_operation(row: SqliteRow) -> Result<DurableOperationRecord, OperationError> {
    let operation_id = stored_id(&row, "operation_id")?;
    let owner_id = stored_id(&row, "owner_id")?;
    let destination = stored_id(&row, "destination")?;
    let scope_digest = stored_digest(&row, "scope_digest")?;
    let payload_digest = stored_digest(&row, "payload_digest")?;
    let expected_predecessor = optional_digest(&row, "expected_predecessor_digest")?;
    let semantic_digest = stored_digest(&row, "semantic_digest")?;
    let owner_generation = stored_generation(&row, "owner_generation")?;
    let authority_epoch = stored_generation(&row, "authority_epoch")?;
    let revision = Revision::new(u64::from_be_bytes(blob(&row, "revision")?))
        .map_err(|_| OperationError::Corrupt("invalid stored operation revision".into()))?;
    let state: String = row.try_get("state").map_err(storage)?;
    let state = match state.as_str() {
        "pending" => DurableOperationState::Pending,
        "dispatched" => DurableOperationState::Dispatched,
        "indeterminate" => DurableOperationState::Indeterminate,
        "applied" => DurableOperationState::Applied,
        "not_applied" => DurableOperationState::NotApplied,
        "quarantined" => DurableOperationState::Quarantined,
        _ => return Err(OperationError::Corrupt("invalid stored operation state".into())),
    };
    let writer_fence: i64 = row.try_get("writer_fence").map_err(storage)?;
    let attempts: i64 = row.try_get("attempts").map_err(storage)?;
    if writer_fence < 0 || !(0..=MAX_DURABLE_OUTBOX_ATTEMPTS).contains(&attempts) {
        return Err(OperationError::Corrupt("invalid stored operation counters".into()));
    }
    let dispatch_digest = optional_digest(&row, "dispatch_digest")?;
    let acknowledgement_digest = optional_digest(&row, "acknowledgement_digest")?;
    let indeterminate_reason_digest = optional_digest(&row, "indeterminate_reason_digest")?;
    let terminal_digest = optional_digest(&row, "terminal_digest")?;
    let intent = PreparedIntent {
        operation_id,
        owner_id,
        scope_digest,
        payload_digest,
        destination,
        expected_predecessor,
        owner_generation,
        authority_epoch,
    };
    intent.validate()?;
    if intent.semantic_digest() != semantic_digest {
        return Err(OperationError::Corrupt("operation semantic digest mismatch".into()));
    }
    match state {
        DurableOperationState::Pending => {
            if dispatch_digest.is_some()
                || indeterminate_reason_digest.is_some()
                || terminal_digest.is_some()
            {
                return Err(OperationError::Corrupt("invalid pending operation evidence".into()));
            }
        }
        DurableOperationState::Dispatched => {
            if dispatch_digest.is_none() || terminal_digest.is_some() {
                return Err(OperationError::Corrupt("invalid dispatched operation evidence".into()));
            }
        }
        DurableOperationState::Indeterminate => {
            if dispatch_digest.is_none()
                || indeterminate_reason_digest.is_none()
                || terminal_digest.is_some()
            {
                return Err(OperationError::Corrupt("invalid indeterminate operation evidence".into()));
            }
        }
        DurableOperationState::Applied | DurableOperationState::NotApplied => {
            if dispatch_digest.is_none() || terminal_digest.is_none() {
                return Err(OperationError::Corrupt("invalid terminal operation evidence".into()));
            }
        }
        DurableOperationState::Quarantined => {
            if terminal_digest.is_none() {
                return Err(OperationError::Corrupt("invalid quarantine evidence".into()));
            }
        }
    }
    Ok(DurableOperationRecord {
        intent,
        semantic_digest,
        revision,
        state,
        writer_fence,
        attempts,
        dispatch_digest,
        acknowledgement_digest,
        indeterminate_reason_digest,
        terminal_digest,
    })
}

fn decode_outbox(row: SqliteRow) -> Result<OutboxRow, OperationError> {
    let state: String = row.try_get("state").map_err(storage)?;
    let payload: Vec<u8> = row.try_get("payload").map_err(storage)?;
    if payload.is_empty() || payload.len() > MAX_DURABLE_PAYLOAD_BYTES {
        return Err(OperationError::Corrupt("invalid stored outbox payload size".into()));
    }
    let payload_digest = stored_digest(&row, "payload_digest")?;
    if Digest32::of_bytes(&payload) != payload_digest {
        return Err(OperationError::Corrupt("stored outbox payload digest mismatch".into()));
    }
    if !matches!(
        state.as_str(),
        "queued"
            | "leased"
            | "dispatched"
            | "indeterminate"
            | "applied"
            | "not_applied"
            | "quarantined"
    ) {
        return Err(OperationError::Corrupt("invalid stored outbox state".into()));
    }
    let fence: i64 = row.try_get("fence").map_err(storage)?;
    let attempts: i64 = row.try_get("attempts").map_err(storage)?;
    let available_at_ms: i64 = row.try_get("available_at_ms").map_err(storage)?;
    let updated_at_ms: i64 = row.try_get("updated_at_ms").map_err(storage)?;
    if fence < 0
        || !(0..=MAX_DURABLE_OUTBOX_ATTEMPTS).contains(&attempts)
        || available_at_ms < 0
        || updated_at_ms < 0
    {
        return Err(OperationError::Corrupt("invalid stored outbox counters".into()));
    }
    let acknowledgement = optional_digest(&row, "acknowledgement_digest")?;
    if acknowledgement.is_some_and(Digest32::is_zero) {
        return Err(OperationError::Corrupt("zero stored acknowledgement".into()));
    }
    Ok(OutboxRow {
        state,
        payload,
        fence,
        attempts,
        worker_id: row.try_get("worker_id").map_err(storage)?,
        lease_until_ms: row.try_get("lease_until_ms").map_err(storage)?,
        available_at_ms,
        updated_at_ms,
    })
}

async fn terminalize_without_effect(
    tx: &mut Transaction<'_, Sqlite>,
    record: &DurableOperationRecord,
    outbox: &OutboxRow,
    reason_digest: Digest32,
    now: i64,
) -> Result<(), OperationError> {
    let revision = next_revision(record.revision, &record.intent.operation_id)?;
    let fence = outbox
        .fence
        .checked_add(1)
        .ok_or(OperationError::StaleLease)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'quarantined', writer_fence = ?,
            terminal_digest = ?, revision = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE operation_id = ?",
    )
    .bind(fence)
    .bind(reason_digest.as_array().as_slice())
    .bind(revision.get().to_be_bytes().as_slice())
    .bind(now)
    .bind(now)
    .bind(record.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'quarantined', fence = ?, worker_id = NULL,
            lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ? WHERE operation_id = ?",
    )
    .bind(fence)
    .bind(now)
    .bind(now)
    .bind(record.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn maintain_terminal_outbox(
    tx: &mut Transaction<'_, Sqlite>,
    now: i64,
) -> Result<u64, OperationError> {
    let age_cutoff = now.saturating_sub(TERMINAL_OUTBOX_RETENTION_MS);
    let old = sqlx::query(
        "DELETE FROM cross_owner_outbox
         WHERE state IN ('applied','not_applied','quarantined') AND terminal_at_ms <= ?",
    )
    .bind(age_cutoff)
    .execute(&mut **tx)
    .await
    .map_err(storage)?
    .rows_affected();
    let overflow = sqlx::query(
        "DELETE FROM cross_owner_outbox WHERE operation_id IN (
            SELECT operation_id FROM cross_owner_outbox
            WHERE state IN ('applied','not_applied','quarantined')
            ORDER BY terminal_at_ms DESC, operation_id DESC LIMIT -1 OFFSET ?
         )",
    )
    .bind(TERMINAL_OUTBOX_RETAINED_ROWS)
    .execute(&mut **tx)
    .await
    .map_err(storage)?
    .rows_affected();
    Ok(old.saturating_add(overflow))
}

async fn verify_quick_check(pool: &SqlitePool) -> Result<(), OperationError> {
    let check: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(pool)
        .await
        .map_err(storage)?;
    if check != "ok" {
        return Err(OperationError::Corrupt(format!("SQLite quick_check failed: {check}")));
    }
    if sqlx::query("PRAGMA foreign_key_check")
        .fetch_optional(pool)
        .await
        .map_err(storage)?
        .is_some()
    {
        return Err(OperationError::Corrupt("SQLite foreign_key_check failed".into()));
    }
    Ok(())
}

async fn verify_schema(pool: &SqlitePool) -> Result<(), OperationError> {
    for name in [
        "operation_ledger",
        "cross_owner_outbox",
        "operation_ledger_identity_immutable",
        "operation_ledger_active_no_delete",
        "cross_owner_outbox_identity_immutable",
        "cross_owner_outbox_active_no_delete",
    ] {
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE name = ?")
            .bind(name)
            .fetch_one(pool)
            .await
            .map_err(storage)?;
        if count != 1 {
            return Err(OperationError::Corrupt(format!(
                "missing operations schema object: {name}"
            )));
        }
    }
    verify_relational_invariants(pool).await?;
    verify_quick_check(pool).await
}

async fn verify_relational_invariants(pool: &SqlitePool) -> Result<(), OperationError> {
    let missing_active_outbox: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_ledger AS ledger
         LEFT JOIN cross_owner_outbox AS outbox
           ON outbox.operation_id = ledger.operation_id
         WHERE ledger.state NOT IN ('applied','not_applied','quarantined')
           AND outbox.operation_id IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(storage)?;
    if missing_active_outbox != 0 {
        return Err(OperationError::Corrupt(
            "active operation ledger row is missing its outbox".into(),
        ));
    }

    let mismatched_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_ledger AS ledger
         JOIN cross_owner_outbox AS outbox
           ON outbox.operation_id = ledger.operation_id
         WHERE ledger.destination IS NOT outbox.destination
            OR ledger.semantic_digest IS NOT outbox.semantic_digest
            OR ledger.payload_digest IS NOT outbox.payload_digest
            OR ledger.writer_fence != outbox.fence
            OR ledger.attempts != outbox.attempts
            OR (ledger.state = 'pending' AND outbox.state NOT IN ('queued','leased'))
            OR (ledger.state != 'pending' AND ledger.state != outbox.state)",
    )
    .fetch_one(pool)
    .await
    .map_err(storage)?;
    if mismatched_rows != 0 {
        return Err(OperationError::Corrupt(
            "operation ledger/outbox relational invariant mismatch".into(),
        ));
    }
    Ok(())
}

fn stored_id(row: &SqliteRow, column: &str) -> Result<StableId, OperationError> {
    StableId::new(row.try_get::<String, _>(column).map_err(storage)?)
        .map_err(|_| OperationError::Corrupt(format!("invalid stored {column}")))
}

fn stored_digest(row: &SqliteRow, column: &str) -> Result<Digest32, OperationError> {
    let digest = Digest32::from_array(blob(row, column)?);
    if digest.is_zero() {
        return Err(OperationError::Corrupt(format!("zero stored {column}")));
    }
    Ok(digest)
}

fn optional_digest(row: &SqliteRow, column: &str) -> Result<Option<Digest32>, OperationError> {
    let bytes: Option<Vec<u8>> = row.try_get(column).map_err(storage)?;
    bytes
        .map(|value| {
            let array: [u8; 32] = value
                .try_into()
                .map_err(|_| OperationError::Corrupt(format!("invalid stored {column} width")))?;
            let digest = Digest32::from_array(array);
            if digest.is_zero() {
                return Err(OperationError::Corrupt(format!("zero stored {column}")));
            }
            Ok(digest)
        })
        .transpose()
}

fn stored_generation(row: &SqliteRow, column: &str) -> Result<Generation, OperationError> {
    Generation::new(u64::from_be_bytes(blob(row, column)?))
        .map_err(|_| OperationError::Corrupt(format!("invalid stored {column}")))
}

fn blob<const N: usize>(row: &SqliteRow, column: &str) -> Result<[u8; N], OperationError> {
    row.try_get::<Vec<u8>, _>(column)
        .map_err(storage)?
        .try_into()
        .map_err(|_| OperationError::Corrupt(format!("invalid stored {column} width")))
}

fn append_text(bytes: &mut Vec<u8>, value: &StableId) {
    let value = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn next_revision(revision: Revision, operation_id: &StableId) -> Result<Revision, OperationError> {
    revision
        .next()
        .map_err(|_| OperationError::Conflict(operation_id.clone()))
}

fn terminal_state(outcome: ReconciliationOutcome) -> DurableOperationState {
    match outcome {
        ReconciliationOutcome::Applied => DurableOperationState::Applied,
        ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
        ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
    }
}

fn attempt_budget_digest(operation_id: &StableId) -> Digest32 {
    let mut bytes = b"hepta.kernel.operations.attempt-budget.v1\0".to_vec();
    append_text(&mut bytes, operation_id);
    Digest32::of_bytes(&bytes)
}

fn handoff_reason_digest(
    operation_id: &StableId,
    old_generation: Generation,
    new_generation: Generation,
    new_authority_epoch: Generation,
) -> Digest32 {
    let mut bytes = b"hepta.kernel.operations.handoff-indeterminate.v1\0".to_vec();
    append_text(&mut bytes, operation_id);
    bytes.extend_from_slice(&old_generation.get().to_be_bytes());
    bytes.extend_from_slice(&new_generation.get().to_be_bytes());
    bytes.extend_from_slice(&new_authority_epoch.get().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn now_millis() -> Result<i64, OperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OperationError::Unavailable)?
        .as_millis();
    i64::try_from(millis).map_err(|_| OperationError::Unavailable)
}

fn storage(error: sqlx::Error) -> OperationError {
    OperationError::Storage(error.to_string())
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
