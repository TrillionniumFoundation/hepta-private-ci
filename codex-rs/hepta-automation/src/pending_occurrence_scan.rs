//! Bounded read-only discovery and exact lookup of admitted recovery work.

use super::recovery_scan::RecoveryScanCursor;
use super::recovery_scan::RecoveryScanTable;
use super::*;
use crate::AutomationOccurrenceWork;

macro_rules! pending_occurrence_window_sql {
    () => {
        "SELECT rowid AS scan_rowid, task_id, occurrence, owner_agent_id, state
             FROM automation_occurrence_lifecycle NOT INDEXED
             WHERE rowid > ? AND rowid <= ? ORDER BY rowid LIMIT 64"
    };
}

const PENDING_OCCURRENCE_WINDOW_SQL: &str = pending_occurrence_window_sql!();
#[cfg(test)]
const PENDING_OCCURRENCE_EXPLAIN_SQL: &str =
    concat!("EXPLAIN QUERY PLAN ", pending_occurrence_window_sql!());
const PENDING_OCCURRENCE_LOOKUP_SQL: &str =
    "SELECT o.*, t.thread_id, t.prompt, t.owner_agent_id AS task_owner
         FROM automation_occurrence_lifecycle o
         LEFT JOIN automation_tasks t ON t.task_id = o.task_id
         WHERE o.task_id = ? AND o.occurrence = ? AND o.owner_agent_id = ?
           AND o.state IN ('admitted', 'running', 'indeterminate')";

/// A non-serializable scheduling position bound to one live store and its clones.
/// Restart creates a fresh scan; this cursor grants no authority to replay effects.
#[derive(Debug)]
pub struct AutomationPendingOccurrenceScan {
    cursor: RecoveryScanCursor,
}

impl AutomationStore {
    /// Start a finite read-only scan for this live observer/store identity.
    pub fn pending_occurrence_scan(&self) -> AutomationPendingOccurrenceScan {
        AutomationPendingOccurrenceScan {
            cursor: RecoveryScanCursor::for_store(self),
        }
    }

    /// Inspect at most 64 physical lifecycle rows, then hydrate at most one
    /// eligible owned row in the same snapshot. An empty page is not evidence
    /// that all historical work is absent. No business timestamps are changed.
    /// The row-count bound is not a hard byte, I/O or elapsed-time bound.
    pub async fn next_pending_occurrence(
        &self,
        scan: &mut AutomationPendingOccurrenceScan,
    ) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
        scan.cursor.verify_store(self)?;
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let through = scan
            .cursor
            .high_water(&mut tx, RecoveryScanTable::Occurrences)
            .await?;
        let Some(through) = through else {
            tx.commit().await.map_err(unavailable)?;
            scan.cursor.reset();
            return Ok(None);
        };
        let rows = sqlx::query(PENDING_OCCURRENCE_WINDOW_SQL)
            .bind(scan.cursor.after)
            .bind(through)
            .fetch_all(&mut *tx)
            .await
            .map_err(unavailable)?;
        let mut last_scanned = scan.cursor.after;
        let mut selected = None;
        for row in &rows {
            let rowid: i64 = row
                .try_get("scan_rowid")
                .map_err(|_| AutomationError::Corrupt)?;
            if rowid <= last_scanned || rowid > through {
                return Err(AutomationError::Corrupt);
            }
            last_scanned = rowid;
            let owner: String = row
                .try_get("owner_agent_id")
                .map_err(|_| AutomationError::Corrupt)?;
            let state: String = row.try_get("state").map_err(|_| AutomationError::Corrupt)?;
            if owner != self.owner_agent_id.as_str()
                || !matches!(state.as_str(), "admitted" | "running" | "indeterminate")
            {
                continue;
            }
            let task_id = parse_task_id(row, "task_id")?;
            let occurrence = to_u64(
                row.try_get("occurrence")
                    .map_err(|_| AutomationError::Corrupt)?,
            )?;
            selected = Some(
                load_pending_work(&mut tx, &self.owner_agent_id, task_id, occurrence)
                    .await?
                    .ok_or(AutomationError::Corrupt)?,
            );
            break;
        }
        tx.commit().await.map_err(unavailable)?;
        if rows.is_empty() {
            scan.cursor.reset();
        } else {
            scan.cursor.advance(last_scanned, through);
        }
        Ok(selected)
    }

    /// Resolve one known occurrence directly, without a bounded-frontier search
    /// that could mistake a younger identity beyond the first page for absence.
    pub async fn pending_occurrence_work_for(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let work = load_pending_work(&mut tx, &self.owner_agent_id, task_id, occurrence).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(work)
    }
}

async fn load_pending_work(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    owner: &AgentId,
    task_id: AutomationTaskId,
    occurrence: u64,
) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
    let row = sqlx::query(PENDING_OCCURRENCE_LOOKUP_SQL)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(owner.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?;
    row.map(|row| {
        let task_owner: String = row
            .try_get("task_owner")
            .map_err(|_| AutomationError::Corrupt)?;
        if task_owner != owner.as_str() {
            return Err(AutomationError::AccessDenied);
        }
        crate::lifecycle::occurrence_work_from_row(&row, owner)
    })
    .transpose()
}

#[cfg(test)]
#[path = "pending_occurrence_scan_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "pending_occurrence_scan_query_tests.rs"]
mod query_tests;
