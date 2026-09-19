use sqlx::Row;

use crate::AutomationError;
use crate::AutomationMissedRunPolicy;
use crate::AutomationOccurrenceTerminal;
use crate::AutomationOverlapPolicy;
use crate::AutomationSchedule;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskId;
use crate::AutomationTaskState;

const MAX_IDENTIFIER_BYTES: usize = 256;
const MAX_DETAIL_BYTES: usize = 4 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOccurrence {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub occurrence_id: String,
    pub schedule_revision: u64,
    pub scheduled_for_ms: u64,
    pub lifecycle_state: String,
    pub taskflow_run_id: Option<String>,
    pub queued_submission_id: Option<String>,
    pub terminal_reason: Option<String>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
    pub terminal_at_ms: Option<u64>,
}

impl AutomationStore {
    pub async fn occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        let row = sqlx::query(
            "SELECT o.task_id, o.occurrence, o.occurrence_id, o.schedule_revision,
                    o.scheduled_for_ms, o.lifecycle_state, o.taskflow_run_id,
                    o.queued_submission_id, o.terminal_reason, o.created_at_ms,
                    o.updated_at_ms, o.terminal_at_ms
             FROM automation_occurrences o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.task_id = ? AND o.occurrence = ? AND t.owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        row.map(|row| occurrence_from_row(&row)).transpose()
    }

