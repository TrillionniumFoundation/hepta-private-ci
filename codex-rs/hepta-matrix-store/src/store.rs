use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::LocalApprovalDecision;
use codex_hepta_matrix_protocol::MAX_PENDING_APPROVALS;
use codex_hepta_matrix_protocol::MatrixdEvent;
use codex_hepta_matrix_protocol::MatrixdEventBatch;
use codex_hepta_matrix_protocol::MatrixdEventKind;
use codex_hepta_matrix_protocol::client_user_message_id;
use codex_hepta_matrix_protocol::room_project_idempotency_key;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::ChangeEvent;
use crate::ChangeKind;
use crate::ChangePage;
use crate::InboxAdmissionDraft;
use crate::InboxDispatchRecord;
use crate::InboxDispatchState;
use crate::InboxDisposition;
use crate::InboxDraft;
use crate::InboxQueuedDraft;
use crate::InboxRecord;
use crate::InboxState;
use crate::MatrixControlPage;
use crate::MatrixControlSnapshot;
use crate::MatrixDurableConfig;
use crate::MatrixEventId;
use crate::MatrixQueueMetrics;
use crate::MatrixRoomId;
use crate::MatrixSnapshot;
use crate::MatrixSyncCheckpoint;
use crate::MatrixSyncCommit;
use crate::MatrixTransactionId;
use crate::MatrixUserId;
use crate::OutboxDisposition;
use crate::OutboxDraft;
use crate::OutboxKind;
use crate::OutboxRecord;
use crate::OutboxState;
use crate::PendingApprovalDraft;
use crate::PendingApprovalKind;
use crate::PendingApprovalRecord;
use crate::RoomBinding;
use crate::RoomBindingDraft;
use crate::RoomThreadBinding;
use crate::RoomThreadBindingDraft;
use crate::model::MAX_PAGE_ITEMS;
use crate::model::MAX_PAYLOAD_BYTES;

#[path = "sync_observation.rs"]
mod sync_observation;
#[path = "sync_v2.rs"]
mod sync_v2;
#[path = "sync_v2_tombstone.rs"]
mod sync_v2_tombstone;

pub use sync_observation::MatrixSyncUnchangedRequestV1;
pub use sync_observation::MatrixSyncUnchangedResultV1;

const MATRIX_SCHEMA_VERSION: u32 = 1;
const MATRIX_DB_FILENAME: &str = "matrix_1.sqlite3";
const MATRIX_V2_SCHEMA_FINGERPRINT: &str =
    "53a59efa865437f08e2bc84b6b44c133b53dc7f40f485ec1dc6200876d221fd1";
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixDurableError {
    #[error("invalid Matrix durable-core request")]
    Invalid,
    #[error("Matrix durable-core owner or binding denied the request")]
    AccessDenied,
    #[error("Matrix durable-core idempotency or state conflict")]
    Conflict,
    #[error("Matrix durable-core state is corrupt")]
    Corrupt,
    #[error("Matrix durable-core storage is unavailable")]
    Unavailable,
}

#[derive(Clone)]
pub struct MatrixDurableStore {
    pool: SqlitePool,
    owner_agent_id: AgentId,
    path: PathBuf,
    pub(crate) config: MatrixDurableConfig,
}

impl MatrixDurableStore {
    pub async fn open(
        layout: &HeptaAgentLayout,
        config: MatrixDurableConfig,
    ) -> Result<Self, MatrixDurableError> {
        Self::open_root(
            layout.matrix_root().to_path_buf(),
            layout.agent_id().clone(),
            config,
        )
        .await
    }

