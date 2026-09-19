//! Durable bridge between scheduler-owned occurrences and the existing TaskFlow ledger.
//!
//! This module does not implement a scheduler or a second workflow engine. It binds one
//! deterministic automation occurrence to one durable TaskFlow run and projects verified
//! TaskFlow terminality back into the automation-owned occurrence record.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceTerminalState;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskId;
use crate::AutomationTaskState;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;

pub const AUTOMATION_OCCURRENCE_WORKFLOW_ID: &str = "automation-occurrence";
pub const AUTOMATION_OCCURRENCE_WORKFLOW_VERSION: u32 = 1;
const RECOVERY_OWNER_ID: &str = "automation-scheduler-recovery";
const MAX_RECONCILE_BATCH: usize = 1_024;

impl AutomationStore {
    /// Ensures the durable TaskFlow run for one materialized occurrence exists
    /// and binds the automation projection to that exact run id. The operation
    /// is idempotent and deliberately does not claim or start the run.
    pub async fn ensure_occurrence_taskflow(
        &self,
        lease: &AutomationLease,
        now_ms: u64,
    ) -> Result<TaskFlowRun, AutomationError> {
        if lease.task.owner_agent_id != *self.owner_agent_id() || lease.schedule_revision == 0 {
            return Err(AutomationError::AccessDenied);
        }
        let definition = automation_occurrence_definition().map_err(map_taskflow_error)?;
        let fence = occurrence_fence(lease)?;
        self.register_taskflow_definition(&definition, &fence, now_ms)
            .await
            .map_err(map_taskflow_error)?;
        let run = self
            .create_taskflow_run(
                lease.occurrence_id.clone(),
                AUTOMATION_OCCURRENCE_WORKFLOW_ID,
                AUTOMATION_OCCURRENCE_WORKFLOW_VERSION,
                definition.definition_digest(),
                lease.task.thread_id.clone(),
                now_ms,
            )
            .await
            .map_err(map_taskflow_error)?;

        let linked = sqlx::query(
            "UPDATE automation_runs
             SET taskflow_run_id = ?
             WHERE task_id = ? AND occurrence = ?
               AND occurrence_id = ? AND schedule_revision = ?
               AND (taskflow_run_id IS NULL OR taskflow_run_id = ?)",
        )
        .bind(&run.run_id)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(&lease.occurrence_id)
        .bind(to_i64(lease.schedule_revision)?)
        .bind(&run.run_id)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if linked.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        Ok(run)
    }

    /// Starts the linked TaskFlow only after queue admission is durably known.
    /// Starting is not completion: the run remains active until a terminal
    /// TaskFlow transition backed by its own effect/observation chain arrives.
    pub async fn start_occurrence_taskflow(
        &self,
        lease: &AutomationLease,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<TaskFlowRun, AutomationError> {
        let run = self.ensure_occurrence_taskflow(lease, now_ms).await?;
        if matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) || run.state == TaskFlowRunState::Running {
            return Ok(run);
        }
        if run.state != TaskFlowRunState::Queued {
            return Err(AutomationError::Conflict);
        }
        let fence = occurrence_fence(lease)?;
        let claimed = self
            .claim_taskflow_run(&run.run_id, &fence, now_ms, lease_duration_ms)
            .await
            .map_err(map_taskflow_error)?;
        if claimed.state == TaskFlowRunState::Running {
            return Ok(claimed);
        }
        let command = TaskFlowCommand::new(
            &run.run_id,
            format!("automation:{}:start", lease.occurrence_id),
            fence,
            claimed.revision,
            TaskFlowTransition::Start,
            now_ms,
        )
        .map_err(map_taskflow_error)?;
        self.apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
        self.taskflow_run(&run.run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)
    }