    pub async fn revise_schedule(
        &self,
        task_id: AutomationTaskId,
        schedule: AutomationSchedule,
        missed_run_policy: AutomationMissedRunPolicy,
        overlap_policy: AutomationOverlapPolicy,
        first_run_at_ms: u64,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        schedule.validate()?;
        missed_run_policy.validate()?;
        to_i64(first_run_at_ms)?;
        to_i64(now_ms)?;
        let (schedule_kind, interval_ms) = schedule_columns(schedule);
        let (missed_kind, catch_up_limit) = missed_run_policy.columns();

        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let current = sqlx::query(
            "SELECT state, schedule_revision
             FROM automation_tasks WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let state = AutomationTaskState::parse(
            &current.try_get::<String, _>("state").map_err(unavailable)?,
        )?;
        if state == AutomationTaskState::Cancelled {
            return Err(AutomationError::Conflict);
        }
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM automation_occurrences
             WHERE task_id = ?
               AND lifecycle_state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(task_id.to_string())
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if active != 0 {
            return Err(AutomationError::Conflict);
        }
        let revision = to_u64(
            current
                .try_get("schedule_revision")
                .map_err(unavailable)?,
        )?
        .checked_add(1)
        .ok_or(AutomationError::Invalid)?;

        let updated = sqlx::query(
            "UPDATE automation_tasks
             SET schedule_kind = ?, interval_ms = ?, schedule_revision = ?,
                 missed_run_policy = ?, catch_up_limit = ?, overlap_policy = ?,
                 state = 'enabled', next_run_at_ms = ?, updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(schedule_kind)
        .bind(interval_ms.map(to_i64).transpose()?)
        .bind(to_i64(revision)?)
        .bind(missed_kind)
        .bind(i64::from(catch_up_limit))
        .bind(overlap_policy.as_str())
        .bind(to_i64(first_run_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        transaction.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    pub async fn bind_taskflow_run(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        taskflow_run_id: &str,
        now_ms: u64,
    ) -> Result<(), AutomationError> {
        validate_identifier(taskflow_run_id)?;
        let updated = sqlx::query(
            "UPDATE automation_occurrences
             SET lifecycle_state = 'taskflow_running', taskflow_run_id = ?, updated_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND lifecycle_state IN ('queue_admitted', 'taskflow_running')
               AND (taskflow_run_id IS NULL OR taskflow_run_id = ?)
               AND EXISTS (
                   SELECT 1 FROM automation_tasks t
                   WHERE t.task_id = automation_occurrences.task_id
                     AND t.owner_agent_id = ?
               )",
        )
        .bind(taskflow_run_id)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(taskflow_run_id)
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        Ok(())
    }

    pub async fn record_provider_observation(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        provider_id: &str,
        operation_id: &str,
        observation: &str,
        payload_digest: &str,
        observed_at_ms: u64,
        detail: Option<&str>,
    ) -> Result<String, AutomationError> {
        validate_identifier(provider_id)?;
        validate_identifier(operation_id)?;
        validate_digest(payload_digest)?;
        if !matches!(
            observation,
            "accepted" | "succeeded" | "failed" | "indeterminate" | "not_admitted"
        ) {
            return Err(AutomationError::Invalid);
        }
        if detail.is_some_and(|value| value.len() > MAX_DETAIL_BYTES || value.contains('\0')) {
            return Err(AutomationError::Invalid);
        }
        let observation_id = uuid::Uuid::now_v7().to_string();
        let result = sqlx::query(
            "INSERT INTO automation_provider_observations (
                 observation_id, task_id, occurrence, provider_id, operation_id,
                 observation, payload_digest, observed_at_ms, detail
             )
             SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
             WHERE EXISTS (
                 SELECT 1 FROM automation_occurrences o
                 JOIN automation_tasks t ON t.task_id = o.task_id
                 WHERE o.task_id = ? AND o.occurrence = ? AND t.owner_agent_id = ?
             )",
        )
        .bind(&observation_id)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(provider_id)
        .bind(operation_id)
        .bind(observation)
        .bind(payload_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(detail)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(self.taskflow_pool())
        .await;
        match result {
            Ok(result) if result.rows_affected() == 1 => Ok(observation_id),
            Ok(_) => Err(AutomationError::Conflict),
            Err(error) if is_unique(&error) => Err(AutomationError::Conflict),
            Err(error) => Err(unavailable(error)),
        }
    }

    pub async fn mark_occurrence_indeterminate(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        now_ms: u64,
        reason: &str,
    ) -> Result<(), AutomationError> {
        validate_reason(reason)?;
        let updated = sqlx::query(
            "UPDATE automation_occurrences
             SET lifecycle_state = 'indeterminate', terminal_reason = ?, updated_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND lifecycle_state IN ('queue_admitted', 'taskflow_running', 'indeterminate')
               AND EXISTS (
                   SELECT 1 FROM automation_tasks t
                   WHERE t.task_id = automation_occurrences.task_id
                     AND t.owner_agent_id = ?
               )",
        )
        .bind(reason)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        Ok(())
    }

    /// Reconciles the automation occurrence only from the durable state of its
    /// already-bound TaskFlow run. Non-terminal TaskFlow projections cannot
    /// advance the recurring schedule.
    pub async fn reconcile_occurrence_from_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        run_id: &str,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        validate_identifier(run_id)?;
        let row = sqlx::query(
            "SELECT o.taskflow_run_id, r.state, r.terminal_reason
             FROM automation_occurrences o
             JOIN automation_tasks t ON t.task_id = o.task_id
             JOIN taskflow_runs r
               ON r.owner_agent_id = t.owner_agent_id AND r.run_id = o.taskflow_run_id
             WHERE o.task_id = ? AND o.occurrence = ?
               AND t.owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let bound_run_id: Option<String> =
            row.try_get("taskflow_run_id").map_err(unavailable)?;
        if bound_run_id.as_deref() != Some(run_id) {
            return Err(AutomationError::Conflict);
        }
        let state: String = row.try_get("state").map_err(unavailable)?;
        let terminal = match state.as_str() {
            "succeeded" => AutomationOccurrenceTerminal::Succeeded,
            "failed" => AutomationOccurrenceTerminal::Failed,
            "cancelled" => AutomationOccurrenceTerminal::Cancelled,
            "indeterminate" => {
                let reason = row
                    .try_get::<Option<String>, _>("terminal_reason")
                    .map_err(unavailable)?
                    .unwrap_or_else(|| "taskflow_indeterminate".to_string());
                self.mark_occurrence_indeterminate(task_id, occurrence, now_ms, &reason)
                    .await?;
                return self.task(task_id).await?.ok_or(AutomationError::Corrupt);
            }
            _ => return Err(AutomationError::Conflict),
        };
        let reason = row
            .try_get::<Option<String>, _>("terminal_reason")
            .map_err(unavailable)?
            .unwrap_or_else(|| format!("taskflow_{state}"));
        self.reconcile_occurrence_terminal(task_id, occurrence, terminal, now_ms, &reason)
            .await
    }

    /// Commits the authoritative occurrence terminal state and only then
    /// advances the recurring schedule.  Queue admission never reaches this
    /// method implicitly.
    pub(crate) async fn reconcile_occurrence_terminal(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        terminal: AutomationOccurrenceTerminal,
        now_ms: u64,
        reason: &str,
    ) -> Result<AutomationTask, AutomationError> {
        validate_reason(reason)?;
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;

        let occurrence_row = sqlx::query(
            "SELECT o.scheduled_for_ms, o.lifecycle_state, o.terminal_reason
             FROM automation_occurrences o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.task_id = ? AND o.occurrence = ? AND t.owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let scheduled_for_ms =
            to_u64(occurrence_row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
        let lifecycle_state: String =
            occurrence_row.try_get("lifecycle_state").map_err(unavailable)?;
        if matches!(lifecycle_state.as_str(), "succeeded" | "failed" | "cancelled") {
            if lifecycle_state != terminal.as_str() {
                return Err(AutomationError::Conflict);
            }
            transaction.commit().await.map_err(unavailable)?;
            return self.task(task_id).await?.ok_or(AutomationError::Corrupt);
        }
        if !matches!(
            lifecycle_state.as_str(),
            "queue_admitted" | "taskflow_running" | "indeterminate"
        ) {
            return Err(AutomationError::Conflict);
        }

        let terminal_update = sqlx::query(
            "UPDATE automation_occurrences
             SET lifecycle_state = ?, terminal_reason = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND lifecycle_state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(terminal.as_str())
        .bind(reason)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if terminal_update.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        let task_row = sqlx::query(
            "SELECT schedule_kind, interval_ms, state, missed_run_policy, catch_up_limit,
                    overlap_policy
             FROM automation_tasks
             WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let state = AutomationTaskState::parse(
            &task_row.try_get::<String, _>("state").map_err(unavailable)?,
        )?;
        let overlap = AutomationOverlapPolicy::parse(
            &task_row
                .try_get::<String, _>("overlap_policy")
                .map_err(unavailable)?,
        )?;
        if overlap != AutomationOverlapPolicy::Forbid {
            return Err(AutomationError::Corrupt);
        }

        if state == AutomationTaskState::Enabled {
            let schedule = schedule_from_row(&task_row)?;
            let missed = AutomationMissedRunPolicy::parse(
                &task_row
                    .try_get::<String, _>("missed_run_policy")
                    .map_err(unavailable)?,
                u16::try_from(to_u64(
                    task_row.try_get("catch_up_limit").map_err(unavailable)?,
                )?)
                .map_err(|_| AutomationError::Corrupt)?,
            )?;
            let next_run = next_after_terminal(schedule, missed, scheduled_for_ms, now_ms)?;
            let next_state = if next_run.is_some() {
                AutomationTaskState::Enabled
            } else {
                AutomationTaskState::Completed
            };
            let advanced = sqlx::query(
                "UPDATE automation_tasks
                 SET state = ?, next_run_at_ms = ?, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ?",
            )
            .bind(next_state.as_str())
            .bind(next_run.map(to_i64).transpose()?)
            .bind(to_i64(now_ms)?)
            .bind(task_id.to_string())
            .bind(self.taskflow_owner_agent_id().as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if advanced.rows_affected() != 1 {
                return Err(AutomationError::Corrupt);
            }
        }

        transaction.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }
}

fn next_after_terminal(
    schedule: AutomationSchedule,
    policy: AutomationMissedRunPolicy,
    scheduled_for_ms: u64,
    now_ms: u64,
) -> Result<Option<u64>, AutomationError> {
    let AutomationSchedule::FixedInterval { interval_ms } = schedule else {
        return Ok(None);
    };
    let nominal = scheduled_for_ms
        .checked_add(interval_ms)
        .ok_or(AutomationError::Invalid)?;
    if nominal > now_ms {
        return Ok(Some(nominal));
    }

    let next = match policy {
        AutomationMissedRunPolicy::Skip => {
            let elapsed = now_ms
                .checked_sub(scheduled_for_ms)
                .ok_or(AutomationError::Invalid)?;
            let slots = elapsed
                .checked_div(interval_ms)
                .ok_or(AutomationError::Invalid)?
                .checked_add(1)
                .ok_or(AutomationError::Invalid)?;
            scheduled_for_ms
                .checked_add(
                    interval_ms
                        .checked_mul(slots)
                        .ok_or(AutomationError::Invalid)?,
                )
                .ok_or(AutomationError::Invalid)?
        }
        AutomationMissedRunPolicy::Coalesce => {
            let elapsed = now_ms
                .checked_sub(scheduled_for_ms)
                .ok_or(AutomationError::Invalid)?;
            let slots = elapsed
                .checked_div(interval_ms)
                .ok_or(AutomationError::Invalid)?;
            scheduled_for_ms
                .checked_add(
                    interval_ms
                        .checked_mul(slots)
                        .ok_or(AutomationError::Invalid)?,
                )
                .ok_or(AutomationError::Invalid)?
        }
        AutomationMissedRunPolicy::BoundedCatchUp { max_occurrences } => {
            let due = now_ms
                .checked_sub(nominal)
                .ok_or(AutomationError::Invalid)?
                .checked_div(interval_ms)
                .ok_or(AutomationError::Invalid)?
                .checked_add(1)
                .ok_or(AutomationError::Invalid)?;
            let skip = due.saturating_sub(u64::from(max_occurrences));
            nominal
                .checked_add(
                    interval_ms
                        .checked_mul(skip)
                        .ok_or(AutomationError::Invalid)?,
                )
                .ok_or(AutomationError::Invalid)?
        }
    };
    Ok(Some(next))
}

fn schedule_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<AutomationSchedule, AutomationError> {
    let kind: String = row.try_get("schedule_kind").map_err(unavailable)?;
    let interval: Option<i64> = row.try_get("interval_ms").map_err(unavailable)?;
    let schedule = match (kind.as_str(), interval) {
        ("once", None) => AutomationSchedule::Once,
        ("fixed_interval", Some(interval)) => AutomationSchedule::FixedInterval {
            interval_ms: to_u64(interval)?,
        },
        _ => return Err(AutomationError::Corrupt),
    };
    schedule.validate().map_err(|_| AutomationError::Corrupt)?;
    Ok(schedule)
}

fn schedule_columns(schedule: AutomationSchedule) -> (&'static str, Option<u64>) {
    match schedule {
        AutomationSchedule::Once => ("once", None),
        AutomationSchedule::FixedInterval { interval_ms } => ("fixed_interval", Some(interval_ms)),
    }
}

fn occurrence_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<AutomationOccurrence, AutomationError> {
    Ok(AutomationOccurrence {
        task_id: AutomationTaskId::parse(
            &row.try_get::<String, _>("task_id").map_err(unavailable)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        occurrence: to_u64(row.try_get("occurrence").map_err(unavailable)?)?,
        occurrence_id: row.try_get("occurrence_id").map_err(unavailable)?,
        schedule_revision: to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?,
        scheduled_for_ms: to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?,
        lifecycle_state: row.try_get("lifecycle_state").map_err(unavailable)?,
        taskflow_run_id: row.try_get("taskflow_run_id").map_err(unavailable)?,
        queued_submission_id: row.try_get("queued_submission_id").map_err(unavailable)?,
        terminal_reason: row.try_get("terminal_reason").map_err(unavailable)?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}

fn validate_identifier(value: &str) -> Result<(), AutomationError> {
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), AutomationError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn validate_reason(value: &str) -> Result<(), AutomationError> {
    if value.is_empty() || value.len() > MAX_DETAIL_BYTES || value.contains('\0') {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn is_unique(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation())
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
    fn skip_moves_to_first_future_slot() {
        assert_eq!(
            next_after_terminal(
                AutomationSchedule::FixedInterval { interval_ms: 10 },
                AutomationMissedRunPolicy::Skip,
                100,
                145,
            ),
            Ok(Some(150))
        );
    }

    #[test]
    fn coalesce_keeps_only_latest_due_slot() {
        assert_eq!(
            next_after_terminal(
                AutomationSchedule::FixedInterval { interval_ms: 10 },
                AutomationMissedRunPolicy::Coalesce,
                100,
                145,
            ),
            Ok(Some(140))
        );
    }

    #[test]
    fn bounded_catch_up_limits_backlog() {
        assert_eq!(
            next_after_terminal(
                AutomationSchedule::FixedInterval { interval_ms: 10 },
                AutomationMissedRunPolicy::BoundedCatchUp { max_occurrences: 3 },
                100,
                200,
            ),
            Ok(Some(180))
        );
    }
}
