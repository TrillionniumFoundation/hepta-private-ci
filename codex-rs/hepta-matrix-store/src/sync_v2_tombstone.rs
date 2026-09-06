use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationDispositionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationOutcomeV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::MatrixDurableError;
use crate::MatrixEventId;
use crate::MatrixRoomId;

const MUTATION_JOURNAL_CAPACITY: i64 = 65_536;
const DECISION_JOURNAL_CAPACITY: i64 = 65_536;
const OUTCOME_JOURNAL_CAPACITY: i64 = 33_554_432;
const DELETION_DECISION_RESERVE: i64 = 4_096;
const DELETION_MUTATION_RESERVE: i64 = 4_096;
const DELETION_OUTCOME_RESERVE: i64 = 4_096;

pub(crate) async fn is_tombstoned_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    event_id: &MatrixEventId,
    binding_revision: u64,
    generation: u64,
) -> Result<bool, MatrixDurableError> {
    let blocked: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM matrix_sync_mutations_v2
            WHERE (tombstone_scope_kind = 'event' AND tombstone_scope_id = ? AND room_id = ?)
               OR (tombstone_scope_kind = 'room' AND tombstone_scope_id = ? AND (
                    tombstone_reason_kind = 'room_replacement'
                    OR (tombstone_reason_kind = 'room_leave'
                        AND binding_revision = ? AND generation = ?)
               ))
         )",
    )
    .bind(event_id.as_str())
    .bind(room_id.as_str())
    .bind(room_id.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(blocked == 1)
}

pub(crate) async fn is_room_tombstoned_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
) -> Result<bool, MatrixDurableError> {
    let blocked: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM matrix_sync_mutations_v2
            WHERE tombstone_scope_kind = 'room' AND tombstone_scope_id = ?
              AND (tombstone_reason_kind = 'room_replacement'
                   OR (tombstone_reason_kind = 'room_leave'
                       AND binding_revision = ? AND generation = ?))
         )",
    )
    .bind(room_id.as_str())
    .bind(to_i64(binding_revision)?)
    .bind(to_i64(generation)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(blocked == 1)
}

pub(crate) async fn is_room_replaced_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
) -> Result<bool, MatrixDurableError> {
    let replaced: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM matrix_sync_mutations_v2
            WHERE tombstone_scope_kind = 'room' AND tombstone_scope_id = ?
              AND tombstone_reason_kind = 'room_replacement'
         )",
    )
    .bind(room_id.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(replaced == 1)
}

pub(crate) async fn active_dispatch_exists_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    mutation: &MatrixSyncMutationV2,
) -> Result<bool, MatrixDurableError> {
    let target_event_id = match &mutation.body {
        MatrixSyncMutationBodyV2::Redaction { target_event_id } => {
            target_event_id
        }
        MatrixSyncMutationBodyV2::Timeline { .. }
        | MatrixSyncMutationBodyV2::RoomLeave { .. }
        | MatrixSyncMutationBodyV2::RoomTombstone { .. } => return Ok(false),
    };
    let exists: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM matrix_actionable_inbox_dispatches_v2
            WHERE event_id = ? AND room_id = ?
              AND binding_revision = ? AND generation = ?
              AND state IN ('begun', 'queued', 'admitted')
         )",
    )
    .bind(target_event_id.as_str())
    .bind(mutation.room_id.as_str())
    .bind(to_i64(mutation.binding_revision)?)
    .bind(to_i64(mutation.generation)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(exists == 1)
}

pub(crate) fn tombstone_fields(
    mutation: &MatrixSyncMutationV2,
) -> (Option<&'static str>, Option<&str>, Option<&'static str>, Option<&str>) {
    match &mutation.body {
        MatrixSyncMutationBodyV2::Timeline { .. } => (None, None, None, None),
        MatrixSyncMutationBodyV2::Redaction { target_event_id } => {
            (Some("event"), Some(target_event_id.as_str()), Some("redaction"), None)
        }
        MatrixSyncMutationBodyV2::RoomLeave { .. } => (
            Some("room"),
            Some(mutation.room_id.as_str()),
            Some("room_leave"),
            None,
        ),
        MatrixSyncMutationBodyV2::RoomTombstone {
            replacement_room_id,
        } => (
            Some("room"),
            Some(mutation.room_id.as_str()),
            Some("room_replacement"),
            Some(replacement_room_id.as_str()),
        ),
    }
}

