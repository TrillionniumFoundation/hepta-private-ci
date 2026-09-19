use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationDispatchState;
use crate::AutomationError;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceState;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::TaskFlowError;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::model::occurrence_id;
use crate::taskflow::load_taskflow_run_tx;

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AutomationCausalError {
    #[error(transparent)]
    Automation(#[from] AutomationError),
    #[error(transparent)]
    TaskFlow(#[from] TaskFlowError),
}

impl AutomationStore {
    /// Reads the durable occurrence projection. Dispatch state and execution
    /// state are intentionally separate: queue submission never implies terminal.
    pub async fn occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        if occurrence == 0 {
            return Err(AutomationError::Invalid);
        }
        let row = sqlx::query(
            "SELECT r.task_id, r.occurrence, r.occurrence_id, r.schedule_revision,
                    r.scheduled_for_ms, r.state, r.execution_state, r.terminal_at_ms,
                    b.taskflow_run_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             LEFT JOIN automation_occurrence_taskflow b
               ON b.owner_agent_id = t.owner_agent_id
              AND b.task_id = r.task_id AND b.occurrence = r.occurrence
             WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        row.map(|row| occurrence_from_row(&row)).transpose()
    }

    /// Ensures the TaskFlow run for one occurrence exists under the
    /// deterministic occurrence id and then installs the immutable binding.
    ///
    /// Run creation and binding are two idempotent transactions on purpose:
    /// a crash after run creation can leave only an inert orphan run; retry
    /// reuses the same deterministic run id and completes the binding without
    /// creating a second execution identity.
    pub async fn ensure_occurrence_taskflow_run(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        workflow_id: &str,
        workflow_version: u32,
        definition_digest: &Sha256Digest,
        created_at_ms: u64,
    ) -> Result<TaskFlowRun, AutomationCausalError> {
        let occurrence_record = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if occurrence_record.execution_state.is_terminal() {
            return Err(AutomationError::Conflict.into());
        }
        let task = self.task(task_id).await?.ok_or(AutomationError::Conflict)?;
        let run_id = occurrence_record.occurrence_id.clone();
        let run = self
            .create_taskflow_run(
                run_id.clone(),
                workflow_id,
                workflow_version,
                definition_digest,
                task.thread_id,
                created_at_ms,
            )
            .await?;
        self.bind_occurrence_taskflow(task_id, occurrence, &run_id, created_at_ms)
            .await?;
        Ok(run)
    }

    /// Installs one immutable occurrence -> TaskFlow binding. The TaskFlow run
    /// id must equal the deterministic occurrence id.
    pub async fn bind_occurrence_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        taskflow_run_id: &str,
        bound_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationCausalError> {
        if occurrence == 0 || taskflow_run_id.is_empty() {
            return Err(AutomationError::Invalid.into());
        }
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let row = load_occurrence_tx(&mut tx, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let occurrence_record = occurrence_from_row(&row)?;
        if occurrence_record.execution_state.is_terminal()
            || taskflow_run_id != occurrence_record.occurrence_id
        {
            return Err(AutomationError::Conflict.into());
        }
        let thread_id: String = row.try_get("thread_id").map_err(unavailable)?;
        let run = load_taskflow_run_tx(
            &mut tx,
            self.taskflow_owner_agent_id(),
            taskflow_run_id,
        )
        .await?
        .ok_or_else(|| TaskFlowError::Conflict("TaskFlow run does not exist".to_string()))?;
        if run.thread_id != thread_id {
            return Err(TaskFlowError::Conflict(
                "automation occurrence and TaskFlow run bind different threads".to_string(),
            )
            .into());
        }

        let existing: Option<String> = sqlx::query_scalar(
            "SELECT taskflow_run_id FROM automation_occurrence_taskflow
             WHERE owner_agent_id = ? AND occurrence_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&occurrence_record.occurrence_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if let Some(existing) = existing {
            if existing != taskflow_run_id {
                return Err(AutomationError::Conflict.into());
            }
        } else {
            sqlx::query(
                "INSERT INTO automation_occurrence_taskflow (
                    owner_agent_id, occurrence_id, task_id, occurrence,
                    taskflow_run_id, bound_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(&occurrence_record.occurrence_id)
            .bind(task_id.to_string())
            .bind(to_i64(occurrence)?)
            .bind(taskflow_run_id)
            .bind(to_i64(bound_at_ms)?)
            .execute(&mut *tx)
            .await
            .map_err(|error| {
                if is_constraint(&error) {
                    AutomationError::Conflict
                } else {
                    unavailable(error)
                }
            })?;
        }
        sqlx::query(
            "UPDATE automation_runs
             SET execution_state = 'taskflow_bound'
             WHERE task_id = ? AND occurrence = ?
               AND execution_state = 'materialized'",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
            .map_err(AutomationCausalError::from)
    }

    /// Projects the bound TaskFlow run state into the automation occurrence.
    /// Only TaskFlow terminal states may terminalize an admitted occurrence.
    /// One-shot task completion is performed in the same transaction.
    pub async fn sync_occurrence_from_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationCausalError> {
        if occurrence == 0 {
            return Err(AutomationError::Invalid.into());
        }
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let row = load_occurrence_tx(&mut tx, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let current = occurrence_from_row(&row)?;
        let run_id = current
            .taskflow_run_id
            .clone()
            .ok_or(AutomationError::Conflict)?;
        if run_id != current.occurrence_id {
            return Err(AutomationError::Corrupt.into());
        }
        let run = load_taskflow_run_tx(
            &mut tx,
            self.taskflow_owner_agent_id(),
            &run_id,
        )
        .await?
        .ok_or_else(|| TaskFlowError::Corrupt("bound TaskFlow run is missing".to_string()))?;
        let next = occurrence_state_for_run(run.state);
        if !valid_execution_transition(current.execution_state, next) {
            return Err(TaskFlowError::Conflict(
                "TaskFlow projection would regress or rewrite a terminal automation occurrence"
                    .to_string(),
            )
            .into());
        }
        let terminal_at_ms = if next.is_terminal() {
            Some(to_i64(observed_at_ms)?)
        } else {
            None
        };
        let updated = sqlx::query(
            "UPDATE automation_runs
             SET execution_state = ?,
                 terminal_at_ms = CASE
                    WHEN ? IS NOT NULL THEN COALESCE(terminal_at_ms, ?)
                    ELSE terminal_at_ms
                 END
             WHERE task_id = ? AND occurrence = ? AND occurrence_id = ?",
        )
        .bind(next.as_str())
        .bind(terminal_at_ms)
        .bind(terminal_at_ms)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(&current.occurrence_id)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict.into());
        }

        let schedule_kind: String = row.try_get("schedule_kind").map_err(unavailable)?;
        if next.is_terminal() && schedule_kind == "once" {
            sqlx::query(
                "UPDATE automation_tasks
                 SET state = 'completed', next_run_at_ms = NULL, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'
                   AND schedule_kind = 'once'",
            )
            .bind(to_i64(observed_at_ms)?)
            .bind(task_id.to_string())
            .bind(self.taskflow_owner_agent_id().as_str())
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        }
        tx.commit().await.map_err(unavailable)?;
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
            .map_err(AutomationCausalError::from)
    }
}

async fn load_occurrence_tx(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    occurrence: u64,
) -> Result<Option<sqlx::sqlite::SqliteRow>, AutomationError> {
    sqlx::query(
        "SELECT r.task_id, r.occurrence, r.occurrence_id, r.schedule_revision,
                r.scheduled_for_ms, r.state, r.execution_state, r.terminal_at_ms,
                b.taskflow_run_id, t.thread_id, t.schedule_kind
         FROM automation_runs r
         JOIN automation_tasks t ON t.task_id = r.task_id
         LEFT JOIN automation_occurrence_taskflow b
           ON b.owner_agent_id = t.owner_agent_id
          AND b.task_id = r.task_id AND b.occurrence = r.occurrence
         WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)
}

fn occurrence_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<AutomationOccurrence, AutomationError> {
    let task_id = AutomationTaskId::parse(
        &row.try_get::<String, _>("task_id").map_err(unavailable)?,
    )
    .map_err(|_| AutomationError::Corrupt)?;
    let occurrence = to_u64(row.try_get("occurrence").map_err(unavailable)?)?;
    let occurrence_id_value: String = row.try_get("occurrence_id").map_err(unavailable)?;
    let schedule_revision = to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?;
    let scheduled_for_ms = to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
    if occurrence == 0
        || schedule_revision == 0
        || occurrence_id_value != occurrence_id(task_id, schedule_revision, scheduled_for_ms)
    {
        return Err(AutomationError::Corrupt);
    }
    Ok(AutomationOccurrence {
        task_id,
        occurrence,
        occurrence_id: occurrence_id_value,
        schedule_revision,
        scheduled_for_ms,
        dispatch_state: AutomationDispatchState::parse(
            &row.try_get::<String, _>("state").map_err(unavailable)?,
        )?,
        execution_state: AutomationOccurrenceState::parse(
            &row.try_get::<String, _>("execution_state").map_err(unavailable)?,
        )?,
        taskflow_run_id: row.try_get("taskflow_run_id").map_err(unavailable)?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}

fn occurrence_state_for_run(state: TaskFlowRunState) -> AutomationOccurrenceState {
    match state {
        TaskFlowRunState::Queued => AutomationOccurrenceState::TaskFlowBound,
        TaskFlowRunState::Running
        | TaskFlowRunState::Waiting
        | TaskFlowRunState::RetryBackoff => AutomationOccurrenceState::Running,
        TaskFlowRunState::Indeterminate => AutomationOccurrenceState::Indeterminate,
        TaskFlowRunState::Succeeded => AutomationOccurrenceState::Succeeded,
        TaskFlowRunState::Failed => AutomationOccurrenceState::Failed,
        TaskFlowRunState::Cancelled => AutomationOccurrenceState::Cancelled,
    }
}

fn valid_execution_transition(
    current: AutomationOccurrenceState,
    next: AutomationOccurrenceState,
) -> bool {
    if current == next {
        return true;
    }
    match current {
        AutomationOccurrenceState::Materialized => true,
        AutomationOccurrenceState::TaskFlowBound => matches!(
            next,
            AutomationOccurrenceState::Running
                | AutomationOccurrenceState::Indeterminate
                | AutomationOccurrenceState::Succeeded
                | AutomationOccurrenceState::Failed
                | AutomationOccurrenceState::Cancelled
        ),
        AutomationOccurrenceState::Running => matches!(
            next,
            AutomationOccurrenceState::Indeterminate
                | AutomationOccurrenceState::Succeeded
                | AutomationOccurrenceState::Failed
                | AutomationOccurrenceState::Cancelled
        ),
        AutomationOccurrenceState::Indeterminate => matches!(
            next,
            AutomationOccurrenceState::Succeeded
                | AutomationOccurrenceState::Failed
                | AutomationOccurrenceState::Cancelled
        ),
        AutomationOccurrenceState::Succeeded
        | AutomationOccurrenceState::Failed
        | AutomationOccurrenceState::Cancelled => false,
    }
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(
        error,
        sqlx::Error::Database(database)
            if database.is_unique_violation()
                || database.is_foreign_key_violation()
                || database.is_check_violation()
    )
}
