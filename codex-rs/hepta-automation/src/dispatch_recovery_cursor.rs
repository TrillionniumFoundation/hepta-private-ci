//! Fair discovery of unresolved queue admissions. This cursor is not effect evidence.
use crate::AutomationDispatchUncertainty;
use crate::AutomationError;
use crate::AutomationStore;
use crate::AutomationTaskId;
use sqlx::Row;

impl AutomationStore {
    pub async fn next_uncertain_dispatch(
        &self,
    ) -> Result<Option<AutomationDispatchUncertainty>, AutomationError> {
        let (mut tx, _) = self.begin_timer_write().await?;
        let saved =
            sqlx::query("SELECT * FROM automation_dispatch_recovery_cursor WHERE singleton = 1")
                .fetch_optional(&mut *tx)
                .await
                .map_err(unavailable)?;
        let (mut at, mut task, mut occurrence) = (-1_i64, String::new(), 0_i64);
        if let Some(saved) = saved {
            let owner: String = saved.try_get("owner_agent_id").map_err(unavailable)?;
            if owner != self.owner_agent_id().as_str() {
                return Err(AutomationError::AccessDenied);
            }
            at = saved.try_get("observed_at_ms").map_err(unavailable)?;
            task = saved.try_get("task_id").map_err(unavailable)?;
            occurrence = saved.try_get("occurrence").map_err(unavailable)?;
            if at < 0 || occurrence <= 0 || AutomationTaskId::parse(&task).is_err() {
                return Err(AutomationError::Corrupt);
            }
        }
        let mut found = None;
        for _ in 0..2 {
            found = sqlx::query(
                "SELECT o.task_id, o.occurrence, r.scheduled_for_ms, o.client_user_message_id, o.observed_at_ms
                 FROM automation_dispatch_outcomes o
                 JOIN automation_runs r ON r.task_id = o.task_id AND r.occurrence = o.occurrence
                 JOIN automation_tasks t ON t.task_id = o.task_id
                 WHERE t.owner_agent_id = ? AND o.outcome = 'uncertain'
                   AND (o.observed_at_ms, o.task_id, o.occurrence) > (?, ?, ?)
                 ORDER BY o.observed_at_ms, o.task_id, o.occurrence LIMIT 1")
                .bind(self.owner_agent_id().as_str()).bind(at).bind(&task).bind(occurrence)
                .fetch_optional(&mut *tx).await.map_err(unavailable)?;
            if found.is_some() {
                break;
            }
            at = -1;
            task.clear();
            occurrence = 0;
        }
        let Some(row) = found else {
            tx.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        let raw_task: String = row.try_get("task_id").map_err(unavailable)?;
        let at: i64 = row.try_get("observed_at_ms").map_err(unavailable)?;
        let occurrence: i64 = row.try_get("occurrence").map_err(unavailable)?;
        let scheduled: i64 = row.try_get("scheduled_for_ms").map_err(unavailable)?;
        let work = AutomationDispatchUncertainty {
            task_id: AutomationTaskId::parse(&raw_task).map_err(|_| AutomationError::Corrupt)?,
            occurrence: u64::try_from(occurrence).map_err(|_| AutomationError::Corrupt)?,
            scheduled_for_ms: u64::try_from(scheduled).map_err(|_| AutomationError::Corrupt)?,
            client_user_message_id: row.try_get("client_user_message_id").map_err(unavailable)?,
            observed_at_ms: u64::try_from(at).map_err(|_| AutomationError::Corrupt)?,
        };
        sqlx::query(
            "INSERT INTO automation_dispatch_recovery_cursor VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET observed_at_ms = excluded.observed_at_ms,
            task_id = excluded.task_id, occurrence = excluded.occurrence",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(at)
        .bind(raw_task)
        .bind(occurrence)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(Some(work))
    }
}
fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}
