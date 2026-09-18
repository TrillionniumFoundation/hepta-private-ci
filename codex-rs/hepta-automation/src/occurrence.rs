use std::fmt;

use sqlx::Row;

use crate::AutomationError;
use crate::AutomationSchedule;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::AutomationTaskState;
use crate::TaskFlowError;
use crate::TaskFlowRunState;

const OCCURRENCE_ID_PREFIX: &str = "hepta.automation.occurrence.v1:";
const MAX_OCCURRENCE_PAGE: usize = 1_024;

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AutomationOccurrenceId(String);

impl AutomationOccurrenceId {
    pub fn for_schedule(
        task_id: AutomationTaskId,
        schedule_revision: u64,
        scheduled_for_ms: u64,
    ) -> Result<Self, AutomationError> {
        if schedule_revision == 0 {
            return Err(AutomationError::Invalid);
        }
        Ok(Self(format!(
            "{OCCURRENCE_ID_PREFIX}{task_id}:{schedule_revision}:{scheduled_for_ms}"
        )))
    }

    pub fn parse(value: impl Into<String>) -> Result<Self, AutomationError> {
        let value = value.into();
        if !value.starts_with(OCCURRENCE_ID_PREFIX)
            || value.len() > 256
            || value.bytes().any(|byte| byte < 0x20)
        {
            return Err(AutomationError::Invalid);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for AutomationOccurrenceId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationOverlapPolicy {
    Forbid,
}

impl AutomationOverlapPolicy {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Forbid => "forbid",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "forbid" => Ok(Self::Forbid),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationMissedRunPolicy {
    Skip,
    CoalesceLatest,
}

impl AutomationMissedRunPolicy {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Skip => "skip",
            Self::CoalesceLatest => "coalesce_latest",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "skip" => Ok(Self::Skip),
            "coalesce_latest" => Ok(Self::CoalesceLatest),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationScheduleRevision {
    pub task_id: AutomationTaskId,
    pub revision: u64,
    pub schedule: AutomationSchedule,
    pub timezone: String,
    pub overlap_policy: AutomationOverlapPolicy,
    pub missed_run_policy: AutomationMissedRunPolicy,
    pub registered_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationOccurrenceState {
    Materialized,
    DispatchUncertain,
    QueueAdmitted,
    TaskFlowBound,
    Running,
    Indeterminate,
    Succeeded,
    Failed,
    Cancelled,
}

impl AutomationOccurrenceState {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Materialized => "materialized",
            Self::DispatchUncertain => "dispatch_uncertain",
            Self::QueueAdmitted => "queue_admitted",
            Self::TaskFlowBound => "taskflow_bound",
            Self::Running => "running",
            Self::Indeterminate => "indeterminate",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "materialized" => Ok(Self::Materialized),
            "dispatch_uncertain" => Ok(Self::DispatchUncertain),
            "queue_admitted" => Ok(Self::QueueAdmitted),
            "taskflow_bound" => Ok(Self::TaskFlowBound),
            "running" => Ok(Self::Running),
            "indeterminate" => Ok(Self::Indeterminate),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(AutomationError::Corrupt),
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationTerminalOutcome {
    Succeeded,
    Failed,
    Cancelled,
}

impl AutomationTerminalOutcome {
    fn state(self) -> AutomationOccurrenceState {
        match self {
            Self::Succeeded => AutomationOccurrenceState::Succeeded,
            Self::Failed => AutomationOccurrenceState::Failed,
            Self::Cancelled => AutomationOccurrenceState::Cancelled,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOccurrence {
    pub occurrence_id: AutomationOccurrenceId,
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub schedule_revision: u64,
    pub scheduled_for_ms: u64,
    pub client_user_message_id: String,
    pub state: AutomationOccurrenceState,
    pub queued_submission_id: Option<String>,
    pub turn_id: Option<String>,
    pub taskflow_run_id: Option<String>,
    pub terminal_reason: Option<String>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

impl AutomationStore {
    pub async fn latest_schedule_revision(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<AutomationScheduleRevision, AutomationError> {
        let row = sqlx::query(
            "SELECT r.task_id, r.revision, r.schedule_kind, r.interval_ms, r.timezone,
                    r.overlap_policy, r.missed_run_policy, r.registered_at_ms
             FROM automation_schedule_revisions r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND t.owner_agent_id = ?
             ORDER BY r.revision DESC LIMIT 1",
        )
        .bind(task_id.to_string())
        .bind(self.owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Corrupt)?;
        schedule_revision_from_row(&row)
    }

    pub async fn occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        sqlx::query(
            "SELECT o.*
             FROM automation_occurrences o
             WHERE o.owner_agent_id = ? AND o.task_id = ? AND o.occurrence = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?
        .map(|row| occurrence_from_row(&row))
        .transpose()
    }

    pub async fn open_occurrences(
        &self,
        limit: usize,
    ) -> Result<Vec<AutomationOccurrence>, AutomationError> {
        if !(1..=MAX_OCCURRENCE_PAGE).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT o.*
             FROM automation_occurrences o
             WHERE o.owner_agent_id = ?
               AND o.state NOT IN ('succeeded', 'failed', 'cancelled')
             ORDER BY o.updated_at_ms, o.occurrence_id
             LIMIT ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        rows.iter().map(occurrence_from_row).collect()
    }

    /// Bind a canonical occurrence to an already-durable TaskFlow run.
    ///
    /// The exact binding is idempotent. A different run id for the same
    /// occurrence is rejected; TaskFlow remains the sole workflow engine.
    pub async fn bind_occurrence_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        run_id: &str,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if run_id.is_empty() || run_id.len() > 256 {
            return Err(AutomationError::Invalid);
        }
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Conflict)?;
        let task = self.task(task_id).await?.ok_or(AutomationError::Conflict)?;
        if run.owner_agent_id != *self.owner_agent_id() || run.thread_id != task.thread_id {
            return Err(AutomationError::AccessDenied);
        }

        let changed = sqlx::query(
            "UPDATE automation_occurrences
             SET taskflow_run_id = ?,
                 state = CASE
                    WHEN state IN ('materialized', 'queue_admitted') THEN 'taskflow_bound'
                    ELSE state
                 END,
                 updated_at_ms = CASE WHEN updated_at_ms < ? THEN ? ELSE updated_at_ms END
             WHERE owner_agent_id = ? AND task_id = ? AND occurrence = ?
               AND (taskflow_run_id IS NULL OR taskflow_run_id = ?)
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(run_id)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(run_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    pub async fn record_occurrence_turn(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        turn_id: &str,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if turn_id.is_empty() || turn_id.len() > 256 {
            return Err(AutomationError::Invalid);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrences
             SET turn_id = ?,
                 state = CASE
                    WHEN state IN ('queue_admitted', 'taskflow_bound') THEN 'running'
                    ELSE state
                 END,
                 updated_at_ms = CASE WHEN updated_at_ms < ? THEN ? ELSE updated_at_ms END
             WHERE owner_agent_id = ? AND task_id = ? AND occurrence = ?
               AND (turn_id IS NULL OR turn_id = ?)
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(turn_id)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(turn_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    pub async fn sync_occurrence_from_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let current = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let run_id = current
            .taskflow_run_id
            .as_deref()
            .ok_or(AutomationError::Conflict)?;
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        match run.state {
            TaskFlowRunState::Queued => {
                self.update_occurrence_nonterminal(
                    task_id,
                    occurrence,
                    AutomationOccurrenceState::TaskFlowBound,
                    now_ms,
                )
                .await
            }
            TaskFlowRunState::Running
            | TaskFlowRunState::Waiting
            | TaskFlowRunState::RetryBackoff => {
                self.update_occurrence_nonterminal(
                    task_id,
                    occurrence,
                    AutomationOccurrenceState::Running,
                    now_ms,
                )
                .await
            }
            TaskFlowRunState::Indeterminate => {
                self.update_occurrence_nonterminal(
                    task_id,
                    occurrence,
                    AutomationOccurrenceState::Indeterminate,
                    now_ms,
                )
                .await
            }
            TaskFlowRunState::Succeeded => {
                self.terminalize_occurrence(
                    task_id,
                    occurrence,
                    AutomationTerminalOutcome::Succeeded,
                    "taskflow_succeeded",
                    now_ms,
                )
                .await
            }
            TaskFlowRunState::Failed => {
                self.terminalize_occurrence(
                    task_id,
                    occurrence,
                    AutomationTerminalOutcome::Failed,
                    "taskflow_failed",
                    now_ms,
                )
                .await
            }
            TaskFlowRunState::Cancelled => {
                self.terminalize_occurrence(
                    task_id,
                    occurrence,
                    AutomationTerminalOutcome::Cancelled,
                    "taskflow_cancelled",
                    now_ms,
                )
                .await
            }
        }
    }

    async fn update_occurrence_nonterminal(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        state: AutomationOccurrenceState,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if state.is_terminal() {
            return Err(AutomationError::Invalid);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrences
             SET state = ?, updated_at_ms = CASE WHEN updated_at_ms < ? THEN ? ELSE updated_at_ms END
             WHERE owner_agent_id = ? AND task_id = ? AND occurrence = ?
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(state.as_str())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    /// The only schedule-progression boundary.
    ///
    /// Queue admission, TaskFlow start, and an indeterminate result never call
    /// this method. A recurring task gets its next canonical slot only after
    /// the occurrence is terminal.
    pub async fn terminalize_occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        outcome: AutomationTerminalOutcome,
        reason: &str,
        terminal_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if reason.is_empty() || reason.len() > 256 || reason.bytes().any(|byte| byte < 0x20) {
            return Err(AutomationError::Invalid);
        }
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT o.*, t.state AS task_state
             FROM automation_occurrences o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.owner_agent_id = ? AND o.task_id = ? AND o.occurrence = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let current = occurrence_from_row(&row)?;
        if current.state.is_terminal() {
            if current.state != outcome.state() || current.terminal_reason.as_deref() != Some(reason) {
                return Err(AutomationError::Conflict);
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }

        let task_state = AutomationTaskState::parse(
            &row.try_get::<String, _>("task_state").map_err(unavailable)?,
        )?;
        let revision_row = sqlx::query(
            "SELECT task_id, revision, schedule_kind, interval_ms, timezone,
                    overlap_policy, missed_run_policy, registered_at_ms
             FROM automation_schedule_revisions
             WHERE task_id = ? AND revision = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(current.schedule_revision)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        let revision = schedule_revision_from_row(&revision_row)?;

        let updated = sqlx::query(
            "UPDATE automation_occurrences
             SET state = ?, terminal_reason = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND task_id = ? AND occurrence = ?
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(outcome.state().as_str())
        .bind(reason)
        .bind(to_i64(terminal_at_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        if task_state == AutomationTaskState::Enabled {
            let next_run = next_run_after_terminal(&revision, current.scheduled_for_ms, terminal_at_ms)?;
            let next_state = if next_run.is_some() {
                AutomationTaskState::Enabled
            } else {
                AutomationTaskState::Completed
            };
            let task_update = sqlx::query(
                "UPDATE automation_tasks
                 SET state = ?, next_run_at_ms = ?, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
            )
            .bind(next_state.as_str())
            .bind(next_run.map(to_i64).transpose()?)
            .bind(to_i64(terminal_at_ms)?)
            .bind(task_id.to_string())
            .bind(self.owner_agent_id().as_str())
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
            if task_update.rows_affected() != 1 {
                return Err(AutomationError::Conflict);
            }
        }

        tx.commit().await.map_err(unavailable)?;
        self.occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)
    }
}

fn next_run_after_terminal(
    revision: &AutomationScheduleRevision,
    scheduled_for_ms: u64,
    terminal_at_ms: u64,
) -> Result<Option<u64>, AutomationError> {
    match revision.schedule {
        AutomationSchedule::Once => Ok(None),
        AutomationSchedule::FixedInterval { interval_ms } => {
            let first_next = scheduled_for_ms
                .checked_add(interval_ms)
                .ok_or(AutomationError::Invalid)?;
            if first_next > terminal_at_ms {
                return Ok(Some(first_next));
            }
            let elapsed = terminal_at_ms
                .checked_sub(scheduled_for_ms)
                .ok_or(AutomationError::Corrupt)?;
            match revision.missed_run_policy {
                AutomationMissedRunPolicy::Skip => {
                    let slots = elapsed
                        .checked_div(interval_ms)
                        .and_then(|value| value.checked_add(1))
                        .ok_or(AutomationError::Invalid)?;
                    scheduled_for_ms
                        .checked_add(
                            slots
                                .checked_mul(interval_ms)
                                .ok_or(AutomationError::Invalid)?,
                        )
                        .map(Some)
                        .ok_or(AutomationError::Invalid)
                }
                AutomationMissedRunPolicy::CoalesceLatest => {
                    let slots = elapsed.checked_div(interval_ms).ok_or(AutomationError::Invalid)?;
                    let slots = slots.max(1);
                    scheduled_for_ms
                        .checked_add(
                            slots
                                .checked_mul(interval_ms)
                                .ok_or(AutomationError::Invalid)?,
                        )
                        .map(Some)
                        .ok_or(AutomationError::Invalid)
                }
            }
        }
    }
}

fn schedule_revision_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<AutomationScheduleRevision, AutomationError> {
    let task_id = AutomationTaskId::parse(
        &row.try_get::<String, _>("task_id").map_err(unavailable)?,
    )
    .map_err(|_| AutomationError::Corrupt)?;
    let schedule_kind: String = row.try_get("schedule_kind").map_err(unavailable)?;
    let interval_ms: Option<i64> = row.try_get("interval_ms").map_err(unavailable)?;
    let schedule = match (schedule_kind.as_str(), interval_ms) {
        ("once", None) => AutomationSchedule::Once,
        ("fixed_interval", Some(interval_ms)) => AutomationSchedule::FixedInterval {
            interval_ms: to_u64(interval_ms)?,
        },
        _ => return Err(AutomationError::Corrupt),
    };
    schedule.validate().map_err(|_| AutomationError::Corrupt)?;
    Ok(AutomationScheduleRevision {
        task_id,
        revision: to_u64(row.try_get("revision").map_err(unavailable)?)?,
        schedule,
        timezone: row.try_get("timezone").map_err(unavailable)?,
        overlap_policy: AutomationOverlapPolicy::parse(
            &row.try_get::<String, _>("overlap_policy").map_err(unavailable)?,
        )?,
        missed_run_policy: AutomationMissedRunPolicy::parse(
            &row.try_get::<String, _>("missed_run_policy").map_err(unavailable)?,
        )?,
        registered_at_ms: to_u64(row.try_get("registered_at_ms").map_err(unavailable)?)?,
    })
}

fn occurrence_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<AutomationOccurrence, AutomationError> {
    Ok(AutomationOccurrence {
        occurrence_id: AutomationOccurrenceId::parse(
            row.try_get::<String, _>("occurrence_id").map_err(unavailable)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        task_id: AutomationTaskId::parse(
            &row.try_get::<String, _>("task_id").map_err(unavailable)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        occurrence: to_u64(row.try_get("occurrence").map_err(unavailable)?)?,
        schedule_revision: to_u64(
            row.try_get("schedule_revision").map_err(unavailable)?,
        )?,
        scheduled_for_ms: to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?,
        client_user_message_id: row
            .try_get("client_user_message_id")
            .map_err(unavailable)?,
        state: AutomationOccurrenceState::parse(
            &row.try_get::<String, _>("state").map_err(unavailable)?,
        )?,
        queued_submission_id: row
            .try_get("queued_submission_id")
            .map_err(unavailable)?,
        turn_id: row.try_get("turn_id").map_err(unavailable)?,
        taskflow_run_id: row.try_get("taskflow_run_id").map_err(unavailable)?,
        terminal_reason: row.try_get("terminal_reason").map_err(unavailable)?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
    })
}

fn map_taskflow_error(error: TaskFlowError) -> AutomationError {
    match error {
        TaskFlowError::Unavailable => AutomationError::Unavailable,
        TaskFlowError::StaleFence => AutomationError::AccessDenied,
        TaskFlowError::Invalid(_) => AutomationError::Invalid,
        TaskFlowError::Conflict(_) | TaskFlowError::InvalidTransition(_) => AutomationError::Conflict,
        TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
    }
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_error: impl std::fmt::Display) -> AutomationError {
    AutomationError::Unavailable
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn occurrence_identity_binds_revision_and_scheduled_instant() {
        let task_id =
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75008").expect("task id");
        assert_eq!(
            AutomationOccurrenceId::for_schedule(task_id, 7, 42)
                .expect("occurrence id")
                .as_str(),
            "hepta.automation.occurrence.v1:019153a4-3088-7000-a56a-9b1964f75008:7:42"
        );
    }

    #[test]
    fn missed_run_policy_is_bounded() {
        let task_id =
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75008").expect("task id");
        let base = AutomationScheduleRevision {
            task_id,
            revision: 1,
            schedule: AutomationSchedule::FixedInterval { interval_ms: 1_000 },
            timezone: "UTC".to_string(),
            overlap_policy: AutomationOverlapPolicy::Forbid,
            missed_run_policy: AutomationMissedRunPolicy::CoalesceLatest,
            registered_at_ms: 0,
        };
        assert_eq!(
            next_run_after_terminal(&base, 1_000, 10_550).expect("coalesced"),
            Some(10_000)
        );
        let skip = AutomationScheduleRevision {
            missed_run_policy: AutomationMissedRunPolicy::Skip,
            ..base
        };
        assert_eq!(
            next_run_after_terminal(&skip, 1_000, 10_550).expect("skipped"),
            Some(11_000)
        );
    }
}
