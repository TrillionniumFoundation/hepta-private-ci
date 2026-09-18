use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::DestinationApplyReceipt;
use crate::DispatchClaim;
use crate::DispatchEffect;
use crate::DurableOperationError;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOutboxState;
use crate::MAX_DURABLE_CLAIM_BATCH;
use crate::MAX_DURABLE_LEASE_MS;
use crate::MAX_DURABLE_OUTBOX_ATTEMPTS;
use crate::MAX_DURABLE_PENDING_OPERATIONS;
use crate::OperationBacklogMetrics;
use crate::OperationIntentV1;
use crate::OutboxStatusV1;
use crate::PrepareDisposition;
use crate::PreparedIntent;
use crate::ReconciliationOutcome;
use crate::ReconciliationReceiptV1;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

const OPERATION_SELECT: &str = r#"
SELECT scope_id, operation_id, semantic_digest, predecessor_operation_id,
       destination, payload_digest, owner_generation, revision, writer_fence,
       state, authority_epoch, authority_digest, dispatch_digest,
       indeterminate_digest, terminal_outcome, terminal_evidence_digest,
       terminal_observer_id, terminal_observer_generation,
       created_at_ms, updated_at_ms, terminal_at_ms
FROM operation_ledger
WHERE scope_id = ? AND operation_id = ?
"#;

const OUTBOX_SELECT: &str = r#"
SELECT destination, scope_id, operation_id, payload_digest, state, fence,
       attempts, worker_id, owner_generation, lease_until_ms,
       next_eligible_at_ms, acknowledgement_digest,
       created_at_ms, updated_at_ms, terminal_at_ms
FROM cross_owner_outbox
WHERE destination = ? AND scope_id = ? AND operation_id = ?
"#;

const RECOVERY_UNKNOWN_DIGEST_DOMAIN: &[u8] =
    b"hepta.kernel.operations.recovery-unknown-effect.v1\0";
const AUTHORITY_REJECTED_DIGEST_DOMAIN: &[u8] =
    b"hepta.kernel.operations.final-use-rejected-before-effect.v1\0";
const ACK_LOST_DIGEST_DOMAIN: &[u8] = b"hepta.kernel.operations.ack-lost.v1\0";

#[derive(Clone)]
pub struct DurableOperationStore {
    pub(crate) pool: SqlitePool,
    path: PathBuf,
}