    async fn open_root(
        root: PathBuf,
        owner_agent_id: AgentId,
        config: MatrixDurableConfig,
    ) -> Result<Self, MatrixDurableError> {
        if !config.is_valid() {
            return Err(MatrixDurableError::Invalid);
        }
        create_private_directory(&root)?;
        let path = root.join(MATRIX_DB_FILENAME);
        let sqlite_home =
            AbsolutePathBuf::try_from(root).map_err(|_| MatrixDurableError::Invalid)?;
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if MIGRATOR.run(&pool).await.is_err() {
            pool.close().await;
            return Err(MatrixDurableError::Unavailable);
        }
        protect_database_file(&path)?;
        sqlx::query(
            "INSERT INTO matrix_meta (singleton, schema_version, owner_agent_id)
             VALUES (1, ?, ?) ON CONFLICT(singleton) DO NOTHING",
        )
        .bind(i64::from(MATRIX_SCHEMA_VERSION))
        .bind(owner_agent_id.as_str())
        .execute(&pool)
        .await
        .map_err(unavailable)?;
        verify_store(&pool, &owner_agent_id).await?;
        Ok(Self {
            pool,
            owner_agent_id,
            path,
            config,
        })
    }

    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub(crate) fn sqlite_pool(&self) -> &SqlitePool {
        &self.pool
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn bind_room(
        &self,
        draft: &RoomBindingDraft,
    ) -> Result<RoomBinding, MatrixDurableError> {
        if draft.generation == 0 || draft.expected_revision == Some(0) {
            return Err(MatrixDurableError::Invalid);
        }
        let generation = to_i64(draft.generation)?;
        let changed_at_ms = to_i64(draft.changed_at_ms)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = sqlx::query(
            "SELECT room_id, owner_agent_id, agent_user_id, revision, generation, changed_at_ms
             FROM room_bindings WHERE room_id = ?",
        )
        .bind(draft.room_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .map(|row| room_binding_from_row(&row))
        .transpose()?;

        let binding = match existing {
            None => {
                if draft.expected_revision.is_some() {
                    return Err(MatrixDurableError::Conflict);
                }
                sqlx::query(
                    "INSERT INTO room_bindings (
                        room_id, owner_agent_id, agent_user_id, revision, generation, changed_at_ms
                     ) VALUES (?, ?, ?, 1, ?, ?)",
                )
                .bind(draft.room_id.as_str())
                .bind(self.owner_agent_id.as_str())
                .bind(draft.agent_user_id.as_str())
                .bind(generation)
                .bind(changed_at_ms)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                let binding = RoomBinding {
                    room_id: draft.room_id.clone(),
                    owner_agent_id: self.owner_agent_id.clone(),
                    agent_user_id: draft.agent_user_id.clone(),
                    revision: 1,
                    generation: draft.generation,
                    changed_at_ms: draft.changed_at_ms,
                };
                self.append_change(
                    &mut transaction,
                    ChangeKind::RoomBound,
                    Some(&draft.room_id),
                    /*event_id*/ None,
                    /*txn_id*/ None,
                    draft.changed_at_ms,
                )
                .await?;
                binding
            }
            Some(existing) => {
                if existing.owner_agent_id != self.owner_agent_id {
                    return Err(MatrixDurableError::AccessDenied);
                }
                if sync_v2_tombstone::is_room_replaced_tx(&mut transaction, &draft.room_id).await? {
                    return Err(MatrixDurableError::AccessDenied);
                }
                if existing.agent_user_id == draft.agent_user_id
                    && existing.generation == draft.generation
                    && (draft.expected_revision.is_none()
                        || draft.expected_revision == Some(existing.revision))
                {
                    transaction.commit().await.map_err(unavailable)?;
                    return Ok(existing);
                }
                if draft.expected_revision != Some(existing.revision)
                    || draft.generation <= existing.generation
                {
                    return Err(MatrixDurableError::Conflict);
                }
                let active_records: i64 = sqlx::query_scalar(
                    "SELECT
                        (SELECT COUNT(*) FROM matrix_visible_inbox_events_v2
                         WHERE room_id = ? AND state = 'pending'
                           AND (length(payload) > 0 OR state != 'processed'))
                      + (SELECT COUNT(*) FROM matrix_actionable_inbox_dispatches_v2
                         WHERE room_id = ? AND state IN ('begun', 'queued', 'admitted'))
                      + (SELECT COUNT(*) FROM matrix_sendable_outbox_v2
                         WHERE room_id = ?
                           AND state IN ('pending', 'in_flight', 'retry_scheduled'))",
                )
                .bind(draft.room_id.as_str())
                .bind(draft.room_id.as_str())
                .bind(draft.room_id.as_str())
                .fetch_one(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if active_records != 0 {
                    return Err(MatrixDurableError::Conflict);
                }
                let next_revision = existing
                    .revision
                    .checked_add(1)
                    .ok_or(MatrixDurableError::Invalid)?;
                let updated = sqlx::query(
                    "UPDATE room_bindings
                     SET agent_user_id = ?, revision = ?, generation = ?, changed_at_ms = ?
                     WHERE room_id = ? AND owner_agent_id = ? AND revision = ?",
                )
                .bind(draft.agent_user_id.as_str())
                .bind(to_i64(next_revision)?)
                .bind(generation)
                .bind(changed_at_ms)
                .bind(draft.room_id.as_str())
                .bind(self.owner_agent_id.as_str())
                .bind(to_i64(existing.revision)?)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if updated.rows_affected() != 1 {
                    return Err(MatrixDurableError::Conflict);
                }
                let binding = RoomBinding {
                    room_id: draft.room_id.clone(),
                    owner_agent_id: self.owner_agent_id.clone(),
                    agent_user_id: draft.agent_user_id.clone(),
                    revision: next_revision,
                    generation: draft.generation,
                    changed_at_ms: draft.changed_at_ms,
                };
                self.append_change(
                    &mut transaction,
                    ChangeKind::RoomBound,
                    Some(&draft.room_id),
                    /*event_id*/ None,
                    /*txn_id*/ None,
                    draft.changed_at_ms,
                )
                .await?;
                binding
            }
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(binding)
    }

    pub async fn room_binding(
        &self,
        room_id: &MatrixRoomId,
    ) -> Result<Option<RoomBinding>, MatrixDurableError> {
        sqlx::query(
            "SELECT room_id, owner_agent_id, agent_user_id, revision, generation, changed_at_ms
             FROM room_bindings WHERE room_id = ?",
        )
        .bind(room_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?
        .map(|row| room_binding_from_row(&row))
        .transpose()
    }

    pub async fn bind_room_thread(
        &self,
        draft: &RoomThreadBindingDraft,
    ) -> Result<RoomThreadBinding, MatrixDurableError> {
        if draft.binding_revision == 0 || draft.generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        validate_local_identity(&draft.project_id)?;
        if draft.project_id != room_project_idempotency_key(&self.owner_agent_id, &draft.room_id) {
            return Err(MatrixDurableError::Invalid);
        }
        if let Some(thread_id) = draft.thread_id.as_deref() {
            validate_local_identity(thread_id)?;
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        require_current_binding(
            &mut transaction,
            &self.owner_agent_id,
            &draft.room_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?;
        let existing = room_thread_tx(
            &mut transaction,
            &draft.room_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?;
        if let Some(thread_id) = draft.thread_id.as_deref() {
            let conflicting_thread: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM room_threads
                 WHERE thread_id = ? AND room_id != ?",
            )
            .bind(thread_id)
            .bind(draft.room_id.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if conflicting_thread != 0 {
                return Err(MatrixDurableError::Conflict);
            }
        }
        let binding = match existing {
            Some(existing) => {
                if existing.project_id != draft.project_id {
                    return Err(MatrixDurableError::Conflict);
                }
                match (&existing.thread_id, &draft.thread_id) {
                    (Some(current), Some(requested)) if current != requested => {
                        return Err(MatrixDurableError::Conflict);
                    }
                    (None, Some(thread_id)) => {
                        let updated = sqlx::query(
                            "UPDATE room_threads SET thread_id = ?, changed_at_ms = ?
                             WHERE room_id = ? AND binding_revision = ? AND generation = ?
                               AND thread_id IS NULL",
                        )
                        .bind(thread_id)
                        .bind(to_i64(draft.changed_at_ms)?)
                        .bind(draft.room_id.as_str())
                        .bind(to_i64(draft.binding_revision)?)
                        .bind(to_i64(draft.generation)?)
                        .execute(&mut *transaction)
                        .await
                        .map_err(unavailable)?;
                        if updated.rows_affected() != 1 {
                            return Err(MatrixDurableError::Conflict);
                        }
                        RoomThreadBinding {
                            thread_id: Some(thread_id.clone()),
                            changed_at_ms: draft.changed_at_ms,
                            ..existing
                        }
                    }
                    _ => {
                        transaction.commit().await.map_err(unavailable)?;
                        return Ok(existing);
                    }
                }
            }
            None => {
                sqlx::query(
                    "INSERT INTO room_threads (
                        room_id, binding_revision, generation, project_id, thread_id, changed_at_ms
                     ) VALUES (?, ?, ?, ?, ?, ?)",
                )
                .bind(draft.room_id.as_str())
                .bind(to_i64(draft.binding_revision)?)
                .bind(to_i64(draft.generation)?)
                .bind(&draft.project_id)
                .bind(draft.thread_id.as_deref())
                .bind(to_i64(draft.changed_at_ms)?)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                RoomThreadBinding {
                    room_id: draft.room_id.clone(),
                    binding_revision: draft.binding_revision,
                    generation: draft.generation,
                    project_id: draft.project_id.clone(),
                    thread_id: draft.thread_id.clone(),
                    changed_at_ms: draft.changed_at_ms,
                }
            }
        };
        self.append_change(
            &mut transaction,
            ChangeKind::RoomThreadBound,
            Some(&draft.room_id),
            /*event_id*/ None,
            /*txn_id*/ None,
            draft.changed_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(binding)
    }

    pub async fn room_thread(
        &self,
        room_id: &MatrixRoomId,
        binding_revision: u64,
        generation: u64,
    ) -> Result<Option<RoomThreadBinding>, MatrixDurableError> {
        if binding_revision == 0 || generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let binding =
            room_thread_tx(&mut transaction, room_id, binding_revision, generation).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(binding)
    }

    pub async fn ingest_inbox(
        &self,
        draft: &InboxDraft,
    ) -> Result<InboxDisposition, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let disposition = self.ingest_inbox_tx(&mut transaction, draft).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(disposition)
    }

    /// Read the only authoritative `/sync` cursor for this Agent generation.
    ///
    /// The Matrix SDK has its own state cursor, but it is never used to choose
    /// the next Hepta ingress batch because the SDK persists that cursor before
    /// invoking event handlers.
    pub async fn sync_checkpoint(
        &self,
        binding_revision: u64,
        generation: u64,
    ) -> Result<Option<MatrixSyncCheckpoint>, MatrixDurableError> {
        if binding_revision == 0 || generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let row = sqlx::query(
            "SELECT owner_agent_id, binding_revision, generation, next_batch, updated_at_ms
             FROM matrix_sync_checkpoint WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let checkpoint = sync_checkpoint_from_row(&row)?;
        if checkpoint.owner_agent_id != self.owner_agent_id
            || checkpoint.binding_revision != binding_revision
            || checkpoint.generation != generation
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        Ok(Some(checkpoint))
    }

    /// Atomically persist one normalized Matrix batch and advance `next_batch`.
    ///
    /// `expected_next_batch` is a compare-and-swap guard. A crash before this
    /// transaction commits replays the old batch; a crash after it commits
    /// observes the new checkpoint. Event-id idempotency makes either outcome
    /// exact without relying on the Matrix SDK handler ordering.
    pub async fn commit_sync_batch(
        &self,
        binding_revision: u64,
        generation: u64,
        expected_next_batch: Option<&str>,
        next_batch: &str,
        events: &[InboxDraft],
        updated_at_ms: u64,
    ) -> Result<MatrixSyncCommit, MatrixDurableError> {
        if binding_revision == 0 || generation == 0 || events.len() > self.config.event_capacity {
            return Err(MatrixDurableError::Invalid);
        }
        validate_sync_token(next_batch)?;
        if let Some(expected) = expected_next_batch {
            validate_sync_token(expected)?;
        }
        if events.iter().any(|event| {
            event.binding_revision != binding_revision || event.generation != generation
        }) {
            return Err(MatrixDurableError::AccessDenied);
        }

        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = sqlx::query(
            "SELECT owner_agent_id, binding_revision, generation, next_batch, updated_at_ms
             FROM matrix_sync_checkpoint WHERE singleton = 1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .map(|row| sync_checkpoint_from_row(&row))
        .transpose()?;
        match (&existing, expected_next_batch) {
            (None, None) => {}
            (Some(checkpoint), Some(expected))
                if checkpoint.owner_agent_id == self.owner_agent_id
                    && checkpoint.binding_revision == binding_revision
                    && checkpoint.generation == generation
                    && checkpoint.next_batch == expected => {}
            (Some(checkpoint), _)
                if checkpoint.owner_agent_id != self.owner_agent_id
                    || checkpoint.binding_revision != binding_revision
                    || checkpoint.generation != generation =>
            {
                return Err(MatrixDurableError::AccessDenied);
            }
            _ => return Err(MatrixDurableError::Conflict),
        }
        let checkpoint_updated_at_ms = existing
            .as_ref()
            .map(|checkpoint| checkpoint.updated_at_ms.max(updated_at_ms))
            .unwrap_or(updated_at_ms);

        let mut accepted = 0_usize;
        let mut duplicates = 0_usize;
        for event in events {
            match self.ingest_inbox_tx(&mut transaction, event).await? {
                InboxDisposition::Accepted(_) => accepted += 1,
                InboxDisposition::Duplicate(_) => duplicates += 1,
            }
        }

        if existing.is_some() {
            let updated = sqlx::query(
                "UPDATE matrix_sync_checkpoint
                 SET next_batch = ?, updated_at_ms = ?
                 WHERE singleton = 1 AND owner_agent_id = ?
                   AND binding_revision = ? AND generation = ? AND next_batch = ?",
            )
            .bind(next_batch)
            .bind(to_i64(checkpoint_updated_at_ms)?)
            .bind(self.owner_agent_id.as_str())
            .bind(to_i64(binding_revision)?)
            .bind(to_i64(generation)?)
            .bind(expected_next_batch.ok_or(MatrixDurableError::Conflict)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if updated.rows_affected() != 1 {
                return Err(MatrixDurableError::Conflict);
            }
        } else {
            sqlx::query(
                "INSERT INTO matrix_sync_checkpoint (
                    singleton, owner_agent_id, binding_revision, generation,
                    next_batch, updated_at_ms
                 ) VALUES (1, ?, ?, ?, ?, ?)",
            )
            .bind(self.owner_agent_id.as_str())
            .bind(to_i64(binding_revision)?)
            .bind(to_i64(generation)?)
            .bind(next_batch)
            .bind(to_i64(checkpoint_updated_at_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        }
        let checkpoint = MatrixSyncCheckpoint {
            owner_agent_id: self.owner_agent_id.clone(),
            binding_revision,
            generation,
            next_batch: next_batch.to_string(),
            updated_at_ms: checkpoint_updated_at_ms,
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixSyncCommit {
            checkpoint,
            accepted,
            duplicates,
        })
    }

    pub(crate) async fn ingest_inbox_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        draft: &InboxDraft,
    ) -> Result<InboxDisposition, MatrixDurableError> {
        validate_event_type(&draft.event_type)?;
        validate_payload(&draft.payload)?;
        if draft.binding_revision == 0 || draft.generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let v2_kind = sqlx::query_scalar::<_, String>(
            "SELECT mutation_kind FROM matrix_sync_mutations_v2 WHERE source_event_id = ?",
        )
        .bind(draft.event_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if let Some(kind) = v2_kind {
            if kind != "timeline" {
                return Err(MatrixDurableError::Conflict);
            }
            // A V2 timeline ledger row is only compatible with V1 when its
            // atomically persisted inbox identity still exists and matches.
            // In particular, a tombstoned V2 timeline has no inbox row and
            // must not let V1 reuse the globally unique event ID elsewhere.
            return match inbox_by_event_tx(transaction, &draft.event_id).await? {
                Some(existing) if inbox_matches_draft(&existing, draft) => {
                    Ok(InboxDisposition::Duplicate(existing))
                }
                Some(_) | None => Err(MatrixDurableError::Conflict),
            };
        }
        if sync_v2_tombstone::is_tombstoned_tx(
            transaction,
            &draft.room_id,
            &draft.event_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        // Duplicate classification must consult the raw identity table, not
        // the tombstone-filtered read view. A V1 row hidden by a prior leave
        // or redaction still owns its globally unique event ID. Otherwise a
        // later fence or room could reach INSERT, turn the UNIQUE violation
        // into Unavailable, and make a permanent collision look retryable.
        if let Some(existing) = raw_inbox_by_event_tx(transaction, &draft.event_id).await? {
            if inbox_matches_draft(&existing, draft) {
                return Ok(InboxDisposition::Duplicate(existing));
            }
            return Err(MatrixDurableError::Conflict);
        }
        require_current_binding(
            transaction,
            &self.owner_agent_id,
            &draft.room_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?;
        let payload_sha256 = Sha256Digest::for_bytes(&draft.payload);
        let inserted = sqlx::query(
            "INSERT INTO inbox_events (
                event_id, room_id, sender_user_id, event_type, payload, payload_sha256,
                binding_revision, generation, origin_server_ts_ms, received_at_ms,
                state, processed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)",
        )
        .bind(draft.event_id.as_str())
        .bind(draft.room_id.as_str())
        .bind(draft.sender.as_str())
        .bind(&draft.event_type)
        .bind(&draft.payload)
        .bind(payload_sha256.as_str())
        .bind(to_i64(draft.binding_revision)?)
        .bind(to_i64(draft.generation)?)
        .bind(to_i64(draft.origin_server_ts_ms)?)
        .bind(to_i64(draft.received_at_ms)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let cursor = to_u64(inserted.last_insert_rowid())?;
        self.append_change(
            transaction,
            ChangeKind::InboxAccepted,
            Some(&draft.room_id),
            Some(&draft.event_id),
            /*txn_id*/ None,
            draft.received_at_ms,
        )
        .await?;
        let record = InboxRecord {
            cursor,
            event_id: draft.event_id.clone(),
            room_id: draft.room_id.clone(),
            sender: draft.sender.clone(),
            event_type: draft.event_type.clone(),
            payload: draft.payload.clone(),
            binding_revision: draft.binding_revision,
            generation: draft.generation,
            origin_server_ts_ms: draft.origin_server_ts_ms,
            received_at_ms: draft.received_at_ms,
            state: InboxState::Pending,
            processed_at_ms: None,
        };
        Ok(InboxDisposition::Accepted(record))
    }

    pub async fn mark_inbox_processed(
        &self,
        event_id: &MatrixEventId,
        processed_at_ms: u64,
    ) -> Result<InboxRecord, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = inbox_by_event_tx(&mut transaction, event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.state == InboxState::Processed {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        if inbox_dispatch_by_event_tx(&mut transaction, event_id)
            .await?
            .is_some()
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE inbox_events SET state = 'processed', processed_at_ms = ?
             WHERE event_id = ? AND state = 'pending'",
        )
        .bind(to_i64(processed_at_ms)?)
        .bind(event_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_change(
            &mut transaction,
            ChangeKind::InboxProcessed,
            Some(&existing.room_id),
            Some(event_id),
            /*txn_id*/ None,
            processed_at_ms,
        )
        .await?;
        let record = InboxRecord {
            state: InboxState::Processed,
            processed_at_ms: Some(processed_at_ms),
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn inbox(
        &self,
        event_id: &MatrixEventId,
    ) -> Result<Option<InboxRecord>, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let inbox = inbox_by_event_tx(&mut transaction, event_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(inbox)
    }

    pub async fn begin_inbox_dispatch(
        &self,
        event_id: &MatrixEventId,
        begun_at_ms: u64,
    ) -> Result<InboxDispatchRecord, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let inbox = inbox_by_event_tx(&mut transaction, event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if inbox.state != InboxState::Pending {
            return Err(MatrixDurableError::Conflict);
        }
        let room_thread = room_thread_tx(
            &mut transaction,
            &inbox.room_id,
            inbox.binding_revision,
            inbox.generation,
        )
        .await?
        .ok_or(MatrixDurableError::Conflict)?;
        require_current_binding(
            &mut transaction,
            &self.owner_agent_id,
            &inbox.room_id,
            inbox.binding_revision,
            inbox.generation,
        )
        .await?;
        let client_user_message_id =
            client_user_message_id(&self.owner_agent_id, &inbox.room_id, event_id);
        if let Some(existing) = inbox_dispatch_by_event_tx(&mut transaction, event_id).await? {
            if existing.client_user_message_id != client_user_message_id
                || existing.room_id != inbox.room_id
                || existing.binding_revision != inbox.binding_revision
                || existing.generation != inbox.generation
                || existing.project_id != room_thread.project_id
            {
                return Err(MatrixDurableError::Corrupt);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        sqlx::query(
            "INSERT INTO inbox_dispatches (
                event_id, client_user_message_id, room_id, binding_revision, generation,
                project_id, state, thread_id, queued_submission_id, turn_id,
                begun_at_ms, updated_at_ms, completed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, 'begun', ?, NULL, NULL, ?, ?, NULL)",
        )
        .bind(event_id.as_str())
        .bind(&client_user_message_id)
        .bind(inbox.room_id.as_str())
        .bind(to_i64(inbox.binding_revision)?)
        .bind(to_i64(inbox.generation)?)
        .bind(&room_thread.project_id)
        .bind(room_thread.thread_id.as_deref())
        .bind(to_i64(begun_at_ms)?)
        .bind(to_i64(begun_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_change(
            &mut transaction,
            ChangeKind::InboxDispatchBegun,
            Some(&inbox.room_id),
            Some(event_id),
            /*txn_id*/ None,
            begun_at_ms,
        )
        .await?;
        let record = InboxDispatchRecord {
            event_id: event_id.clone(),
            client_user_message_id,
            room_id: inbox.room_id,
            binding_revision: inbox.binding_revision,
            generation: inbox.generation,
            project_id: room_thread.project_id,
            state: InboxDispatchState::Begun,
            thread_id: room_thread.thread_id,
            queued_submission_id: None,
            turn_id: None,
            begun_at_ms,
            updated_at_ms: begun_at_ms,
            completed_at_ms: None,
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_inbox_queued(
        &self,
        draft: &InboxQueuedDraft,
    ) -> Result<InboxDispatchRecord, MatrixDurableError> {
        validate_local_identity(&draft.client_user_message_id)?;
        validate_local_identity(&draft.project_id)?;
        validate_local_identity(&draft.thread_id)?;
        validate_local_identity(&draft.queued_submission_id)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = inbox_dispatch_by_event_tx(&mut transaction, &draft.event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.client_user_message_id != draft.client_user_message_id
            || existing.project_id != draft.project_id
            || draft.queued_at_ms < existing.begun_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        if existing.state != InboxDispatchState::Begun {
            if existing.thread_id.as_deref() == Some(&draft.thread_id)
                && existing.queued_submission_id.as_deref() == Some(&draft.queued_submission_id)
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(MatrixDurableError::Conflict);
        }
        require_current_binding(
            &mut transaction,
            &self.owner_agent_id,
            &existing.room_id,
            existing.binding_revision,
            existing.generation,
        )
        .await?;
        ensure_dispatch_thread_tx(
            &mut transaction,
            &existing,
            &draft.project_id,
            &draft.thread_id,
            draft.queued_at_ms,
        )
        .await?;
        let updated = sqlx::query(
            "UPDATE inbox_dispatches
             SET state = 'queued', thread_id = ?, queued_submission_id = ?, updated_at_ms = ?
             WHERE event_id = ? AND state = 'begun' AND client_user_message_id = ?",
        )
        .bind(&draft.thread_id)
        .bind(&draft.queued_submission_id)
        .bind(to_i64(draft.queued_at_ms)?)
        .bind(draft.event_id.as_str())
        .bind(&draft.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_change(
            &mut transaction,
            ChangeKind::InboxDispatchQueued,
            Some(&existing.room_id),
            Some(&draft.event_id),
            /*txn_id*/ None,
            draft.queued_at_ms,
        )
        .await?;
        let record = InboxDispatchRecord {
            state: InboxDispatchState::Queued,
            thread_id: Some(draft.thread_id.clone()),
            queued_submission_id: Some(draft.queued_submission_id.clone()),
            updated_at_ms: draft.queued_at_ms,
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_inbox_admitted(
        &self,
        draft: &InboxAdmissionDraft,
    ) -> Result<InboxDispatchRecord, MatrixDurableError> {
        validate_local_identity(&draft.client_user_message_id)?;
        validate_local_identity(&draft.project_id)?;
        validate_local_identity(&draft.thread_id)?;
        validate_local_identity(&draft.turn_id)?;
        if let Some(queued_submission_id) = draft.queued_submission_id.as_deref() {
            validate_local_identity(queued_submission_id)?;
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = inbox_dispatch_by_event_tx(&mut transaction, &draft.event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.client_user_message_id != draft.client_user_message_id
            || existing.project_id != draft.project_id
            || draft.admitted_at_ms < existing.begun_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        match existing.state {
            InboxDispatchState::Begun if draft.queued_submission_id.is_some() => {
                return Err(MatrixDurableError::Conflict);
            }
            InboxDispatchState::Queued
                if draft.queued_submission_id != existing.queued_submission_id =>
            {
                return Err(MatrixDurableError::Conflict);
            }
            InboxDispatchState::Admitted | InboxDispatchState::Completed => {
                if existing.thread_id.as_deref() == Some(&draft.thread_id)
                    && existing.queued_submission_id == draft.queued_submission_id
                    && existing.turn_id.as_deref() == Some(&draft.turn_id)
                {
                    transaction.commit().await.map_err(unavailable)?;
                    return Ok(existing);
                }
                return Err(MatrixDurableError::Conflict);
            }
            _ => {}
        }
        if draft.admitted_at_ms < existing.updated_at_ms {
            return Err(MatrixDurableError::Conflict);
        }
        require_current_binding(
            &mut transaction,
            &self.owner_agent_id,
            &existing.room_id,
            existing.binding_revision,
            existing.generation,
        )
        .await?;
        ensure_dispatch_thread_tx(
            &mut transaction,
            &existing,
            &draft.project_id,
            &draft.thread_id,
            draft.admitted_at_ms,
        )
        .await?;
        let prior_state = match existing.state {
            InboxDispatchState::Begun => "begun",
            InboxDispatchState::Queued => "queued",
            InboxDispatchState::Admitted | InboxDispatchState::Completed => {
                return Err(MatrixDurableError::Conflict);
            }
        };
        let updated = sqlx::query(
            "UPDATE inbox_dispatches
             SET state = 'admitted', thread_id = ?, queued_submission_id = ?,
                 turn_id = ?, updated_at_ms = ?
             WHERE event_id = ? AND state = ? AND client_user_message_id = ?",
        )
        .bind(&draft.thread_id)
        .bind(draft.queued_submission_id.as_deref())
        .bind(&draft.turn_id)
        .bind(to_i64(draft.admitted_at_ms)?)
        .bind(draft.event_id.as_str())
        .bind(prior_state)
        .bind(&draft.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_change(
            &mut transaction,
            ChangeKind::InboxDispatchAdmitted,
            Some(&existing.room_id),
            Some(&draft.event_id),
            /*txn_id*/ None,
            draft.admitted_at_ms,
        )
        .await?;
        let record = InboxDispatchRecord {
            state: InboxDispatchState::Admitted,
            thread_id: Some(draft.thread_id.clone()),
            queued_submission_id: draft.queued_submission_id.clone(),
            turn_id: Some(draft.turn_id.clone()),
            updated_at_ms: draft.admitted_at_ms,
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn complete_inbox_dispatch(
        &self,
        draft: &InboxAdmissionDraft,
        completed_at_ms: u64,
    ) -> Result<InboxDispatchRecord, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = inbox_dispatch_by_event_tx(&mut transaction, &draft.event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.client_user_message_id != draft.client_user_message_id
            || existing.project_id != draft.project_id
            || existing.thread_id.as_deref() != Some(&draft.thread_id)
            || existing.queued_submission_id != draft.queued_submission_id
            || existing.turn_id.as_deref() != Some(&draft.turn_id)
        {
            return Err(MatrixDurableError::Conflict);
        }
        if existing.state == InboxDispatchState::Completed {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        if existing.state != InboxDispatchState::Admitted
            || completed_at_ms < existing.updated_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        let inbox = inbox_by_event_tx(&mut transaction, &draft.event_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if inbox.state != InboxState::Pending {
            return Err(MatrixDurableError::Corrupt);
        }
        let dispatch_updated = sqlx::query(
            "UPDATE inbox_dispatches
             SET state = 'completed', updated_at_ms = ?, completed_at_ms = ?
             WHERE event_id = ? AND state = 'admitted'",
        )
        .bind(to_i64(completed_at_ms)?)
        .bind(to_i64(completed_at_ms)?)
        .bind(draft.event_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if dispatch_updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let inbox_updated = sqlx::query(
            "UPDATE inbox_events SET state = 'processed', processed_at_ms = ?
             WHERE event_id = ? AND state = 'pending'",
        )
        .bind(to_i64(completed_at_ms)?)
        .bind(draft.event_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if inbox_updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_change(
            &mut transaction,
            ChangeKind::InboxProcessed,
            Some(&existing.room_id),
            Some(&draft.event_id),
            /*txn_id*/ None,
            completed_at_ms,
        )
        .await?;
        let record = InboxDispatchRecord {
            state: InboxDispatchState::Completed,
            updated_at_ms: completed_at_ms,
            completed_at_ms: Some(completed_at_ms),
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn inbox_dispatch(
        &self,
        event_id: &MatrixEventId,
    ) -> Result<Option<InboxDispatchRecord>, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let dispatch = inbox_dispatch_by_event_tx(&mut transaction, event_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(dispatch)
    }

    pub async fn inbox_dispatch_for_turn(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<Option<InboxDispatchRecord>, MatrixDurableError> {
        validate_local_identity(thread_id)?;
        validate_local_identity(turn_id)?;
        let rows = sqlx::query(
            "SELECT event_id, client_user_message_id, room_id, binding_revision, generation,
                    project_id, state, thread_id, queued_submission_id, turn_id,
                    begun_at_ms, updated_at_ms, completed_at_ms
             FROM inbox_dispatches WHERE thread_id = ? AND turn_id = ? LIMIT 2",
        )
        .bind(thread_id)
        .bind(turn_id)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        match rows.as_slice() {
            [] => Ok(None),
            [row] => Ok(Some(inbox_dispatch_from_row(row)?)),
            _ => Err(MatrixDurableError::Corrupt),
        }
    }

    pub async fn pending_dispatches(
        &self,
        limit: usize,
    ) -> Result<Vec<InboxDispatchRecord>, MatrixDurableError> {
        validate_limit(limit)?;
        let rows = sqlx::query(
            "SELECT event_id, client_user_message_id, room_id, binding_revision, generation,
                    project_id, state, thread_id, queued_submission_id, turn_id,
                    begun_at_ms, updated_at_ms,
                    completed_at_ms
             FROM matrix_actionable_inbox_dispatches_v2
             WHERE state IN ('begun', 'queued', 'admitted')
             ORDER BY begun_at_ms, event_id LIMIT ?",
        )
        .bind(to_i64(limit as u64)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter().map(inbox_dispatch_from_row).collect()
    }

    pub async fn pending_inbox(
        &self,
        limit: usize,
    ) -> Result<Vec<InboxRecord>, MatrixDurableError> {
        validate_limit(limit)?;
        let rows = sqlx::query(
            "SELECT inbox_cursor, event_id, room_id, sender_user_id, event_type,
                    payload, payload_sha256,
                    binding_revision, generation, origin_server_ts_ms, received_at_ms,
                    state, processed_at_ms
             FROM matrix_visible_inbox_events_v2 WHERE state = 'pending'
             ORDER BY inbox_cursor LIMIT ?",
        )
        .bind(to_i64(limit as u64)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter().map(inbox_from_row).collect()
    }

    pub async fn enqueue_outbox(
        &self,
        draft: &OutboxDraft,
    ) -> Result<OutboxDisposition, MatrixDurableError> {
        validate_payload(&draft.payload)?;
        validate_local_identity(&draft.logical_outbox_id)?;
        if draft.revision == 0
            || draft.binding_revision == 0
            || draft.generation == 0
            || transaction_id(&draft.logical_outbox_id, draft.revision)
                .map_err(|_| MatrixDurableError::Invalid)?
                != draft.txn_id
        {
            return Err(MatrixDurableError::Invalid);
        }
        // Read/modify/write outbox operations must reserve the SQLite writer
        // before reading. Otherwise a concurrent claim can leave this
        // transaction on a stale WAL snapshot and make the later coalesce or
        // insert fail with SQLITE_BUSY_SNAPSHOT.
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some((existing, fragment)) =
            outbox_by_logical_txn_tx(&mut transaction, &draft.txn_id).await?
        {
            if outbox_fragment_matches(&existing, &fragment, draft) {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(OutboxDisposition::Duplicate(existing));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if sync_v2_tombstone::is_room_tombstoned_tx(
            &mut transaction,
            &draft.room_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        require_current_binding(
            &mut transaction,
            &self.owner_agent_id,
            &draft.room_id,
            draft.binding_revision,
            draft.generation,
        )
        .await?;

        if draft.kind == OutboxKind::Final
            && let Some(existing) = pending_stream_record_tx(
                &mut transaction,
                &draft.logical_outbox_id,
                &draft.room_id,
                draft.binding_revision,
                draft.generation,
            )
            .await?
        {
            let payload_sha256 = Sha256Digest::for_bytes(&draft.payload);
            sqlx::query(
                "UPDATE outbox_messages
                 SET kind = 'final', payload = ?, payload_sha256 = ?,
                     logical_txn_count = logical_txn_count + 1,
                     next_attempt_at_ms = ?, updated_at_ms = ?
                 WHERE outbox_id = ? AND state = 'pending' AND kind = 'text_delta'",
            )
            .bind(&draft.payload)
            .bind(payload_sha256.as_str())
            .bind(to_i64(draft.created_at_ms)?)
            .bind(to_i64(draft.created_at_ms)?)
            .bind(to_i64(existing.outbox_id)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            insert_outbox_txn(&mut transaction, existing.outbox_id, draft).await?;
            self.append_change(
                &mut transaction,
                ChangeKind::OutboxCoalesced,
                Some(&draft.room_id),
                /*event_id*/ None,
                Some(&draft.txn_id),
                draft.created_at_ms,
            )
            .await?;
            let record = OutboxRecord {
                kind: OutboxKind::Final,
                payload: draft.payload.clone(),
                logical_txn_count: existing.logical_txn_count + 1,
                next_attempt_at_ms: draft.created_at_ms,
                updated_at_ms: draft.created_at_ms,
                ..existing
            };
            transaction.commit().await.map_err(unavailable)?;
            return Ok(OutboxDisposition::Coalesced(record));
        }

        if draft.kind == OutboxKind::TextDelta
            && let Some(existing) = self.coalesce_candidate(&mut transaction, draft).await?
        {
            let mut payload = existing.payload;
            payload.extend_from_slice(&draft.payload);
            let payload_sha256 = Sha256Digest::for_bytes(&payload);
            sqlx::query(
                "UPDATE outbox_messages
                 SET payload = ?, payload_sha256 = ?, logical_txn_count = logical_txn_count + 1,
                     updated_at_ms = ?
                 WHERE outbox_id = ? AND state = 'pending'",
            )
            .bind(&payload)
            .bind(payload_sha256.as_str())
            .bind(to_i64(draft.created_at_ms)?)
            .bind(to_i64(existing.outbox_id)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            insert_outbox_txn(&mut transaction, existing.outbox_id, draft).await?;
            self.append_change(
                &mut transaction,
                ChangeKind::OutboxCoalesced,
                Some(&draft.room_id),
                /*event_id*/ None,
                Some(&draft.txn_id),
                draft.created_at_ms,
            )
            .await?;
            let record = OutboxRecord {
                payload,
                logical_txn_count: existing.logical_txn_count + 1,
                updated_at_ms: draft.created_at_ms,
                ..existing
            };
            transaction.commit().await.map_err(unavailable)?;
            return Ok(OutboxDisposition::Coalesced(record));
        }

        let payload = if draft.kind == OutboxKind::TextDelta {
            let latest = logical_stream_latest_tx(
                &mut transaction,
                &draft.logical_outbox_id,
                &draft.room_id,
                draft.binding_revision,
                draft.generation,
            )
            .await?;
            if latest
                .as_ref()
                .is_some_and(|record| record.kind == OutboxKind::Final)
            {
                return Err(MatrixDurableError::Conflict);
            }
            // Each row renders the complete stream prefix, while the
            // coalescing limit is enforced against the raw fragments mapped
            // to that row. A later m.replace therefore never loses history.
            let mut payload = latest.map(|record| record.payload).unwrap_or_default();
            payload.extend_from_slice(&draft.payload);
            validate_payload(&payload)?;
            payload
        } else {
            draft.payload.clone()
        };
        let payload_sha256 = Sha256Digest::for_bytes(&payload);
        let next_attempt_at_ms = match draft.kind {
            OutboxKind::TextDelta => draft
                .created_at_ms
                .checked_add(self.config.delta_coalesce_window_ms)
                .ok_or(MatrixDurableError::Invalid)?,
            OutboxKind::Final
            | OutboxKind::ToolTransition
            | OutboxKind::Approval
            | OutboxKind::Terminal => draft.created_at_ms,
        };
        let inserted = sqlx::query(
            "INSERT INTO outbox_messages (
                stable_txn_id, logical_outbox_id, room_id, kind, payload, payload_sha256,
                logical_txn_count,
                binding_revision, generation, state, attempts, next_attempt_at_ms,
                lease_until_ms, created_at_ms, updated_at_ms, sent_event_id
             ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'pending', 0, ?, NULL, ?, ?, NULL)",
        )
        .bind(draft.txn_id.as_str())
        .bind(&draft.logical_outbox_id)
        .bind(draft.room_id.as_str())
        .bind(draft.kind.as_str())
        .bind(&payload)
        .bind(payload_sha256.as_str())
        .bind(to_i64(draft.binding_revision)?)
        .bind(to_i64(draft.generation)?)
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let outbox_id = to_u64(inserted.last_insert_rowid())?;
        insert_outbox_txn(&mut transaction, outbox_id, draft).await?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxEnqueued,
            Some(&draft.room_id),
            /*event_id*/ None,
            Some(&draft.txn_id),
            draft.created_at_ms,
        )
        .await?;
        let record = OutboxRecord {
            outbox_id,
            stable_txn_id: draft.txn_id.clone(),
            room_id: draft.room_id.clone(),
            kind: draft.kind,
            payload,
            logical_txn_count: 1,
            binding_revision: draft.binding_revision,
            generation: draft.generation,
            state: OutboxState::Pending,
            attempts: 0,
            next_attempt_at_ms,
            lease_until_ms: None,
            created_at_ms: draft.created_at_ms,
            updated_at_ms: draft.created_at_ms,
            sent_event_id: None,
            replaces_event_id: None,
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(OutboxDisposition::Enqueued(record))
    }

    /// Return the first unused revision for one logical outbound projection.
    ///
    /// The fenced per-Agent runtime serializes this read with `enqueue_outbox`.
    /// A second writer still fails closed on the database unique constraint.
    pub async fn next_outbox_revision(
        &self,
        logical_outbox_id: &str,
    ) -> Result<u64, MatrixDurableError> {
        validate_local_identity(logical_outbox_id)?;
        let row = sqlx::query(
            "SELECT MAX(revision) AS max_revision
             FROM outbox_txns WHERE logical_outbox_id = ?",
        )
        .bind(logical_outbox_id)
        .fetch_one(&self.pool)
        .await
        .map_err(unavailable)?;
        let revision = row
            .try_get::<Option<i64>, _>("max_revision")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?
            .unwrap_or(0)
            .checked_add(1)
            .ok_or(MatrixDurableError::Invalid)?;
        Ok(revision)
    }

    /// Return the revision of an already-recorded exact stream fragment.
    ///
    /// Final App Server notifications may be replayed after a projector
    /// reconnect. Reusing their original revision preserves one stable Matrix
    /// transaction instead of manufacturing a second logical final.
    pub async fn exact_outbox_revision(
        &self,
        logical_outbox_id: &str,
        room_id: &MatrixRoomId,
        kind: OutboxKind,
        payload: &[u8],
        binding_revision: u64,
        generation: u64,
    ) -> Result<Option<u64>, MatrixDurableError> {
        validate_local_identity(logical_outbox_id)?;
        validate_payload(payload)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let rows = sqlx::query(
            "SELECT revision, room_id, fragment, fragment_sha256,
                    binding_revision, generation
             FROM outbox_txns
             WHERE logical_outbox_id = ? AND kind = ?
             ORDER BY revision",
        )
        .bind(logical_outbox_id)
        .bind(kind.as_str())
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let mut exact_revision = None;
        for row in rows {
            let fragment: Vec<u8> = row.try_get("fragment").map_err(unavailable)?;
            let fragment_sha256: String = row.try_get("fragment_sha256").map_err(unavailable)?;
            if Sha256Digest::for_bytes(&fragment).as_str() != fragment_sha256 {
                return Err(MatrixDurableError::Corrupt);
            }
            let stored_room =
                MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
                    .map_err(|_| MatrixDurableError::Corrupt)?;
            let stored_binding = to_u64(row.try_get("binding_revision").map_err(unavailable)?)?;
            let stored_generation = to_u64(row.try_get("generation").map_err(unavailable)?)?;
            if stored_room != *room_id
                || stored_binding != binding_revision
                || stored_generation != generation
            {
                return Err(MatrixDurableError::Conflict);
            }
            if fragment == payload {
                if exact_revision.is_some() {
                    return Err(MatrixDurableError::Corrupt);
                }
                exact_revision = Some(to_u64(row.try_get("revision").map_err(unavailable)?)?);
            }
        }
        if exact_revision.is_some() {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(exact_revision);
        }
        if sync_v2_tombstone::is_room_tombstoned_tx(
            &mut transaction,
            room_id,
            binding_revision,
            generation,
        )
        .await?
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(None)
    }

    async fn coalesce_candidate(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        draft: &OutboxDraft,
    ) -> Result<Option<OutboxRecord>, MatrixDurableError> {
        let earliest = draft
            .created_at_ms
            .saturating_sub(self.config.delta_coalesce_window_ms);
        let remaining = self
            .config
            .max_delta_batch_bytes
            .checked_sub(draft.payload.len())
            .ok_or(MatrixDurableError::Invalid)?;
        sqlx::query(
            "SELECT outbox_messages.outbox_id, outbox_messages.stable_txn_id,
                    outbox_messages.room_id, outbox_messages.kind,
                    outbox_messages.payload, outbox_messages.payload_sha256,
                    outbox_messages.logical_txn_count,
                    outbox_messages.binding_revision, outbox_messages.generation,
                    outbox_messages.state, outbox_messages.attempts,
                    outbox_messages.next_attempt_at_ms, outbox_messages.lease_until_ms,
                    outbox_messages.created_at_ms, outbox_messages.updated_at_ms,
                    outbox_messages.sent_event_id
             FROM matrix_sendable_outbox_v2 AS outbox_messages
             WHERE outbox_messages.logical_outbox_id = ?
               AND outbox_messages.room_id = ?
               AND outbox_messages.kind = 'text_delta'
               AND outbox_messages.state = 'pending'
               AND outbox_messages.binding_revision = ?
               AND outbox_messages.generation = ?
               AND outbox_messages.created_at_ms BETWEEN ? AND ?
               AND (
                   SELECT COALESCE(SUM(length(fragment)), 0)
                   FROM outbox_txns
                   WHERE outbox_txns.outbox_id = outbox_messages.outbox_id
               ) <= ?
             ORDER BY outbox_messages.outbox_id DESC LIMIT 1",
        )
        .bind(&draft.logical_outbox_id)
        .bind(draft.room_id.as_str())
        .bind(to_i64(draft.binding_revision)?)
        .bind(to_i64(draft.generation)?)
        .bind(to_i64(earliest)?)
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(remaining as u64)?)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?
        .map(|row| outbox_from_row(&row))
        .transpose()
    }

    pub async fn claim_outbox(
        &self,
        now_ms: u64,
        lease_ms: u64,
        limit: usize,
    ) -> Result<Vec<OutboxRecord>, MatrixDurableError> {
        validate_limit(limit)?;
        if lease_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let lease_until_ms = now_ms
            .checked_add(lease_ms)
            .ok_or(MatrixDurableError::Invalid)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let rows = sqlx::query(
            "SELECT outbox_id, stable_txn_id, room_id, kind,
                    payload, payload_sha256, logical_txn_count,
                    binding_revision, generation, state, attempts, next_attempt_at_ms,
                    lease_until_ms, created_at_ms, updated_at_ms, sent_event_id
             FROM matrix_sendable_outbox_v2
             WHERE (
                    state IN ('pending', 'retry_scheduled') AND next_attempt_at_ms <= ?
                   ) OR (
                    state = 'in_flight' AND lease_until_ms <= ?
                   )
             ORDER BY next_attempt_at_ms, outbox_id LIMIT ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let mut claimed = Vec::with_capacity(rows.len());
        for row in rows {
            let mut record = outbox_from_row(&row)?;
            match logical_stream_dependency_tx(&mut transaction, &record.stable_txn_id).await? {
                LogicalStreamDependency::Root => {}
                LogicalStreamDependency::Replace(event_id) => {
                    record.replaces_event_id = Some(event_id);
                }
                LogicalStreamDependency::Waiting => continue,
                LogicalStreamDependency::RootFailed => {
                    let updated = sqlx::query(
                        "UPDATE outbox_messages
                         SET state = 'permanent_failure', updated_at_ms = ?
                         WHERE outbox_id = ? AND state = ? AND attempts = ?",
                    )
                    .bind(to_i64(now_ms)?)
                    .bind(to_i64(record.outbox_id)?)
                    .bind(record.state.as_str())
                    .bind(to_i64(record.attempts)?)
                    .execute(&mut *transaction)
                    .await
                    .map_err(unavailable)?;
                    if updated.rows_affected() != 1 {
                        return Err(MatrixDurableError::Conflict);
                    }
                    self.append_change(
                        &mut transaction,
                        ChangeKind::OutboxFailed,
                        Some(&record.room_id),
                        /*event_id*/ None,
                        Some(&record.stable_txn_id),
                        now_ms,
                    )
                    .await?;
                    continue;
                }
            }
            let attempts = record
                .attempts
                .checked_add(1)
                .ok_or(MatrixDurableError::Invalid)?;
            let updated = sqlx::query(
                "UPDATE outbox_messages
                 SET state = 'in_flight', attempts = ?, lease_until_ms = ?, updated_at_ms = ?
                 WHERE outbox_id = ? AND state = ? AND attempts = ?",
            )
            .bind(to_i64(attempts)?)
            .bind(to_i64(lease_until_ms)?)
            .bind(to_i64(now_ms)?)
            .bind(to_i64(record.outbox_id)?)
            .bind(record.state.as_str())
            .bind(to_i64(record.attempts)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if updated.rows_affected() != 1 {
                return Err(MatrixDurableError::Conflict);
            }
            self.append_change(
                &mut transaction,
                ChangeKind::OutboxClaimed,
                Some(&record.room_id),
                /*event_id*/ None,
                Some(&record.stable_txn_id),
                now_ms,
            )
            .await?;
            claimed.push(OutboxRecord {
                state: OutboxState::InFlight,
                attempts,
                lease_until_ms: Some(lease_until_ms),
                updated_at_ms: now_ms,
                ..record
            });
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(claimed)
    }

    pub async fn mark_outbox_retry(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
        next_attempt_at_ms: u64,
    ) -> Result<OutboxRecord, MatrixDurableError> {
        if expected_attempt == 0 || next_attempt_at_ms < now_ms {
            return Err(MatrixDurableError::Invalid);
        }
        self.transition_outbox(
            txn_id,
            expected_attempt,
            now_ms,
            OutboxTransition::Retry { next_attempt_at_ms },
        )
        .await
    }

    pub async fn mark_outbox_sent(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<OutboxRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        self.transition_outbox(
            txn_id,
            expected_attempt,
            now_ms,
            OutboxTransition::Sent {
                event_id: event_id.clone(),
            },
        )
        .await
    }

    pub async fn mark_outbox_permanent_failure(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<OutboxRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        self.transition_outbox(
            txn_id,
            expected_attempt,
            now_ms,
            OutboxTransition::PermanentFailure,
        )
        .await
    }

    async fn transition_outbox(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
        transition: OutboxTransition,
    ) -> Result<OutboxRecord, MatrixDurableError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let (existing, _) = outbox_by_logical_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        // Exact terminal/retry replay is a lost-ack recovery read. A later
        // room tombstone must not erase the already-durable outcome.
        if let Some(idempotent) = transition.idempotent_result(&existing) {
            transaction.commit().await.map_err(unavailable)?;
            return idempotent;
        }
        if existing.state != OutboxState::InFlight || existing.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        // A room fence prevents new claims, but the holder of the exact
        // already-issued attempt may still record its observed result. This
        // transition cannot initiate another Matrix send.
        let (state, next_attempt_at_ms, sent_event_id, change_kind) = match &transition {
            OutboxTransition::Retry { next_attempt_at_ms } => (
                OutboxState::RetryScheduled,
                *next_attempt_at_ms,
                None,
                ChangeKind::OutboxRetryScheduled,
            ),
            OutboxTransition::Sent { event_id } => (
                OutboxState::Sent,
                existing.next_attempt_at_ms,
                Some(event_id.clone()),
                ChangeKind::OutboxSent,
            ),
            OutboxTransition::PermanentFailure => (
                OutboxState::PermanentFailure,
                existing.next_attempt_at_ms,
                None,
                ChangeKind::OutboxFailed,
            ),
        };
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = ?, next_attempt_at_ms = ?, lease_until_ms = NULL,
                 updated_at_ms = ?, sent_event_id = ?
             WHERE outbox_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(state.as_str())
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(sent_event_id.as_ref().map(MatrixEventId::as_str))
        .bind(to_i64(existing.outbox_id)?)
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_change(
            &mut transaction,
            change_kind,
            Some(&existing.room_id),
            sent_event_id.as_ref(),
            Some(&existing.stable_txn_id),
            now_ms,
        )
        .await?;
        let record = OutboxRecord {
            state,
            next_attempt_at_ms,
            lease_until_ms: None,
            updated_at_ms: now_ms,
            sent_event_id,
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn pending_outbox(
        &self,
        limit: usize,
    ) -> Result<Vec<OutboxRecord>, MatrixDurableError> {
        validate_limit(limit)?;
        let rows = sqlx::query(
            "SELECT outbox_id, stable_txn_id, room_id, kind,
                    payload, payload_sha256, logical_txn_count,
                    binding_revision, generation, state, attempts, next_attempt_at_ms,
                    lease_until_ms, created_at_ms, updated_at_ms, sent_event_id
             FROM matrix_sendable_outbox_v2
             WHERE state IN ('pending', 'in_flight', 'retry_scheduled')
             ORDER BY outbox_id LIMIT ?",
        )
        .bind(to_i64(limit as u64)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter().map(outbox_from_row).collect()
    }

    pub async fn outbox_for_txn(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<OutboxRecord>, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let record = outbox_by_logical_txn_tx(&mut transaction, txn_id)
            .await?
            .map(|(record, _)| record);
        if let Some(record) = &record
            && sync_v2_tombstone::is_room_tombstoned_tx(
                &mut transaction,
                &record.room_id,
                record.binding_revision,
                record.generation,
            )
            .await?
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(None);
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn store_pending_approval(
        &self,
        draft: &PendingApprovalDraft,
    ) -> Result<PendingApprovalRecord, MatrixDurableError> {
        draft
            .approval
            .validate()
            .map_err(|_| MatrixDurableError::Invalid)?;
        validate_request_id_json(&draft.request_id_json)?;
        validate_runtime_identifier(&draft.process_incarnation)?;
        if draft.attached_agent_generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let pending_json =
            serde_json::to_string(&draft.approval).map_err(|_| MatrixDurableError::Invalid)?;
        if pending_json.len() > 8_192 {
            return Err(MatrixDurableError::Invalid);
        }

        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let existing = pending_approval_tx(&mut transaction, &draft.approval.approval_key).await?;
        let requested = PendingApprovalRecord {
            approval: draft.approval.clone(),
            request_id_json: draft.request_id_json.clone(),
            request_kind: draft.request_kind,
            attached_agent_generation: draft.attached_agent_generation,
            process_incarnation: draft.process_incarnation.clone(),
            resolution_decision: None,
            resolving_at_ms: None,
        };
        if let Some(existing) = existing {
            if existing == requested {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(MatrixDurableError::Conflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM pending_approvals")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if to_u64(count)? >= MAX_PENDING_APPROVALS as u64 {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "INSERT INTO pending_approvals (
                approval_key, pending_json, request_id_json, request_kind,
                attached_agent_generation, process_incarnation, created_at_ms,
                resolution_decision, resolving_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
        )
        .bind(&draft.approval.approval_key)
        .bind(&pending_json)
        .bind(&draft.request_id_json)
        .bind(draft.request_kind.as_str())
        .bind(to_i64(draft.attached_agent_generation)?)
        .bind(&draft.process_incarnation)
        .bind(to_i64(draft.approval.created_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_control_event(
            &mut transaction,
            MatrixdEventKind::ApprovalPending {
                approval: draft.approval.clone(),
            },
            draft.approval.created_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(requested)
    }

    pub async fn pending_approval(
        &self,
        approval_key: &str,
    ) -> Result<Option<PendingApprovalRecord>, MatrixDurableError> {
        validate_runtime_identifier(approval_key)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let approval = pending_approval_tx(&mut transaction, approval_key).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(approval)
    }

    pub async fn begin_pending_approval_resolution(
        &self,
        approval_key: &str,
        attached_agent_generation: u64,
        process_incarnation: &str,
        decision: LocalApprovalDecision,
        resolving_at_ms: u64,
    ) -> Result<PendingApprovalRecord, MatrixDurableError> {
        validate_runtime_identifier(approval_key)?;
        validate_runtime_identifier(process_incarnation)?;
        if attached_agent_generation == 0 || resolving_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = pending_approval_tx(&mut transaction, approval_key)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.attached_agent_generation != attached_agent_generation
            || existing.process_incarnation != process_incarnation
            || resolving_at_ms < existing.approval.created_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(existing_decision) = existing.resolution_decision {
            if existing_decision != decision {
                return Err(MatrixDurableError::Conflict);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        let updated = sqlx::query(
            "UPDATE pending_approvals
             SET resolution_decision = ?, resolving_at_ms = ?
             WHERE approval_key = ? AND attached_agent_generation = ?
               AND process_incarnation = ? AND resolution_decision IS NULL",
        )
        .bind(local_approval_decision_name(decision))
        .bind(to_i64(resolving_at_ms)?)
        .bind(approval_key)
        .bind(to_i64(attached_agent_generation)?)
        .bind(process_incarnation)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let record = PendingApprovalRecord {
            resolution_decision: Some(decision),
            resolving_at_ms: Some(resolving_at_ms),
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn complete_pending_approval_resolution(
        &self,
        approval_key: &str,
        attached_agent_generation: u64,
        process_incarnation: &str,
        decision: LocalApprovalDecision,
        resolved_at_ms: u64,
    ) -> Result<PendingApprovalRecord, MatrixDurableError> {
        validate_runtime_identifier(approval_key)?;
        validate_runtime_identifier(process_incarnation)?;
        if attached_agent_generation == 0 || resolved_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = pending_approval_tx(&mut transaction, approval_key)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.attached_agent_generation != attached_agent_generation
            || existing.process_incarnation != process_incarnation
            || existing.resolution_decision != Some(decision)
            || existing
                .resolving_at_ms
                .is_none_or(|resolving_at_ms| resolved_at_ms < resolving_at_ms)
        {
            return Err(MatrixDurableError::Conflict);
        }
        let deleted = sqlx::query(
            "DELETE FROM pending_approvals
             WHERE approval_key = ? AND attached_agent_generation = ?
               AND process_incarnation = ? AND resolution_decision = ?",
        )
        .bind(approval_key)
        .bind(to_i64(attached_agent_generation)?)
        .bind(process_incarnation)
        .bind(local_approval_decision_name(decision))
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if deleted.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_control_event(
            &mut transaction,
            MatrixdEventKind::ApprovalResolved {
                approval_key: approval_key.to_string(),
            },
            resolved_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(existing)
    }

    /// Reconciles App Server's authoritative `serverRequest/resolved`
    /// notification with the owner-local pending map.
    ///
    /// This closes the crash window in which the response reached App Server
    /// but the local resolution transaction did not commit. It also removes a
    /// request that App Server resolved while changing turn state. The exact
    /// request ID, thread, generation, and process incarnation must all agree.
    pub async fn reconcile_server_request_resolved(
        &self,
        request_id_json: &str,
        thread_id: &str,
        attached_agent_generation: u64,
        process_incarnation: &str,
        resolved_at_ms: u64,
    ) -> Result<Option<PendingApprovalRecord>, MatrixDurableError> {
        validate_runtime_identifier(thread_id)?;
        validate_runtime_identifier(process_incarnation)?;
        if request_id_json.is_empty()
            || request_id_json.len() > 1_024
            || attached_agent_generation == 0
            || resolved_at_ms == 0
        {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT approval_key, pending_json, request_id_json, request_kind,
                    attached_agent_generation, process_incarnation, created_at_ms,
                    resolution_decision, resolving_at_ms
             FROM pending_approvals WHERE request_id_json = ?",
        )
        .bind(request_id_json)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let Some(record) = row.as_ref().map(pending_approval_from_row).transpose()? else {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        if record.approval.thread_id != thread_id
            || record.attached_agent_generation != attached_agent_generation
            || record.process_incarnation != process_incarnation
        {
            return Err(MatrixDurableError::Conflict);
        }
        let deleted = sqlx::query(
            "DELETE FROM pending_approvals
             WHERE approval_key = ? AND request_id_json = ?
               AND attached_agent_generation = ? AND process_incarnation = ?",
        )
        .bind(&record.approval.approval_key)
        .bind(request_id_json)
        .bind(to_i64(attached_agent_generation)?)
        .bind(process_incarnation)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if deleted.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        self.append_control_event(
            &mut transaction,
            MatrixdEventKind::ApprovalResolved {
                approval_key: record.approval.approval_key.clone(),
            },
            resolved_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(Some(record))
    }

    /// Transfers pending App Server requests to a newly authorized sidecar
    /// incarnation when the attached Agent generation is unchanged, while
    /// terminalizing requests from superseded Agent generations.
    ///
    /// A persisted resolving decision survives the transfer unchanged, so a
    /// crash-before-send retry cannot silently choose a different outcome.
    /// The incarnation compare-and-swap fences the crashed process.
    pub async fn fence_stale_pending_approvals(
        &self,
        attached_agent_generation: u64,
        process_incarnation: &str,
        fenced_at_ms: u64,
    ) -> Result<usize, MatrixDurableError> {
        validate_runtime_identifier(process_incarnation)?;
        if attached_agent_generation == 0 || fenced_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let rows = sqlx::query(
            "SELECT approval_key, pending_json, request_id_json, request_kind,
                    attached_agent_generation, process_incarnation, created_at_ms,
                    resolution_decision, resolving_at_ms
             FROM pending_approvals
             WHERE attached_agent_generation != ? OR process_incarnation != ?
             ORDER BY created_at_ms, approval_key",
        )
        .bind(to_i64(attached_agent_generation)?)
        .bind(process_incarnation)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let records = rows
            .iter()
            .map(pending_approval_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let mut fenced = 0_usize;
        for record in &records {
            if record.attached_agent_generation == attached_agent_generation {
                let updated = sqlx::query(
                    "UPDATE pending_approvals
                     SET process_incarnation = ?
                     WHERE approval_key = ? AND attached_agent_generation = ?
                       AND process_incarnation = ?",
                )
                .bind(process_incarnation)
                .bind(&record.approval.approval_key)
                .bind(to_i64(attached_agent_generation)?)
                .bind(&record.process_incarnation)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if updated.rows_affected() != 1 {
                    return Err(MatrixDurableError::Conflict);
                }
                self.append_control_event(
                    &mut transaction,
                    MatrixdEventKind::ApprovalPending {
                        approval: record.approval.clone(),
                    },
                    fenced_at_ms,
                )
                .await?;
            } else {
                let deleted = sqlx::query(
                    "DELETE FROM pending_approvals
                     WHERE approval_key = ? AND attached_agent_generation = ?
                       AND process_incarnation = ?",
                )
                .bind(&record.approval.approval_key)
                .bind(to_i64(record.attached_agent_generation)?)
                .bind(&record.process_incarnation)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if deleted.rows_affected() != 1 {
                    return Err(MatrixDurableError::Conflict);
                }
                self.append_control_event(
                    &mut transaction,
                    MatrixdEventKind::ApprovalResolved {
                        approval_key: record.approval.approval_key.clone(),
                    },
                    fenced_at_ms,
                )
                .await?;
                fenced += 1;
            }
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(fenced)
    }

    pub async fn record_turn_started(
        &self,
        thread_id: &str,
        turn_id: &str,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        validate_runtime_identifier(thread_id)?;
        validate_runtime_identifier(turn_id)?;
        if recorded_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        sqlx::query(
            "UPDATE matrix_control_state
             SET active_thread_id = ?, active_turn_id = ? WHERE singleton = 1",
        )
        .bind(thread_id)
        .bind(turn_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_control_event(
            &mut transaction,
            MatrixdEventKind::TurnStarted {
                thread_id: thread_id.to_string(),
                turn_id: turn_id.to_string(),
            },
            recorded_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn record_turn_completed(
        &self,
        thread_id: &str,
        turn_id: &str,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        validate_runtime_identifier(thread_id)?;
        validate_runtime_identifier(turn_id)?;
        if recorded_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        sqlx::query(
            "UPDATE matrix_control_state
             SET active_thread_id = NULL, active_turn_id = NULL
             WHERE singleton = 1 AND active_thread_id = ? AND active_turn_id = ?",
        )
        .bind(thread_id)
        .bind(turn_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_control_event(
            &mut transaction,
            MatrixdEventKind::TurnCompleted {
                thread_id: thread_id.to_string(),
                turn_id: turn_id.to_string(),
            },
            recorded_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn control_snapshot(&self) -> Result<MatrixControlSnapshot, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let cursor = latest_control_cursor_tx(&mut transaction).await?;
        let state = sqlx::query(
            "SELECT active_thread_id, active_turn_id
             FROM matrix_control_state WHERE singleton = 1",
        )
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let active_thread_id: Option<String> =
            state.try_get("active_thread_id").map_err(unavailable)?;
        let active_turn_id: Option<String> =
            state.try_get("active_turn_id").map_err(unavailable)?;
        if active_thread_id.is_some() != active_turn_id.is_some() {
            return Err(MatrixDurableError::Corrupt);
        }
        if let Some(value) = active_thread_id.as_deref() {
            validate_stored_runtime_identifier(value)?;
        }
        if let Some(value) = active_turn_id.as_deref() {
            validate_stored_runtime_identifier(value)?;
        }
        let rows = sqlx::query(
            "SELECT approval_key, pending_json, request_id_json, request_kind,
                    attached_agent_generation, process_incarnation, created_at_ms,
                    resolution_decision, resolving_at_ms
             FROM pending_approvals ORDER BY created_at_ms, approval_key",
        )
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if rows.len() > MAX_PENDING_APPROVALS {
            return Err(MatrixDurableError::Corrupt);
        }
        let pending_approvals = rows
            .iter()
            .map(pending_approval_from_row)
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .map(|record| record.approval)
            .collect();
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixControlSnapshot {
            cursor,
            active_thread_id,
            active_turn_id,
            pending_approvals,
        })
    }

    pub async fn read_control_events(
        &self,
        after_cursor: u64,
        limit: usize,
    ) -> Result<MatrixControlPage, MatrixDurableError> {
        validate_limit(limit)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let latest_cursor = latest_control_cursor_tx(&mut transaction).await?;
        if after_cursor > latest_cursor {
            return Err(MatrixDurableError::Invalid);
        }
        let oldest: Option<i64> =
            sqlx::query_scalar("SELECT MIN(cursor) FROM matrix_control_events")
                .fetch_one(&mut *transaction)
                .await
                .map_err(unavailable)?;
        let oldest = oldest.map(to_u64).transpose()?;
        let gap = oldest.is_some_and(|cursor| cursor > after_cursor.saturating_add(1));
        if gap {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(MatrixControlPage {
                batch: MatrixdEventBatch {
                    events: Vec::new(),
                    gap: true,
                    next_cursor: after_cursor,
                    latest_cursor,
                },
            });
        }
        let rows = sqlx::query(
            "SELECT cursor, event_json FROM matrix_control_events
             WHERE cursor > ? ORDER BY cursor LIMIT ?",
        )
        .bind(to_i64(after_cursor)?)
        .bind(to_i64(limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let events = rows
            .iter()
            .map(control_event_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let next_cursor = events.last().map_or(after_cursor, |event| event.cursor);
        let batch = MatrixdEventBatch {
            events,
            gap: false,
            next_cursor,
            latest_cursor,
        };
        batch
            .validate_after(after_cursor)
            .map_err(|_| MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixControlPage { batch })
    }

    pub async fn queue_metrics(
        &self,
        now_ms: u64,
    ) -> Result<MatrixQueueMetrics, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let metrics = queue_metrics_tx(&mut transaction, now_ms).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(metrics)
    }

    pub async fn read_changes(
        &self,
        after_cursor: u64,
        limit: usize,
    ) -> Result<ChangePage, MatrixDurableError> {
        validate_limit(limit)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let latest_cursor = latest_cursor_tx(&mut transaction).await?;
        if after_cursor > latest_cursor {
            return Err(MatrixDurableError::Invalid);
        }
        let oldest: Option<i64> = sqlx::query_scalar("SELECT MIN(cursor) FROM change_log")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        let oldest = oldest.map(to_u64).transpose()?;
        let gap = oldest.is_some_and(|cursor| cursor > after_cursor.saturating_add(1));
        if gap {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(ChangePage {
                events: Vec::new(),
                next_cursor: after_cursor,
                latest_cursor,
                gap: true,
            });
        }
        let rows = sqlx::query(
            "SELECT cursor, kind, room_id, event_id, txn_id, recorded_at_ms
             FROM change_log WHERE cursor > ? ORDER BY cursor LIMIT ?",
        )
        .bind(to_i64(after_cursor)?)
        .bind(to_i64(limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let events: Vec<_> = rows.iter().map(change_from_row).collect::<Result<_, _>>()?;
        let next_cursor = events.last().map_or(after_cursor, |event| event.cursor);
        transaction.commit().await.map_err(unavailable)?;
        Ok(ChangePage {
            events,
            next_cursor,
            latest_cursor,
            gap: false,
        })
    }

    pub async fn snapshot(
        &self,
        now_ms: u64,
        queue_limit: usize,
    ) -> Result<MatrixSnapshot, MatrixDurableError> {
        validate_limit(queue_limit)?;
        let fetch_limit = queue_limit
            .checked_add(1)
            .ok_or(MatrixDurableError::Invalid)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let cursor = latest_cursor_tx(&mut transaction).await?;
        let binding_rows = sqlx::query(
            "SELECT room_id, owner_agent_id, agent_user_id, revision, generation, changed_at_ms
             FROM room_bindings ORDER BY room_id",
        )
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let bindings = binding_rows
            .iter()
            .map(room_binding_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let room_thread_rows = sqlx::query(
            "SELECT room_id, binding_revision, generation, project_id, thread_id, changed_at_ms
             FROM room_threads ORDER BY room_id, binding_revision, generation",
        )
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let room_threads = room_thread_rows
            .iter()
            .map(room_thread_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let inbox_rows = sqlx::query(
            "SELECT inbox_cursor, event_id, room_id, sender_user_id, event_type,
                    payload, payload_sha256,
                    binding_revision, generation, origin_server_ts_ms, received_at_ms,
                    state, processed_at_ms
             FROM matrix_visible_inbox_events_v2 WHERE state = 'pending'
             ORDER BY inbox_cursor LIMIT ?",
        )
        .bind(to_i64(fetch_limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let mut pending_inbox = inbox_rows
            .iter()
            .map(inbox_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let inbox_truncated = pending_inbox.len() > queue_limit;
        pending_inbox.truncate(queue_limit);
        let dispatch_rows = sqlx::query(
            "SELECT event_id, client_user_message_id, room_id, binding_revision, generation,
                    project_id, state, thread_id, queued_submission_id, turn_id,
                    begun_at_ms, updated_at_ms,
                    completed_at_ms
             FROM matrix_actionable_inbox_dispatches_v2
             WHERE state IN ('begun', 'queued', 'admitted')
             ORDER BY begun_at_ms, event_id LIMIT ?",
        )
        .bind(to_i64(fetch_limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let mut pending_dispatches = dispatch_rows
            .iter()
            .map(inbox_dispatch_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let dispatch_truncated = pending_dispatches.len() > queue_limit;
        pending_dispatches.truncate(queue_limit);
        let outbox_rows = sqlx::query(
            "SELECT outbox_id, stable_txn_id, room_id, kind,
                    payload, payload_sha256, logical_txn_count,
                    binding_revision, generation, state, attempts, next_attempt_at_ms,
                    lease_until_ms, created_at_ms, updated_at_ms, sent_event_id
             FROM matrix_sendable_outbox_v2
             WHERE state IN ('pending', 'in_flight', 'retry_scheduled')
             ORDER BY outbox_id LIMIT ?",
        )
        .bind(to_i64(fetch_limit as u64)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let mut pending_outbox = outbox_rows
            .iter()
            .map(outbox_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let outbox_truncated = pending_outbox.len() > queue_limit;
        pending_outbox.truncate(queue_limit);
        let metrics = queue_metrics_tx(&mut transaction, now_ms).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixSnapshot {
            owner_agent_id: self.owner_agent_id.clone(),
            cursor,
            bindings,
            room_threads,
            pending_inbox,
            pending_dispatches,
            pending_outbox,
            metrics,
            inbox_truncated,
            dispatch_truncated,
            outbox_truncated,
        })
    }

    pub(crate) async fn append_change(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        kind: ChangeKind,
        room_id: Option<&MatrixRoomId>,
        event_id: Option<&MatrixEventId>,
        txn_id: Option<&MatrixTransactionId>,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        sqlx::query(
            "INSERT INTO change_log (kind, room_id, event_id, txn_id, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?)",
        )
        .bind(kind.as_str())
        .bind(room_id.map(MatrixRoomId::as_str))
        .bind(event_id.map(MatrixEventId::as_str))
        .bind(txn_id.map(MatrixTransactionId::as_str))
        .bind(to_i64(recorded_at_ms)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "DELETE FROM change_log
             WHERE cursor <= (SELECT COALESCE(MAX(cursor), 0) - ? FROM change_log)",
        )
        .bind(to_i64(self.config.event_capacity as u64)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        Ok(())
    }

    async fn append_control_event(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        kind: MatrixdEventKind,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        if recorded_at_ms == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        MatrixdEventBatch {
            events: vec![MatrixdEvent {
                cursor: 1,
                kind: kind.clone(),
            }],
            gap: false,
            next_cursor: 1,
            latest_cursor: 1,
        }
        .validate_after(/*after_cursor*/ 0)
        .map_err(|_| MatrixDurableError::Invalid)?;
        let event_json = serde_json::to_string(&kind).map_err(|_| MatrixDurableError::Invalid)?;
        if event_json.len() > 8_192 {
            return Err(MatrixDurableError::Invalid);
        }
        sqlx::query("INSERT INTO matrix_control_events (event_json, recorded_at_ms) VALUES (?, ?)")
            .bind(event_json)
            .bind(to_i64(recorded_at_ms)?)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        sqlx::query(
            "DELETE FROM matrix_control_events
             WHERE cursor <= (
                SELECT COALESCE(MAX(cursor), 0) - ? FROM matrix_control_events
             )",
        )
        .bind(to_i64(self.config.event_capacity as u64)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        Ok(())
    }
}

enum OutboxTransition {
    Retry { next_attempt_at_ms: u64 },
    Sent { event_id: MatrixEventId },
    PermanentFailure,
}

impl OutboxTransition {
    fn idempotent_result(
        &self,
        existing: &OutboxRecord,
    ) -> Option<Result<OutboxRecord, MatrixDurableError>> {
        match self {
            Self::Sent { event_id } if existing.state == OutboxState::Sent => Some(
                (existing.sent_event_id.as_ref() == Some(event_id))
                    .then(|| existing.clone())
                    .ok_or(MatrixDurableError::Conflict),
            ),
            Self::PermanentFailure if existing.state == OutboxState::PermanentFailure => {
                Some(Ok(existing.clone()))
            }
            Self::Retry { next_attempt_at_ms } if existing.state == OutboxState::RetryScheduled => {
                Some(
                    (existing.next_attempt_at_ms == *next_attempt_at_ms)
                        .then(|| existing.clone())
                        .ok_or(MatrixDurableError::Conflict),
                )
            }
            _ if existing.state.is_terminal() => Some(Err(MatrixDurableError::Conflict)),
            _ => None,
        }
    }
}

struct OutboxFragment {
    logical_outbox_id: String,
    revision: u64,
    room_id: MatrixRoomId,
    kind: OutboxKind,
    payload: Vec<u8>,
    binding_revision: u64,
    generation: u64,
}

async fn require_current_binding(
    transaction: &mut Transaction<'_, Sqlite>,
    owner_agent_id: &AgentId,
    room_id: &MatrixRoomId,
    revision: u64,
    generation: u64,
) -> Result<(), MatrixDurableError> {
    let row = sqlx::query(
        "SELECT owner_agent_id, revision, generation FROM room_bindings WHERE room_id = ?",
    )
    .bind(room_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or(MatrixDurableError::AccessDenied)?;
    let owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
    let stored_revision = to_u64(row.try_get("revision").map_err(unavailable)?)?;
    let stored_generation = to_u64(row.try_get("generation").map_err(unavailable)?)?;
    if owner != owner_agent_id.as_str()
        || stored_revision != revision
        || stored_generation != generation
    {
        return Err(MatrixDurableError::AccessDenied);
    }
    if sync_v2_tombstone::is_room_tombstoned_tx(transaction, room_id, revision, generation).await? {
        return Err(MatrixDurableError::AccessDenied);
    }
    Ok(())
}

async fn inbox_by_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<InboxRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT inbox_cursor, event_id, room_id, sender_user_id, event_type,
                payload, payload_sha256,
                binding_revision, generation, origin_server_ts_ms, received_at_ms,
                state, processed_at_ms
         FROM matrix_visible_inbox_events_v2 WHERE event_id = ?",
    )
    .bind(event_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| inbox_from_row(&row))
    .transpose()
}

async fn raw_inbox_by_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<InboxRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT inbox_cursor, event_id, room_id, sender_user_id, event_type,
                payload, payload_sha256,
                binding_revision, generation, origin_server_ts_ms, received_at_ms,
                state, processed_at_ms
         FROM inbox_events WHERE event_id = ?",
    )
    .bind(event_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| inbox_from_row(&row))
    .transpose()
}

async fn room_thread_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<Option<RoomThreadBinding>, MatrixDurableError> {
    sqlx::query(
        "SELECT room_id, binding_revision, generation, project_id, thread_id, changed_at_ms
         FROM room_threads
         WHERE room_id = ? AND binding_revision = ? AND generation = ?",
    )
    .bind(room_id.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| room_thread_from_row(&row))
    .transpose()
}

async fn inbox_dispatch_by_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<InboxDispatchRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT event_id, client_user_message_id, room_id, binding_revision, generation,
                project_id, state, thread_id, queued_submission_id, turn_id,
                begun_at_ms, updated_at_ms,
                completed_at_ms
         FROM inbox_dispatches WHERE event_id = ?",
    )
    .bind(event_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| inbox_dispatch_from_row(&row))
    .transpose()
}

async fn ensure_dispatch_thread_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    dispatch: &InboxDispatchRecord,
    project_id: &str,
    thread_id: &str,
    changed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let room_thread = room_thread_tx(
        transaction,
        &dispatch.room_id,
        dispatch.binding_revision,
        dispatch.generation,
    )
    .await?
    .ok_or(MatrixDurableError::Conflict)?;
    if room_thread.project_id != project_id
        || room_thread
            .thread_id
            .as_deref()
            .is_some_and(|current| current != thread_id)
        || dispatch
            .thread_id
            .as_deref()
            .is_some_and(|current| current != thread_id)
    {
        return Err(MatrixDurableError::Conflict);
    }
    let conflicting_thread: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM room_threads
         WHERE thread_id = ? AND room_id != ?",
    )
    .bind(thread_id)
    .bind(dispatch.room_id.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if conflicting_thread != 0 {
        return Err(MatrixDurableError::Conflict);
    }
    if room_thread.thread_id.is_none() {
        let updated = sqlx::query(
            "UPDATE room_threads SET thread_id = ?, changed_at_ms = ?
             WHERE room_id = ? AND binding_revision = ? AND generation = ?
               AND project_id = ? AND thread_id IS NULL",
        )
        .bind(thread_id)
        .bind(to_i64(changed_at_ms)?)
        .bind(dispatch.room_id.as_str())
        .bind(to_i64(dispatch.binding_revision)?)
        .bind(to_i64(dispatch.generation)?)
        .bind(project_id)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
    }
    Ok(())
}

fn inbox_matches_draft(record: &InboxRecord, draft: &InboxDraft) -> bool {
    record.event_id == draft.event_id
        && record.room_id == draft.room_id
        && record.sender == draft.sender
        && record.event_type == draft.event_type
        && record.payload == draft.payload
        && record.binding_revision == draft.binding_revision
        && record.generation == draft.generation
        && record.origin_server_ts_ms == draft.origin_server_ts_ms
}

async fn insert_outbox_txn(
    transaction: &mut Transaction<'_, Sqlite>,
    outbox_id: u64,
    draft: &OutboxDraft,
) -> Result<(), MatrixDurableError> {
    let fragment_sha256 = Sha256Digest::for_bytes(&draft.payload);
    sqlx::query(
        "INSERT INTO outbox_txns (
            txn_id, logical_outbox_id, revision, outbox_id, room_id, kind, fragment, fragment_sha256,
            binding_revision, generation
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(draft.txn_id.as_str())
    .bind(&draft.logical_outbox_id)
    .bind(to_i64(draft.revision)?)
    .bind(to_i64(outbox_id)?)
    .bind(draft.room_id.as_str())
    .bind(draft.kind.as_str())
    .bind(&draft.payload)
    .bind(fragment_sha256.as_str())
    .bind(to_i64(draft.binding_revision)?)
    .bind(to_i64(draft.generation)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn pending_stream_record_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    logical_outbox_id: &str,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<Option<OutboxRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT message.outbox_id, message.stable_txn_id, message.room_id, message.kind,
                message.payload, message.payload_sha256, message.logical_txn_count,
                message.binding_revision, message.generation, message.state, message.attempts,
                message.next_attempt_at_ms, message.lease_until_ms, message.created_at_ms,
                message.updated_at_ms, message.sent_event_id
         FROM outbox_messages AS message
         WHERE message.logical_outbox_id = ? AND message.room_id = ?
           AND message.binding_revision = ? AND message.generation = ?
           AND message.state = 'pending' AND message.kind = 'text_delta'
         ORDER BY message.outbox_id DESC LIMIT 1",
    )
    .bind(logical_outbox_id)
    .bind(room_id.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| outbox_from_row(&row))
    .transpose()
}

async fn logical_stream_latest_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    logical_outbox_id: &str,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<Option<OutboxRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT message.outbox_id, message.stable_txn_id, message.room_id, message.kind,
                message.payload, message.payload_sha256, message.logical_txn_count,
                message.binding_revision, message.generation, message.state, message.attempts,
                message.next_attempt_at_ms, message.lease_until_ms, message.created_at_ms,
                message.updated_at_ms, message.sent_event_id
         FROM outbox_messages AS message
         WHERE message.logical_outbox_id = ? AND message.room_id = ?
           AND message.binding_revision = ? AND message.generation = ?
         ORDER BY message.outbox_id DESC LIMIT 1",
    )
    .bind(logical_outbox_id)
    .bind(room_id.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| outbox_from_row(&row))
    .transpose()
}

enum LogicalStreamDependency {
    Root,
    Replace(MatrixEventId),
    Waiting,
    RootFailed,
}

async fn logical_stream_dependency_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    stable_txn_id: &MatrixTransactionId,
) -> Result<LogicalStreamDependency, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT current_txn.revision AS current_revision,
                root_txn.revision AS root_revision,
                root_message.state AS root_state,
                root_message.sent_event_id AS root_sent_event_id
         FROM outbox_txns AS current_txn
         JOIN outbox_txns AS root_txn
           ON root_txn.logical_outbox_id = current_txn.logical_outbox_id
          AND root_txn.revision = (
              SELECT MIN(candidate.revision) FROM outbox_txns AS candidate
              WHERE candidate.logical_outbox_id = current_txn.logical_outbox_id
          )
         JOIN outbox_messages AS root_message ON root_message.outbox_id = root_txn.outbox_id
         WHERE current_txn.txn_id = ?",
    )
    .bind(stable_txn_id.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let current_revision = to_u64(row.try_get("current_revision").map_err(unavailable)?)?;
    let root_revision = to_u64(row.try_get("root_revision").map_err(unavailable)?)?;
    if current_revision == root_revision {
        return Ok(LogicalStreamDependency::Root);
    }
    let root_state = OutboxState::parse(
        row.try_get::<String, _>("root_state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    match root_state {
        OutboxState::Sent => {
            let event_id = row
                .try_get::<Option<String>, _>("root_sent_event_id")
                .map_err(unavailable)?
                .ok_or(MatrixDurableError::Corrupt)?;
            Ok(LogicalStreamDependency::Replace(
                MatrixEventId::parse(event_id).map_err(|_| MatrixDurableError::Corrupt)?,
            ))
        }
        OutboxState::PermanentFailure => Ok(LogicalStreamDependency::RootFailed),
        OutboxState::Pending | OutboxState::InFlight | OutboxState::RetryScheduled => {
            Ok(LogicalStreamDependency::Waiting)
        }
    }
}

async fn outbox_by_logical_txn_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<(OutboxRecord, OutboxFragment)>, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT
            message.outbox_id, message.stable_txn_id, message.room_id, message.kind,
            message.payload, message.payload_sha256, message.logical_txn_count,
            message.binding_revision,
            message.generation, message.state, message.attempts,
            message.next_attempt_at_ms, message.lease_until_ms, message.created_at_ms,
            message.updated_at_ms, message.sent_event_id,
            txn.logical_outbox_id AS txn_logical_outbox_id, txn.revision AS txn_revision,
            txn.room_id AS txn_room_id, txn.kind AS txn_kind, txn.fragment,
            txn.fragment_sha256 AS txn_fragment_sha256,
            txn.binding_revision AS txn_binding_revision, txn.generation AS txn_generation
         FROM outbox_txns AS txn
         JOIN outbox_messages AS message ON message.outbox_id = txn.outbox_id
         WHERE txn.txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    row.map(|row| {
        let record = outbox_from_row(&row)?;
        let room_id = MatrixRoomId::parse(
            row.try_get::<String, _>("txn_room_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let kind = OutboxKind::parse(
            row.try_get::<String, _>("txn_kind")
                .map_err(unavailable)?
                .as_str(),
        )
        .ok_or(MatrixDurableError::Corrupt)?;
        let payload: Vec<u8> = row.try_get("fragment").map_err(unavailable)?;
        let fragment_sha256: String = row.try_get("txn_fragment_sha256").map_err(unavailable)?;
        if Sha256Digest::for_bytes(&payload).as_str() != fragment_sha256 {
            return Err(MatrixDurableError::Corrupt);
        }
        let fragment = OutboxFragment {
            logical_outbox_id: row.try_get("txn_logical_outbox_id").map_err(unavailable)?,
            revision: to_u64(row.try_get("txn_revision").map_err(unavailable)?)?,
            room_id,
            kind,
            payload,
            binding_revision: to_u64(row.try_get("txn_binding_revision").map_err(unavailable)?)?,
            generation: to_u64(row.try_get("txn_generation").map_err(unavailable)?)?,
        };
        Ok((record, fragment))
    })
    .transpose()
}

fn outbox_fragment_matches(
    _record: &OutboxRecord,
    fragment: &OutboxFragment,
    draft: &OutboxDraft,
) -> bool {
    fragment.logical_outbox_id == draft.logical_outbox_id
        && fragment.revision == draft.revision
        && fragment.room_id == draft.room_id
        && fragment.kind == draft.kind
        && fragment.payload == draft.payload
        && fragment.binding_revision == draft.binding_revision
        && fragment.generation == draft.generation
}

async fn latest_cursor_tx(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<u64, MatrixDurableError> {
    let cursor: i64 = sqlx::query_scalar("SELECT COALESCE(MAX(cursor), 0) FROM change_log")
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
    to_u64(cursor)
}

async fn latest_control_cursor_tx(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<u64, MatrixDurableError> {
    let cursor: i64 =
        sqlx::query_scalar("SELECT COALESCE(MAX(cursor), 0) FROM matrix_control_events")
            .fetch_one(&mut **transaction)
            .await
            .map_err(unavailable)?;
    to_u64(cursor)
}

async fn pending_approval_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    approval_key: &str,
) -> Result<Option<PendingApprovalRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT approval_key, pending_json, request_id_json, request_kind,
                attached_agent_generation, process_incarnation, created_at_ms,
                resolution_decision, resolving_at_ms
         FROM pending_approvals WHERE approval_key = ?",
    )
    .bind(approval_key)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| pending_approval_from_row(&row))
    .transpose()
}

fn pending_approval_from_row(row: &SqliteRow) -> Result<PendingApprovalRecord, MatrixDurableError> {
    let approval_key: String = row.try_get("approval_key").map_err(unavailable)?;
    let pending_json: String = row.try_get("pending_json").map_err(unavailable)?;
    let request_id_json: String = row.try_get("request_id_json").map_err(unavailable)?;
    let request_kind = PendingApprovalKind::parse(
        row.try_get::<String, _>("request_kind")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let process_incarnation: String = row.try_get("process_incarnation").map_err(unavailable)?;
    let resolution_decision = row
        .try_get::<Option<String>, _>("resolution_decision")
        .map_err(unavailable)?
        .map(|value| parse_local_approval_decision(&value).ok_or(MatrixDurableError::Corrupt))
        .transpose()?;
    let resolving_at_ms = row
        .try_get::<Option<i64>, _>("resolving_at_ms")
        .map_err(unavailable)?
        .map(to_u64)
        .transpose()?;
    validate_stored_runtime_identifier(&approval_key)?;
    validate_stored_runtime_identifier(&process_incarnation)?;
    validate_request_id_json(&request_id_json).map_err(|_| MatrixDurableError::Corrupt)?;
    let approval: codex_hepta_matrix_protocol::PendingApproval =
        serde_json::from_str(&pending_json).map_err(|_| MatrixDurableError::Corrupt)?;
    approval
        .validate()
        .map_err(|_| MatrixDurableError::Corrupt)?;
    if approval.approval_key != approval_key
        || approval.created_at_ms != to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?
        || resolution_decision.is_some() != resolving_at_ms.is_some()
        || resolving_at_ms.is_some_and(|at_ms| at_ms < approval.created_at_ms)
    {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(PendingApprovalRecord {
        approval,
        request_id_json,
        request_kind,
        attached_agent_generation: to_u64(
            row.try_get("attached_agent_generation")
                .map_err(unavailable)?,
        )?,
        process_incarnation,
        resolution_decision,
        resolving_at_ms,
    })
}

fn control_event_from_row(row: &SqliteRow) -> Result<MatrixdEvent, MatrixDurableError> {
    let cursor = to_u64(row.try_get("cursor").map_err(unavailable)?)?;
    let event_json: String = row.try_get("event_json").map_err(unavailable)?;
    let kind = serde_json::from_str(&event_json).map_err(|_| MatrixDurableError::Corrupt)?;
    Ok(MatrixdEvent { cursor, kind })
}

async fn queue_metrics_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    now_ms: u64,
) -> Result<MatrixQueueMetrics, MatrixDurableError> {
    let inbox = sqlx::query(
        "SELECT COUNT(*) AS depth, MIN(received_at_ms) AS oldest
         FROM matrix_visible_inbox_events_v2 WHERE state = 'pending'",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let dispatch = sqlx::query(
        "SELECT COUNT(*) AS depth, MIN(begun_at_ms) AS oldest
         FROM matrix_actionable_inbox_dispatches_v2
         WHERE state IN ('begun', 'queued', 'admitted')",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let outbox = sqlx::query(
        "SELECT COUNT(*) AS depth, MIN(created_at_ms) AS oldest
         FROM matrix_sendable_outbox_v2
         WHERE state IN ('pending', 'in_flight', 'retry_scheduled')",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let inbox_depth = to_u64(inbox.try_get("depth").map_err(unavailable)?)?;
    let dispatch_depth = to_u64(dispatch.try_get("depth").map_err(unavailable)?)?;
    let outbox_depth = to_u64(outbox.try_get("depth").map_err(unavailable)?)?;
    let inbox_oldest = inbox
        .try_get::<Option<i64>, _>("oldest")
        .map_err(unavailable)?
        .map(to_u64)
        .transpose()?;
    let dispatch_oldest = dispatch
        .try_get::<Option<i64>, _>("oldest")
        .map_err(unavailable)?
        .map(to_u64)
        .transpose()?;
    let outbox_oldest = outbox
        .try_get::<Option<i64>, _>("oldest")
        .map_err(unavailable)?
        .map(to_u64)
        .transpose()?;
    Ok(MatrixQueueMetrics {
        pending_inbox_depth: inbox_depth,
        pending_dispatch_depth: dispatch_depth,
        pending_outbox_depth: outbox_depth,
        oldest_inbox_age_ms: inbox_oldest.map(|oldest| now_ms.saturating_sub(oldest)),
        oldest_dispatch_age_ms: dispatch_oldest.map(|oldest| now_ms.saturating_sub(oldest)),
        oldest_outbox_age_ms: outbox_oldest.map(|oldest| now_ms.saturating_sub(oldest)),
    })
}

fn room_binding_from_row(row: &SqliteRow) -> Result<RoomBinding, MatrixDurableError> {
    Ok(RoomBinding {
        room_id: MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        owner_agent_id: AgentId::parse(
            row.try_get::<String, _>("owner_agent_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        agent_user_id: MatrixUserId::parse(
            row.try_get::<String, _>("agent_user_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        revision: to_u64(row.try_get("revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        changed_at_ms: to_u64(row.try_get("changed_at_ms").map_err(unavailable)?)?,
    })
}

fn room_thread_from_row(row: &SqliteRow) -> Result<RoomThreadBinding, MatrixDurableError> {
    let project_id: String = row.try_get("project_id").map_err(unavailable)?;
    validate_stored_identity(&project_id)?;
    let thread_id: Option<String> = row.try_get("thread_id").map_err(unavailable)?;
    if let Some(thread_id) = thread_id.as_deref() {
        validate_stored_identity(thread_id)?;
    }
    Ok(RoomThreadBinding {
        room_id: MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        project_id,
        thread_id,
        changed_at_ms: to_u64(row.try_get("changed_at_ms").map_err(unavailable)?)?,
    })
}

fn sync_checkpoint_from_row(row: &SqliteRow) -> Result<MatrixSyncCheckpoint, MatrixDurableError> {
    let next_batch: String = row.try_get("next_batch").map_err(unavailable)?;
    validate_sync_token(&next_batch).map_err(|_| MatrixDurableError::Corrupt)?;
    Ok(MatrixSyncCheckpoint {
        owner_agent_id: AgentId::parse(
            row.try_get::<String, _>("owner_agent_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        next_batch,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
    })
}

fn inbox_from_row(row: &SqliteRow) -> Result<InboxRecord, MatrixDurableError> {
    let state = InboxState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let payload: Vec<u8> = row.try_get("payload").map_err(unavailable)?;
    let payload_sha256: String = row.try_get("payload_sha256").map_err(unavailable)?;
    if Sha256Digest::for_bytes(&payload).as_str() != payload_sha256 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(InboxRecord {
        cursor: to_u64(row.try_get("inbox_cursor").map_err(unavailable)?)?,
        event_id: MatrixEventId::parse(row.try_get::<String, _>("event_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        room_id: MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        sender: MatrixUserId::parse(
            row.try_get::<String, _>("sender_user_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        event_type: row.try_get("event_type").map_err(unavailable)?,
        payload,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        origin_server_ts_ms: to_u64(row.try_get("origin_server_ts_ms").map_err(unavailable)?)?,
        received_at_ms: to_u64(row.try_get("received_at_ms").map_err(unavailable)?)?,
        state,
        processed_at_ms: row
            .try_get::<Option<i64>, _>("processed_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}

fn inbox_dispatch_from_row(row: &SqliteRow) -> Result<InboxDispatchRecord, MatrixDurableError> {
    let state = InboxDispatchState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let client_user_message_id: String =
        row.try_get("client_user_message_id").map_err(unavailable)?;
    let project_id: String = row.try_get("project_id").map_err(unavailable)?;
    let thread_id: Option<String> = row.try_get("thread_id").map_err(unavailable)?;
    let queued_submission_id: Option<String> =
        row.try_get("queued_submission_id").map_err(unavailable)?;
    let turn_id: Option<String> = row.try_get("turn_id").map_err(unavailable)?;
    validate_stored_identity(&client_user_message_id)?;
    validate_stored_identity(&project_id)?;
    if let Some(thread_id) = thread_id.as_deref() {
        validate_stored_identity(thread_id)?;
    }
    if let Some(queued_submission_id) = queued_submission_id.as_deref() {
        validate_stored_identity(queued_submission_id)?;
    }
    if let Some(turn_id) = turn_id.as_deref() {
        validate_stored_identity(turn_id)?;
    }
    let record = InboxDispatchRecord {
        event_id: MatrixEventId::parse(row.try_get::<String, _>("event_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        client_user_message_id,
        room_id: MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        project_id,
        state,
        thread_id,
        queued_submission_id,
        turn_id,
        begun_at_ms: to_u64(row.try_get("begun_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        completed_at_ms: row
            .try_get::<Option<i64>, _>("completed_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    };
    let structurally_valid = match record.state {
        InboxDispatchState::Begun => {
            record.queued_submission_id.is_none()
                && record.turn_id.is_none()
                && record.completed_at_ms.is_none()
        }
        InboxDispatchState::Queued => {
            record.thread_id.is_some()
                && record.queued_submission_id.is_some()
                && record.turn_id.is_none()
                && record.completed_at_ms.is_none()
        }
        InboxDispatchState::Admitted => {
            record.thread_id.is_some()
                && record.turn_id.is_some()
                && record.completed_at_ms.is_none()
        }
        InboxDispatchState::Completed => {
            record.thread_id.is_some()
                && record.turn_id.is_some()
                && record.completed_at_ms == Some(record.updated_at_ms)
        }
    };
    if !structurally_valid || record.updated_at_ms < record.begun_at_ms {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(record)
}

fn outbox_from_row(row: &SqliteRow) -> Result<OutboxRecord, MatrixDurableError> {
    let kind = OutboxKind::parse(
        row.try_get::<String, _>("kind")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let state = OutboxState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let sent_event_id = row
        .try_get::<Option<String>, _>("sent_event_id")
        .map_err(unavailable)?
        .map(MatrixEventId::parse)
        .transpose()
        .map_err(|_| MatrixDurableError::Corrupt)?;
    let payload: Vec<u8> = row.try_get("payload").map_err(unavailable)?;
    let payload_sha256: String = row.try_get("payload_sha256").map_err(unavailable)?;
    if Sha256Digest::for_bytes(&payload).as_str() != payload_sha256 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(OutboxRecord {
        outbox_id: to_u64(row.try_get("outbox_id").map_err(unavailable)?)?,
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        room_id: MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        kind,
        payload,
        logical_txn_count: to_u64(row.try_get("logical_txn_count").map_err(unavailable)?)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        state,
        attempts: to_u64(row.try_get("attempts").map_err(unavailable)?)?,
        next_attempt_at_ms: to_u64(row.try_get("next_attempt_at_ms").map_err(unavailable)?)?,
        lease_until_ms: row
            .try_get::<Option<i64>, _>("lease_until_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        sent_event_id,
        replaces_event_id: None,
    })
}

fn change_from_row(row: &SqliteRow) -> Result<ChangeEvent, MatrixDurableError> {
    let kind = ChangeKind::parse(
        row.try_get::<String, _>("kind")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    Ok(ChangeEvent {
        cursor: to_u64(row.try_get("cursor").map_err(unavailable)?)?,
        kind,
        room_id: row
            .try_get::<Option<String>, _>("room_id")
            .map_err(unavailable)?
            .map(MatrixRoomId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        event_id: row
            .try_get::<Option<String>, _>("event_id")
            .map_err(unavailable)?
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        txn_id: row
            .try_get::<Option<String>, _>("txn_id")
            .map_err(unavailable)?
            .map(MatrixTransactionId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        recorded_at_ms: to_u64(row.try_get("recorded_at_ms").map_err(unavailable)?)?,
    })
}

async fn verify_matrix_v2_schema(pool: &SqlitePool) -> Result<(), MatrixDurableError> {
    let rows = sqlx::query(
        "SELECT name, type, sql FROM sqlite_schema
         WHERE name IN (
            'inbox_dispatches_by_room_active',
            'inbox_events_by_room_actionable',
            'matrix_actionable_inbox_dispatches_v2',
            'matrix_sendable_outbox_v2',
            'outbox_messages_by_room_active',
            'matrix_sync_decision_outcomes_v2',
            'matrix_sync_decision_outcomes_v2_guard_insert',
            'matrix_sync_decision_outcomes_v2_no_delete',
            'matrix_sync_decision_outcomes_v2_no_update',
            'matrix_sync_decisions_v2',
            'matrix_sync_decisions_v2_no_delete',
            'matrix_sync_decisions_v2_no_update',
            'matrix_sync_mutations_v2',
            'matrix_sync_mutations_v2_by_tombstone',
            'matrix_sync_mutations_v2_no_delete',
            'matrix_sync_mutations_v2_no_update',
            'matrix_visible_inbox_events_v2'
         ) ORDER BY name",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if rows.len() != 17 {
        return Err(MatrixDurableError::Corrupt);
    }
    let mut identity = Vec::new();
    for row in rows {
        let name: String = row.try_get("name").map_err(unavailable)?;
        let object_type: String = row.try_get("type").map_err(unavailable)?;
        let sql: String = row.try_get("sql").map_err(unavailable)?;
        // SQLite preserves the migration file's checkout line endings in
        // sqlite_schema.sql. Canonicalize only line endings so an equivalent
        // CRLF checkout cannot make a database created by this binary fail
        // its own schema fingerprint on restart.
        let normalized_sql = sql.replace("\r\n", "\n").replace('\r', "\n");
        for component in [
            name.as_bytes(),
            object_type.as_bytes(),
            normalized_sql.as_bytes(),
        ] {
            identity.extend_from_slice(component);
            identity.push(0);
        }
    }
    if Sha256Digest::for_bytes(&identity).as_str() != MATRIX_V2_SCHEMA_FINGERPRINT {
        return Err(MatrixDurableError::Corrupt);
    }
    let invalid_decisions: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM matrix_sync_decisions_v2 AS decision
         WHERE (decision.decision_kind = 'cancel' AND EXISTS (
                   SELECT 1 FROM matrix_sync_decision_outcomes_v2 AS outcome
                   WHERE outcome.decision_seq = decision.decision_seq
               ))
            OR (decision.decision_kind = 'commit' AND (
                   (SELECT COUNT(*) FROM matrix_sync_decision_outcomes_v2 AS outcome
                    WHERE outcome.decision_seq = decision.decision_seq)
                       != decision.outcome_count
                   OR (decision.outcome_count > 0 AND (
                       (SELECT MIN(outcome_index)
                        FROM matrix_sync_decision_outcomes_v2 AS outcome
                        WHERE outcome.decision_seq = decision.decision_seq) != 0
                       OR (SELECT MAX(outcome_index)
                           FROM matrix_sync_decision_outcomes_v2 AS outcome
                           WHERE outcome.decision_seq = decision.decision_seq)
                              != decision.outcome_count - 1
                   ))
               ))",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_decisions != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}

async fn verify_store(
    pool: &SqlitePool,
    owner_agent_id: &AgentId,
) -> Result<(), MatrixDurableError> {
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if quick_check != ["ok"] {
        return Err(MatrixDurableError::Corrupt);
    }
    if !sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?
        .is_empty()
    {
        return Err(MatrixDurableError::Corrupt);
    }
    let required_objects: i64 = sqlx::query_scalar(
        "WITH required(name, type) AS (VALUES
            ('matrix_meta_no_update', 'trigger'), ('matrix_meta_no_delete', 'trigger'),
            ('room_bindings', 'table'), ('room_threads', 'table'),
            ('inbox_events', 'table'), ('inbox_dispatches', 'table'),
            ('outbox_messages', 'table'), ('outbox_txns', 'table'), ('change_log', 'table'),
            ('matrix_sync_checkpoint', 'table'),
            ('matrix_sync_checkpoint_no_delete', 'trigger'),
            ('pending_approvals', 'table'), ('matrix_control_state', 'table'),
            ('matrix_control_events', 'table'), ('matrix_sync_mutations_v2', 'table'),
            ('matrix_sync_mutations_v2_by_tombstone', 'index'),
            ('matrix_sync_mutations_v2_no_update', 'trigger'),
            ('matrix_sync_mutations_v2_no_delete', 'trigger'),
            ('matrix_sync_decisions_v2', 'table'),
            ('matrix_sync_decisions_v2_no_update', 'trigger'),
            ('matrix_sync_decisions_v2_no_delete', 'trigger'),
            ('matrix_sync_decision_outcomes_v2', 'table'),
            ('matrix_sync_decision_outcomes_v2_no_update', 'trigger'),
            ('matrix_sync_decision_outcomes_v2_no_delete', 'trigger'),
            ('matrix_sync_decision_outcomes_v2_guard_insert', 'trigger'),
            ('inbox_events_by_room_actionable', 'index'),
            ('inbox_dispatches_by_room_active', 'index'),
            ('outbox_messages_by_room_active', 'index'),
            ('matrix_visible_inbox_events_v2', 'view'),
            ('matrix_actionable_inbox_dispatches_v2', 'view'),
            ('matrix_sendable_outbox_v2', 'view')
         )
         SELECT COUNT(*) FROM required
         JOIN sqlite_schema USING (name) WHERE sqlite_schema.type = required.type",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if required_objects != 31 {
        return Err(MatrixDurableError::Corrupt);
    }
    verify_matrix_v2_schema(pool).await?;
    let row =
        sqlx::query("SELECT schema_version, owner_agent_id FROM matrix_meta WHERE singleton = 1")
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    let schema_version: i64 = row.try_get("schema_version").map_err(unavailable)?;
    let stored_owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
    if schema_version != i64::from(MATRIX_SCHEMA_VERSION) {
        return Err(MatrixDurableError::Corrupt);
    }
    if stored_owner != owner_agent_id.as_str() {
        return Err(MatrixDurableError::AccessDenied);
    }
    let invalid_logical_streams: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM outbox_messages AS message
         LEFT JOIN outbox_txns AS stable_txn
           ON stable_txn.txn_id = message.stable_txn_id
         WHERE message.logical_outbox_id IS NULL
            OR stable_txn.logical_outbox_id IS NULL
            OR message.logical_outbox_id != stable_txn.logical_outbox_id",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_logical_streams != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    let foreign_checkpoint: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM matrix_sync_checkpoint WHERE owner_agent_id != ?")
            .bind(owner_agent_id.as_str())
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    if foreign_checkpoint != 0 {
        return Err(MatrixDurableError::AccessDenied);
    }
    let foreign_owners: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM room_bindings WHERE owner_agent_id != ?")
            .bind(owner_agent_id.as_str())
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    if foreign_owners != 0 {
        return Err(MatrixDurableError::AccessDenied);
    }
    let room_projects = sqlx::query("SELECT room_id, project_id FROM room_threads")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    for row in room_projects {
        let room_id =
            MatrixRoomId::parse(row.try_get::<String, _>("room_id").map_err(unavailable)?)
                .map_err(|_| MatrixDurableError::Corrupt)?;
        let project_id: String = row.try_get("project_id").map_err(unavailable)?;
        if project_id != room_project_idempotency_key(owner_agent_id, &room_id) {
            return Err(MatrixDurableError::Corrupt);
        }
    }
    let cross_room_threads: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM room_threads AS first
         JOIN room_threads AS second
           ON second.thread_id = first.thread_id
          AND second.room_id > first.room_id
         WHERE first.thread_id IS NOT NULL
           AND first.room_id != second.room_id",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if cross_room_threads != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    let invalid_dispatches: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM inbox_dispatches AS dispatch
         JOIN inbox_events AS inbox ON inbox.event_id = dispatch.event_id
         LEFT JOIN room_threads AS room_thread
           ON room_thread.room_id = dispatch.room_id
          AND room_thread.binding_revision = dispatch.binding_revision
          AND room_thread.generation = dispatch.generation
         WHERE dispatch.room_id != inbox.room_id
            OR dispatch.binding_revision != inbox.binding_revision
            OR dispatch.generation != inbox.generation
            OR room_thread.project_id IS NULL
            OR room_thread.project_id != dispatch.project_id
            OR (
                dispatch.thread_id IS NOT NULL
                AND (
                    room_thread.thread_id IS NULL
                    OR room_thread.thread_id != dispatch.thread_id
                )
            )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_dispatches != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}

fn validate_event_type(event_type: &str) -> Result<(), MatrixDurableError> {
    if !(1..=128).contains(&event_type.len())
        || !event_type
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_payload(payload: &[u8]) -> Result<(), MatrixDurableError> {
    if payload.is_empty() || payload.len() > MAX_PAYLOAD_BYTES {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_local_identity(value: &str) -> Result<(), MatrixDurableError> {
    if !(1..=512).contains(&value.len())
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !matches!(byte, b'/' | b'\\'))
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_runtime_identifier(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty()
        || value.len() > codex_hepta_matrix_protocol::MAX_RUNTIME_IDENTIFIER_BYTES
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_stored_runtime_identifier(value: &str) -> Result<(), MatrixDurableError> {
    validate_runtime_identifier(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn validate_request_id_json(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty() || value.len() > 1_024 {
        return Err(MatrixDurableError::Invalid);
    }
    match serde_json::from_str::<serde_json::Value>(value)
        .map_err(|_| MatrixDurableError::Invalid)?
    {
        serde_json::Value::String(value) => validate_runtime_identifier(&value),
        serde_json::Value::Number(value) if value.as_i64().is_some() => Ok(()),
        _ => Err(MatrixDurableError::Invalid),
    }
}

fn local_approval_decision_name(decision: LocalApprovalDecision) -> &'static str {
    match decision {
        LocalApprovalDecision::Accept => "accept",
        LocalApprovalDecision::AcceptForSession => "accept_for_session",
        LocalApprovalDecision::Decline => "decline",
        LocalApprovalDecision::Cancel => "cancel",
    }
}

fn parse_local_approval_decision(value: &str) -> Option<LocalApprovalDecision> {
    match value {
        "accept" => Some(LocalApprovalDecision::Accept),
        "accept_for_session" => Some(LocalApprovalDecision::AcceptForSession),
        "decline" => Some(LocalApprovalDecision::Decline),
        "cancel" => Some(LocalApprovalDecision::Cancel),
        _ => None,
    }
}

fn validate_stored_identity(value: &str) -> Result<(), MatrixDurableError> {
    validate_local_identity(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn validate_sync_token(value: &str) -> Result<(), MatrixDurableError> {
    if !(1..=4096).contains(&value.len()) || !value.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_limit(limit: usize) -> Result<(), MatrixDurableError> {
    if !(1..=MAX_PAGE_ITEMS).contains(&limit) {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_error: impl std::fmt::Display) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}

fn create_private_directory(path: &Path) -> Result<(), MatrixDurableError> {
    fs::create_dir_all(path).map_err(unavailable)?;
    if path.canonicalize().map_err(unavailable)? != path {
        return Err(MatrixDurableError::Invalid);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
    }
    Ok(())
}

fn protect_database_file(_path: &Path) -> Result<(), MatrixDurableError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(_path, fs::Permissions::from_mode(0o600)).map_err(unavailable)?;
    }
    Ok(())
}
