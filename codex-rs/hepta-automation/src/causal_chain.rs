use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationQueueReceipt;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;

const OCCURRENCE_DOMAIN: &[u8] = b"hepta.automation.occurrence.v1\0";
const MAX_POLICY_CATCH_UP: u32 = 1_024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOverlapPolicy {
    Forbid,
    Queue,
    Allow,
}

impl AutomationOverlapPolicy {
    fn as_str(self) -> &'static str {
        match self {
            Self::Forbid => "forbid",
            Self::Queue => "queue",
            Self::Allow => "allow",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "forbid" => Ok(Self::Forbid),
            "queue" => Ok(Self::Queue),
            "allow" => Ok(Self::Allow),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationMissedRunPolicy {
    Skip,
    CoalesceLatest,
    CatchUpBounded,
}

impl AutomationMissedRunPolicy {
    fn as_str(self) -> &'static str {
        match self {
            Self::Skip => "skip",
            Self::CoalesceLatest => "coalesce_latest",
            Self::CatchUpBounded => "catch_up_bounded",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "skip" => Ok(Self::Skip),
            "coalesce_latest" => Ok(Self::CoalesceLatest),
            "catch_up_bounded" => Ok(Self::CatchUpBounded),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationScheduleContract {
    pub task_id: AutomationTaskId,
    pub schedule_revision: u64,
    pub overlap_policy: AutomationOverlapPolicy,
    pub missed_run_policy: AutomationMissedRunPolicy,
    pub max_catch_up: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOccurrenceState {
    Materialized,
    QueueAdmitted,
    TaskflowBound,
    Running,
    Indeterminate,
    Succeeded,
    Failed,
    Cancelled,
}

impl AutomationOccurrenceState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Materialized => "materialized",
            Self::QueueAdmitted => "queue_admitted",
            Self::TaskflowBound => "taskflow_bound",
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
            "queue_admitted" => Ok(Self::QueueAdmitted),
            "taskflow_bound" => Ok(Self::TaskflowBound),
            "running" => Ok(Self::Running),
            "indeterminate" => Ok(Self::Indeterminate),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(AutomationError::Corrupt),
        }
    }

    fn terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationOccurrence {
    pub occurrence_id: String,
    pub task_id: AutomationTaskId,
    pub schedule_revision: u64,
    pub ordinal: u64,
    pub scheduled_for_ms: u64,
    pub client_user_message_id: String,
    pub state: AutomationOccurrenceState,
    pub queued_submission_id: Option<String>,
    pub taskflow_run_id: Option<String>,
    pub provider_observation_digest: Option<Sha256Digest>,
    pub terminal_reason: Option<String>,
    pub materialized_at_ms: u64,
    pub updated_at_ms: u64,
    pub terminal_at_ms: Option<u64>,
}

pub fn deterministic_occurrence_id(
    task_id: AutomationTaskId,
    schedule_revision: u64,
    scheduled_for_ms: u64,
) -> Result<String, AutomationError> {
    if schedule_revision == 0 {
        return Err(AutomationError::Invalid);
    }
    let mut hasher = Sha256::new();
    hasher.update(OCCURRENCE_DOMAIN);
    hasher.update(task_id.to_string().as_bytes());
    hasher.update([0]);
    hasher.update(schedule_revision.to_be_bytes());
    hasher.update(scheduled_for_ms.to_be_bytes());
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in digest {
        out.push(char::from(HEX[usize::from(byte >> 4)]));
        out.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    Ok(out)
}

impl AutomationStore {
    pub async fn schedule_contract(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<AutomationScheduleContract, AutomationError> {
        let row = sqlx::query(
            "SELECT schedule_revision, overlap_policy, missed_run_policy, max_catch_up
             FROM automation_tasks WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?
        .ok_or(AutomationError::Conflict)?;
        Ok(AutomationScheduleContract {
            task_id,
            schedule_revision: to_u64(row.try_get("schedule_revision").map_err(|_| AutomationError::Corrupt)?)?,
            overlap_policy: AutomationOverlapPolicy::parse(
                &row.try_get::<String, _>("overlap_policy").map_err(|_| AutomationError::Corrupt)?,
            )?,
            missed_run_policy: AutomationMissedRunPolicy::parse(
                &row.try_get::<String, _>("missed_run_policy").map_err(|_| AutomationError::Corrupt)?,
            )?,
            max_catch_up: u32::try_from(
                row.try_get::<i64, _>("max_catch_up").map_err(|_| AutomationError::Corrupt)?,
            )
            .map_err(|_| AutomationError::Corrupt)?,
        })
    }

    pub async fn set_recurring_policy(
        &self,
        task_id: AutomationTaskId,
        overlap_policy: AutomationOverlapPolicy,
        missed_run_policy: AutomationMissedRunPolicy,
        max_catch_up: u32,
        now_ms: u64,
    ) -> Result<AutomationScheduleContract, AutomationError> {
        // The current scheduler has one lease/admission lane per automation.
        // Activate only the semantics it can enforce without inventing a
        // second scheduler. Queue/allow remain reserved schema values until a
        // caller can materialize multiple durable occurrences independently.
        if overlap_policy != AutomationOverlapPolicy::Forbid
            || max_catch_up == 0
            || max_catch_up > MAX_POLICY_CATCH_UP
        {
            return Err(AutomationError::Invalid);
        }
        let changed = sqlx::query(
            "UPDATE automation_tasks
             SET overlap_policy = ?, missed_run_policy = ?, max_catch_up = ?,
                 schedule_revision = schedule_revision + 1, updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ?
               AND state IN ('enabled', 'disabled')",
        )
        .bind(overlap_policy.as_str())
        .bind(missed_run_policy.as_str())
        .bind(i64::from(max_catch_up))
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.schedule_contract(task_id).await
    }

    /// Materialize the semantic occurrence identity beside the scheduler lease.
    /// Queue admission and semantic completion are deliberately separate states.
    pub async fn materialize_causal_occurrence(
        &self,
        lease: &AutomationLease,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if &lease.task.owner_agent_id != self.taskflow_owner_agent_id() {
            return Err(AutomationError::AccessDenied);
        }
        let contract = self.schedule_contract(lease.task.task_id).await?;
        let occurrence_id = deterministic_occurrence_id(
            lease.task.task_id,
            contract.schedule_revision,
            lease.scheduled_for_ms,
        )?;
        sqlx::query(
            "INSERT INTO automation_occurrences (
                owner_agent_id, occurrence_id, task_id, schedule_revision, ordinal,
                scheduled_for_ms, client_user_message_id, state,
                materialized_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, 'materialized', ?, ?)
             ON CONFLICT(owner_agent_id, occurrence_id) DO NOTHING",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&occurrence_id)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(contract.schedule_revision)?)
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.scheduled_for_ms)?)
        .bind(&lease.client_user_message_id)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let occurrence = self
            .causal_occurrence(&occurrence_id)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        if occurrence.task_id != lease.task.task_id
            || occurrence.ordinal != lease.occurrence
            || occurrence.scheduled_for_ms != lease.scheduled_for_ms
            || occurrence.client_user_message_id != lease.client_user_message_id
        {
            return Err(AutomationError::Conflict);
        }
        Ok(occurrence)
    }

    pub async fn causal_occurrence(
        &self,
        occurrence_id: &str,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        let row = sqlx::query(
            "SELECT occurrence_id, task_id, schedule_revision, ordinal, scheduled_for_ms,
                    client_user_message_id, state, queued_submission_id, taskflow_run_id,
                    provider_observation_digest, terminal_reason, materialized_at_ms,
                    updated_at_ms, terminal_at_ms
             FROM automation_occurrences
             WHERE owner_agent_id = ? AND occurrence_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        row.map(|row| occurrence_from_row(&row)).transpose()
    }

    pub async fn record_causal_queue_admission(
        &self,
        lease: &AutomationLease,
        receipt: &AutomationQueueReceipt,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if receipt.client_user_message_id != lease.client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            return Err(AutomationError::AccessDenied);
        }
        let occurrence = self.materialize_causal_occurrence(lease, now_ms).await?;
        if occurrence.state.terminal() {
            return Err(AutomationError::Conflict);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrences
             SET state = CASE
                     WHEN state = 'materialized' THEN 'queue_admitted'
                     ELSE state
                 END,
                 queued_submission_id = COALESCE(queued_submission_id, ?),
                 updated_at_ms = ?
             WHERE owner_agent_id = ? AND occurrence_id = ?
               AND (queued_submission_id IS NULL OR queued_submission_id = ?)",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&occurrence.occurrence_id)
        .bind(&receipt.queued_submission_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.causal_occurrence(&occurrence.occurrence_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    /// Ensure the occurrence has a deterministic durable TaskFlow run, then
    /// bind it to the occurrence. A crash between run creation and binding is
    /// safe: both operations are idempotent and the deterministic run id is
    /// derived only from the occurrence id.
    pub async fn ensure_occurrence_taskflow_run(
        &self,
        occurrence_id: &str,
        workflow_id: &str,
        workflow_version: u32,
        definition_digest: &Sha256Digest,
        created_at_ms: u64,
    ) -> Result<TaskFlowRun, AutomationError> {
        let occurrence = self
            .causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let task = self
            .task(occurrence.task_id)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        let run_id = format!("automation:{}", occurrence.occurrence_id);
        let run = self
            .create_taskflow_run(
                run_id.clone(),
                workflow_id,
                workflow_version,
                definition_digest,
                task.thread_id,
                created_at_ms,
            )
            .await
            .map_err(map_taskflow_error)?;
        self.bind_occurrence_taskflow_run(occurrence_id, &run_id, created_at_ms)
            .await?;
        Ok(run)
    }

    /// Bind an already durable TaskFlow run to this occurrence. The run must
    /// belong to the same Agent. This is idempotent for the exact same binding.
    pub async fn bind_occurrence_taskflow_run(
        &self,
        occurrence_id: &str,
        run_id: &str,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(|_| AutomationError::Unavailable)?
            .ok_or(AutomationError::Conflict)?;
        if &run.owner_agent_id != self.taskflow_owner_agent_id() {
            return Err(AutomationError::AccessDenied);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrences
             SET taskflow_run_id = COALESCE(taskflow_run_id, ?),
                 state = CASE
                     WHEN state IN ('materialized', 'queue_admitted') THEN 'taskflow_bound'
                     ELSE state
                 END,
                 updated_at_ms = ?
             WHERE owner_agent_id = ? AND occurrence_id = ?
               AND (taskflow_run_id IS NULL OR taskflow_run_id = ?)
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(run_id)
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence_id)
        .bind(run_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    pub async fn record_provider_observation(
        &self,
        occurrence_id: &str,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        receipt_digest: &Sha256Digest,
        observation: AutomationProviderObservation,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if attempt == 0 || step_id.is_empty() || run_id.is_empty() {
            return Err(AutomationError::Invalid);
        }
        let occurrence = self
            .causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if occurrence.taskflow_run_id.as_deref() != Some(run_id) || occurrence.state.terminal() {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "INSERT INTO automation_provider_observations (
                 owner_agent_id, occurrence_id, run_id, step_id, attempt,
                 receipt_digest, observation, observed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(owner_agent_id, occurrence_id, run_id, step_id, attempt, receipt_digest)
             DO NOTHING",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence_id)
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(receipt_digest.as_str())
        .bind(observation.as_str())
        .bind(to_i64(observed_at_ms)?)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let next_state = if observation == AutomationProviderObservation::Indeterminate {
            AutomationOccurrenceState::Indeterminate
        } else {
            AutomationOccurrenceState::Running
        };
        sqlx::query(
            "UPDATE automation_occurrences
             SET state = ?, provider_observation_digest = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND occurrence_id = ?
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(next_state.as_str())
        .bind(receipt_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        self.causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    /// Project a terminal TaskFlow state onto the automation occurrence and
    /// only then advance the recurring schedule.
    pub async fn reconcile_occurrence_from_taskflow(
        &self,
        occurrence_id: &str,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let occurrence = self
            .causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if occurrence.state.terminal() {
            return Ok(occurrence);
        }
        let run_id = occurrence
            .taskflow_run_id
            .clone()
            .ok_or(AutomationError::Conflict)?;
        let run = self
            .taskflow_run(&run_id)
            .await
            .map_err(|_| AutomationError::Unavailable)?
            .ok_or(AutomationError::Conflict)?;
        let terminal = match run.state {
            TaskFlowRunState::Succeeded => Some((AutomationOccurrenceState::Succeeded, None)),
            TaskFlowRunState::Failed => Some((
                AutomationOccurrenceState::Failed,
                run.terminal_reason.clone(),
            )),
            TaskFlowRunState::Cancelled => Some((
                AutomationOccurrenceState::Cancelled,
                run.terminal_reason.clone(),
            )),
            TaskFlowRunState::Indeterminate => {
                sqlx::query(
                    "UPDATE automation_occurrences
                     SET state = 'indeterminate', updated_at_ms = ?
                     WHERE owner_agent_id = ? AND occurrence_id = ?
                       AND state NOT IN ('succeeded', 'failed', 'cancelled')",
                )
                .bind(to_i64(now_ms)?)
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(occurrence_id)
                .execute(self.taskflow_pool())
                .await
                .map_err(|_| AutomationError::Unavailable)?;
                return self
                    .causal_occurrence(occurrence_id)
                    .await?
                    .ok_or(AutomationError::Corrupt);
            }
            TaskFlowRunState::Queued
            | TaskFlowRunState::Running
            | TaskFlowRunState::Waiting
            | TaskFlowRunState::RetryBackoff => None,
        };
        let Some((terminal_state, reason)) = terminal else {
            return Err(AutomationError::Conflict);
        };

        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let updated = sqlx::query(
            "UPDATE automation_occurrences
             SET state = ?, terminal_reason = ?, terminal_at_ms = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND occurrence_id = ?
               AND state NOT IN ('succeeded', 'failed', 'cancelled')",
        )
        .bind(terminal_state.as_str())
        .bind(reason.as_deref())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        let task = sqlx::query(
            "SELECT state, schedule_kind, interval_ms, missed_run_policy, max_catch_up
             FROM automation_tasks
             WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(occurrence.task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let task_state: String = task.try_get("state").map_err(|_| AutomationError::Corrupt)?;
        if task_state == "enabled" {
            let schedule_kind: String =
                task.try_get("schedule_kind").map_err(|_| AutomationError::Corrupt)?;
            let (next_state, next_run) = if schedule_kind == "once" {
                ("completed", None)
            } else {
                let interval_ms = to_u64(
                    task.try_get::<i64, _>("interval_ms")
                        .map_err(|_| AutomationError::Corrupt)?,
                )?;
                let policy = AutomationMissedRunPolicy::parse(
                    &task
                        .try_get::<String, _>("missed_run_policy")
                        .map_err(|_| AutomationError::Corrupt)?,
                )?;
                let max_catch_up = u32::try_from(
                    task.try_get::<i64, _>("max_catch_up")
                        .map_err(|_| AutomationError::Corrupt)?,
                )
                .map_err(|_| AutomationError::Corrupt)?;
                (
                    "enabled",
                    Some(next_scheduled_instant(
                        occurrence.scheduled_for_ms,
                        interval_ms,
                        now_ms,
                        policy,
                        max_catch_up,
                    )?),
                )
            };
            sqlx::query(
                "UPDATE automation_tasks
                 SET state = ?, next_run_at_ms = ?, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ?",
            )
            .bind(next_state)
            .bind(next_run.map(to_i64).transpose()?)
            .bind(to_i64(now_ms)?)
            .bind(occurrence.task_id.to_string())
            .bind(self.taskflow_owner_agent_id().as_str())
            .execute(&mut *tx)
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        }
        tx.commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        self.causal_occurrence(occurrence_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationProviderObservation {
    Succeeded,
    Failed,
    Indeterminate,
}

impl AutomationProviderObservation {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Indeterminate => "indeterminate",
        }
    }
}

fn occurrence_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<AutomationOccurrence, AutomationError> {
    let task_id = AutomationTaskId::parse(
        &row.try_get::<String, _>("task_id")
            .map_err(|_| AutomationError::Corrupt)?,
    )
    .map_err(|_| AutomationError::Corrupt)?;
    let provider_observation_digest = row
        .try_get::<Option<String>, _>("provider_observation_digest")
        .map_err(|_| AutomationError::Corrupt)?
        .map(|value| Sha256Digest::parse(&value).map_err(|_| AutomationError::Corrupt))
        .transpose()?;
    Ok(AutomationOccurrence {
        occurrence_id: row.try_get("occurrence_id").map_err(|_| AutomationError::Corrupt)?,
        task_id,
        schedule_revision: to_u64(
            row.try_get("schedule_revision")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        ordinal: to_u64(row.try_get("ordinal").map_err(|_| AutomationError::Corrupt)?)?,
        scheduled_for_ms: to_u64(
            row.try_get("scheduled_for_ms")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        client_user_message_id: row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?,
        state: AutomationOccurrenceState::parse(
            &row.try_get::<String, _>("state")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        queued_submission_id: row
            .try_get("queued_submission_id")
            .map_err(|_| AutomationError::Corrupt)?,
        taskflow_run_id: row
            .try_get("taskflow_run_id")
            .map_err(|_| AutomationError::Corrupt)?,
        provider_observation_digest,
        terminal_reason: row
            .try_get("terminal_reason")
            .map_err(|_| AutomationError::Corrupt)?,
        materialized_at_ms: to_u64(
            row.try_get("materialized_at_ms")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        updated_at_ms: to_u64(
            row.try_get("updated_at_ms")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(|_| AutomationError::Corrupt)?
            .map(to_u64)
            .transpose()?,
    })
}

fn next_scheduled_instant(
    previous_ms: u64,
    interval_ms: u64,
    now_ms: u64,
    policy: AutomationMissedRunPolicy,
    max_catch_up: u32,
) -> Result<u64, AutomationError> {
    if interval_ms == 0 || max_catch_up == 0 {
        return Err(AutomationError::Corrupt);
    }
    let base = previous_ms
        .checked_add(interval_ms)
        .ok_or(AutomationError::Invalid)?;
    if base > now_ms {
        return Ok(base);
    }
    let elapsed = now_ms.saturating_sub(previous_ms);
    let intervals_elapsed = elapsed / interval_ms;
    match policy {
        AutomationMissedRunPolicy::Skip => {
            let steps = intervals_elapsed
                .checked_add(1)
                .ok_or(AutomationError::Invalid)?;
            previous_ms
                .checked_add(interval_ms.checked_mul(steps).ok_or(AutomationError::Invalid)?)
                .ok_or(AutomationError::Invalid)
        }
        AutomationMissedRunPolicy::CoalesceLatest => previous_ms
            .checked_add(
                interval_ms
                    .checked_mul(intervals_elapsed.max(1))
                    .ok_or(AutomationError::Invalid)?,
            )
            .ok_or(AutomationError::Invalid),
        AutomationMissedRunPolicy::CatchUpBounded => {
            let backlog = intervals_elapsed.max(1);
            let cap = u64::from(max_catch_up);
            let first_remaining = backlog.saturating_sub(cap.saturating_sub(1)).max(1);
            previous_ms
                .checked_add(
                    interval_ms
                        .checked_mul(first_remaining)
                        .ok_or(AutomationError::Invalid)?,
                )
                .ok_or(AutomationError::Invalid)
        }
    }
}

fn map_taskflow_error(error: crate::TaskFlowError) -> AutomationError {
    match error {
        crate::TaskFlowError::Unavailable => AutomationError::Unavailable,
        crate::TaskFlowError::StaleFence => AutomationError::AccessDenied,
        crate::TaskFlowError::Invalid(_) => AutomationError::Invalid,
        crate::TaskFlowError::Conflict(_) | crate::TaskFlowError::InvalidTransition(_) => {
            AutomationError::Conflict
        }
        crate::TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
    }
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn occurrence_identity_changes_with_revision_and_time() {
        let task = AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75008").unwrap();
        let a = deterministic_occurrence_id(task, 1, 1000).unwrap();
        assert_eq!(a, deterministic_occurrence_id(task, 1, 1000).unwrap());
        assert_ne!(a, deterministic_occurrence_id(task, 2, 1000).unwrap());
        assert_ne!(a, deterministic_occurrence_id(task, 1, 2000).unwrap());
    }

    #[test]
    fn missed_run_policies_are_bounded_and_deterministic() {
        assert_eq!(
            next_scheduled_instant(1_000, 1_000, 5_500, AutomationMissedRunPolicy::Skip, 1).unwrap(),
            6_000
        );
        assert_eq!(
            next_scheduled_instant(
                1_000,
                1_000,
                5_500,
                AutomationMissedRunPolicy::CoalesceLatest,
                1,
            )
            .unwrap(),
            5_000
        );
        assert_eq!(
            next_scheduled_instant(
                1_000,
                1_000,
                5_500,
                AutomationMissedRunPolicy::CatchUpBounded,
                2,
            )
            .unwrap(),
            4_000
        );
    }
}
