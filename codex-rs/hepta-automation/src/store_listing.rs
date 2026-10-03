//! Byte-bounded keyset reads in the existing automation owner.
use super::*;
use crate::AutomationTaskCursorV1;
use crate::AutomationTaskPageV1;

const MAX_PAGE_ROWS: usize = 32;
const MAX_PAGE_BYTES: usize = 65_536;

impl AutomationStore {
    /// Read one bounded live page. No writer claim, lifecycle transition or
    /// private snapshot registry is created. The caller must retain its existing
    /// generation fence; a cursor never acts as authority or frozen evidence.
    pub async fn list_task_page_v1(
        &self,
        limit: usize,
        after: Option<AutomationTaskCursorV1>,
        maximum_bytes: usize,
    ) -> Result<AutomationTaskPageV1, AutomationError> {
        if !(1..=MAX_TASK_PAGE).contains(&limit) || !(1..=MAX_PAGE_BYTES).contains(&maximum_bytes) {
            return Err(AutomationError::Invalid);
        }
        let limit = limit.min(MAX_PAGE_ROWS);
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new(
            "SELECT task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                    state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
             FROM automation_tasks INDEXED BY automation_tasks_listing_idx",
        );
        if let Some(cursor) = after {
            AutomationTaskId::parse(&cursor.task_id.to_string())?;
            query
                .push(" WHERE (created_at_ms, task_id) > (")
                .push_bind(to_i64(cursor.created_at_ms)?)
                .push(", ")
                .push_bind(cursor.task_id.to_string())
                .push(")");
        }
        query
            .push(" ORDER BY created_at_ms, task_id LIMIT ")
            .push_bind(i64::try_from(limit + 1).map_err(|_| AutomationError::Invalid)?);
        let rows = query
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(unavailable)?;
        let tasks = rows
            .iter()
            .map(|row| task_from_row(row, &self.owner_agent_id))
            .collect::<Result<Vec<_>, _>>()?;
        let mut page = AutomationTaskPageV1 {
            tasks: Vec::new(),
            next_cursor: None,
        };
        let mut encoded_bytes = serde_json::to_vec(&page)
            .map_err(|_| AutomationError::Corrupt)?
            .len();
        // Reserve the largest actual continuation key before packing, including
        // its JSON envelope. UTF-8 and escaped control characters count as their
        // encoded bytes, not their raw string length.
        if !tasks.is_empty() {
            let cursor_bytes = tasks
                .iter()
                .map(|task| {
                    serde_json::to_vec(&AutomationTaskCursorV1::from_task(task))
                        .map(|bytes| bytes.len())
                        .map_err(|_| AutomationError::Corrupt)
                })
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .max()
                .ok_or(AutomationError::Corrupt)?;
            encoded_bytes += cursor_bytes - 4; // replace JSON null, not a digest/claim
        }
        if encoded_bytes > maximum_bytes {
            return Err(AutomationError::Invalid);
        }
        let available = tasks.len();
        for task in tasks.into_iter().take(limit) {
            let task_bytes = serde_json::to_vec(&task)
                .map_err(|_| AutomationError::Corrupt)?
                .len()
                + usize::from(!page.tasks.is_empty());
            if encoded_bytes + task_bytes > maximum_bytes {
                if page.tasks.is_empty() {
                    return Err(AutomationError::PageItemTooLarge);
                }
                break;
            }
            encoded_bytes += task_bytes;
            page.tasks.push(task);
        }
        if page.tasks.len() < available {
            page.next_cursor = page.tasks.last().map(AutomationTaskCursorV1::from_task);
        }
        Ok(page)
    }
}

#[cfg(test)]
#[path = "store_listing_tests.rs"]
mod tests;
