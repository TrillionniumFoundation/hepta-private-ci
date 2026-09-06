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
        MatrixSyncMutationBodyV2::Redaction { target_event_id } => target_event_id,
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
) -> (
    Option<&'static str>,
    Option<&str>,
    Option<&'static str>,
    Option<&str>,
) {
    match &mutation.body {
        MatrixSyncMutationBodyV2::Timeline { .. } => (None, None, None, None),
        MatrixSyncMutationBodyV2::Redaction { target_event_id } => (
            Some("event"),
            Some(target_event_id.as_str()),
            Some("redaction"),
            None,
        ),
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
            .all(|mutation| !matches!(&mutation.body, MatrixSyncMutationBodyV2::Timeline { .. }));
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
    let decision_seq: i64 =
        sqlx::query_scalar("SELECT COALESCE(MAX(decision_seq), 0) FROM matrix_sync_decisions_v2")
            .fetch_one(&mut **transaction)
            .await
            .map_err(unavailable)?;
    if !(0..=DECISION_JOURNAL_CAPACITY).contains(&decision_seq) {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(decision_seq < DECISION_JOURNAL_CAPACITY - DELETION_DECISION_RESERVE)
}

pub(crate) async fn recover_decision_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    expected_kind: &str,
    expected_digest: &Sha256Digest,
    expected_mutations: Option<&[MatrixSyncMutationV2]>,
) -> Result<Option<MatrixSyncResultV2>, MatrixDurableError> {
    read_decision_tx(
        transaction,
        operation_id,
        Some(expected_kind),
        Some(expected_digest),
        expected_mutations,
    )
    .await
}

pub(crate) async fn lookup_decision_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<MatrixSyncResultV2>, MatrixDurableError> {
    read_decision_tx(
        transaction,
        operation_id,
        /*expected_kind*/ None,
        /*expected_digest*/ None,
        /*expected_mutations*/ None,
    )
    .await
}

async fn read_decision_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    expected_kind: Option<&str>,
    expected_digest: Option<&Sha256Digest>,
    expected_mutations: Option<&[MatrixSyncMutationV2]>,
) -> Result<Option<MatrixSyncResultV2>, MatrixDurableError> {
    let Some(row) = sqlx::query(
        "SELECT decision_seq, decision_kind, decision_sha256, schema_version,
                checkpoint_revision, checkpoint_generation, next_batch,
                retained_next_batch, outcome_count
         FROM matrix_sync_decisions_v2 WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    else {
        return Ok(None);
    };
    let decision_kind: String = row.try_get("decision_kind").map_err(unavailable)?;
    let decision_sha256: String = row.try_get("decision_sha256").map_err(unavailable)?;
    match (expected_kind, expected_digest) {
        (Some(kind), Some(digest))
            if decision_kind != kind || decision_sha256 != digest.as_str() =>
        {
            return Err(MatrixDurableError::Conflict);
        }
        (Some(_), Some(_)) | (None, None) => {}
        _ => return Err(MatrixDurableError::Corrupt),
    }
    let decision_seq: i64 = row.try_get("decision_seq").map_err(unavailable)?;
    let schema_version = to_u32(row.try_get("schema_version").map_err(unavailable)?)?;
    let checkpoint_revision = to_u64(row.try_get("checkpoint_revision").map_err(unavailable)?)?;
    let checkpoint_generation = to_u64(row.try_get("checkpoint_generation").map_err(unavailable)?)?;
    let next_batch: Option<String> = row.try_get("next_batch").map_err(unavailable)?;
    let retained_next_batch: Option<String> =
        row.try_get("retained_next_batch").map_err(unavailable)?;
    let outcome_count = to_usize(row.try_get("outcome_count").map_err(unavailable)?)?;
    if !(1..=65_536).contains(&decision_seq)
        || schema_version != MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2
        || checkpoint_revision == 0
        || checkpoint_generation == 0
        || outcome_count > 512
    {
        return Err(MatrixDurableError::Corrupt);
    }
    match decision_kind.as_str() {
        "commit" => {
            let next_batch = next_batch
                .filter(|value| valid_sync_token(value.as_str()))
                .ok_or(MatrixDurableError::Corrupt)?;
            if retained_next_batch.is_some()
                || expected_mutations.is_some_and(|mutations| mutations.len() != outcome_count)
            {
                return Err(MatrixDurableError::Corrupt);
            }
            let rows = sqlx::query(
                "SELECT outcome_index, source_event_id, disposition
                 FROM matrix_sync_decision_outcomes_v2
                 WHERE decision_seq = ? ORDER BY outcome_index",
            )
            .bind(decision_seq)
            .fetch_all(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if rows.len() != outcome_count {
                return Err(MatrixDurableError::Corrupt);
            }
            let mut outcomes = Vec::with_capacity(rows.len());
            for (expected_index, outcome) in rows.iter().enumerate() {
                if to_usize(outcome.try_get("outcome_index").map_err(unavailable)?)?
                    != expected_index
                {
                    return Err(MatrixDurableError::Corrupt);
                }
                let source_event_id = MatrixEventId::parse(
                    outcome
                        .try_get::<String, _>("source_event_id")
                        .map_err(unavailable)?,
                )
                .map_err(|_| MatrixDurableError::Corrupt)?;
                if let Some(expected_mutations) = expected_mutations
                    && source_event_id.as_str()
                        != expected_mutations[expected_index].source_event_id.as_str()
                {
                    return Err(MatrixDurableError::Corrupt);
                }
                outcomes.push(MatrixSyncMutationOutcomeV2 {
                    source_event_id,
                    disposition: parse_disposition(
                        &outcome
                            .try_get::<String, _>("disposition")
                            .map_err(unavailable)?,
                    )?,
                });
            }
            Ok(Some(MatrixSyncResultV2::Committed {
                schema_version,
                operation_id: operation_id.to_string(),
                checkpoint_revision,
                checkpoint_generation,
                next_batch,
                outcomes,
            }))
        }
        "cancel" => {
            if expected_mutations.is_some()
                || next_batch.is_some()
                || outcome_count != 0
                || retained_next_batch
                    .as_deref()
                    .is_some_and(|value| !valid_sync_token(value))
            {
                return Err(MatrixDurableError::Corrupt);
            }
            Ok(Some(MatrixSyncResultV2::Cancelled {
                schema_version,
                operation_id: operation_id.to_string(),
                checkpoint_revision,
                checkpoint_generation,
                retained_next_batch,
            }))
        }
        _ => Err(MatrixDurableError::Corrupt),
    }
}

pub(crate) async fn insert_commit_decision_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    batch: &MatrixSyncBatchV2,
    digest: &Sha256Digest,
) -> Result<i64, MatrixDurableError> {
    let inserted = sqlx::query(
        "INSERT INTO matrix_sync_decisions_v2 (
            operation_id, decision_kind, decision_sha256, schema_version,
            checkpoint_revision, checkpoint_generation, expected_next_batch, next_batch,
            retained_next_batch, outcome_count
         ) VALUES (?, 'commit', ?, ?, ?, ?, ?, ?, NULL, ?)",
    )
    .bind(&batch.operation_id)
    .bind(digest.as_str())
    .bind(i64::from(batch.schema_version))
    .bind(to_i64(batch.checkpoint_revision)?)
    .bind(to_i64(batch.checkpoint_generation)?)
    .bind(batch.expected_next_batch.as_deref())
    .bind(&batch.next_batch)
    .bind(to_i64(batch.mutations.len() as u64)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(inserted.last_insert_rowid())
}

pub(crate) async fn insert_cancel_decision_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    digest: &Sha256Digest,
    checkpoint_revision: u64,
    checkpoint_generation: u64,
    expected_next_batch: Option<&str>,
    retained_next_batch: Option<&str>,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT INTO matrix_sync_decisions_v2 (
            operation_id, decision_kind, decision_sha256, schema_version,
            checkpoint_revision, checkpoint_generation, expected_next_batch, next_batch,
            retained_next_batch, outcome_count
         ) VALUES (?, 'cancel', ?, ?, ?, ?, ?, NULL, ?, 0)",
    )
    .bind(operation_id)
    .bind(digest.as_str())
    .bind(i64::from(MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2))
    .bind(to_i64(checkpoint_revision)?)
    .bind(to_i64(checkpoint_generation)?)
    .bind(expected_next_batch)
    .bind(retained_next_batch)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn insert_decision_outcomes_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    decision_seq: i64,
    outcomes: &[MatrixSyncMutationOutcomeV2],
) -> Result<(), MatrixDurableError> {
    for (outcome_index, outcome) in outcomes.iter().enumerate() {
        sqlx::query(
            "INSERT INTO matrix_sync_decision_outcomes_v2 (
                decision_seq, outcome_index, source_event_id, disposition
             ) VALUES (?, ?, ?, ?)",
        )
        .bind(decision_seq)
        .bind(to_i64(outcome_index as u64)?)
        .bind(outcome.source_event_id.as_str())
        .bind(disposition_str(outcome.disposition))
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
    }
    Ok(())
}