impl DurableOperationStore {
    pub async fn open(path: &Path) -> Result<Self, DurableOperationError> {
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
        if let Err(error) = verify_quick_check(&pool).await {
            pool.close().await;
            return Err(error);
        }
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(DurableOperationError::Corrupt(format!(
                "migration failed: {error}"
            )));
        }
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        let store = Self {
            pool,
            path: path.to_path_buf(),
        };
        store.recover_expired_leases().await?;
        Ok(store)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    /// Atomically creates the operation ledger row and its source-side outbox.
    pub async fn prepare_intent(
        &self,
        intent: &OperationIntentV1,
    ) -> Result<PreparedIntent, DurableOperationError> {
        intent.validate()?;
        if intent.expected_predecessor.as_ref() == Some(&intent.operation_id) {
            return Err(DurableOperationError::Invalid("self predecessor"));
        }
        let semantic_digest = intent.semantic_digest();
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        ensure_clock_not_behind(&mut tx, now).await?;
        if tombstone_exists(&mut tx, intent, semantic_digest).await? {
            return Err(DurableOperationError::Retired(intent.operation_id.clone()));
        }
        if let Some(existing) = load_operation_tx(&mut tx, &intent.scope_id, &intent.operation_id).await?
        {
            if existing.semantic_digest != semantic_digest {
                return Err(DurableOperationError::Conflict(intent.operation_id.clone()));
            }
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(PreparedIntent {
                disposition: PrepareDisposition::AlreadyPresent,
                record: existing,
            });
        }
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_ledger WHERE terminal_at_ms IS NULL",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if active >= MAX_DURABLE_PENDING_OPERATIONS {
            return Err(DurableOperationError::Capacity);
        }
        if let Some(predecessor) = intent.expected_predecessor.as_ref() {
            let exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM operation_ledger WHERE scope_id = ? AND operation_id = ?
                 UNION SELECT 1 FROM operation_tombstones WHERE scope_id = ? AND operation_id = ?)",
            )
            .bind(intent.scope_id.as_str())
            .bind(predecessor.as_str())
            .bind(intent.scope_id.as_str())
            .bind(predecessor.as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(sqlx_error)?;
            if !exists {
                return Err(DurableOperationError::Missing(predecessor.clone()));
            }
        }
        sqlx::query(
            "INSERT INTO operation_ledger (
                scope_id, operation_id, semantic_digest, predecessor_operation_id,
                destination, payload_digest, owner_generation, revision, writer_fence,
                state, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, 'prepared', ?, ?)",
        )
        .bind(intent.scope_id.as_str())
        .bind(intent.operation_id.as_str())
        .bind(semantic_digest.as_array().as_slice())
        .bind(intent.expected_predecessor.as_ref().map(StableId::as_str))
        .bind(intent.destination.as_str())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(encode_u64(intent.owner_generation.get()))
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "INSERT INTO cross_owner_outbox (
                destination, scope_id, operation_id, payload_digest, state, fence,
                attempts, owner_generation, next_eligible_at_ms, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?, ?)",
        )
        .bind(intent.destination.as_str())
        .bind(intent.scope_id.as_str())
        .bind(intent.operation_id.as_str())
        .bind(intent.payload_digest.as_array().as_slice())
        .bind(encode_u64(intent.owner_generation.get()))
        .bind(now)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let record = load_operation_tx(&mut tx, &intent.scope_id, &intent.operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(intent.operation_id.clone()))?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(PreparedIntent {
            disposition: PrepareDisposition::Inserted,
            record,
        })
    }

    pub async fn operation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DurableOperationRecord>, DurableOperationError> {
        let row = sqlx::query(OPERATION_SELECT)
            .bind(scope_id.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(sqlx_error)?;
        row.map(|row| decode_operation(&row)).transpose()
    }

    pub async fn outbox_status(
        &self,
        destination: &StableId,
        scope_id: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<OutboxStatusV1>, DurableOperationError> {
        let row = sqlx::query(OUTBOX_SELECT)
            .bind(destination.as_str())
            .bind(scope_id.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(sqlx_error)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let operation = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        Ok(Some(decode_outbox(&row, operation.intent)?))
    }

    /// Claim one ready source-side outbox row. Expired leases are recovered
    /// first. A higher generation may take over; a lower generation is fenced.
    pub async fn claim_next(
        &self,
        destination: &StableId,
        worker_id: &StableId,
        owner_generation: Generation,
        lease: Duration,
    ) -> Result<Option<DispatchClaim>, DurableOperationError> {
        let lease_ms = validate_lease(lease)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        ensure_clock_not_behind(&mut tx, now).await?;
        recover_expired_leases_tx(&mut tx, now).await?;
        let candidate = sqlx::query(
            "SELECT o.scope_id, o.operation_id, o.owner_generation, o.fence, o.attempts
             FROM cross_owner_outbox o
             JOIN operation_ledger l ON l.scope_id = o.scope_id AND l.operation_id = o.operation_id
             WHERE o.destination = ? AND o.state = 'queued' AND o.next_eligible_at_ms <= ?
               AND l.state = 'prepared'
             ORDER BY o.next_eligible_at_ms, o.operation_id LIMIT 1",
        )
        .bind(destination.as_str())
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let Some(candidate) = candidate else {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(None);
        };
        let scope = parse_id(candidate.try_get("scope_id").map_err(sqlx_error)?)?;
        let operation_id = parse_id(candidate.try_get("operation_id").map_err(sqlx_error)?)?;
        let current_generation = decode_generation(
            candidate
                .try_get::<Vec<u8>, _>("owner_generation")
                .map_err(sqlx_error)?,
        )?;
        if owner_generation.get() < current_generation.get() {
            return Err(DurableOperationError::StaleGeneration);
        }
        let attempts = to_u32(candidate.try_get::<i64, _>("attempts").map_err(sqlx_error)?)?;
        if attempts >= MAX_DURABLE_OUTBOX_ATTEMPTS {
            quarantine_attempt_limit_tx(&mut tx, destination, &scope, &operation_id, now).await?;
            tx.commit().await.map_err(sqlx_error)?;
            return Err(DurableOperationError::Capacity);
        }
        let fence = to_u64(candidate.try_get::<i64, _>("fence").map_err(sqlx_error)?)?
            .checked_add(1)
            .ok_or(DurableOperationError::Capacity)?;
        let next_attempts = attempts + 1;
        let lease_until = now
            .checked_add(i64::try_from(lease_ms).map_err(|_| DurableOperationError::Capacity)?)
            .ok_or(DurableOperationError::Capacity)?;
        let operation = load_operation_tx(&mut tx, &scope, &operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let revision = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, attempts = ?,
             worker_id = ?, owner_generation = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(i64::from(next_attempts))
        .bind(worker_id.as_str())
        .bind(encode_u64(owner_generation.get()))
        .bind(lease_until)
        .bind(now)
        .bind(destination.as_str())
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "UPDATE operation_ledger SET owner_generation = ?, writer_fence = ?, revision = ?,
             updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(encode_u64(owner_generation.get()))
        .bind(to_i64(fence)?)
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let operation = load_operation_tx(&mut tx, &scope, &operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(Some(DispatchClaim {
            intent: operation.intent,
            worker_id: worker_id.clone(),
            owner_generation,
            fence,
            attempts: next_attempts,
            expires_at_unix_ms: to_u64(lease_until)?,
        }))
    }

    pub async fn renew_claim(
        &self,
        claim: &DispatchClaim,
        lease: Duration,
    ) -> Result<DispatchClaim, DurableOperationError> {
        let lease_ms = validate_lease(lease)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        let status = require_current_lease(&mut tx, claim, now).await?;
        let fence = status.fence.checked_add(1).ok_or(DurableOperationError::Capacity)?;
        let lease_until = now
            .checked_add(i64::try_from(lease_ms).map_err(|_| DurableOperationError::Capacity)?)
            .ok_or(DurableOperationError::Capacity)?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        let revision = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET fence = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(lease_until)
        .bind(now)
        .bind(claim.intent.destination.as_str())
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "UPDATE operation_ledger SET writer_fence = ?, revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(DispatchClaim {
            intent: claim.intent.clone(),
            worker_id: claim.worker_id.clone(),
            owner_generation: claim.owner_generation,
            fence,
            attempts: claim.attempts,
            expires_at_unix_ms: to_u64(lease_until)?,
        })
    }

    /// Consume a real final-use grant and durably enter `dispatching` before the
    /// effect boundary. If the process dies after this commit, recovery becomes
    /// indeterminate and never blindly requeues the effect.
    pub async fn authorize_dispatch(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        claim: &DispatchClaim,
    ) -> Result<AuthorizedDispatch, DurableOperationError> {
        let binding = claim.intent.final_use_binding();
        let signing_bytes = signed.grant.signing_bytes()?;
        let authority_digest = Digest32::of_bytes(&signing_bytes);
        let token = authority.claim(signed, &binding)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        require_current_lease(&mut tx, claim, now).await?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.state != DurableOperationState::Prepared {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "dispatching",
            });
        }
        let revision = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatching', authority_epoch = ?,
             authority_digest = ?, writer_fence = ?, revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(encode_u64(signed.grant.authority_epoch))
        .bind(authority_digest.as_array().as_slice())
        .bind(to_i64(claim.fence)?)
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(AuthorizedDispatch {
            authority: authority.clone(),
            binding,
            claim: claim.clone(),
            token: Some(token),
        })
    }

    /// Execute one synchronous adapter entry under the live final-use token and
    /// persist its classified outcome. Async adapters should make their actual
    /// side-effect entry synchronous (for example enqueue to an owner runtime)
    /// and reconcile any later uncertainty through `observe_terminal`.
    pub async fn execute_authorized<T>(
        &self,
        authorized: AuthorizedDispatch,
        effect: impl FnOnce(&OperationIntentV1) -> DispatchEffect<T>,
    ) -> Result<T, DurableOperationError> {
        let claim = authorized.claim.clone();
        let observation = match authorized.enter(effect) {
            Ok(observation) => observation,
            Err(error) => {
                self.release_not_dispatched(
                    &claim,
                    Digest32::of_bytes(AUTHORITY_REJECTED_DIGEST_DOMAIN),
                    Duration::ZERO,
                )
                .await?;
                return Err(error);
            }
        };
        match observation {
            DispatchEffect::Dispatched {
                value,
                dispatch_digest,
                acknowledgement_digest,
            } => {
                if dispatch_digest.is_zero()
                    || acknowledgement_digest.is_some_and(Digest32::is_zero)
                {
                    self.mark_indeterminate(
                        &claim,
                        Digest32::of_bytes(ACK_LOST_DIGEST_DOMAIN),
                    )
                    .await?;
                    return Err(DurableOperationError::Invalid("dispatch evidence digest"));
                }
                self.record_dispatch(&claim, dispatch_digest).await?;
                match acknowledgement_digest {
                    Some(acknowledgement) => {
                        self.acknowledge_outbox(&claim, acknowledgement).await?;
                    }
                    None => {
                        self.mark_indeterminate(
                            &claim,
                            Digest32::of_bytes(ACK_LOST_DIGEST_DOMAIN),
                        )
                        .await?;
                    }
                }
                Ok(value)
            }
            DispatchEffect::NotDispatched {
                value,
                reason_digest,
                retry_after,
            } => {
                self.release_not_dispatched(&claim, reason_digest, retry_after)
                    .await?;
                Ok(value)
            }
            DispatchEffect::Indeterminate {
                value,
                reason_digest,
            } => {
                self.mark_indeterminate(&claim, reason_digest).await?;
                Ok(value)
            }
        }
    }

    pub async fn record_dispatch(
        &self,
        claim: &DispatchClaim,
        dispatch_digest: Digest32,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        if dispatch_digest.is_zero() {
            return Err(DurableOperationError::Invalid("dispatch digest"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        require_current_lease(&mut tx, claim, now).await?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.state == DurableOperationState::Dispatched
            && operation.dispatch_digest == Some(dispatch_digest)
        {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(operation);
        }
        if operation.state != DurableOperationState::Dispatching {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "dispatched",
            });
        }
        let revision = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatched', dispatch_digest = ?,
             revision = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(dispatch_digest.as_array().as_slice())
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(operation)
    }

    pub async fn acknowledge_outbox(
        &self,
        claim: &DispatchClaim,
        acknowledgement_digest: Digest32,
    ) -> Result<(), DurableOperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(DurableOperationError::Invalid("acknowledgement digest"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        let status = load_outbox_tx(
            &mut tx,
            &claim.intent.destination,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if status.state == DurableOutboxState::Acknowledged {
            if status.acknowledgement_digest == Some(acknowledgement_digest) {
                tx.commit().await.map_err(sqlx_error)?;
                return Ok(());
            }
            return Err(DurableOperationError::Conflict(claim.intent.operation_id.clone()));
        }
        require_current_lease(&mut tx, claim, now).await?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.state != DurableOperationState::Dispatched {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "outbox_acknowledged",
            });
        }
        let fence = status.fence.checked_add(1).ok_or(DurableOperationError::Capacity)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
             lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(acknowledgement_digest.as_array().as_slice())
        .bind(now)
        .bind(now)
        .bind(claim.intent.destination.as_str())
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(())
    }

    pub async fn mark_indeterminate(
        &self,
        claim: &DispatchClaim,
        reason_digest: Digest32,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::Invalid("indeterminate digest"));
        }
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.state == DurableOperationState::Indeterminate
            && operation.indeterminate_digest == Some(reason_digest)
        {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(operation);
        }
        require_current_lease(&mut tx, claim, now).await?;
        if !matches!(
            operation.state,
            DurableOperationState::Dispatching | DurableOperationState::Dispatched
        ) {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "indeterminate",
            });
        }
        let revision = next_revision(operation.revision)?;
        let status = load_outbox_tx(
            &mut tx,
            &claim.intent.destination,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        let fence = status.fence.checked_add(1).ok_or(DurableOperationError::Capacity)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
             revision = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(reason_digest.as_array().as_slice())
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = ?, worker_id = NULL,
             lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(now)
        .bind(now)
        .bind(claim.intent.destination.as_str())
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(operation)
    }

    pub async fn release_not_dispatched(
        &self,
        claim: &DispatchClaim,
        reason_digest: Digest32,
        retry_after: Duration,
    ) -> Result<(), DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(DurableOperationError::Invalid("not-dispatched reason digest"));
        }
        let retry_ms = u64::try_from(retry_after.as_millis())
            .map_err(|_| DurableOperationError::Invalid("retry duration"))?;
        if retry_ms > MAX_DURABLE_LEASE_MS {
            return Err(DurableOperationError::Invalid("retry duration"));
        }
        let now = now_millis()?;
        let next_eligible = now
            .checked_add(i64::try_from(retry_ms).map_err(|_| DurableOperationError::Capacity)?)
            .ok_or(DurableOperationError::Capacity)?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        require_current_lease(&mut tx, claim, now).await?;
        let operation = load_operation_tx(
            &mut tx,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.state != DurableOperationState::Dispatching {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "prepared",
            });
        }
        let revision = next_revision(operation.revision)?;
        let status = load_outbox_tx(
            &mut tx,
            &claim.intent.destination,
            &claim.intent.scope_id,
            &claim.intent.operation_id,
        )
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        let fence = status.fence.checked_add(1).ok_or(DurableOperationError::Capacity)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = 'prepared', authority_epoch = NULL,
             authority_digest = NULL, dispatch_digest = NULL, indeterminate_digest = NULL,
             revision = ?, writer_fence = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(revision)?)
        .bind(to_i64(fence)?)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'queued', fence = ?, worker_id = NULL,
             lease_until_ms = NULL, next_eligible_at_ms = ?, updated_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(to_i64(fence)?)
        .bind(next_eligible)
        .bind(now)
        .bind(claim.intent.destination.as_str())
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(())
    }

    /// Settle a dispatched or unknown operation only from independently supplied
    /// terminal evidence under the current owner generation.
    pub async fn observe_terminal(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        receipt: &ReconciliationReceiptV1,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        receipt.validate()?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if operation.intent.owner_generation != receipt.observer_generation {
            return Err(DurableOperationError::StaleGeneration);
        }
        if operation.state.is_terminal() {
            if operation.terminal_outcome == Some(receipt.outcome)
                && operation.terminal_evidence_digest == Some(receipt.evidence_digest)
                && operation.terminal_observer_id.as_ref() == Some(&receipt.observer_id)
                && operation.terminal_observer_generation == Some(receipt.observer_generation)
            {
                tx.commit().await.map_err(sqlx_error)?;
                return Ok(operation);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatching
                | DurableOperationState::Dispatched
                | DurableOperationState::Indeterminate
        ) {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "terminal_observation",
            });
        }
        let state = match receipt.outcome {
            ReconciliationOutcome::Applied => DurableOperationState::Applied,
            ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
            ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
        };
        let revision = next_revision(operation.revision)?;
        sqlx::query(
            "UPDATE operation_ledger SET state = ?, terminal_outcome = ?,
             terminal_evidence_digest = ?, terminal_observer_id = ?,
             terminal_observer_generation = ?, revision = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(state.as_str())
        .bind(state.as_str())
        .bind(receipt.evidence_digest.as_array().as_slice())
        .bind(receipt.observer_id.as_str())
        .bind(encode_u64(receipt.observer_generation.get()))
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(now)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
        {
            if status.state != DurableOutboxState::Acknowledged {
                let fence = status.fence.checked_add(1).ok_or(DurableOperationError::Capacity)?;
                sqlx::query(
                    "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                     lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                     terminal_at_ms = COALESCE(terminal_at_ms, ?)
                     WHERE destination = ? AND scope_id = ? AND operation_id = ?",
                )
                .bind(to_i64(fence)?)
                .bind(receipt.evidence_digest.as_array().as_slice())
                .bind(now)
                .bind(now)
                .bind(operation.intent.destination.as_str())
                .bind(scope_id.as_str())
                .bind(operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
            }
        }
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(operation)
    }

    pub async fn unsettled_operations(
        &self,
        destination: &StableId,
        limit: u32,
    ) -> Result<Vec<DurableOperationRecord>, DurableOperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(DurableOperationError::Invalid("unsettled limit"));
        }
        let rows = sqlx::query(
            "SELECT scope_id, operation_id FROM operation_ledger
             WHERE destination = ? AND state IN ('dispatching', 'dispatched', 'indeterminate')
             ORDER BY updated_at_ms, operation_id LIMIT ?",
        )
        .bind(destination.as_str())
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let mut result = Vec::with_capacity(rows.len());
        for row in rows {
            let scope = parse_id(row.try_get("scope_id").map_err(sqlx_error)?)?;
            let operation_id = parse_id(row.try_get("operation_id").map_err(sqlx_error)?)?;
            let operation = self
                .operation(&scope, &operation_id)
                .await?
                .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
            result.push(operation);
        }
        Ok(result)
    }

    pub async fn backlog_metrics(&self) -> Result<OperationBacklogMetrics, DurableOperationError> {
        let now = now_millis()?;
        let active_operations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_ledger WHERE terminal_at_ms IS NULL",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let terminal_operations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_ledger WHERE terminal_at_ms IS NOT NULL",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let indeterminate_operations: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM operation_ledger WHERE state = 'indeterminate'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let queued_outbox = count_outbox(&self.pool, "queued").await?;
        let leased_outbox = count_outbox(&self.pool, "leased").await?;
        let acknowledged_outbox = count_outbox(&self.pool, "acked").await?;
        let oldest: Option<i64> = sqlx::query_scalar(
            "SELECT MIN(created_at_ms) FROM cross_owner_outbox WHERE state IN ('queued', 'leased')",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)?;
        Ok(OperationBacklogMetrics {
            active_operations: to_u64(active_operations)?,
            queued_outbox: to_u64(queued_outbox)?,
            leased_outbox: to_u64(leased_outbox)?,
            acknowledged_outbox: to_u64(acknowledged_outbox)?,
            indeterminate_operations: to_u64(indeterminate_operations)?,
            terminal_operations: to_u64(terminal_operations)?,
            oldest_active_outbox_age_ms: oldest
                .map(|created| to_u64(now.saturating_sub(created)))
                .transpose()?
                .unwrap_or(0),
        })
    }

    /// Compact settled source rows while retaining a permanent semantic
    /// tombstone so backup restore or identity reuse cannot resurrect an effect.
    pub async fn prune_terminal(
        &self,
        terminal_before_unix_ms: u64,
        limit: u32,
    ) -> Result<u32, DurableOperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(DurableOperationError::Invalid("prune limit"));
        }
        let before = to_i64(terminal_before_unix_ms)?;
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        let rows = sqlx::query(
            "SELECT l.scope_id, l.operation_id, l.semantic_digest, l.destination,
                    l.payload_digest, l.terminal_outcome, l.terminal_evidence_digest
             FROM operation_ledger l
             JOIN cross_owner_outbox o ON o.scope_id = l.scope_id AND o.operation_id = l.operation_id
             WHERE l.terminal_at_ms IS NOT NULL AND l.terminal_at_ms <= ?
               AND o.state IN ('acked', 'indeterminate', 'quarantined')
             ORDER BY l.terminal_at_ms, l.operation_id LIMIT ?",
        )
        .bind(before)
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        for row in &rows {
            let scope: String = row.try_get("scope_id").map_err(sqlx_error)?;
            let operation_id: String = row.try_get("operation_id").map_err(sqlx_error)?;
            let semantic: Vec<u8> = row.try_get("semantic_digest").map_err(sqlx_error)?;
            let destination: String = row.try_get("destination").map_err(sqlx_error)?;
            let payload: Vec<u8> = row.try_get("payload_digest").map_err(sqlx_error)?;
            let outcome: String = row.try_get("terminal_outcome").map_err(sqlx_error)?;
            let evidence: Vec<u8> = row.try_get("terminal_evidence_digest").map_err(sqlx_error)?;
            sqlx::query(
                "INSERT INTO operation_tombstones (
                    scope_id, operation_id, semantic_digest, destination, payload_digest,
                    terminal_outcome, terminal_evidence_digest, retired_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            )
            .bind(&scope)
            .bind(&operation_id)
            .bind(semantic)
            .bind(destination)
            .bind(payload)
            .bind(outcome)
            .bind(evidence)
            .bind(now)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
            sqlx::query(
                "DELETE FROM cross_owner_outbox WHERE scope_id = ? AND operation_id = ?",
            )
            .bind(&scope)
            .bind(&operation_id)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
            sqlx::query("DELETE FROM operation_ledger WHERE scope_id = ? AND operation_id = ?")
                .bind(&scope)
                .bind(&operation_id)
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        }
        tx.commit().await.map_err(sqlx_error)?;
        u32::try_from(rows.len()).map_err(|_| DurableOperationError::Capacity)
    }

    /// Resolve an authoritative destination dedupe receipt as terminal applied
    /// evidence. Absence is deliberately not treated as `NotApplied` here.
    pub async fn reconcile_destination_receipt(
        &self,
        receipt: &DestinationApplyReceipt,
        observer_id: StableId,
        observer_generation: Generation,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        if receipt.outcome_digest.is_zero() {
            return Err(DurableOperationError::Invalid("destination outcome digest"));
        }
        self.observe_terminal(
            &receipt.identity.scope_id,
            &receipt.identity.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: receipt.outcome_digest,
                observer_id,
                observer_generation,
            },
        )
        .await
    }

    pub async fn recover_expired_leases(&self) -> Result<(), DurableOperationError> {
        let now = now_millis()?;
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await.map_err(sqlx_error)?;
        ensure_clock_not_behind(&mut tx, now).await?;
        recover_expired_leases_tx(&mut tx, now).await?;
        tx.commit().await.map_err(sqlx_error)
    }
}

