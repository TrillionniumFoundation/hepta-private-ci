//! Bounded startup verification for durable automation occurrence history.
//!
//! The implementation remains in `lifecycle.rs`; this wrapper preserves its
//! public API while replacing the old whole-history `fetch_all` verifier with a
//! fixed-memory keyset scan. A corrupt row on any page still fails startup.

#[path = "lifecycle.rs"]
#[allow(
    dead_code,
    reason = "the wrapper replaces only the legacy unbounded verifier"
)]
mod implementation;

pub use implementation::AutomationMissedRunPolicy;
pub use implementation::AutomationOccurrence;
pub use implementation::AutomationOccurrenceState;
pub use implementation::AutomationOccurrenceTerminalState;
pub use implementation::AutomationOccurrenceWork;
pub use implementation::AutomationOverlapPolicy;
pub use implementation::AutomationSchedulePolicy;
pub use implementation::deterministic_occurrence_id;

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationTaskId;

const OCCURRENCE_VERIFY_PAGE_SIZE: i64 = 256;
const MAX_TERMINAL_SCAN_CURSOR_BYTES: usize = 2_048;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

pub(crate) async fn verify_occurrence_store(
    pool: &sqlx::SqlitePool,
    expected_owner: &str,
) -> Result<(), AutomationError> {
    let mut cursor: Option<(String, i64)> = None;
    loop {
        let rows = if let Some((task_id, occurrence)) = cursor.as_ref() {
            sqlx::query(
                "SELECT * FROM automation_occurrence_lifecycle
                 WHERE task_id > ? OR (task_id = ? AND occurrence > ?)
                 ORDER BY task_id, occurrence LIMIT ?",
            )
            .bind(task_id)
            .bind(task_id)
            .bind(*occurrence)
            .bind(OCCURRENCE_VERIFY_PAGE_SIZE)
            .fetch_all(pool)
            .await
            .map_err(unavailable)?
        } else {
            sqlx::query(
                "SELECT * FROM automation_occurrence_lifecycle
                 ORDER BY task_id, occurrence LIMIT ?",
            )
            .bind(OCCURRENCE_VERIFY_PAGE_SIZE)
            .fetch_all(pool)
            .await
            .map_err(unavailable)?
        };
        if rows.is_empty() {
            return Ok(());
        }
        for row in &rows {
            verify_occurrence_row(row, expected_owner)?;
        }
        let last = rows.last().ok_or(AutomationError::Corrupt)?;
        cursor = Some((
            last.try_get("task_id")
                .map_err(|_| AutomationError::Corrupt)?,
            last.try_get("occurrence")
                .map_err(|_| AutomationError::Corrupt)?,
        ));
        if i64::try_from(rows.len()).map_err(|_| AutomationError::Corrupt)?
            < OCCURRENCE_VERIFY_PAGE_SIZE
        {
            return Ok(());
        }
    }
}

fn verify_occurrence_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &str,
) -> Result<(), AutomationError> {
    let owner: String = required(row, "owner_agent_id")?;
    if owner != expected_owner {
        return Err(AutomationError::AccessDenied);
    }
    let task_raw: String = required(row, "task_id")?;
    let task_id = AutomationTaskId::parse(&task_raw).map_err(|_| AutomationError::Corrupt)?;
    let _occurrence = nonnegative(required::<i64>(row, "occurrence")?)?;
    let schedule_revision = nonnegative(required::<i64>(row, "schedule_revision")?)?;
    let scheduled_for_ms = nonnegative(required::<i64>(row, "scheduled_for_ms")?)?;
    let occurrence_id: String = required(row, "occurrence_id")?;
    if occurrence_id
        != deterministic_occurrence_id(expected_owner, task_id, schedule_revision, scheduled_for_ms)
    {
        return Err(AutomationError::Corrupt);
    }
    let taskflow_run_id: String = required(row, "taskflow_run_id")?;
    let expected_run_id = format!(
        "automation-run:{}",
        Sha256Digest::for_bytes(occurrence_id.as_bytes()).as_str()
    );
    if taskflow_run_id != expected_run_id {
        return Err(AutomationError::Corrupt);
    }

    let state: String = required(row, "state")?;
    if !matches!(
        state.as_str(),
        "claimed" | "admitted" | "running" | "succeeded" | "failed" | "cancelled" | "indeterminate"
    ) {
        return Err(AutomationError::Corrupt);
    }
    let overlap: String = required(row, "overlap_policy")?;
    if !matches!(overlap.as_str(), "forbid" | "allow") {
        return Err(AutomationError::Corrupt);
    }
    let _: String = required(row, "client_user_message_id")?;
    let _ = nonnegative(required::<i64>(row, "claim_generation")?)?;
    let _: String = required(row, "claim_token")?;
    u32::try_from(required::<i64>(row, "step_attempt")?).map_err(|_| AutomationError::Corrupt)?;
    let _: Option<String> = optional(row, "queued_submission_id")?;
    let _: Option<String> = optional(row, "provider_payload_sha256")?;
    let _: Option<String> = optional(row, "turn_id")?;

    let cursor: Option<String> = optional(row, "terminal_scan_cursor")?;
    if cursor
        .as_ref()
        .is_some_and(|value| value.is_empty() || value.len() > MAX_TERMINAL_SCAN_CURSOR_BYTES)
    {
        return Err(AutomationError::Corrupt);
    }
    let terminal_digest: Option<String> = optional(row, "terminal_receipt_digest")?;
    if let Some(value) = terminal_digest.as_deref() {
        validate_digest(value)?;
    }
    let _ = nonnegative(required::<i64>(row, "updated_at_ms")?)?;
    if let Some(value) = optional::<i64>(row, "terminal_at_ms")? {
        let _ = nonnegative(value)?;
    }
    Ok(())
}