pub(crate) async fn inbox_exists_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    event_id: &MatrixEventId,
) -> Result<bool, MatrixDurableError> {
    let count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM inbox_events WHERE room_id = ? AND event_id = ?")
            .bind(room_id.as_str())
            .bind(event_id.as_str())
            .fetch_one(&mut **transaction)
            .await
            .map_err(unavailable)?;
    Ok(count == 1)
}

pub(crate) async fn inbox_source_exists_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<bool, MatrixDurableError> {
    let count: i64 =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM inbox_events WHERE event_id = ?)")
            .bind(event_id.as_str())
            .fetch_one(&mut **transaction)
            .await
            .map_err(unavailable)?;
    Ok(count == 1)
}

pub(crate) async fn scrub_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    event_id: &MatrixEventId,
    recorded_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let empty_digest = Sha256Digest::for_bytes(&[]);
    sqlx::query(
        "UPDATE inbox_events SET payload = X'', payload_sha256 = ?,
         state = 'processed', processed_at_ms = CASE WHEN state = 'pending'
         THEN MAX(received_at_ms, ?) ELSE processed_at_ms END
         WHERE room_id = ? AND event_id = ?",
    )
    .bind(empty_digest.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .bind(room_id.as_str())
    .bind(event_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn scrub_room_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    room_id: &MatrixRoomId,
    recorded_at_ms: u64,
    remaining_budget: &mut usize,
) -> Result<(), MatrixDurableError> {
    if *remaining_budget == 0 {
        return Ok(());
    }
    let cursors = sqlx::query_scalar::<_, i64>(
        "SELECT inbox_cursor FROM inbox_events
         WHERE room_id = ? AND (length(payload) > 0 OR state != 'processed')
         ORDER BY inbox_cursor LIMIT ?",
    )
    .bind(room_id.as_str())
    .bind(to_i64(*remaining_budget as u64)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    *remaining_budget -= cursors.len();
    for cursor in cursors {
        scrub_inbox_cursor_tx(transaction, cursor, recorded_at_ms).await?;
    }
    Ok(())
}

async fn scrub_inbox_cursor_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    inbox_cursor: i64,
    recorded_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let empty_digest = Sha256Digest::for_bytes(&[]);
    sqlx::query(
        "UPDATE inbox_events SET payload = X'', payload_sha256 = ?,
         state = 'processed', processed_at_ms = CASE WHEN state = 'pending'
         THEN MAX(received_at_ms, ?) ELSE processed_at_ms END
         WHERE inbox_cursor = ?",
    )
    .bind(empty_digest.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .bind(inbox_cursor)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn disposition_str(disposition: MatrixSyncMutationDispositionV2) -> &'static str {
    match disposition {
        MatrixSyncMutationDispositionV2::Applied => "applied",
        MatrixSyncMutationDispositionV2::Duplicate => "duplicate",
        MatrixSyncMutationDispositionV2::Missing => "missing",
        MatrixSyncMutationDispositionV2::Tombstoned => "tombstoned",
    }
}

fn parse_disposition(value: &str) -> Result<MatrixSyncMutationDispositionV2, MatrixDurableError> {
    match value {
        "applied" => Ok(MatrixSyncMutationDispositionV2::Applied),
        "duplicate" => Ok(MatrixSyncMutationDispositionV2::Duplicate),
        "missing" => Ok(MatrixSyncMutationDispositionV2::Missing),
        "tombstoned" => Ok(MatrixSyncMutationDispositionV2::Tombstoned),
        _ => Err(MatrixDurableError::Corrupt),
    }
}

fn valid_sync_token(value: &str) -> bool {
    (1..=4_096).contains(&value.len()) && value.bytes().all(|byte| (b' '..=b'~').contains(&byte))
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn to_u32(value: i64) -> Result<u32, MatrixDurableError> {
    u32::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn to_usize(value: i64) -> Result<usize, MatrixDurableError> {
    usize::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
