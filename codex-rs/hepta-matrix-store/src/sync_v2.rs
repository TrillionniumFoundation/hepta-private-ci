use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationDispositionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationOutcomeV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::sync_v2_tombstone::active_dispatch_exists_tx;
use super::sync_v2_tombstone::has_cancel_capacity_tx;
use super::sync_v2_tombstone::has_commit_capacity_tx;
use super::sync_v2_tombstone::inbox_exists_tx;
use super::sync_v2_tombstone::inbox_source_exists_tx;
use super::sync_v2_tombstone::insert_cancel_decision_tx;
use super::sync_v2_tombstone::insert_commit_decision_tx;
use super::sync_v2_tombstone::insert_decision_outcomes_tx;
use super::sync_v2_tombstone::is_tombstoned_tx;
use super::sync_v2_tombstone::lookup_decision_tx;
use super::sync_v2_tombstone::recover_decision_tx;
use super::sync_v2_tombstone::scrub_event_tx;
use super::sync_v2_tombstone::scrub_room_tx;
use super::sync_v2_tombstone::tombstone_fields;
use crate::ChangeKind;
use crate::InboxDisposition;
use crate::InboxDraft;
use crate::MatrixDurableError;
use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::MatrixSyncCheckpoint;
use crate::MatrixUserId;
use crate::store::MatrixDurableStore;

const MUTATION_DIGEST_DOMAIN: &[u8] = b"hepta.matrix.sync-mutation.v2";
const COMMIT_DIGEST_DOMAIN: &[u8] = b"hepta.matrix.sync-commit.v2";
const CANCEL_DIGEST_DOMAIN: &[u8] = b"hepta.matrix.sync-cancel.v2";

#[derive(Serialize)]
struct MatrixSyncMutationIdentityV2<'a> {
    source_event_id: &'a MatrixEventId,
    room_id: &'a MatrixRoomId,
    sender: &'a MatrixUserId,
    binding_revision: u64,
    generation: u64,
    origin_server_ts_ms: u64,
    received_at_ms: Option<u64>,
    body: MatrixSyncMutationBodyIdentityV2<'a>,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum MatrixSyncMutationBodyIdentityV2<'a> {
    Timeline {
        event_type: &'a str,
        payload_len: usize,
        payload_sha256: Sha256Digest,
    },
    Redaction {
        target_event_id: &'a MatrixEventId,
    },
    RoomLeave {
        departed_user_id: &'a MatrixUserId,
    },
    RoomTombstone {
        replacement_room_id: &'a MatrixRoomId,
    },
}

#[derive(Serialize)]
struct MatrixSyncCommitIdentityV2<'a> {
    schema_version: u32,
    operation_id: &'a str,
    checkpoint_revision: u64,
    checkpoint_generation: u64,
    expected_next_batch: Option<&'a str>,
    next_batch: &'a str,
    observed_at_ms: u64,
    mutations: Vec<MatrixSyncMutationIdentityV2<'a>>,
}

#[derive(Serialize)]
struct MatrixSyncCancelIdentityV2<'a> {
    schema_version: u32,
    operation_id: &'a str,
    checkpoint_revision: u64,
    checkpoint_generation: u64,
    expected_next_batch: Option<&'a str>,
}

impl MatrixDurableStore {
    /// Apply or cancel one explicit V2 sync decision.
    ///
    /// A committed response persists every mutation, every derived tombstone,
    /// and the cursor CAS in one writer transaction. Cancellation persists
    /// only its idempotency decision record, never a domain mutation or cursor
    /// advance, and returns a distinct result with the retained cursor.
    ///
    /// This is not an admission or authority boundary. A future Matrix-owned
    /// composer must establish source provenance and response completeness;
    /// this store verifies only owner-local binding and cursor fences.
    pub async fn apply_sync_decision_v2(
        &self,
        decision: &MatrixSyncDecisionV2,
    ) -> Result<MatrixSyncResultV2, MatrixDurableError> {
        decision
            .validate()
            .map_err(|_| MatrixDurableError::Invalid)?;
        match decision {
            MatrixSyncDecisionV2::Commit { batch } => self.commit_sync_batch_v2(batch).await,
            MatrixSyncDecisionV2::Cancel {
                schema_version: _,
                operation_id,
                checkpoint_revision,
                checkpoint_generation,
                expected_next_batch,
            } => self
                .cancel_sync_v2(
                    operation_id,
                    *checkpoint_revision,
                    *checkpoint_generation,
                    expected_next_batch.as_deref(),
                )
                .await,
        }
    }