pub struct AuthorizedDispatch {
    authority: FinalUseAuthority,
    binding: FinalUseBinding,
    claim: DispatchClaim,
    token: Option<VerifiedUseToken>,
}

impl AuthorizedDispatch {
    pub fn claim(&self) -> &DispatchClaim {
        &self.claim
    }

    pub fn binding(&self) -> &FinalUseBinding {
        &self.binding
    }

    fn enter<T>(
        mut self,
        effect: impl FnOnce(&OperationIntentV1) -> DispatchEffect<T>,
    ) -> Result<DispatchEffect<T>, DurableOperationError> {
        let token = self
            .token
            .take()
            .ok_or(DurableOperationError::Unavailable(
                "final-use token already consumed".to_owned(),
            ))?;
        self.authority
            .with_verified_use(token, &self.binding, || effect(&self.claim.intent))
            .map_err(DurableOperationError::Authority)
    }
}

async fn require_current_lease(
    tx: &mut Transaction<'_, Sqlite>,
    claim: &DispatchClaim,
    now: i64,
) -> Result<OutboxStatusV1, DurableOperationError> {
    let status = load_outbox_tx(
        tx,
        &claim.intent.destination,
        &claim.intent.scope_id,
        &claim.intent.operation_id,
    )
    .await?
    .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if status.updated_at_unix_ms > to_u64(now)? {
        return Err(DurableOperationError::ClockRollback);
    }
    if status.state != DurableOutboxState::Leased
        || status.worker_id.as_ref() != Some(&claim.worker_id)
        || status.fence != claim.fence
        || status.intent.owner_generation != claim.owner_generation
        || status
            .lease_until_unix_ms
            .is_none_or(|until| until <= to_u64(now).unwrap_or(u64::MAX))
    {
        return Err(DurableOperationError::StaleLease);
    }
    Ok(status)
}