    /// Replays the safe half of a crash window where queue admission committed
    /// but the process died before the TaskFlow Start transition. A queued run
    /// can be claimed by the current scheduler generation; a still-live older
    /// fence is simply left alone until it expires.
    pub async fn start_submitted_taskflows(
        &self,
        generation: u64,
        now_ms: u64,
        lease_duration_ms: u64,
        limit: usize,
    ) -> Result<u64, AutomationError> {
        if generation == 0
            || lease_duration_ms == 0
            || !(1..=MAX_RECONCILE_BATCH).contains(&limit)
        {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT r.taskflow_run_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             JOIN taskflow_runs f
               ON f.owner_agent_id = t.owner_agent_id
              AND f.run_id = r.taskflow_run_id
             WHERE t.owner_agent_id = ? AND r.state = 'submitted'
               AND r.terminal_state IS NULL AND f.state = 'queued'
             ORDER BY r.scheduled_for_ms, r.task_id, r.occurrence
             LIMIT ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;

        let mut started = 0_u64;
        for row in rows {
            let run_id: String = row
                .try_get("taskflow_run_id")
                .map_err(|_| AutomationError::Corrupt)?;
            let fence = TaskFlowFence::new(
                self.owner_agent_id().clone(),
                RECOVERY_OWNER_ID,
                generation,
                generation,
                uuid::Uuid::now_v7().to_string(),
            )
            .map_err(map_taskflow_error)?;
            let claimed = match self
                .claim_taskflow_run(&run_id, &fence, now_ms, lease_duration_ms)
                .await
            {
                Ok(run) => run,
                Err(TaskFlowError::StaleFence | TaskFlowError::Conflict(_)) => continue,
                Err(error) => return Err(map_taskflow_error(error)),
            };
            if claimed.state != TaskFlowRunState::Queued {
                continue;
            }
            let command = TaskFlowCommand::new(
                &run_id,
                format!("automation:{run_id}:recovery-start"),
                fence,
                claimed.revision,
                TaskFlowTransition::Start,
                now_ms,
            )
            .map_err(map_taskflow_error)?;
            match self.apply_taskflow_command(&command).await {
                Ok(_) => started = started.saturating_add(1),
                Err(TaskFlowError::StaleFence | TaskFlowError::Conflict(_)) => {}
                Err(error) => return Err(map_taskflow_error(error)),
            }
        }
        Ok(started)
    }

    pub async fn occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        let row = sqlx::query(
            "SELECT r.task_id, r.occurrence, r.occurrence_id, r.schedule_revision,
                    r.scheduled_for_ms, r.taskflow_run_id, r.terminal_state,
                    r.terminal_receipt_digest, r.terminal_at_ms
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE t.owner_agent_id = ? AND r.task_id = ? AND r.occurrence = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        row.map(|row| occurrence_from_row(&row)).transpose()
    }

    /// Projects a verified durable TaskFlow terminal state into the
    /// automation-owned occurrence. Replaying after a crash is idempotent.
    pub async fn finalize_occurrence_from_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        let projection = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let run_id = projection
            .taskflow_run_id
            .as_deref()
            .ok_or(AutomationError::Conflict)?;
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        let terminal = taskflow_terminal(run.state).ok_or(AutomationError::Conflict)?;
        let receipt_digest = run.state_digest.as_str().to_string();

        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let current = sqlx::query(
            "SELECT terminal_state, terminal_receipt_digest
             FROM automation_runs
             WHERE task_id = ? AND occurrence = ? AND occurrence_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(&projection.occurrence_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let current_state: Option<String> = current
            .try_get("terminal_state")
            .map_err(|_| AutomationError::Corrupt)?;
        let current_digest: Option<String> = current
            .try_get("terminal_receipt_digest")
            .map_err(|_| AutomationError::Corrupt)?;
        if let Some(state) = current_state {
            if AutomationOccurrenceTerminalState::parse(&state)? != terminal
                || current_digest.as_deref() != Some(receipt_digest.as_str())
            {
                return Err(AutomationError::Conflict);
            }
            transaction
                .commit()
                .await
                .map_err(|_| AutomationError::Unavailable)?;
            return self.task(task_id).await?.ok_or(AutomationError::Corrupt);
        }

        let updated = sqlx::query(
            "UPDATE automation_runs
             SET terminal_state = ?, terminal_receipt_digest = ?, terminal_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND terminal_state IS NULL
               AND taskflow_run_id = ?",
        )
        .bind(terminal.as_str())
        .bind(&receipt_digest)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(run_id)
        .execute(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        // A one-shot schedule has no future frontier. It becomes completed only
        // here, after the occurrence itself is terminal, never at queue admission.
        sqlx::query(
            "UPDATE automation_tasks
             SET state = 'completed', updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'
               AND schedule_kind = 'once' AND next_run_at_ms IS NULL",
        )
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.owner_agent_id().as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?;

        transaction
            .commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    /// Bounded reconciliation sweep used by the existing scheduler loop.
    /// Only already-terminal TaskFlow projections are considered.
    pub async fn reconcile_terminal_occurrences(
        &self,
        now_ms: u64,
        limit: usize,
    ) -> Result<u64, AutomationError> {
        if !(1..=MAX_RECONCILE_BATCH).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT r.task_id, r.occurrence
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             JOIN taskflow_runs f
               ON f.owner_agent_id = t.owner_agent_id
              AND f.run_id = r.taskflow_run_id
             WHERE t.owner_agent_id = ? AND r.terminal_state IS NULL
               AND f.state IN ('succeeded', 'failed', 'cancelled')
             ORDER BY r.scheduled_for_ms, r.task_id, r.occurrence
             LIMIT ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let mut reconciled = 0_u64;
        for row in rows {
            let task_id = AutomationTaskId::parse(
                &row.try_get::<String, _>("task_id")
                    .map_err(|_| AutomationError::Corrupt)?,
            )?;
            let occurrence = to_u64(
                row.try_get("occurrence")
                    .map_err(|_| AutomationError::Corrupt)?,
            )?;
            self.finalize_occurrence_from_taskflow(task_id, occurrence, now_ms)
                .await?;
            reconciled = reconciled.saturating_add(1);
        }
        Ok(reconciled)
    }
}

fn automation_occurrence_definition() -> Result<TaskFlowDefinition, TaskFlowError> {
    TaskFlowDefinition::new(
        AUTOMATION_OCCURRENCE_WORKFLOW_ID,
        AUTOMATION_OCCURRENCE_WORKFLOW_VERSION,
        "codex_turn",
        vec![
            TaskFlowNodeSpec::new("codex_turn", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("codex_turn", "success"),
            TaskFlowEdgeSpec::new("codex_turn", "failure"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"hepta.automation.occurrence.workflow.v1"),
    )
}

fn occurrence_fence(lease: &AutomationLease) -> Result<TaskFlowFence, AutomationError> {
    TaskFlowFence::new(
        lease.task.owner_agent_id.clone(),
        "automation-scheduler",
        lease.lease_generation,
        lease.lease_generation,
        lease.lease_token.clone(),
    )
    .map_err(map_taskflow_error)
}

fn taskflow_terminal(state: TaskFlowRunState) -> Option<AutomationOccurrenceTerminalState> {
    match state {
        TaskFlowRunState::Succeeded => Some(AutomationOccurrenceTerminalState::Succeeded),
        TaskFlowRunState::Failed => Some(AutomationOccurrenceTerminalState::Failed),
        TaskFlowRunState::Cancelled => Some(AutomationOccurrenceTerminalState::Cancelled),
        TaskFlowRunState::Queued
        | TaskFlowRunState::Running
        | TaskFlowRunState::Waiting
        | TaskFlowRunState::RetryBackoff
        | TaskFlowRunState::Indeterminate => None,
    }
}

fn occurrence_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<AutomationOccurrence, AutomationError> {
    let terminal_state = row
        .try_get::<Option<String>, _>("terminal_state")
        .map_err(|_| AutomationError::Corrupt)?
        .map(|value| AutomationOccurrenceTerminalState::parse(&value))
        .transpose()?;
    Ok(AutomationOccurrence {
        task_id: AutomationTaskId::parse(
            &row.try_get::<String, _>("task_id")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        occurrence: to_u64(
            row.try_get("occurrence")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        occurrence_id: row
            .try_get("occurrence_id")
            .map_err(|_| AutomationError::Corrupt)?,
        schedule_revision: to_u64(
            row.try_get("schedule_revision")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        scheduled_for_ms: to_u64(
            row.try_get("scheduled_for_ms")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        taskflow_run_id: row
            .try_get("taskflow_run_id")
            .map_err(|_| AutomationError::Corrupt)?,
        terminal_state,
        terminal_receipt_digest: row
            .try_get("terminal_receipt_digest")
            .map_err(|_| AutomationError::Corrupt)?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(|_| AutomationError::Corrupt)?
            .map(to_u64)
            .transpose()?,
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