fn required<T>(row: &sqlx::sqlite::SqliteRow, name: &str) -> Result<T, AutomationError>
where
    for<'r> T: sqlx::Decode<'r, sqlx::Sqlite> + sqlx::Type<sqlx::Sqlite>,
{
    row.try_get(name).map_err(|_| AutomationError::Corrupt)
}

fn optional<T>(row: &sqlx::sqlite::SqliteRow, name: &str) -> Result<Option<T>, AutomationError>
where
    for<'r> T: sqlx::Decode<'r, sqlx::Sqlite> + sqlx::Type<sqlx::Sqlite>,
{
    row.try_get(name).map_err(|_| AutomationError::Corrupt)
}

fn nonnegative(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn validate_digest(value: &str) -> Result<(), AutomationError> {
    if value == ZERO_DIGEST
        || value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AutomationError::Corrupt);
    }
    Ok(())
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

#[cfg(test)]
mod tests {
    use sqlx::sqlite::SqlitePoolOptions;

    use super::*;

    #[tokio::test]
    async fn bounded_startup_scan_rejects_corruption_after_the_first_page() {
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect("sqlite::memory:")
            .await
            .expect("pool");
        sqlx::query(
            "CREATE TABLE automation_occurrence_lifecycle (
                task_id TEXT NOT NULL,
                occurrence INTEGER NOT NULL,
                occurrence_id TEXT NOT NULL,
                owner_agent_id TEXT NOT NULL,
                schedule_revision INTEGER NOT NULL,
                scheduled_for_ms INTEGER NOT NULL,
                client_user_message_id TEXT NOT NULL,
                state TEXT NOT NULL,
                overlap_policy TEXT NOT NULL,
                claim_generation INTEGER NOT NULL,
                claim_token TEXT NOT NULL,
                step_attempt INTEGER NOT NULL,
                taskflow_run_id TEXT NOT NULL,
                queued_submission_id TEXT,
                provider_payload_sha256 TEXT,
                turn_id TEXT,
                terminal_scan_cursor TEXT,
                terminal_receipt_digest TEXT,
                updated_at_ms INTEGER NOT NULL,
                terminal_at_ms INTEGER,
                PRIMARY KEY(task_id, occurrence)
             )",
        )
        .execute(&pool)
        .await
        .expect("schema");

        let owner = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
        let mut task_ids = (0..257)
            .map(|_| AutomationTaskId::new())
            .collect::<Vec<_>>();
        task_ids.sort_by_key(ToString::to_string);
        for (index, task_id) in task_ids.iter().enumerate() {
            let scheduled_for_ms = u64::try_from(index + 1).expect("time");
            let occurrence_id = deterministic_occurrence_id(owner, *task_id, 1, scheduled_for_ms);
            let run_id = format!(
                "automation-run:{}",
                Sha256Digest::for_bytes(occurrence_id.as_bytes()).as_str()
            );
            sqlx::query(
                "INSERT INTO automation_occurrence_lifecycle (
                    task_id, occurrence, occurrence_id, owner_agent_id,
                    schedule_revision, scheduled_for_ms, client_user_message_id,
                    state, overlap_policy, claim_generation, claim_token,
                    step_attempt, taskflow_run_id, updated_at_ms
                 ) VALUES (?, 1, ?, ?, 1, ?, ?, 'claimed', 'allow', 1, ?, 1, ?, ?)",
            )
            .bind(task_id.to_string())
            .bind(occurrence_id)
            .bind(owner)
            .bind(i64::try_from(scheduled_for_ms).expect("time i64"))
            .bind(format!("client-{index}"))
            .bind(format!("claim-{index}"))
            .bind(run_id)
            .bind(i64::try_from(scheduled_for_ms).expect("update i64"))
            .execute(&pool)
            .await
            .expect("insert");
        }
        verify_occurrence_store(&pool, owner)
            .await
            .expect("valid paged history");

        let last = task_ids.last().expect("second-page task").to_string();
        sqlx::query(
            "UPDATE automation_occurrence_lifecycle
             SET occurrence_id = 'tampered' WHERE task_id = ?",
        )
        .bind(last)
        .execute(&pool)
        .await
        .expect("corrupt later page");
        assert!(matches!(
            verify_occurrence_store(&pool, owner).await,
            Err(AutomationError::Corrupt)
        ));
    }
}