async fn recover_expired_leases_tx(
    tx: &mut Transaction<'_, Sqlite>,
    now: i64,
) -> Result<(), DurableOperationError> {
    let unknown = Digest32::of_bytes(RECOVERY_UNKNOWN_DIGEST_DOMAIN);
    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = revision + 1, updated_at_ms = ?
         WHERE state IN ('dispatching', 'dispatched') AND EXISTS (
             SELECT 1 FROM cross_owner_outbox o
             WHERE o.scope_id = operation_ledger.scope_id
               AND o.operation_id = operation_ledger.operation_id
               AND o.state = 'leased' AND o.lease_until_ms <= ?)",
    )
    .bind(unknown.as_array().as_slice())
    .bind(now)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = fence + 1,
         worker_id = NULL, lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
         WHERE state = 'leased' AND lease_until_ms <= ? AND EXISTS (
             SELECT 1 FROM operation_ledger l
             WHERE l.scope_id = cross_owner_outbox.scope_id
               AND l.operation_id = cross_owner_outbox.operation_id
               AND l.state = 'indeterminate')",
    )
    .bind(now)
    .bind(now)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'queued', fence = fence + 1,
         worker_id = NULL, lease_until_ms = NULL, next_eligible_at_ms = ?, updated_at_ms = ?
         WHERE state = 'leased' AND lease_until_ms <= ? AND EXISTS (
             SELECT 1 FROM operation_ledger l
             WHERE l.scope_id = cross_owner_outbox.scope_id
               AND l.operation_id = cross_owner_outbox.operation_id
               AND l.state = 'prepared')",
    )
    .bind(now)
    .bind(now)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

