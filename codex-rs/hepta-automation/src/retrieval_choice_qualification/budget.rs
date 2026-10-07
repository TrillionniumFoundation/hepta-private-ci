use sqlx::Column;
use sqlx::Row;
use sqlx::TypeInfo;
use sqlx::ValueRef;
use sqlx::sqlite::SqliteRow;

use super::FixtureError;
use super::encoding::FieldValue;
use super::encoding::MAX_RETAINED_BYTES;
use super::encoding::RetainedBudget;
use super::encoding::encode_record;
use super::records::PhaseCommand;
use super::records::PhaseOperation;

// Conservative capacity reservation for fixed metadata, two native step rows,
// one native Cancel event, its full command, and the complete run projection.
// This is a sizing upper bound for this fixed profile, not a category quota.
// Actual retained SQL rows are independently counted before EVERY commit.
const FIXED_PROFILE_OVERHEAD_BOUND: usize = 12_000;

pub(crate) fn reserve(command: &PhaseCommand) -> Result<(), FixtureError> {
    let mut prepare = command.clone();
    prepare.operation = PhaseOperation::Prepare;
    prepare.command_id = "xxxxxxxx".to_owned();
    prepare.prepare_digest = None;
    prepare.now_ms = i64::MAX as u64;
    let mut claim = prepare.claim(i64::MAX as u64)?;
    claim.command_id = "xxxxxxxx".to_owned();
    let maximum = prepare
        .canonical()?
        .0
        .len()
        .checked_add(claim.canonical()?.0.len())
        .and_then(|n| n.checked_add(FIXED_PROFILE_OVERHEAD_BOUND))
        .ok_or(FixtureError::Budget)?;
    if maximum > MAX_RETAINED_BYTES {
        return Err(FixtureError::Budget);
    }
    Ok(())
}

enum OwnedValue {
    Null,
    Uint(u64),
    Text(String),
    Blob(Vec<u8>),
}

fn charge_row(budget: &mut RetainedBudget, row: &SqliteRow) -> Result<(), FixtureError> {
    let mut owned = Vec::new();
    for (index, column) in row.columns().iter().enumerate() {
        let raw = row.try_get_raw(index)?;
        let value = if raw.is_null() {
            OwnedValue::Null
        } else {
            match raw.type_info().name() {
                "INTEGER" => OwnedValue::Uint(
                    u64::try_from(row.try_get::<i64, _>(index)?)
                        .map_err(|_| FixtureError::Invalid)?,
                ),
                "TEXT" => OwnedValue::Text(row.try_get(index)?),
                "BLOB" => OwnedValue::Blob(row.try_get(index)?),
                _ => return Err(FixtureError::Invalid),
            }
        };
        owned.push((column.name().to_owned(), value));
    }
    let fields: Vec<_> = owned
        .iter()
        .map(|(name, value)| {
            let value = match value {
                OwnedValue::Null => FieldValue::Null,
                OwnedValue::Uint(value) => FieldValue::Uint(*value),
                OwnedValue::Text(value) => FieldValue::Text(value),
                OwnedValue::Blob(value) => FieldValue::Blob(value),
            };
            (name.as_str(), value)
        })
        .collect();
    let record = encode_record(&fields).map_err(|_| FixtureError::Budget)?;
    budget.charge(&record).map_err(|_| FixtureError::Budget)
}

pub(crate) async fn retained_bytes(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    command: &PhaseCommand,
    bootstrap_event_seq: i64,
) -> Result<usize, FixtureError> {
    let mut budget = RetainedBudget::default();
    // Complete static SQL literals satisfy SqlSafeStr. LIMIT 65 bounds row
    // count only, not heap bytes; this private synthetic profile is bounded.
    // Every column and retained duplicate is charged after fetch.
    for (sql, has_floor) in [
        (
            "SELECT * FROM qualification_retrieval_choices WHERE owner_agent_id = ? AND run_id = ? LIMIT 65",
            false,
        ),
        (
            "SELECT * FROM qualification_retrieval_claims WHERE owner_agent_id = ? AND run_id = ? LIMIT 65",
            false,
        ),
        (
            "SELECT * FROM taskflow_step_outbox WHERE owner_agent_id = ? AND run_id = ? LIMIT 65",
            false,
        ),
        (
            "SELECT * FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ? LIMIT 65",
            false,
        ),
        (
            "SELECT * FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ? AND event_seq > ? LIMIT 65",
            true,
        ),
    ] {
        let mut query = sqlx::query(sql)
            .bind(command.fence.owner_agent_id.as_str())
            .bind(&command.run_id);
        if has_floor {
            query = query.bind(bootstrap_event_seq);
        }
        let rows = query.fetch_all(&mut **tx).await?;
        if rows.len() >= 65 {
            return Err(FixtureError::Budget);
        }
        for row in &rows {
            charge_row(&mut budget, row)?;
        }
    }
    Ok(budget.used())
}
