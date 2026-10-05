//! Validate journal bookkeeping before any owner write can reuse a change ID.
//! This checks local consistency, not authenticity of a pruned historical chain.

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::AuthBusAuthorityError;
use crate::authority_store::storage;

const INVALID: AuthBusAuthorityError =
    AuthBusAuthorityError::CorruptState("invalid AuthBus frontier sequence");

fn nonnegative_integer(row: &SqliteRow) -> Result<i64, AuthBusAuthorityError> {
    if row.try_get::<&str, _>("value_type").map_err(|_| INVALID)? != "integer" {
        return Err(INVALID);
    }
    let value = row.try_get::<i64, _>("value").map_err(|_| INVALID)?;
    if value < 0 {
        return Err(INVALID);
    }
    Ok(value)
}

/// The caller holds BEGIN IMMEDIATE. No authority mutation may precede this.
/// Seed/fold and pruning commit atomically, so no committed retained event may
/// have an ID at or below the already-applied frontier, even if sqlite_sequence
/// has since advanced again and concealed an earlier rewind.
pub(crate) async fn validate(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<(), AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT typeof(applied_change_id) AS value_type, applied_change_id AS value
         FROM authbus_frontier_accumulator WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(INVALID)?;
    let applied = nonnegative_integer(&row)?;
    // sqlite_sequence itself has no uniqueness/type constraint. Bound the read
    // to two rows: seeing a second matching row is already a corruption error.
    let sequences = sqlx::query(
        "SELECT typeof(seq) AS value_type, seq AS value FROM sqlite_sequence
         WHERE name = 'authbus_frontier_change' LIMIT 2",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(storage)?;
    let first: Option<i64> = sqlx::query_scalar(
        "SELECT change_id FROM authbus_frontier_change ORDER BY change_id LIMIT 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    let last: Option<i64> = sqlx::query_scalar(
        "SELECT change_id FROM authbus_frontier_change ORDER BY change_id DESC LIMIT 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    if first.is_some_and(|first| first <= applied) || first.is_none() != last.is_none() {
        return Err(INVALID);
    }
    match sequences.as_slice() {
        [] if applied == 0 && first.is_none() => Ok(()),
        [row] => {
            let sequence = nonnegative_integer(row)?;
            if sequence < applied || last.is_some_and(|last| last > sequence) {
                return Err(INVALID);
            }
            Ok(())
        }
        _ => Err(INVALID),
    }
}

#[cfg(test)]
#[path = "frontier_sequence_tests.rs"]
mod tests;