/// Preflight the immutable journal while the caller holds `BEGIN IMMEDIATE`.
///
/// Normal timeline traffic cannot consume the final reserve. A destructive-
/// only batch may use it, while exhaustion is surfaced as a terminal capacity
/// condition instead of an ambiguous transient storage failure.
pub(crate) async fn has_commit_capacity_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    batch: &MatrixSyncBatchV2,
) -> Result<bool, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT
            (SELECT COALESCE(MAX(ledger_seq), 0) FROM matrix_sync_mutations_v2)
                AS mutation_seq,
            (SELECT COALESCE(MAX(decision_seq), 0) FROM matrix_sync_decisions_v2)
                AS decision_seq,
            (SELECT COALESCE(MAX(outcome_seq), 0)
             FROM matrix_sync_decision_outcomes_v2) AS outcome_seq",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let mutation_seq: i64 = row.try_get("mutation_seq").map_err(unavailable)?;
    let decision_seq: i64 = row.try_get("decision_seq").map_err(unavailable)?;
    let outcome_seq: i64 = row.try_get("outcome_seq").map_err(unavailable)?;
    if !(0..=MUTATION_JOURNAL_CAPACITY).contains(&mutation_seq)
        || !(0..=DECISION_JOURNAL_CAPACITY).contains(&decision_seq)
        || !(0..=OUTCOME_JOURNAL_CAPACITY).contains(&outcome_seq)
    {
        return Err(MatrixDurableError::Corrupt);
    }
    let destructive_only = !batch.mutations.is_empty()
        && batch
            .mutations
            .iter()
            .all(|mutation| {
                !matches!(&mutation.body, MatrixSyncMutationBodyV2::Timeline { .. })
            });
    let mutation_limit = if destructive_only {
        MUTATION_JOURNAL_CAPACITY
    } else {
        MUTATION_JOURNAL_CAPACITY - DELETION_MUTATION_RESERVE
    };
    let decision_limit = if destructive_only {
        DECISION_JOURNAL_CAPACITY
    } else {
        DECISION_JOURNAL_CAPACITY - DELETION_DECISION_RESERVE
    };
    let outcome_limit = if destructive_only {
        OUTCOME_JOURNAL_CAPACITY
    } else {
        OUTCOME_JOURNAL_CAPACITY - DELETION_OUTCOME_RESERVE
    };
    let mut new_mutations = 0_i64;
    for mutation in &batch.mutations {
        let exists: i64 = sqlx::query_scalar(
            "SELECT EXISTS(
                SELECT 1 FROM matrix_sync_mutations_v2 WHERE source_event_id = ?
             )",
        )
        .bind(mutation.source_event_id.as_str())
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if exists == 0 {
            new_mutations = new_mutations
                .checked_add(1)
                .ok_or(MatrixDurableError::Corrupt)?;
        }
    }
    if mutation_seq
        .checked_add(new_mutations)
        .is_none_or(|next| next > mutation_limit)
        || decision_seq
            .checked_add(1)
            .is_none_or(|next| next > decision_limit)
        || outcome_seq
            .checked_add(batch.mutations.len() as i64)
            .is_none_or(|next| next > outcome_limit)
    {
        return Ok(false);
    }
    Ok(true)
}

pub(crate) async fn has_cancel_capacity_tx(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<bool, MatrixDurableError> {
    let decision_seq: i64 = sqlx::query_scalar(
        "SELECT COALESCE(MAX(decision_seq), 0) FROM matrix_sync_decisions_v2",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if !(0..=DECISION_JOURNAL_CAPACITY).contains(&decision_seq) {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(decision_seq < DECISION_JOURNAL_CAPACITY - DELETION_DECISION_RESERVE)
}
