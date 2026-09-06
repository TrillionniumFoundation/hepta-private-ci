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
