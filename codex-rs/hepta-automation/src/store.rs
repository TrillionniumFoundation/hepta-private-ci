use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationDispatchUncertainty;
use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationMissedRunPolicy;
use crate::AutomationOccurrenceId;
use crate::AutomationOccurrenceTerminal;
use crate::AutomationOverlapPolicy;
use crate::AutomationProviderObservationKind;
use crate::AutomationQueueReceipt;
use crate::AutomationSchedule;
use crate::AutomationSchedulePolicy;
use crate::AutomationTask;
use crate::AutomationTaskDraft;
use crate::AutomationTaskId;
use crate::AutomationTaskState;
use crate::AutomationSubmittedOccurrence;
use crate::model::client_message_id;
use crate::taskflow::TaskFlowError;
use crate::taskflow::verify_taskflow_store;

const AUTOMATION_DB_FILENAME: &str = "automation_1.sqlite3";
const MAX_TASK_PAGE: usize = 1_024;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone)]
pub struct AutomationStore {
    pool: SqlitePool,
    owner_agent_id: AgentId,
    path: PathBuf,
}

impl AutomationStore {
    pub async fn open(layout: &HeptaAgentLayout) -> Result<Self, AutomationError> {
        Self::open_root(
            layout.automation_root().to_path_buf(),
            layout.agent_id().clone(),
        )
        .await
    }

    async fn open_root(root: PathBuf, owner_agent_id: AgentId) -> Result<Self, AutomationError> {
        create_private_directory(&root)?;
        let path = root.join(AUTOMATION_DB_FILENAME);
        let sqlite_home = AbsolutePathBuf::try_from(root).map_err(|_| AutomationError::Invalid)?;
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if MIGRATOR.run(&pool).await.is_err() {
            pool.close().await;
            return Err(AutomationError::Unavailable);
        }
        protect_database_file(&path)?;
        sqlx::query(
            "INSERT INTO automation_meta (singleton, schema_version, owner_agent_id)
             VALUES (1, ?, ?) ON CONFLICT(singleton) DO NOTHING",
        )
        .bind(i64::from(AUTOMATION_SCHEMA_VERSION))
        .bind(owner_agent_id.as_str())
        .execute(&pool)
        .await
        .map_err(unavailable)?;
        verify_store(&pool, &owner_agent_id).await?;
        Ok(Self {
            pool,
            owner_agent_id,
            path,
        })
    }

    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub(crate) fn taskflow_pool(&self) -> &SqlitePool {
        &self.pool
    }

    pub(crate) fn taskflow_owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn create_task(
        &self,
        draft: &AutomationTaskDraft,
    ) -> Result<AutomationTask, AutomationError> {
        draft.validate()?;
        let (schedule_kind, interval_ms) = schedule_columns(draft.schedule)?;
        let (missed_run_policy, missed_run_limit) = draft.policy.missed_run.columns();
        let result = sqlx::query(
            "INSERT INTO automation_tasks (
                task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                schedule_revision, overlap_policy, missed_run_policy, missed_run_limit,
                state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'enabled', ?, 1, ?, ?)",
        )
        .bind(draft.task_id.to_string())
        .bind(self.owner_agent_id.as_str())
        .bind(&draft.thread_id)
        .bind(&draft.prompt)
        .bind(schedule_kind)
        .bind(interval_ms.map(to_i64).transpose()?)
        .bind(draft.policy.overlap.as_str())
        .bind(missed_run_policy)
        .bind(missed_run_limit.map(i64::from))
        .bind(to_i64(draft.first_run_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&self.pool)
        .await;
        match result {
            Ok(_) => self
                .task(draft.task_id)
                .await?
                .ok_or(AutomationError::Corrupt),
            Err(error) if is_constraint(&error) => Err(AutomationError::Conflict),
            Err(error) => Err(unavailable(error)),
        }
    }

    pub async fn task(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<Option<AutomationTask>, AutomationError> {
        sqlx::query(TASK_SELECT_BY_ID)
            .bind(task_id.to_string())
            .fetch_optional(&self.pool)
            .await
            .map_err(unavailable)?
            .map(|row| task_from_row(&row, &self.owner_agent_id))
            .transpose()
    }

    pub async fn list_tasks(&self, limit: usize) -> Result<Vec<AutomationTask>, AutomationError> {
        if !(1..=MAX_TASK_PAGE).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                    schedule_revision, overlap_policy, missed_run_policy, missed_run_limit,
                    state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
             FROM automation_tasks ORDER BY created_at_ms, task_id LIMIT ?",
        )
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter()
            .map(|row| task_from_row(row, &self.owner_agent_id))
            .collect()
    }

    /// Returns provider admissions whose terminal outcome is not known.
    ///
    /// An uncertain occurrence is deliberately not eligible for automatic
    /// retry.  A provider-specific reconciler may call
    /// [`Self::reconcile_dispatch`] after it obtains a receipt, or an operator
    /// may call [`Self::release_uncertain_for_retry`] after independently
    /// proving that no admission was accepted.
    pub async fn uncertain_dispatches(
        &self,
        limit: usize,
    ) -> Result<Vec<AutomationDispatchUncertainty>, AutomationError> {
        if !(1..=MAX_TASK_PAGE).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT o.task_id, o.occurrence, r.scheduled_for_ms,
                    o.client_user_message_id, o.observed_at_ms
             FROM automation_dispatch_outcomes o
             JOIN automation_runs r
               ON r.task_id = o.task_id AND r.occurrence = o.occurrence
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE t.owner_agent_id = ? AND o.outcome = 'uncertain'
             ORDER BY o.observed_at_ms, o.task_id, o.occurrence LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter()
            .map(|row| {
                Ok(AutomationDispatchUncertainty {
                    task_id: parse_task_id(row, "task_id")?,
                    occurrence: to_u64(row.try_get("occurrence").map_err(unavailable)?)?,
                    scheduled_for_ms: to_u64(
                        row.try_get("scheduled_for_ms").map_err(unavailable)?,
                    )?,
                    client_user_message_id: row
                        .try_get("client_user_message_id")
                        .map_err(unavailable)?,
                    observed_at_ms: to_u64(row.try_get("observed_at_ms").map_err(unavailable)?)?,
                })
            })
            .collect()
    }