    /// Reconcile a lost response by its caller-persisted operation identity.
    ///
    /// `None` means no durable decision exists. This read confers no source
    /// completeness or execution authority and never mutates the cursor.
    pub async fn lookup_sync_decision_v2(
        &self,
        operation_id: &str,
    ) -> Result<Option<MatrixSyncResultV2>, MatrixDurableError> {
        if !valid_operation_id(operation_id) {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let result = lookup_decision_tx(&mut transaction, operation_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    async fn cancel_sync_v2(
        &self,
        operation_id: &str,
        checkpoint_revision: u64,
        checkpoint_generation: u64,
        expected_next_batch: Option<&str>,
    ) -> Result<MatrixSyncResultV2, MatrixDurableError> {
        let identity = MatrixSyncCancelIdentityV2 {
            schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
            operation_id,
            checkpoint_revision,
            checkpoint_generation,
            expected_next_batch,
        };
        let decision_digest = domain_digest(CANCEL_DIGEST_DOMAIN, &identity)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some(result) = recover_decision_tx(
            &mut transaction,
            operation_id,
            "cancel",
            &decision_digest,
            /*expected_mutations*/ None,
        )
        .await?
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(result);
        }
        let checkpoint = checkpoint_tx(&mut transaction).await?;
        verify_checkpoint(
            checkpoint.as_ref(),
            self.owner_agent_id(),
            checkpoint_revision,
            checkpoint_generation,
            expected_next_batch,
        )?;
        if !has_cancel_capacity_tx(&mut transaction).await? {
            return Ok(MatrixSyncResultV2::CapacityExhausted {
                schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
                operation_id: operation_id.to_string(),
                checkpoint_revision,
                checkpoint_generation,
            });
        }
        let retained_next_batch = checkpoint.map(|checkpoint| checkpoint.next_batch);
        insert_cancel_decision_tx(
            &mut transaction,
            operation_id,
            &decision_digest,
            checkpoint_revision,
            checkpoint_generation,
            expected_next_batch,
            retained_next_batch.as_deref(),
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixSyncResultV2::Cancelled {
            schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
            operation_id: operation_id.to_string(),
            checkpoint_revision,
            checkpoint_generation,
            retained_next_batch,
        })
    }

    async fn commit_sync_batch_v2(
        &self,
        batch: &MatrixSyncBatchV2,
    ) -> Result<MatrixSyncResultV2, MatrixDurableError> {
        let identity = MatrixSyncCommitIdentityV2 {
            schema_version: batch.schema_version,
            operation_id: batch.operation_id.as_str(),
            checkpoint_revision: batch.checkpoint_revision,
            checkpoint_generation: batch.checkpoint_generation,
            expected_next_batch: batch.expected_next_batch.as_deref(),
            next_batch: batch.next_batch.as_str(),
            observed_at_ms: batch.observed_at_ms,
            mutations: batch
                .mutations
                .iter()
                .map(decision_mutation_identity)
                .collect(),
        };
        let decision_digest = domain_digest(COMMIT_DIGEST_DOMAIN, &identity)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some(result) = recover_decision_tx(
            &mut transaction,
            &batch.operation_id,
            "commit",
            &decision_digest,
            Some(&batch.mutations),
        )
        .await?
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(result);
        }
        // Runtime capacity is deliberately checked only after durable replay.
        // A configuration reduction must not make an already-committed
        // operation lose its exact journaled result.
        if batch.mutations.len() > self.config.event_capacity {
            return Err(MatrixDurableError::Invalid);
        }
        let existing = checkpoint_tx(&mut transaction).await?;
        verify_checkpoint(
            existing.as_ref(),
            self.owner_agent_id(),
            batch.checkpoint_revision,
            batch.checkpoint_generation,
            batch.expected_next_batch.as_deref(),
        )?;
        if !has_commit_capacity_tx(&mut transaction, batch).await? {
            return Ok(MatrixSyncResultV2::CapacityExhausted {
                schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
                operation_id: batch.operation_id.clone(),
                checkpoint_revision: batch.checkpoint_revision,
                checkpoint_generation: batch.checkpoint_generation,
            });
        }
        let decision_seq = insert_commit_decision_tx(
            &mut transaction,
            batch,
            &decision_digest,
        )
        .await?;

        let mut outcomes = Vec::with_capacity(batch.mutations.len());
        let mut remaining_scrub_budget = self.config.event_capacity;
        for mutation in &batch.mutations {
            outcomes.push(
                self.apply_mutation_v2(&mut transaction, mutation, &mut remaining_scrub_budget)
                    .await?,
            );
        }
        insert_decision_outcomes_tx(&mut transaction, decision_seq, &outcomes).await?;

        let updated_at_ms = existing
            .as_ref()
            .map(|checkpoint| checkpoint.updated_at_ms.max(batch.observed_at_ms))
            .unwrap_or(batch.observed_at_ms);
        advance_checkpoint(
            &mut transaction,
            existing.is_some(),
            self.owner_agent_id(),
            batch,
            updated_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(MatrixSyncResultV2::Committed {
            schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
            operation_id: batch.operation_id.clone(),
            checkpoint_revision: batch.checkpoint_revision,
            checkpoint_generation: batch.checkpoint_generation,
            next_batch: batch.next_batch.clone(),
            outcomes,
        })
    }

    async fn apply_mutation_v2(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        mutation: &MatrixSyncMutationV2,
        remaining_scrub_budget: &mut usize,
    ) -> Result<MatrixSyncMutationOutcomeV2, MatrixDurableError> {
        // received_at_ms is local first-seen metadata, not part of a homeserver
        // event's stable identity. Retried sync pages may observe it later.
        let identity = semantic_mutation_identity(mutation);
        let semantic_digest = domain_digest(MUTATION_DIGEST_DOMAIN, &identity)?;
        let bound_user = require_room_binding_tx(
            transaction,
            self.owner_agent_id(),
            &mutation.room_id,
            mutation.binding_revision,
            mutation.generation,
        )
        .await?;
        // This is only a local shape invariant. The event sender may be a
        // remote moderator when the bound user was kicked or banned. The
        // departed identity is caller supplied, so equality with the binding
        // does not prove homeserver provenance or grant authority to leave.
        if let MatrixSyncMutationBodyV2::RoomLeave { departed_user_id } = &mutation.body
            && departed_user_id != &bound_user
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        if !matches!(&mutation.body, MatrixSyncMutationBodyV2::Timeline { .. }) {
            let source_exists: i64 =
                sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM inbox_events WHERE event_id = ?)")
                    .bind(mutation.source_event_id.as_str())
                    .fetch_one(&mut **transaction)
                    .await
                    .map_err(unavailable)?;
            if source_exists == 1 {
                return Err(MatrixDurableError::Conflict);
            }
        }
        if active_dispatch_exists_tx(transaction, mutation).await? {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(row) = sqlx::query(
            "SELECT mutation_sha256, binding_revision, generation \
             FROM matrix_sync_mutations_v2 WHERE source_event_id = ?",
        )
        .bind(mutation.source_event_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?
        {
            let stored_digest: String = row.try_get("mutation_sha256").map_err(unavailable)?;
            let stored_revision = to_u64(row.try_get("binding_revision").map_err(unavailable)?)?;
            let stored_generation = to_u64(row.try_get("generation").map_err(unavailable)?)?;
            if stored_digest != semantic_digest.as_str()
                || stored_revision != mutation.binding_revision
                || stored_generation != mutation.generation
            {
                return Err(MatrixDurableError::Conflict);
            }
            return Ok(MatrixSyncMutationOutcomeV2 {
                source_event_id: mutation.source_event_id.clone(),
                disposition: MatrixSyncMutationDispositionV2::Duplicate,
            });
        }

        // Destructive mutations become logical fences before best-effort
        // physical scrubbing. Both are still in this cursor transaction, so
        // readers can never observe an advanced cursor without the fence.
        if !matches!(&mutation.body, MatrixSyncMutationBodyV2::Timeline { .. }) {
            insert_mutation_ledger_tx(transaction, mutation, &semantic_digest).await?;
        }

        let disposition = match &mutation.body {
            MatrixSyncMutationBodyV2::Timeline {
                event_type,
                payload,
            } => {
                if is_tombstoned_tx(
                    transaction,
                    &mutation.room_id,
                    &mutation.source_event_id,
                    mutation.binding_revision,
                    mutation.generation,
                )
                .await?
                {
                    if inbox_source_exists_tx(transaction, &mutation.source_event_id).await? {
                        // A prior V1 inbox row has already been scrubbed, so
                        // its original payload identity can no longer be
                        // compared. Do not let a later V2 timeline certify a
                        // potentially different meaning for the same ID.
                        return Err(MatrixDurableError::Conflict);
                    }
                    MatrixSyncMutationDispositionV2::Tombstoned
                } else {
                    let draft = InboxDraft {
                        event_id: mutation.source_event_id.clone(),
                        room_id: mutation.room_id.clone(),
                        sender: mutation.sender.clone(),
                        event_type: event_type.clone(),
                        payload: payload.clone(),
                        binding_revision: mutation.binding_revision,
                        generation: mutation.generation,
                        origin_server_ts_ms: mutation.origin_server_ts_ms,
                        received_at_ms: mutation.received_at_ms,
                    };
                    match self.ingest_inbox_tx(transaction, &draft).await? {
                        InboxDisposition::Accepted(_) => MatrixSyncMutationDispositionV2::Applied,
                        InboxDisposition::Duplicate(_) => {
                            MatrixSyncMutationDispositionV2::Duplicate
                        }
                    }
                }
            }
            MatrixSyncMutationBodyV2::Redaction { target_event_id } => {
                let existed =
                    inbox_exists_tx(transaction, &mutation.room_id, target_event_id).await?;
                scrub_event_tx(
                    transaction,
                    &mutation.room_id,
                    target_event_id,
                    mutation.received_at_ms,
                )
                .await?;
                self.append_change(
                    transaction,
                    ChangeKind::InboxRedacted,
                    Some(&mutation.room_id),
                    Some(target_event_id),
                    /*txn_id*/ None,
                    mutation.received_at_ms,
                )
                .await?;
                if existed {
                    MatrixSyncMutationDispositionV2::Applied
                } else {
                    MatrixSyncMutationDispositionV2::Missing
                }
            }
            MatrixSyncMutationBodyV2::RoomLeave { .. } => {
                scrub_room_tx(
                    transaction,
                    &mutation.room_id,
                    mutation.received_at_ms,
                    remaining_scrub_budget,
                )
                .await?;
                self.append_change(
                    transaction,
                    ChangeKind::RoomLeft,
                    Some(&mutation.room_id),
                    Some(&mutation.source_event_id),
                    /*txn_id*/ None,
                    mutation.received_at_ms,
                )
                .await?;
                MatrixSyncMutationDispositionV2::Applied
            }
            MatrixSyncMutationBodyV2::RoomTombstone { .. } => {
                scrub_room_tx(
                    transaction,
                    &mutation.room_id,
                    mutation.received_at_ms,
                    remaining_scrub_budget,
                )
                .await?;
                self.append_change(
                    transaction,
                    ChangeKind::RoomTombstoned,
                    Some(&mutation.room_id),
                    Some(&mutation.source_event_id),
                    /*txn_id*/ None,
                    mutation.received_at_ms,
                )
                .await?;
                MatrixSyncMutationDispositionV2::Applied
            }
        };
        if matches!(&mutation.body, MatrixSyncMutationBodyV2::Timeline { .. }) {
            // Timeline rows are inserted after inbox persistence because the
            // V1 compatibility path treats an unmatched ledger row as a
            // collision. The surrounding transaction remains atomic.
            insert_mutation_ledger_tx(transaction, mutation, &semantic_digest).await?;
        }
        Ok(MatrixSyncMutationOutcomeV2 {
            source_event_id: mutation.source_event_id.clone(),
            disposition,
        })
    }
}

async fn insert_mutation_ledger_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    mutation: &MatrixSyncMutationV2,
    semantic_digest: &Sha256Digest,
) -> Result<(), MatrixDurableError> {
    let (scope_kind, scope_id, reason_kind, replacement_room_id) =
        tombstone_fields(mutation);
    sqlx::query(
        "INSERT INTO matrix_sync_mutations_v2 (
            source_event_id, room_id, sender_user_id, mutation_kind, mutation_sha256,
            tombstone_scope_kind, tombstone_scope_id, tombstone_reason_kind,
            replacement_room_id, binding_revision, generation,
            origin_server_ts_ms, received_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(mutation.source_event_id.as_str())
    .bind(mutation.room_id.as_str())
    .bind(mutation.sender.as_str())
    .bind(mutation_kind(&mutation.body))
    .bind(semantic_digest.as_str())
    .bind(scope_kind)
    .bind(scope_id)
    .bind(reason_kind)
    .bind(replacement_room_id)
    .bind(to_i64(mutation.binding_revision)?)
    .bind(to_i64(mutation.generation)?)
    .bind(to_i64(mutation.origin_server_ts_ms)?)
    .bind(to_i64(mutation.received_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn checkpoint_tx(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<Option<MatrixSyncCheckpoint>, MatrixDurableError> {
    // The V1 table names predate multi-room V2. V2 treats these two values as
    // an account-wide cursor epoch and never rewrites them during room rebind;
    // each mutation verifies its own room revision and generation separately.
    sqlx::query(
        "SELECT owner_agent_id, binding_revision, generation, next_batch, updated_at_ms \
         FROM matrix_sync_checkpoint WHERE singleton = 1",
    )
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| {
        Ok(MatrixSyncCheckpoint {
            owner_agent_id: AgentId::parse(
                row.try_get::<String, _>("owner_agent_id")
                    .map_err(unavailable)?,
            )
            .map_err(|_| MatrixDurableError::Corrupt)?,
            binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
            generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
            next_batch: row.try_get("next_batch").map_err(unavailable)?,
            updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        })
    })
    .transpose()
}

fn verify_checkpoint(
    checkpoint: Option<&MatrixSyncCheckpoint>,
    owner: &AgentId,
    checkpoint_revision: u64,
    checkpoint_generation: u64,
    expected_next_batch: Option<&str>,
) -> Result<(), MatrixDurableError> {
    match (checkpoint, expected_next_batch) {
        (None, None) => Ok(()),
        (Some(checkpoint), Some(expected))
            if checkpoint.owner_agent_id.as_str() == owner.as_str()
                && checkpoint.binding_revision == checkpoint_revision
                && checkpoint.generation == checkpoint_generation
                && checkpoint.next_batch == expected =>
        {
            Ok(())
        }
        (Some(checkpoint), _)
            if checkpoint.owner_agent_id.as_str() != owner.as_str()
                || checkpoint.binding_revision != checkpoint_revision
                || checkpoint.generation != checkpoint_generation =>
        {
            Err(MatrixDurableError::AccessDenied)
        }
        _ => Err(MatrixDurableError::Conflict),
    }
}

async fn advance_checkpoint(
    transaction: &mut Transaction<'_, Sqlite>,
    exists: bool,
    owner: &AgentId,
    batch: &MatrixSyncBatchV2,
    updated_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    if exists {
        let updated = sqlx::query(
            "UPDATE matrix_sync_checkpoint SET next_batch = ?, updated_at_ms = ? \
             WHERE singleton = 1 AND owner_agent_id = ? AND binding_revision = ? \
               AND generation = ? AND next_batch = ?",
        )
        .bind(&batch.next_batch)
        .bind(to_i64(updated_at_ms)?)
        .bind(owner.as_str())
        .bind(to_i64(batch.checkpoint_revision)?)
        .bind(to_i64(batch.checkpoint_generation)?)
        .bind(
            batch
                .expected_next_batch
                .as_deref()
                .ok_or(MatrixDurableError::Conflict)?,
        )
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
    } else {
        sqlx::query(
            "INSERT INTO matrix_sync_checkpoint (
                singleton, owner_agent_id, binding_revision, generation, next_batch, updated_at_ms
             ) VALUES (1, ?, ?, ?, ?, ?)",
        )
        .bind(owner.as_str())
        .bind(to_i64(batch.checkpoint_revision)?)
        .bind(to_i64(batch.checkpoint_generation)?)
        .bind(&batch.next_batch)
        .bind(to_i64(updated_at_ms)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
    }
    Ok(())
}

async fn require_room_binding_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<MatrixUserId, MatrixDurableError> {
    let user_id = sqlx::query_scalar::<_, String>(
        "SELECT agent_user_id FROM room_bindings \
         WHERE room_id = ? AND owner_agent_id = ? AND revision = ? AND generation = ?",
    )
    .bind(room_id.as_str())
    .bind(owner.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or(MatrixDurableError::AccessDenied)?;
    MatrixUserId::parse(user_id).map_err(|_| MatrixDurableError::Corrupt)
}

fn mutation_kind(body: &MatrixSyncMutationBodyV2) -> &'static str {
    match body {
        MatrixSyncMutationBodyV2::Timeline { .. } => "timeline",
        MatrixSyncMutationBodyV2::Redaction { .. } => "redaction",
        MatrixSyncMutationBodyV2::RoomLeave { .. } => "room_leave",
        MatrixSyncMutationBodyV2::RoomTombstone { .. } => "room_tombstone",
    }
}

fn semantic_mutation_identity(
    mutation: &MatrixSyncMutationV2,
) -> MatrixSyncMutationIdentityV2<'_> {
    mutation_identity(mutation, /*received_at_ms*/ None)
}

fn decision_mutation_identity(
    mutation: &MatrixSyncMutationV2,
) -> MatrixSyncMutationIdentityV2<'_> {
    mutation_identity(mutation, Some(mutation.received_at_ms))
}

fn mutation_identity(
    mutation: &MatrixSyncMutationV2,
    received_at_ms: Option<u64>,
) -> MatrixSyncMutationIdentityV2<'_> {
    MatrixSyncMutationIdentityV2 {
        source_event_id: &mutation.source_event_id,
        room_id: &mutation.room_id,
        sender: &mutation.sender,
        binding_revision: mutation.binding_revision,
        generation: mutation.generation,
        origin_server_ts_ms: mutation.origin_server_ts_ms,
        received_at_ms,
        body: mutation_body_identity(&mutation.body),
    }
}

fn mutation_body_identity(
    body: &MatrixSyncMutationBodyV2,
) -> MatrixSyncMutationBodyIdentityV2<'_> {
    match body {
        MatrixSyncMutationBodyV2::Timeline {
            event_type,
            payload,
        } => MatrixSyncMutationBodyIdentityV2::Timeline {
            event_type,
            payload_len: payload.len(),
            payload_sha256: Sha256Digest::for_bytes(payload),
        },
        MatrixSyncMutationBodyV2::Redaction { target_event_id } => {
            MatrixSyncMutationBodyIdentityV2::Redaction { target_event_id }
        }
        MatrixSyncMutationBodyV2::RoomLeave { departed_user_id } => {
            MatrixSyncMutationBodyIdentityV2::RoomLeave { departed_user_id }
        }
        MatrixSyncMutationBodyV2::RoomTombstone {
            replacement_room_id,
        } => MatrixSyncMutationBodyIdentityV2::RoomTombstone {
            replacement_room_id,
        },
    }
}

fn domain_digest(
    domain: &[u8],
    identity: &impl Serialize,
) -> Result<Sha256Digest, MatrixDurableError> {
    let encoded = serde_json::to_vec(identity).map_err(|_| MatrixDurableError::Invalid)?;
    let mut semantic_bytes = Vec::with_capacity(domain.len() + 1 + encoded.len());
    semantic_bytes.extend_from_slice(domain);
    semantic_bytes.push(0);
    semantic_bytes.extend_from_slice(&encoded);
    Ok(Sha256Digest::for_bytes(&semantic_bytes))
}

fn valid_operation_id(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