async fn quarantine_attempt_limit_tx(
    tx: &mut Transaction<'_, Sqlite>,
    destination: &StableId,
    scope: &StableId,
    operation_id: &StableId,
    now: i64,
) -> Result<(), DurableOperationError> {
    let evidence = Digest32::of_bytes(b"hepta.kernel.operations.attempt-limit.v1\0");
    let observer = "kernel.operations:attempt-limit";
    let generation = sqlx::query_scalar::<_, Vec<u8>>(
        "SELECT owner_generation FROM operation_ledger WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(scope.as_str())
    .bind(operation_id.as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'quarantined', terminal_outcome = 'quarantined',
         terminal_evidence_digest = ?, terminal_observer_id = ?, terminal_observer_generation = ?,
         revision = revision + 1, updated_at_ms = ?, terminal_at_ms = ?
         WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(evidence.as_array().as_slice())
    .bind(observer)
    .bind(generation)
    .bind(now)
    .bind(now)
    .bind(scope.as_str())
    .bind(operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'quarantined', fence = fence + 1,
         worker_id = NULL, lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
         WHERE destination = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(now)
    .bind(now)
    .bind(destination.as_str())
    .bind(scope.as_str())
    .bind(operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

async fn tombstone_exists(
    tx: &mut Transaction<'_, Sqlite>,
    intent: &OperationIntentV1,
    semantic_digest: Digest32,
) -> Result<bool, DurableOperationError> {
    let row = sqlx::query(
        "SELECT semantic_digest FROM operation_tombstones WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(intent.scope_id.as_str())
    .bind(intent.operation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    let Some(row) = row else {
        return Ok(false);
    };
    let existing = decode_digest(row.try_get("semantic_digest").map_err(sqlx_error)?)?;
    if existing != semantic_digest {
        return Err(DurableOperationError::Conflict(intent.operation_id.clone()));
    }
    Ok(true)
}

async fn load_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    scope_id: &StableId,
    operation_id: &StableId,
) -> Result<Option<DurableOperationRecord>, DurableOperationError> {
    sqlx::query(OPERATION_SELECT)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(sqlx_error)?
        .map(|row| decode_operation(&row))
        .transpose()
}

async fn load_outbox_tx(
    tx: &mut Transaction<'_, Sqlite>,
    destination: &StableId,
    scope_id: &StableId,
    operation_id: &StableId,
) -> Result<Option<OutboxStatusV1>, DurableOperationError> {
    let row = sqlx::query(OUTBOX_SELECT)
        .bind(destination.as_str())
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(sqlx_error)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let operation = load_operation_tx(tx, scope_id, operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
    Ok(Some(decode_outbox(&row, operation.intent)?))
}

fn decode_operation(row: &sqlx::sqlite::SqliteRow) -> Result<DurableOperationRecord, DurableOperationError> {
    let scope_id = parse_id(row.try_get("scope_id").map_err(sqlx_error)?)?;
    let operation_id = parse_id(row.try_get("operation_id").map_err(sqlx_error)?)?;
    let expected_predecessor = row
        .try_get::<Option<String>, _>("predecessor_operation_id")
        .map_err(sqlx_error)?
        .map(parse_id)
        .transpose()?;
    let destination = parse_id(row.try_get("destination").map_err(sqlx_error)?)?;
    let payload_digest = decode_digest(row.try_get("payload_digest").map_err(sqlx_error)?)?;
    let owner_generation = decode_generation(row.try_get("owner_generation").map_err(sqlx_error)?)?;
    let state_text: String = row.try_get("state").map_err(sqlx_error)?;
    let terminal_outcome = row
        .try_get::<Option<String>, _>("terminal_outcome")
        .map_err(sqlx_error)?
        .map(|value| parse_outcome(&value))
        .transpose()?;
    Ok(DurableOperationRecord {
        intent: OperationIntentV1 {
            scope_id,
            operation_id,
            expected_predecessor,
            destination,
            payload_digest,
            owner_generation,
        },
        semantic_digest: decode_digest(row.try_get("semantic_digest").map_err(sqlx_error)?)?,
        revision: to_u64(row.try_get("revision").map_err(sqlx_error)?)?,
        writer_fence: to_u64(row.try_get("writer_fence").map_err(sqlx_error)?)?,
        state: DurableOperationState::parse(&state_text)?,
        authority_epoch: row
            .try_get::<Option<Vec<u8>>, _>("authority_epoch")
            .map_err(sqlx_error)?
            .map(decode_u64)
            .transpose()?,
        authority_digest: row
            .try_get::<Option<Vec<u8>>, _>("authority_digest")
            .map_err(sqlx_error)?
            .map(decode_digest)
            .transpose()?,
        dispatch_digest: row
            .try_get::<Option<Vec<u8>>, _>("dispatch_digest")
            .map_err(sqlx_error)?
            .map(decode_digest)
            .transpose()?,
        indeterminate_digest: row
            .try_get::<Option<Vec<u8>>, _>("indeterminate_digest")
            .map_err(sqlx_error)?
            .map(decode_digest)
            .transpose()?,
        terminal_outcome,
        terminal_evidence_digest: row
            .try_get::<Option<Vec<u8>>, _>("terminal_evidence_digest")
            .map_err(sqlx_error)?
            .map(decode_digest)
            .transpose()?,
        terminal_observer_id: row
            .try_get::<Option<String>, _>("terminal_observer_id")
            .map_err(sqlx_error)?
            .map(parse_id)
            .transpose()?,
        terminal_observer_generation: row
            .try_get::<Option<Vec<u8>>, _>("terminal_observer_generation")
            .map_err(sqlx_error)?
            .map(decode_generation)
            .transpose()?,
        created_at_unix_ms: to_u64(row.try_get("created_at_ms").map_err(sqlx_error)?)?,
        updated_at_unix_ms: to_u64(row.try_get("updated_at_ms").map_err(sqlx_error)?)?,
        terminal_at_unix_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(sqlx_error)?
            .map(to_u64)
            .transpose()?,
    })
}

fn decode_outbox(
    row: &sqlx::sqlite::SqliteRow,
    mut intent: OperationIntentV1,
) -> Result<OutboxStatusV1, DurableOperationError> {
    let state_text: String = row.try_get("state").map_err(sqlx_error)?;
    intent.owner_generation = decode_generation(row.try_get("owner_generation").map_err(sqlx_error)?)?;
    Ok(OutboxStatusV1 {
        intent,
        state: DurableOutboxState::parse(&state_text)?,
        fence: to_u64(row.try_get("fence").map_err(sqlx_error)?)?,
        attempts: to_u32(row.try_get("attempts").map_err(sqlx_error)?)?,
        worker_id: row
            .try_get::<Option<String>, _>("worker_id")
            .map_err(sqlx_error)?
            .map(parse_id)
            .transpose()?,
        lease_until_unix_ms: row
            .try_get::<Option<i64>, _>("lease_until_ms")
            .map_err(sqlx_error)?
            .map(to_u64)
            .transpose()?,
        next_eligible_unix_ms: to_u64(
            row.try_get("next_eligible_at_ms").map_err(sqlx_error)?,
        )?,
        acknowledgement_digest: row
            .try_get::<Option<Vec<u8>>, _>("acknowledgement_digest")
            .map_err(sqlx_error)?
            .map(decode_digest)
            .transpose()?,
        created_at_unix_ms: to_u64(row.try_get("created_at_ms").map_err(sqlx_error)?)?,
        updated_at_unix_ms: to_u64(row.try_get("updated_at_ms").map_err(sqlx_error)?)?,
        terminal_at_unix_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(sqlx_error)?
            .map(to_u64)
            .transpose()?,
    })
}

async fn verify_store(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    verify_quick_check(pool).await?;
    let rows = sqlx::query(
        "SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .map_err(sqlx_error)?;
    if rows.len() != MIGRATOR.migrations.len() {
        return Err(DurableOperationError::Corrupt(
            "migration ledger count does not match current lineage".to_owned(),
        ));
    }
    for (row, migration) in rows.iter().zip(MIGRATOR.migrations.iter()) {
        let version: i64 = row.try_get("version").map_err(sqlx_error)?;
        let description: String = row.try_get("description").map_err(sqlx_error)?;
        let success: bool = row.try_get("success").map_err(sqlx_error)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(sqlx_error)?;
        if version != migration.version
            || description != migration.description.as_ref()
            || !success
            || checksum.as_slice() != migration.checksum.as_ref()
        {
            return Err(DurableOperationError::Corrupt(format!(
                "migration ledger entry {version} differs from current lineage"
            )));
        }
    }
    for table in [
        "operation_ledger",
        "cross_owner_outbox",
        "operation_tombstones",
    ] {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name = ?",
        )
        .bind(table)
        .fetch_one(pool)
        .await
        .map_err(sqlx_error)?;
        if count != 1 {
            return Err(DurableOperationError::Corrupt(format!(
                "required table {table} is missing"
            )));
        }
    }
    let foreign_key_rows = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(sqlx_error)?;
    if !foreign_key_rows.is_empty() {
        return Err(DurableOperationError::Corrupt(
            "foreign key check failed".to_owned(),
        ));
    }
    Ok(())
}

async fn verify_quick_check(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    let rows: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_all(pool)
        .await
        .map_err(sqlx_error)?;
    if rows.as_slice() != ["ok"] {
        return Err(DurableOperationError::Corrupt(format!(
            "sqlite quick_check failed: {}",
            rows.join("; ")
        )));
    }
    Ok(())
}

async fn ensure_clock_not_behind(
    tx: &mut Transaction<'_, Sqlite>,
    now: i64,
) -> Result<(), DurableOperationError> {
    let latest: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(updated_at_ms) FROM operation_ledger WHERE terminal_at_ms IS NULL",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    if latest.is_some_and(|value| value > now) {
        return Err(DurableOperationError::ClockRollback);
    }
    Ok(())
}

async fn count_outbox(pool: &SqlitePool, state: &str) -> Result<i64, DurableOperationError> {
    sqlx::query_scalar("SELECT COUNT(*) FROM cross_owner_outbox WHERE state = ?")
        .bind(state)
        .fetch_one(pool)
        .await
        .map_err(sqlx_error)
}

fn validate_lease(lease: Duration) -> Result<u64, DurableOperationError> {
    let millis = u64::try_from(lease.as_millis())
        .map_err(|_| DurableOperationError::Invalid("lease duration"))?;
    if !(1..=MAX_DURABLE_LEASE_MS).contains(&millis) {
        return Err(DurableOperationError::Invalid("lease duration"));
    }
    Ok(millis)
}

fn next_revision(revision: u64) -> Result<u64, DurableOperationError> {
    revision.checked_add(1).ok_or(DurableOperationError::Capacity)
}

fn now_millis() -> Result<i64, DurableOperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?
        .as_millis();
    i64::try_from(millis).map_err(|_| DurableOperationError::Capacity)
}

fn encode_u64(value: u64) -> Vec<u8> {
    value.to_be_bytes().to_vec()
}

fn decode_u64(value: Vec<u8>) -> Result<u64, DurableOperationError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| DurableOperationError::Corrupt("invalid u64 width".to_owned()))?;
    Ok(u64::from_be_bytes(bytes))
}

fn decode_generation(value: Vec<u8>) -> Result<Generation, DurableOperationError> {
    Generation::new(decode_u64(value)?)
        .map_err(|error| DurableOperationError::Corrupt(error.to_string()))
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

fn parse_outcome(value: &str) -> Result<ReconciliationOutcome, DurableOperationError> {
    match value {
        "applied" => Ok(ReconciliationOutcome::Applied),
        "not_applied" => Ok(ReconciliationOutcome::NotApplied),
        "quarantined" => Ok(ReconciliationOutcome::Quarantined),
        _ => Err(DurableOperationError::Corrupt(format!(
            "unknown terminal outcome {value}"
        ))),
    }
}

fn to_u64(value: i64) -> Result<u64, DurableOperationError> {
    u64::try_from(value).map_err(|_| DurableOperationError::Corrupt("negative integer".to_owned()))
}

fn to_u32(value: i64) -> Result<u32, DurableOperationError> {
    u32::try_from(value).map_err(|_| DurableOperationError::Corrupt("invalid u32".to_owned()))
}

fn to_i64(value: u64) -> Result<i64, DurableOperationError> {
    i64::try_from(value).map_err(|_| DurableOperationError::Capacity)
}

fn sqlx_error(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
#[path = "durable_store_tests.rs"]
mod tests;