    pub async fn cancel_task(
        &self,
        task_id: AutomationTaskId,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let changed = sqlx::query(
            "UPDATE automation_tasks
             SET state = 'cancelled', next_run_at_ms = NULL, updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ? AND state IN ('enabled', 'disabled')",
        )
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.owner_agent_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "UPDATE automation_runs
             SET state = 'cancelled', lease_generation = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL
             WHERE task_id = ? AND state = 'pending'",
        )
        .bind(task_id.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    pub async fn set_enabled(
        &self,
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let changed = if enabled {
            let resume_at_ms = resume_at_ms.ok_or(AutomationError::Invalid)?;
            sqlx::query(
                "UPDATE automation_tasks
                 SET state = 'enabled', next_run_at_ms = ?, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ? AND state = 'disabled'
                   AND NOT EXISTS (
                       SELECT 1 FROM automation_runs r
                       WHERE r.task_id = automation_tasks.task_id AND r.state = 'leased'
                   )",
            )
            .bind(to_i64(resume_at_ms)?)
            .bind(to_i64(now_ms)?)
            .bind(task_id.to_string())
            .bind(self.owner_agent_id.as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?
        } else {
            if resume_at_ms.is_some() {
                return Err(AutomationError::Invalid);
            }
            let changed = sqlx::query(
                "UPDATE automation_tasks
                 SET state = 'disabled', next_run_at_ms = NULL, updated_at_ms = ?
                 WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
            )
            .bind(to_i64(now_ms)?)
            .bind(task_id.to_string())
            .bind(self.owner_agent_id.as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if changed.rows_affected() == 1 {
                sqlx::query(
                    "UPDATE automation_runs
                     SET state = 'cancelled', lease_generation = NULL, lease_token = NULL,
                         lease_expires_at_ms = NULL
                     WHERE task_id = ? AND state = 'pending'",
                )
                .bind(task_id.to_string())
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
            }
            changed
        };
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        transaction.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    /// Replaces the future schedule contract while preserving historical
    /// occurrences. Every accepted edit increments the immutable schedule
    /// revision used by deterministic occurrence identity.
    pub async fn revise_task_schedule(
        &self,
        task_id: AutomationTaskId,
        schedule: AutomationSchedule,
        policy: AutomationSchedulePolicy,
        first_run_at_ms: u64,
        now_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        schedule.validate()?;
        policy.validate()?;
        if schedule == AutomationSchedule::Once && policy.overlap == AutomationOverlapPolicy::Allow
        {
            return Err(AutomationError::Invalid);
        }
        let (schedule_kind, interval_ms) = schedule_columns(schedule)?;
        let (missed_run_policy, missed_run_limit) = policy.missed_run.columns();
        let updated = sqlx::query(
            "UPDATE automation_tasks
             SET schedule_kind = ?, interval_ms = ?,
                 schedule_revision = schedule_revision + 1,
                 overlap_policy = ?, missed_run_policy = ?, missed_run_limit = ?,
                 next_run_at_ms = CASE WHEN state = 'enabled' THEN ? ELSE NULL END,
                 updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ?
               AND state IN ('enabled', 'disabled')
               AND schedule_revision < 9223372036854775807",
        )
        .bind(schedule_kind)
        .bind(interval_ms.map(to_i64).transpose()?)
        .bind(policy.overlap.as_str())
        .bind(missed_run_policy)
        .bind(missed_run_limit.map(i64::from))
        .bind(to_i64(first_run_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.owner_agent_id.as_str())
        .execute(&self.pool)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    /// Returns admitted occurrences that still require a persisted provider
    /// turn/terminal observation. This is the restart-safe worklist for the
    /// Agentd reconciler; queue admission is intentionally non-terminal.
    pub async fn submitted_occurrences(
        &self,
        limit: usize,
    ) -> Result<Vec<AutomationSubmittedOccurrence>, AutomationError> {
        if !(1..=MAX_TASK_PAGE).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT r.task_id, r.occurrence, r.occurrence_id, r.schedule_revision,
                    r.taskflow_step_attempt, r.scheduled_for_ms, r.client_user_message_id,
                    r.queued_submission_id, r.taskflow_run_id, r.taskflow_step_attempt,
                    r.provider_turn_id, r.submitted_at_ms, t.thread_id, t.prompt
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE t.owner_agent_id = ? AND r.state = 'submitted'
               AND r.terminal_state IS NULL
             ORDER BY r.submitted_at_ms, r.task_id, r.occurrence
             LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter()
            .map(|row| {
                let task_id = parse_task_id(row, "task_id")?;
                let occurrence = to_u64(row.try_get("occurrence").map_err(unavailable)?)?;
                let schedule_revision =
                    to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?;
                let taskflow_step_attempt = u32::try_from(to_u64(
                    row.try_get("taskflow_step_attempt").map_err(unavailable)?,
                )?)
                .map_err(|_| AutomationError::Corrupt)?;
                let scheduled_for_ms =
                    to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
                let raw_occurrence_id: String =
                    row.try_get("occurrence_id").map_err(unavailable)?;
                let occurrence_id = if raw_occurrence_id.is_empty() {
                    AutomationOccurrenceId::derive(task_id, schedule_revision, scheduled_for_ms)?
                } else {
                    AutomationOccurrenceId::parse(&raw_occurrence_id)
                        .map_err(|_| AutomationError::Corrupt)?
                };
                let queued_submission_id: Option<String> =
                    row.try_get("queued_submission_id").map_err(unavailable)?;
                let submitted_at_ms: Option<i64> =
                    row.try_get("submitted_at_ms").map_err(unavailable)?;
                Ok(AutomationSubmittedOccurrence {
                    admission: crate::AutomationAdmission {
                        agent_id: self.owner_agent_id.clone(),
                        task_id,
                        occurrence,
                        occurrence_id,
                        schedule_revision,
                        scheduled_for_ms,
                        thread_id: row.try_get("thread_id").map_err(unavailable)?,
                        prompt: row.try_get("prompt").map_err(unavailable)?,
                        client_user_message_id: row
                            .try_get("client_user_message_id")
                            .map_err(unavailable)?,
                    },
                    queued_submission_id: queued_submission_id.ok_or(AutomationError::Corrupt)?,
                    taskflow_run_id: row
                        .try_get::<Option<String>, _>("taskflow_run_id")
                        .map_err(unavailable)?
                        .ok_or(AutomationError::Corrupt)?,
                    taskflow_step_attempt: u32::try_from(
                        to_u64(
                            row.try_get("taskflow_step_attempt")
                                .map_err(unavailable)?,
                        )?,
                    )
                    .map_err(|_| AutomationError::Corrupt)?,
                    provider_turn_id: row.try_get("provider_turn_id").map_err(unavailable)?,
                    submitted_at_ms: submitted_at_ms
                        .map(to_u64)
                        .transpose()?
                        .ok_or(AutomationError::Corrupt)?,
                })
            })
            .collect()
    }

    /// Persists the durable provider turn identity once queue reconciliation
    /// proves that the exact client message was materialized as a turn.
    pub async fn record_provider_turn(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        turn_id: &str,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        if turn_id.is_empty() || turn_id.len() > 256 || turn_id.contains('\0') {
            return Err(AutomationError::Invalid);
        }
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT r.provider_turn_id, r.queued_submission_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?
               AND r.state = 'submitted' AND r.terminal_state IS NULL",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.owner_agent_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let existing: Option<String> = row.try_get("provider_turn_id").map_err(unavailable)?;
        if let Some(existing) = existing {
            if existing != turn_id {
                return Err(AutomationError::Conflict);
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(());
        }
        let queued_submission_id: Option<String> =
            row.try_get("queued_submission_id").map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE automation_runs SET provider_turn_id = ?
             WHERE task_id = ? AND occurrence = ?
               AND provider_turn_id IS NULL AND terminal_state IS NULL",
        )
        .bind(turn_id)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        let digest = provider_observation_digest(
            AutomationProviderObservationKind::TurnPersisted,
            task_id,
            occurrence,
            queued_submission_id.as_deref(),
            Some(turn_id),
        );
        append_provider_observation(
            &mut tx,
            task_id,
            occurrence,
            AutomationProviderObservationKind::TurnPersisted,
            queued_submission_id.as_deref(),
            Some(turn_id),
            &digest,
            observed_at_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)
    }

    /// Appends non-terminal reconciliation evidence without changing scheduler
    /// eligibility. Exact replay of the latest observation is idempotent.
    pub async fn record_provider_reconciliation_observation(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        kind: AutomationProviderObservationKind,
        receipt_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        if !matches!(
            kind,
            AutomationProviderObservationKind::Indeterminate
                | AutomationProviderObservationKind::ReconciledMissing
        ) {
            return Err(AutomationError::Invalid);
        }
        validate_sha256(receipt_digest)?;
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT r.queued_submission_id, r.provider_turn_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?
               AND r.state = 'submitted' AND r.terminal_state IS NULL",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.owner_agent_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let queued_submission_id: Option<String> =
            row.try_get("queued_submission_id").map_err(unavailable)?;
        let provider_turn_id: Option<String> =
            row.try_get("provider_turn_id").map_err(unavailable)?;
        let last = sqlx::query(
            "SELECT observation_kind, receipt_digest
             FROM automation_provider_observations
             WHERE task_id = ? AND occurrence = ?
             ORDER BY observation_seq DESC LIMIT 1",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if let Some(last) = last {
            let last_kind: String = last.try_get("observation_kind").map_err(unavailable)?;
            let last_digest: String = last.try_get("receipt_digest").map_err(unavailable)?;
            if last_kind == kind.as_str() && last_digest == receipt_digest.as_str() {
                tx.commit().await.map_err(unavailable)?;
                return Ok(());
            }
        }
        append_provider_observation(
            &mut tx,
            task_id,
            occurrence,
            kind,
            queued_submission_id.as_deref(),
            provider_turn_id.as_deref(),
            receipt_digest,
            observed_at_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)
    }

    /// Records a trusted terminal provider observation and only then advances
    /// a non-overlapping recurring schedule. Replays of the exact terminal
    /// state are idempotent; conflicting terminal evidence fails closed.
    pub async fn terminalize_occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        terminal: AutomationOccurrenceTerminal,
        receipt_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        validate_sha256(receipt_digest)?;
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT r.schedule_revision, r.scheduled_for_ms, r.terminal_state,
                    r.queued_submission_id, r.provider_turn_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?
               AND r.state = 'submitted'",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.owner_agent_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let schedule_revision =
            to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?;
        let scheduled_for_ms =
            to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
        let existing_terminal: Option<String> =
            row.try_get("terminal_state").map_err(unavailable)?;
        if let Some(existing_terminal) = existing_terminal {
            if AutomationOccurrenceTerminal::parse(&existing_terminal)? != terminal {
                return Err(AutomationError::Conflict);
            }
            let current_row = sqlx::query(TASK_SELECT_BY_ID)
                .bind(task_id.to_string())
                .fetch_one(&mut *tx)
                .await
                .map_err(unavailable)?;
            let current = task_from_row(&current_row, &self.owner_agent_id)?;
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        let queued_submission_id: Option<String> =
            row.try_get("queued_submission_id").map_err(unavailable)?;
        let provider_turn_id: Option<String> =
            row.try_get("provider_turn_id").map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE automation_runs
             SET terminal_state = ?, terminal_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND terminal_state IS NULL",
        )
        .bind(terminal.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        let kind = match terminal {
            AutomationOccurrenceTerminal::Succeeded => {
                AutomationProviderObservationKind::TurnCompleted
            }
            AutomationOccurrenceTerminal::Failed => AutomationProviderObservationKind::TurnFailed,
            AutomationOccurrenceTerminal::Cancelled => {
                AutomationProviderObservationKind::TurnInterrupted
            }
        };
        append_provider_observation(
            &mut tx,
            task_id,
            occurrence,
            kind,
            queued_submission_id.as_deref(),
            provider_turn_id.as_deref(),
            receipt_digest,
            observed_at_ms,
        )
        .await?;

        let current_row = sqlx::query(TASK_SELECT_BY_ID)
            .bind(task_id.to_string())
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        let current = task_from_row(&current_row, &self.owner_agent_id)?;
        if current.schedule_revision == schedule_revision
            && current.policy.overlap == AutomationOverlapPolicy::Forbid
        {
            advance_task_after_occurrence(
                &mut tx,
                &self.owner_agent_id,
                &current,
                schedule_revision,
                scheduled_for_ms,
                observed_at_ms,
            )
            .await?;
        }
        tx.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    /// Releases work held by an older process generation. The caller must own
    /// the per-Agent writer lock before invoking this immediate recovery path.
    pub async fn recover_stale_generation(
        &self,
        current_generation: u64,
    ) -> Result<u64, AutomationError> {
        if current_generation == 0 {
            return Err(AutomationError::Invalid);
        }
        let recovered = sqlx::query(
            "UPDATE automation_runs
             SET state = CASE WHEN EXISTS (
                     SELECT 1 FROM automation_tasks t
                     WHERE t.task_id = automation_runs.task_id AND t.state = 'enabled'
                 ) THEN 'pending' ELSE 'cancelled' END,
                 lease_generation = NULL, lease_token = NULL, lease_expires_at_ms = NULL
             WHERE state = 'leased' AND lease_generation != ?
               AND EXISTS (
                   SELECT 1 FROM automation_tasks t
                   WHERE t.task_id = automation_runs.task_id
                     AND t.owner_agent_id = ?
               )
               AND NOT EXISTS (
                   SELECT 1 FROM automation_dispatch_outcomes o
                   WHERE o.task_id = automation_runs.task_id
                     AND o.occurrence = automation_runs.occurrence
                     AND o.outcome = 'uncertain'
               )",
        )
        .bind(to_i64(current_generation)?)
        .bind(self.owner_agent_id.as_str())
        .execute(&self.pool)
        .await
        .map_err(unavailable)?;
        Ok(recovered.rows_affected())
    }

    pub async fn claim_due(
        &self,
        now_ms: u64,
        generation: u64,
        lease_duration_ms: u64,
    ) -> Result<Option<AutomationLease>, AutomationError> {
        if generation == 0 || lease_duration_ms == 0 {
            return Err(AutomationError::Invalid);
        }
        let lease_expires_at_ms = now_ms
            .checked_add(lease_duration_ms)
            .ok_or(AutomationError::Invalid)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;

        let reclaim = sqlx::query(
            "SELECT r.task_id, r.occurrence, r.occurrence_id, r.schedule_revision,
                    r.scheduled_for_ms, r.client_user_message_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE t.owner_agent_id = ? AND t.state = 'enabled'
               AND r.terminal_state IS NULL
               AND (r.state = 'pending'
                    OR (r.state = 'leased' AND r.lease_expires_at_ms <= ?))
               AND NOT EXISTS (
                   SELECT 1 FROM automation_dispatch_outcomes o
                   WHERE o.task_id = r.task_id AND o.occurrence = r.occurrence
                     AND o.outcome = 'uncertain'
               )
             ORDER BY r.scheduled_for_ms, r.task_id, r.occurrence LIMIT 1",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(to_i64(now_ms)?)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;

        let (
            task_id,
            occurrence,
            occurrence_id,
            schedule_revision,
            taskflow_step_attempt,
            scheduled_for_ms,
            client_id,
        ) = if let Some(row) = reclaim {
                let task_id = AutomationTaskId::parse(
                    &row.try_get::<String, _>("task_id").map_err(unavailable)?,
                )
                .map_err(|_| AutomationError::Corrupt)?;
                let occurrence = to_u64(row.try_get("occurrence").map_err(unavailable)?)?;
                let schedule_revision =
                    to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?;
                let scheduled_for_ms =
                    to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
                let raw_occurrence_id: String =
                    row.try_get("occurrence_id").map_err(unavailable)?;
                let occurrence_id = if raw_occurrence_id.is_empty() {
                    let derived = AutomationOccurrenceId::derive(
                        task_id,
                        schedule_revision,
                        scheduled_for_ms,
                    )?;
                    let backfilled = sqlx::query(
                        "UPDATE automation_runs SET occurrence_id = ?
                         WHERE task_id = ? AND occurrence = ? AND occurrence_id = ''",
                    )
                    .bind(derived.as_str())
                    .bind(task_id.to_string())
                    .bind(to_i64(occurrence)?)
                    .execute(&mut *transaction)
                    .await
                    .map_err(unavailable)?;
                    if backfilled.rows_affected() != 1 {
                        return Err(AutomationError::Conflict);
                    }
                    derived
                } else {
                    AutomationOccurrenceId::parse(&raw_occurrence_id)
                        .map_err(|_| AutomationError::Corrupt)?
                };
                (
                    task_id,
                    occurrence,
                    occurrence_id,
                    schedule_revision,
                    taskflow_step_attempt,
                    scheduled_for_ms,
                    row.try_get("client_user_message_id").map_err(unavailable)?,
                )
            } else {
                let row = sqlx::query(
                    "SELECT t.task_id, t.next_occurrence, t.next_run_at_ms,
                            t.schedule_revision, t.overlap_policy
                     FROM automation_tasks t
                     WHERE t.owner_agent_id = ? AND t.state = 'enabled'
                       AND t.next_run_at_ms IS NOT NULL AND t.next_run_at_ms <= ?
                       AND (
                           t.overlap_policy = 'allow'
                           OR NOT EXISTS (
                               SELECT 1 FROM automation_runs r
                               WHERE r.task_id = t.task_id
                                 AND r.state IN ('pending', 'leased', 'submitted')
                                 AND r.terminal_state IS NULL
                           )
                       )
                     ORDER BY t.next_run_at_ms, t.task_id LIMIT 1",
                )
                .bind(self.owner_agent_id.as_str())
                .bind(to_i64(now_ms)?)
                .fetch_optional(&mut *transaction)
                .await
                .map_err(unavailable)?;
                let Some(row) = row else {
                    transaction.commit().await.map_err(unavailable)?;
                    return Ok(None);
                };
                let task_id = AutomationTaskId::parse(
                    &row.try_get::<String, _>("task_id").map_err(unavailable)?,
                )
                .map_err(|_| AutomationError::Corrupt)?;
                let occurrence = to_u64(row.try_get("next_occurrence").map_err(unavailable)?)?;
                let schedule_revision =
                    to_u64(row.try_get("schedule_revision").map_err(unavailable)?)?;
                let scheduled_for_ms =
                    to_u64(row.try_get("next_run_at_ms").map_err(unavailable)?)?;
                let occurrence_id =
                    AutomationOccurrenceId::derive(task_id, schedule_revision, scheduled_for_ms)?;
                let client_id = client_message_id(&occurrence_id);
                sqlx::query(
                    "INSERT INTO automation_runs (
                        task_id, occurrence, occurrence_id, schedule_revision,
                        scheduled_for_ms, client_user_message_id, state
                     ) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                )
                .bind(task_id.to_string())
                .bind(to_i64(occurrence)?)
                .bind(occurrence_id.as_str())
                .bind(to_i64(schedule_revision)?)
                .bind(to_i64(scheduled_for_ms)?)
                .bind(&client_id)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                let advanced = sqlx::query(
                    "UPDATE automation_tasks SET next_occurrence = next_occurrence + 1
                     WHERE task_id = ? AND next_occurrence = ? AND schedule_revision = ?",
                )
                .bind(task_id.to_string())
                .bind(to_i64(occurrence)?)
                .bind(to_i64(schedule_revision)?)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if advanced.rows_affected() != 1 {
                    return Err(AutomationError::Conflict);
                }

                let task_row = sqlx::query(TASK_SELECT_BY_ID)
                    .bind(task_id.to_string())
                    .fetch_one(&mut *transaction)
                    .await
                    .map_err(unavailable)?;
                let materialized_task = task_from_row(&task_row, &self.owner_agent_id)?;
                if materialized_task.policy.overlap == AutomationOverlapPolicy::Allow {
                    advance_task_after_occurrence(
                        &mut transaction,
                        &self.owner_agent_id,
                        &materialized_task,
                        schedule_revision,
                        scheduled_for_ms,
                        now_ms,
                    )
                    .await?;
                }
                (
                    task_id,
                    occurrence,
                    occurrence_id,
                    schedule_revision,
                    1,
                    scheduled_for_ms,
                    client_id,
                )
            };

        let lease_token = uuid::Uuid::now_v7().to_string();
        let leased = sqlx::query(
            "UPDATE automation_runs
             SET state = 'leased', lease_generation = ?, lease_token = ?, lease_expires_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND terminal_state IS NULL
               AND (state = 'pending' OR (state = 'leased' AND lease_expires_at_ms <= ?))",
        )
        .bind(to_i64(generation)?)
        .bind(&lease_token)
        .bind(to_i64(lease_expires_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if leased.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        let task_row = sqlx::query(TASK_SELECT_BY_ID)
            .bind(task_id.to_string())
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        let task = task_from_row(&task_row, &self.owner_agent_id)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(Some(AutomationLease {
            task,
            occurrence,
            occurrence_id,
            schedule_revision,
            taskflow_step_attempt,
            scheduled_for_ms,
            client_user_message_id: client_id,
            lease_generation: generation,
            lease_token,
            lease_expires_at_ms,
        }))
    }

    /// Records a dispatch intent before (or immediately after) crossing the
    /// provider seam when the terminal outcome cannot be determined.
    ///
    /// The occurrence remains leased and is excluded from both stale-generation
    /// recovery and automatic retry.  This is the durable boundary that keeps
    /// a lost provider response from becoming an unbounded duplicate stream.
    pub async fn record_dispatch_uncertain(
        &self,
        lease: &AutomationLease,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        if lease.task.owner_agent_id != self.owner_agent_id {
            return Err(AutomationError::AccessDenied);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE automation_runs
             SET state = 'leased'
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND lease_generation = ? AND lease_token = ?
               AND client_user_message_id = ?",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        let existing = sqlx::query(
            "SELECT outcome FROM automation_dispatch_outcomes
             WHERE task_id = ? AND occurrence = ?",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        match existing {
            Some(row) => {
                let outcome: String = row.try_get("outcome").map_err(unavailable)?;
                if outcome != "uncertain" {
                    return Err(AutomationError::Conflict);
                }
                sqlx::query(
                    "UPDATE automation_dispatch_outcomes SET observed_at_ms = ?
                     WHERE task_id = ? AND occurrence = ? AND outcome = 'uncertain'",
                )
                .bind(to_i64(observed_at_ms)?)
                .bind(lease.task.task_id.to_string())
                .bind(to_i64(lease.occurrence)?)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
            }
            None => {
                sqlx::query(
                    "INSERT INTO automation_dispatch_outcomes (
                         task_id, occurrence, client_user_message_id, outcome, observed_at_ms
                     ) VALUES (?, ?, ?, 'uncertain', ?)",
                )
                .bind(lease.task.task_id.to_string())
                .bind(to_i64(lease.occurrence)?)
                .bind(&lease.client_user_message_id)
                .bind(to_i64(observed_at_ms)?)
                .execute(&mut *transaction)
                .await
                .map_err(|error| {
                    if is_constraint(&error) {
                        AutomationError::Conflict
                    } else {
                        unavailable(error)
                    }
                })?;
            }
        }
        transaction.commit().await.map_err(unavailable)
    }

    /// Aborts an intent only when the queue implementation has proved that the
    /// request failed before the external admission seam.  The uncertainty
    /// row and lease are removed in one transaction so a retry cannot race a
    /// crash between the two local updates.
    pub async fn abort_dispatch_before_admission(
        &self,
        lease: &AutomationLease,
    ) -> Result<(), AutomationError> {
        if lease.task.owner_agent_id != self.owner_agent_id {
            return Err(AutomationError::AccessDenied);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let removed = sqlx::query(
            "DELETE FROM automation_dispatch_outcomes
             WHERE task_id = ? AND occurrence = ?
               AND client_user_message_id = ? AND outcome = 'uncertain'",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                AutomationError::Conflict
            } else {
                unavailable(error)
            }
        })?;
        if removed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        let released = sqlx::query(
            "UPDATE automation_runs
             SET state = CASE WHEN EXISTS (
                     SELECT 1 FROM automation_tasks t
                     WHERE t.task_id = automation_runs.task_id AND t.state = 'enabled'
                 ) THEN 'pending' ELSE 'cancelled' END,
                 lease_generation = NULL, lease_token = NULL, lease_expires_at_ms = NULL
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND lease_generation = ? AND lease_token = ?
               AND client_user_message_id = ?",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if released.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        transaction.commit().await.map_err(unavailable)
    }

    /// Reconciles an uncertain occurrence after an external/provider-specific
    /// lookup returns a durable queue receipt.  This method only proves local
    /// terminalization and client-id fencing; it makes no physical provider
    /// exactly-once claim.
    pub async fn reconcile_dispatch(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        receipt: &AutomationQueueReceipt,
        submitted_at_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        if receipt.queued_submission_id.is_empty() {
            return Err(AutomationError::Invalid);
        }
        to_i64(submitted_at_ms)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT r.scheduled_for_ms, r.state, o.client_user_message_id,
                    o.outcome, r.client_user_message_id AS run_client_id,
                    r.queued_submission_id AS run_submission_id,
                    o.queued_submission_id AS outcome_submission_id
             FROM automation_runs r
             JOIN automation_dispatch_outcomes o
               ON o.task_id = r.task_id AND o.occurrence = r.occurrence
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.owner_agent_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let scheduled_for_ms = to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
        let state: String = row.try_get("state").map_err(unavailable)?;
        let outcome: String = row.try_get("outcome").map_err(unavailable)?;
        let client_id: String = row.try_get("client_user_message_id").map_err(unavailable)?;
        let run_client_id: String = row.try_get("run_client_id").map_err(unavailable)?;
        if client_id != receipt.client_user_message_id || run_client_id != client_id {
            return Err(AutomationError::Conflict);
        }
        if state == "submitted" && outcome == "submitted" {
            let run_submission: Option<String> =
                row.try_get("run_submission_id").map_err(unavailable)?;
            let outcome_submission: Option<String> =
                row.try_get("outcome_submission_id").map_err(unavailable)?;
            if run_submission.as_deref() != Some(receipt.queued_submission_id.as_str())
                || outcome_submission != run_submission
            {
                return Err(AutomationError::Conflict);
            }
            // The transaction may have committed before its acknowledgement was
            // lost. Re-observing that receipt must not advance the schedule or
            // overwrite a subsequent disable/cancel decision.
            let current_row = sqlx::query(TASK_SELECT_BY_ID)
                .bind(task_id.to_string())
                .fetch_one(&mut *transaction)
                .await
                .map_err(unavailable)?;
            let current = task_from_row(&current_row, &self.owner_agent_id)?;
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if state != "leased" || outcome != "uncertain" {
            return Err(AutomationError::Conflict);
        }

        let updated = sqlx::query(
            "UPDATE automation_runs
             SET state = 'submitted', lease_generation = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL, queued_submission_id = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(submitted_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                AutomationError::Conflict
            } else {
                unavailable(error)
            }
        })?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "UPDATE automation_dispatch_outcomes
             SET outcome = 'submitted', queued_submission_id = ?,
                 observed_at_ms = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND outcome = 'uncertain'",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(submitted_at_ms)?)
        .bind(to_i64(submitted_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;

        let digest = provider_observation_digest(
            AutomationProviderObservationKind::QueueAdmitted,
            task_id,
            occurrence,
            Some(&receipt.queued_submission_id),
            None,
        );
        append_provider_observation(
            &mut transaction,
            task_id,
            occurrence,
            AutomationProviderObservationKind::QueueAdmitted,
            Some(&receipt.queued_submission_id),
            None,
            &digest,
            submitted_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        self.task(task_id).await?.ok_or(AutomationError::Corrupt)
    }

    /// Releases an uncertain occurrence only after an external check proves
    /// that the provider did not accept it.  The same client id is retained
    /// when the occurrence is claimed again.
    pub async fn release_uncertain_for_retry(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
    ) -> Result<(), AutomationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE automation_runs
             SET state = CASE WHEN EXISTS (
                     SELECT 1 FROM automation_tasks t
                     WHERE t.task_id = automation_runs.task_id AND t.state = 'enabled'
                 ) THEN 'pending' ELSE 'cancelled' END,
                 lease_generation = NULL, lease_token = NULL, lease_expires_at_ms = NULL
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND client_user_message_id = ?
               AND EXISTS (
                   SELECT 1 FROM automation_dispatch_outcomes o
                   WHERE o.task_id = automation_runs.task_id
                     AND o.occurrence = automation_runs.occurrence
                     AND o.outcome = 'uncertain'
               )
               AND EXISTS (
                   SELECT 1 FROM automation_tasks t
                   WHERE t.task_id = automation_runs.task_id
                     AND t.owner_agent_id = ?
               )",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(client_user_message_id)
        .bind(self.owner_agent_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "DELETE FROM automation_dispatch_outcomes
             WHERE task_id = ? AND occurrence = ? AND outcome = 'uncertain'",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn mark_submitted(
        &self,
        lease: &AutomationLease,
        receipt: &AutomationQueueReceipt,
        submitted_at_ms: u64,
    ) -> Result<AutomationTask, AutomationError> {
        if lease.task.owner_agent_id != self.owner_agent_id
            || receipt.client_user_message_id != lease.client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            return Err(AutomationError::AccessDenied);
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let run = sqlx::query(
            "UPDATE automation_runs
             SET state = 'submitted', lease_generation = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL, queued_submission_id = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND lease_generation = ? AND lease_token = ?
               AND client_user_message_id = ?",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(submitted_at_ms)?)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if run.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        let uncertainty = sqlx::query(
            "UPDATE automation_dispatch_outcomes
             SET outcome = 'submitted', queued_submission_id = ?,
                 observed_at_ms = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND client_user_message_id = ? AND outcome = 'uncertain'",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(submitted_at_ms)?)
        .bind(to_i64(submitted_at_ms)?)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                AutomationError::Conflict
            } else {
                unavailable(error)
            }
        })?;
        if uncertainty.rows_affected() == 0 {
            sqlx::query(
                "INSERT INTO automation_dispatch_outcomes (
                     task_id, occurrence, client_user_message_id, queued_submission_id,
                     outcome, observed_at_ms, submitted_at_ms
                 ) VALUES (?, ?, ?, ?, 'submitted', ?, ?)",
            )
            .bind(lease.task.task_id.to_string())
            .bind(to_i64(lease.occurrence)?)
            .bind(&lease.client_user_message_id)
            .bind(&receipt.queued_submission_id)
            .bind(to_i64(submitted_at_ms)?)
            .bind(to_i64(submitted_at_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(|error| {
                if is_constraint(&error) {
                    AutomationError::Conflict
                } else {
                    unavailable(error)
                }
            })?;
        }

        // Queue admission is durable evidence, but it is not occurrence
        // completion. The scheduler remains blocked by the active submitted
        // occurrence under the default overlap policy until a trusted
        // terminal provider observation is recorded.
        let digest = provider_observation_digest(
            AutomationProviderObservationKind::QueueAdmitted,
            lease.task.task_id,
            lease.occurrence,
            Some(&receipt.queued_submission_id),
            None,
        );
        append_provider_observation(
            &mut transaction,
            lease.task.task_id,
            lease.occurrence,
            AutomationProviderObservationKind::QueueAdmitted,
            Some(&receipt.queued_submission_id),
            None,
            &digest,
            submitted_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        self.task(lease.task.task_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    pub async fn release_for_retry(&self, lease: &AutomationLease) -> Result<(), AutomationError> {
        if lease.task.owner_agent_id != self.owner_agent_id {
            return Err(AutomationError::AccessDenied);
        }
        let updated = sqlx::query(
            "UPDATE automation_runs
             SET state = CASE WHEN EXISTS (
                     SELECT 1 FROM automation_tasks t
                     WHERE t.task_id = automation_runs.task_id AND t.state = 'enabled'
                 ) THEN 'pending' ELSE 'cancelled' END,
                 lease_generation = NULL, lease_token = NULL, lease_expires_at_ms = NULL
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND lease_generation = ? AND lease_token = ?
               AND client_user_message_id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM automation_dispatch_outcomes o
                   WHERE o.task_id = automation_runs.task_id
                     AND o.occurrence = automation_runs.occurrence
               )",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .execute(&self.pool)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        Ok(())
    }
}

async fn advance_task_after_occurrence(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    owner_agent_id: &AgentId,
    current: &AutomationTask,
    expected_schedule_revision: u64,
    scheduled_for_ms: u64,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    if current.schedule_revision != expected_schedule_revision {
        return Err(AutomationError::Conflict);
    }
    let (next_state, next_run) = match current.state {
        AutomationTaskState::Enabled => {
            let next_run = next_run_after_observation(
                current.schedule,
                current.policy.missed_run,
                scheduled_for_ms,
                observed_at_ms,
            )?;
            let next_state = if next_run.is_some() {
                AutomationTaskState::Enabled
            } else {
                AutomationTaskState::Completed
            };
            (next_state, next_run)
        }
        AutomationTaskState::Disabled
        | AutomationTaskState::Cancelled
        | AutomationTaskState::Completed => return Ok(()),
    };
    let updated = sqlx::query(
        "UPDATE automation_tasks
         SET state = ?, next_run_at_ms = ?, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ? AND schedule_revision = ?",
    )
    .bind(next_state.as_str())
    .bind(next_run.map(to_i64).transpose()?)
    .bind(to_i64(observed_at_ms)?)
    .bind(current.task_id.to_string())
    .bind(owner_agent_id.as_str())
    .bind(to_i64(expected_schedule_revision)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if updated.rows_affected() != 1 {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}

fn next_run_after_observation(
    schedule: AutomationSchedule,
    policy: AutomationMissedRunPolicy,
    scheduled_for_ms: u64,
    observed_at_ms: u64,
) -> Result<Option<u64>, AutomationError> {
    let Some(base) = schedule.next_after(scheduled_for_ms)? else {
        return Ok(None);
    };
    if base > observed_at_ms {
        return Ok(Some(base));
    }
    let AutomationSchedule::FixedInterval { interval_ms } = schedule else {
        return Ok(None);
    };
    let elapsed = observed_at_ms
        .checked_sub(base)
        .ok_or(AutomationError::Invalid)?;
    let due_count = elapsed
        .checked_div(interval_ms)
        .and_then(|value| value.checked_add(1))
        .ok_or(AutomationError::Invalid)?;
    let skip_slots = match policy {
        AutomationMissedRunPolicy::Skip => due_count,
        AutomationMissedRunPolicy::Coalesce => due_count.saturating_sub(1),
        AutomationMissedRunPolicy::BoundedCatchUp { max_occurrences } => {
            due_count.saturating_sub(u64::from(max_occurrences))
        }
    };
    base.checked_add(
        interval_ms
            .checked_mul(skip_slots)
            .ok_or(AutomationError::Invalid)?,
    )
    .map(Some)
    .ok_or(AutomationError::Invalid)
}

async fn append_provider_observation(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    task_id: AutomationTaskId,
    occurrence: u64,
    kind: AutomationProviderObservationKind,
    queued_submission_id: Option<&str>,
    turn_id: Option<&str>,
    receipt_digest: &Sha256Digest,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    validate_sha256(receipt_digest)?;
    let previous_seq = sqlx::query_scalar::<_, Option<i64>>(
        "SELECT MAX(observation_seq)
         FROM automation_provider_observations
         WHERE task_id = ? AND occurrence = ?",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?
    .unwrap_or(0);
    let next_seq = to_u64(previous_seq)?
        .checked_add(1)
        .ok_or(AutomationError::Corrupt)?;
    sqlx::query(
        "INSERT INTO automation_provider_observations (
            task_id, occurrence, observation_seq, observation_kind,
            queued_submission_id, turn_id, receipt_digest, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .bind(to_i64(next_seq)?)
    .bind(kind.as_str())
    .bind(queued_submission_id)
    .bind(turn_id)
    .bind(receipt_digest.as_str())
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(|error| {
        if is_constraint(&error) {
            AutomationError::Conflict
        } else {
            unavailable(error)
        }
    })?;
    Ok(())
}

fn provider_observation_digest(
    kind: AutomationProviderObservationKind,
    task_id: AutomationTaskId,
    occurrence: u64,
    queued_submission_id: Option<&str>,
    turn_id: Option<&str>,
) -> Sha256Digest {
    let canonical = format!(
        "hepta.automation.provider-observation.v1\\0{}\\0{}\\0{}\\0{}\\0{}",
        kind.as_str(),
        task_id,
        occurrence,
        queued_submission_id.unwrap_or(""),
        turn_id.unwrap_or(""),
    );
    Sha256Digest::for_bytes(canonical.as_bytes())
}

fn validate_sha256(digest: &Sha256Digest) -> Result<(), AutomationError> {
    let value = digest.as_str();
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

const TASK_SELECT_BY_ID: &str =
    "SELECT task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
            schedule_revision, overlap_policy, missed_run_policy, missed_run_limit,
            state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
     FROM automation_tasks WHERE task_id = ?";

fn task_from_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &AgentId,
) -> Result<AutomationTask, AutomationError> {
    let owner = AgentId::parse(
        row.try_get::<String, _>("owner_agent_id")
            .map_err(unavailable)?,
    )
    .map_err(|_| AutomationError::Corrupt)?;
    if &owner != expected_owner {
        return Err(AutomationError::AccessDenied);
    }
    let task_id =
        AutomationTaskId::parse(&row.try_get::<String, _>("task_id").map_err(unavailable)?)
            .map_err(|_| AutomationError::Corrupt)?;
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
    Ok(AutomationTask {
        task_id,
        owner_agent_id: owner,
        thread_id: row.try_get("thread_id").map_err(unavailable)?,
        prompt: row.try_get("prompt").map_err(unavailable)?,
        schedule,
        schedule_revision: to_u64(
            row.try_get("schedule_revision").map_err(unavailable)?,
        )?,
        policy: AutomationSchedulePolicy {
            overlap: AutomationOverlapPolicy::parse(
                &row.try_get::<String, _>("overlap_policy").map_err(unavailable)?,
            )?,
            missed_run: AutomationMissedRunPolicy::parse(
                &row.try_get::<String, _>("missed_run_policy").map_err(unavailable)?,
                row.try_get("missed_run_limit").map_err(unavailable)?,
            )?,
        },
        state: AutomationTaskState::parse(
            &row.try_get::<String, _>("state").map_err(unavailable)?,
        )?,
        next_run_at_ms: row
            .try_get::<Option<i64>, _>("next_run_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        next_occurrence: to_u64(row.try_get("next_occurrence").map_err(unavailable)?)?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
    })
}

fn schedule_columns(
    schedule: AutomationSchedule,
) -> Result<(&'static str, Option<u64>), AutomationError> {
    schedule.validate()?;
    Ok(match schedule {
        AutomationSchedule::Once => ("once", None),
        AutomationSchedule::FixedInterval { interval_ms } => ("fixed_interval", Some(interval_ms)),
    })
}

async fn verify_store(pool: &SqlitePool, owner_agent_id: &AgentId) -> Result<(), AutomationError> {
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if quick_check != ["ok"] {
        return Err(AutomationError::Corrupt);
    }
    if !sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?
        .is_empty()
    {
        return Err(AutomationError::Corrupt);
    }
    let row = sqlx::query(
        "SELECT schema_version, owner_agent_id FROM automation_meta WHERE singleton = 1",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    let schema: i64 = row.try_get("schema_version").map_err(unavailable)?;
    let owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
    if schema != i64::from(AUTOMATION_SCHEMA_VERSION) {
        return Err(AutomationError::Corrupt);
    }
    if owner != owner_agent_id.as_str() {
        return Err(AutomationError::AccessDenied);
    }
    let foreign: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM automation_tasks WHERE owner_agent_id != ?")
            .bind(owner_agent_id.as_str())
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    if foreign != 0 {
        return Err(AutomationError::AccessDenied);
    }
    let invalid_outcomes: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM automation_dispatch_outcomes o
         LEFT JOIN automation_runs r
           ON r.task_id = o.task_id AND r.occurrence = o.occurrence
         JOIN automation_tasks t ON t.task_id = o.task_id
         WHERE t.owner_agent_id = ?
           AND (r.task_id IS NULL
                OR (o.outcome = 'uncertain' AND r.state != 'leased')
                OR (o.outcome = 'submitted' AND r.state != 'submitted')
                OR o.client_user_message_id != r.client_user_message_id
                OR (o.outcome = 'submitted' AND (
                    o.queued_submission_id IS NULL
                    OR o.queued_submission_id IS NOT r.queued_submission_id
                    OR o.submitted_at_ms IS NOT r.submitted_at_ms
                )))",
    )
    .bind(owner_agent_id.as_str())
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_outcomes != 0 {
        return Err(AutomationError::Corrupt);
    }
    verify_taskflow_store(pool, owner_agent_id)
        .await
        .map_err(map_taskflow_verify_error)?;
    Ok(())
}

fn map_taskflow_verify_error(error: TaskFlowError) -> AutomationError {
    match error {
        TaskFlowError::Unavailable => AutomationError::Unavailable,
        TaskFlowError::StaleFence => AutomationError::AccessDenied,
        TaskFlowError::Invalid(_)
        | TaskFlowError::Conflict(_)
        | TaskFlowError::Corrupt(_)
        | TaskFlowError::InvalidTransition(_) => AutomationError::Corrupt,
    }
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation())
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn parse_task_id(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<AutomationTaskId, AutomationError> {
    AutomationTaskId::parse(&row.try_get::<String, _>(column).map_err(unavailable)?)
        .map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_error: impl std::fmt::Display) -> AutomationError {
    AutomationError::Unavailable
}

fn create_private_directory(path: &Path) -> Result<(), AutomationError> {
    fs::create_dir_all(path).map_err(unavailable)?;
    if path.canonicalize().map_err(unavailable)? != path {
        return Err(AutomationError::Invalid);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
    }
    Ok(())
}

fn protect_database_file(_path: &Path) -> Result<(), AutomationError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(_path, fs::Permissions::from_mode(0o600)).map_err(unavailable)?;
    }
    Ok(())
}
