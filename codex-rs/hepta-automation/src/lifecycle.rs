//! Durable schedule revision and automation-occurrence lifecycle.
//!
//! This module composes the existing timer store instead of replacing it.
//! `automation_runs` remains the compatibility record for due work and Core
//! queue admission; this layer binds that record to an immutable schedule
//! revision and deterministic occurrence identity, then keeps queue admission
//! distinct from terminal execution.

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sqlx::Row;

use crate::AutomationAdmission;
use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationQueueReceipt;
use crate::AutomationStore;
use crate::AutomationTaskId;

const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const MAX_CATCH_UP: u16 = 1_024;
const MAX_RECOVERY_SCAN: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationMissedRunPolicy {
    Skip,
    Coalesce,
    CatchUp { max_occurrences: u16 },
}

impl AutomationMissedRunPolicy {
    fn db_parts(self) -> (&'static str, u16) {
        match self {
            Self::Skip => ("skip", 0),
            Self::Coalesce => ("coalesce", 0),
            Self::CatchUp { max_occurrences } => ("catch_up", max_occurrences),
        }
    }

    fn parse(kind: &str, maximum: u16) -> Result<Self, AutomationError> {
        match kind {
            "skip" if maximum == 0 => Ok(Self::Skip),
            "coalesce" if maximum == 0 => Ok(Self::Coalesce),
            "catch_up" if (1..=MAX_CATCH_UP).contains(&maximum) => {
                Ok(Self::CatchUp {
                    max_occurrences: maximum,
                })
            }
            _ => Err(AutomationError::Corrupt),
        }
    }

    fn validate(self) -> Result<(), AutomationError> {
        match self {
            Self::CatchUp { max_occurrences }
                if !(1..=MAX_CATCH_UP).contains(&max_occurrences) =>
            {
                Err(AutomationError::Invalid)
            }
            _ => Ok(()),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOverlapPolicy {
    /// Do not materialize the next occurrence until this occurrence is terminal.
    Forbid,
    /// Advance recurrence after durable Core admission while retaining this
    /// occurrence as non-terminal until its terminal observer settles it.
    Allow,
}

impl AutomationOverlapPolicy {
    fn as_str(self) -> &'static str {
        match self {
            Self::Forbid => "forbid",
            Self::Allow => "allow",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "forbid" => Ok(Self::Forbid),
            "allow" => Ok(Self::Allow),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationSchedulePolicy {
    pub revision: u64,
    pub missed_run: AutomationMissedRunPolicy,
    pub overlap: AutomationOverlapPolicy,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOccurrenceState {
    Claimed,
    Admitted,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

impl AutomationOccurrenceState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::Admitted => "admitted",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "claimed" => Ok(Self::Claimed),
            "admitted" => Ok(Self::Admitted),
            "running" => Ok(Self::Running),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(AutomationError::Corrupt),
        }
    }

    fn terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOccurrenceTerminalState {
    Succeeded,
    Failed,
    Cancelled,
}

impl AutomationOccurrenceTerminalState {
    fn state(self) -> AutomationOccurrenceState {
        match self {
            Self::Succeeded => AutomationOccurrenceState::Succeeded,
            Self::Failed => AutomationOccurrenceState::Failed,
            Self::Cancelled => AutomationOccurrenceState::Cancelled,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationOccurrence {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub occurrence_id: String,
    pub schedule_revision: u64,
    pub scheduled_for_ms: u64,
    pub client_user_message_id: String,
    pub state: AutomationOccurrenceState,
    pub overlap: AutomationOverlapPolicy,
    pub claim_generation: u64,
    pub claim_token: String,
    pub step_attempt: u32,
    pub taskflow_run_id: String,
    pub queued_submission_id: Option<String>,
    pub provider_payload_sha256: Option<String>,
    pub turn_id: Option<String>,
    pub terminal_receipt_digest: Option<Sha256Digest>,
    pub updated_at_ms: u64,
    pub terminal_at_ms: Option<u64>,
}

/// Bounded recovery projection used by the owning runtime. Prompt text stays
/// owner-local and is returned only to the already-authorized Agent runtime.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOccurrenceWork {
    pub occurrence: AutomationOccurrence,
    pub admission: AutomationAdmission,
}

#[derive(Serialize)]
struct OccurrenceCommandCanonical<'a> {
    operation: &'a str,
    occurrence_id: &'a str,
    state: &'a str,
    claim_generation: u64,
    claim_token: &'a str,
    queued_submission_id: Option<&'a str>,
    turn_id: Option<&'a str>,
    receipt_digest: Option<&'a str>,
}

#[derive(Serialize)]
struct OccurrenceEventCanonical<'a> {
    previous_event_digest: &'a str,
    command_digest: &'a str,
    event_kind: &'a str,
    state: &'a str,
    receipt_digest: Option<&'a str>,
    recorded_at_ms: u64,
}

impl AutomationStore {
    pub async fn schedule_policy(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<AutomationSchedulePolicy, AutomationError> {
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        ensure_schedule_metadata(&mut transaction, self, task_id).await?;
        let policy = load_schedule_policy(&mut transaction, self, task_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(policy)
    }

    /// Revision-bump recurrence policy. A materialized occurrence owns its
    /// schedule revision; policy mutation therefore conflicts while any
    /// occurrence for the task is non-terminal.
    pub async fn set_schedule_policy(
        &self,
        task_id: AutomationTaskId,
        expected_revision: u64,
        missed_run: AutomationMissedRunPolicy,
        overlap: AutomationOverlapPolicy,
        now_ms: u64,
    ) -> Result<AutomationSchedulePolicy, AutomationError> {
        missed_run.validate()?;
        if expected_revision == 0 {
            return Err(AutomationError::Invalid);
        }
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or(AutomationError::Invalid)?;
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        ensure_schedule_metadata(&mut transaction, self, task_id).await?;
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM automation_occurrence_lifecycle
             WHERE task_id = ? AND owner_agent_id = ?
               AND state IN ('claimed', 'admitted', 'running', 'indeterminate')",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if active != 0 {
            return Err(AutomationError::Conflict);
        }
        let (kind, maximum) = missed_run.db_parts();
        let changed = sqlx::query(
            "UPDATE automation_schedule_metadata
             SET revision = ?, missed_run_policy = ?, max_catch_up_occurrences = ?,
                 catch_up_remaining = 0, catch_up_active = 0,
                 overlap_policy = ?, updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ? AND revision = ?",
        )
        .bind(to_i64(next_revision)?)
        .bind(kind)
        .bind(i64::from(maximum))
        .bind(overlap.as_str())
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(to_i64(expected_revision)?)
        .execute(&mut *transaction)
        .await
        .map_err(constraint_or_unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(AutomationSchedulePolicy {
            revision: next_revision,
            missed_run,
            overlap,
        })
    }

    /// Bind a leased compatibility run to its immutable schedule revision and
    /// deterministic occurrence ID before any provider call.
    pub async fn materialize_occurrence(
        &self,
        lease: &AutomationLease,
        now_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if lease.task.owner_agent_id != *self.taskflow_owner_agent_id() {
            return Err(AutomationError::AccessDenied);
        }
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        ensure_schedule_metadata(&mut transaction, self, lease.task.task_id).await?;
        if let Some(current) = load_occurrence_row(
            &mut transaction,
            self,
            lease.task.task_id,
            lease.occurrence,
        )
        .await?
        {
            if current.scheduled_for_ms != lease.scheduled_for_ms
                || current.client_user_message_id != lease.client_user_message_id
            {
                return Err(AutomationError::Conflict);
            }
            if current.state != AutomationOccurrenceState::Claimed {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(current);
            }
            if current.claim_generation != lease.lease_generation
                || current.claim_token != lease.lease_token
            {
                let changed = sqlx::query(
                    "UPDATE automation_occurrence_lifecycle
                     SET claim_generation = ?, claim_token = ?, updated_at_ms = ?
                     WHERE task_id = ? AND occurrence = ? AND state = 'claimed'",
                )
                .bind(to_i64(lease.lease_generation)?)
                .bind(&lease.lease_token)
                .bind(to_i64(now_ms)?)
                .bind(lease.task.task_id.to_string())
                .bind(to_i64(lease.occurrence)?)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if changed.rows_affected() != 1 {
                    return Err(AutomationError::Conflict);
                }
                append_occurrence_event(
                    &mut transaction,
                    lease.task.task_id,
                    lease.occurrence,
                    &current.occurrence_id,
                    "reclaimed",
                    AutomationOccurrenceState::Claimed,
                    lease.lease_generation,
                    &lease.lease_token,
                    None,
                    None,
                    None,
                    &format!("occurrence:reclaim:{}:{}", lease.occurrence, lease.lease_generation),
                    now_ms,
                )
                .await?;
            }
            let current = load_occurrence_row(
                &mut transaction,
                self,
                lease.task.task_id,
                lease.occurrence,
            )
            .await?
            .ok_or(AutomationError::Corrupt)?;
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }

        let policy = load_schedule_policy(&mut transaction, self, lease.task.task_id).await?;
        let occurrence_id = deterministic_occurrence_id(
            self.taskflow_owner_agent_id().as_str(),
            lease.task.task_id,
            policy.revision,
            lease.scheduled_for_ms,
        );
        let taskflow_run_id = format!("automation-run:{}", digest_suffix(&occurrence_id));
        sqlx::query(
            "INSERT INTO automation_occurrence_lifecycle (
                task_id, occurrence, occurrence_id, owner_agent_id, schedule_revision,
                scheduled_for_ms, client_user_message_id, state, overlap_policy,
                claim_generation, claim_token, taskflow_run_id, recovery_phase,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?, ?, 'awaiting_admission', ?, ?)",
        )
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(&occurrence_id)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(to_i64(policy.revision)?)
        .bind(to_i64(lease.scheduled_for_ms)?)
        .bind(&lease.client_user_message_id)
        .bind(policy.overlap.as_str())
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&taskflow_run_id)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(constraint_or_unavailable)?;
        append_occurrence_event(
            &mut transaction,
            lease.task.task_id,
            lease.occurrence,
            &occurrence_id,
            "claimed",
            AutomationOccurrenceState::Claimed,
            lease.lease_generation,
            &lease.lease_token,
            None,
            None,
            None,
            &format!("occurrence:claim:{}:{}", lease.occurrence, lease.lease_generation),
            now_ms,
        )
        .await?;
        let current = load_occurrence_row(
            &mut transaction,
            self,
            lease.task.task_id,
            lease.occurrence,
        )
        .await?
        .ok_or(AutomationError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(current)
    }

    /// Persist Core admission without declaring the automation occurrence
    /// complete. With overlap forbidden, the timer is parked until the
    /// occurrence's terminal observation advances it.
    pub async fn record_occurrence_admitted(
        &self,
        lease: &AutomationLease,
        receipt: &AutomationQueueReceipt,
        admitted_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        if lease.task.owner_agent_id != *self.taskflow_owner_agent_id()
            || receipt.client_user_message_id != lease.client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            return Err(AutomationError::AccessDenied);
        }
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let current = load_occurrence_row(
            &mut transaction,
            self,
            lease.task.task_id,
            lease.occurrence,
        )
        .await?
        .ok_or(AutomationError::Conflict)?;
        if current.state != AutomationOccurrenceState::Claimed
            || current.claim_generation != lease.lease_generation
        {
            return Err(AutomationError::Conflict);
        }
        let run = sqlx::query(
            "UPDATE automation_runs
             SET state = 'submitted', lease_generation = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL, queued_submission_id = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND state = 'leased'
               AND lease_generation = ? AND lease_token = ?
               AND client_user_message_id = ?",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(admitted_at_ms)?)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(constraint_or_unavailable)?;
        if run.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        let dispatch = sqlx::query(
            "UPDATE automation_dispatch_outcomes
             SET outcome = 'submitted', queued_submission_id = ?, observed_at_ms = ?, submitted_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND client_user_message_id = ?
               AND outcome = 'uncertain'",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(admitted_at_ms)?)
        .bind(to_i64(admitted_at_ms)?)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(&lease.client_user_message_id)
        .execute(&mut *transaction)
        .await
        .map_err(constraint_or_unavailable)?;
        if dispatch.rows_affected() == 0 {
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
            .bind(to_i64(admitted_at_ms)?)
            .bind(to_i64(admitted_at_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(constraint_or_unavailable)?;
        }
        let lifecycle = sqlx::query(
            "UPDATE automation_occurrence_lifecycle
             SET state = 'admitted', queued_submission_id = ?,
                 recovery_phase = 'awaiting_turn', updated_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND state = 'claimed'
               AND claim_generation = ? AND claim_token = ?",
        )
        .bind(&receipt.queued_submission_id)
        .bind(to_i64(admitted_at_ms)?)
        .bind(lease.task.task_id.to_string())
        .bind(to_i64(lease.occurrence)?)
        .bind(to_i64(lease.lease_generation)?)
        .bind(&lease.lease_token)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if lifecycle.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        append_occurrence_event(
            &mut transaction,
            lease.task.task_id,
            lease.occurrence,
            &current.occurrence_id,
            "admitted",
            AutomationOccurrenceState::Admitted,
            lease.lease_generation,
            &lease.lease_token,
            Some(&receipt.queued_submission_id),
            None,
            None,
            &format!("occurrence:admitted:{}", lease.occurrence),
            admitted_at_ms,
        )
        .await?;

        match current.overlap {
            AutomationOverlapPolicy::Forbid => {
                sqlx::query(
                    "UPDATE automation_tasks SET next_run_at_ms = NULL, updated_at_ms = ?
                     WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
                )
                .bind(to_i64(admitted_at_ms)?)
                .bind(lease.task.task_id.to_string())
                .bind(self.taskflow_owner_agent_id().as_str())
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
            }
            AutomationOverlapPolicy::Allow => {
                advance_schedule(
                    &mut transaction,
                    self,
                    lease.task.task_id,
                    lease.scheduled_for_ms,
                    admitted_at_ms,
                )
                .await?;
            }
        }
        let next = load_occurrence_row(
            &mut transaction,
            self,
            lease.task.task_id,
            lease.occurrence,
        )
        .await?
        .ok_or(AutomationError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(next)
    }

    pub async fn record_occurrence_turn(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
        turn_id: &str,
        provider_payload_sha256: &str,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        validate_digest_text(provider_payload_sha256)?;
        if turn_id.is_empty() || turn_id.len() > 256 {
            return Err(AutomationError::Invalid);
        }
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let current = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if current.client_user_message_id != client_user_message_id {
            return Err(AutomationError::Conflict);
        }
        if current.state == AutomationOccurrenceState::Running {
            if current.turn_id.as_deref() != Some(turn_id)
                || current.provider_payload_sha256.as_deref() != Some(provider_payload_sha256)
            {
                return Err(AutomationError::Conflict);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != AutomationOccurrenceState::Admitted {
            return Err(AutomationError::Conflict);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrence_lifecycle
             SET state = 'running', turn_id = ?, provider_payload_sha256 = ?,
                 recovery_phase = 'awaiting_terminal', updated_at_ms = ?
             WHERE task_id = ? AND occurrence = ? AND state = 'admitted'",
        )
        .bind(turn_id)
        .bind(provider_payload_sha256)
        .bind(to_i64(observed_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        append_occurrence_event(
            &mut transaction,
            task_id,
            occurrence,
            &current.occurrence_id,
            "turn_persisted",
            AutomationOccurrenceState::Running,
            current.claim_generation,
            "historical-claim",
            current.queued_submission_id.as_deref(),
            Some(turn_id),
            None,
            &format!("occurrence:turn:{occurrence}:{turn_id}"),
            observed_at_ms,
        )
        .await?;
        let next = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(next)
    }

    pub async fn mark_occurrence_indeterminate(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        receipt_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        validate_digest_text(receipt_digest.as_str())?;
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let current = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if current.state.terminal() {
            return Err(AutomationError::Conflict);
        }
        if current.state == AutomationOccurrenceState::Indeterminate {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        let changed = sqlx::query(
            "UPDATE automation_occurrence_lifecycle
             SET state = 'indeterminate', terminal_receipt_digest = ?,
                 recovery_phase = 'reconciliation_required', updated_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND state IN ('claimed', 'admitted', 'running')",
        )
        .bind(receipt_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        append_occurrence_event(
            &mut transaction,
            task_id,
            occurrence,
            &current.occurrence_id,
            "indeterminate",
            AutomationOccurrenceState::Indeterminate,
            current.claim_generation,
            "historical-claim",
            current.queued_submission_id.as_deref(),
            current.turn_id.as_deref(),
            Some(receipt_digest.as_str()),
            &format!("occurrence:indeterminate:{occurrence}:{}", receipt_digest.as_str()),
            observed_at_ms,
        )
        .await?;
        let next = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(next)
    }

    /// Terminalize one occurrence after a trusted terminal observation or
    /// explicit reconciliation. Only this boundary advances a forbidden-
    /// overlap schedule.
    pub async fn complete_occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        terminal: AutomationOccurrenceTerminalState,
        receipt_digest: &Sha256Digest,
        completed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        validate_digest_text(receipt_digest.as_str())?;
        let terminal_state = terminal.state();
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let current = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if current.state.terminal() {
            if current.state == terminal_state
                && current.terminal_receipt_digest.as_ref() == Some(receipt_digest)
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(current);
            }
            return Err(AutomationError::Conflict);
        }
        if !matches!(
            current.state,
            AutomationOccurrenceState::Admitted
                | AutomationOccurrenceState::Running
                | AutomationOccurrenceState::Indeterminate
        ) {
            return Err(AutomationError::Conflict);
        }
        let event_kind = terminal_state.as_str();
        let changed = sqlx::query(
            "UPDATE automation_occurrence_lifecycle
             SET state = ?, terminal_receipt_digest = ?, recovery_phase = 'terminal',
                 updated_at_ms = ?, terminal_at_ms = ?
             WHERE task_id = ? AND occurrence = ?
               AND state IN ('admitted', 'running', 'indeterminate')",
        )
        .bind(event_kind)
        .bind(receipt_digest.as_str())
        .bind(to_i64(completed_at_ms)?)
        .bind(to_i64(completed_at_ms)?)
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        append_occurrence_event(
            &mut transaction,
            task_id,
            occurrence,
            &current.occurrence_id,
            event_kind,
            terminal_state,
            current.claim_generation,
            "historical-claim",
            current.queued_submission_id.as_deref(),
            current.turn_id.as_deref(),
            Some(receipt_digest.as_str()),
            &format!("occurrence:terminal:{occurrence}:{event_kind}:{}", receipt_digest.as_str()),
            completed_at_ms,
        )
        .await?;
        if current.overlap == AutomationOverlapPolicy::Forbid {
            advance_schedule(
                &mut transaction,
                self,
                task_id,
                current.scheduled_for_ms,
                completed_at_ms,
            )
            .await?;
        }
        let next = load_occurrence_row(&mut transaction, self, task_id, occurrence)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(next)
    }

    pub async fn automation_occurrence(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrence>, AutomationError> {
        let mut transaction = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let row = load_occurrence_row(&mut transaction, self, task_id, occurrence).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(row)
    }

    /// Return a bounded set of non-terminal occurrences that already crossed
    /// Core admission or need explicit reconciliation. Claimed pre-admission
    /// work remains owned by the scheduler lease/uncertainty path.
    pub async fn pending_occurrence_work(
        &self,
        limit: usize,
    ) -> Result<Vec<AutomationOccurrenceWork>, AutomationError> {
        if limit == 0 || limit > MAX_RECOVERY_SCAN {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT o.*, t.thread_id, t.prompt
             FROM automation_occurrence_lifecycle o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.owner_agent_id = ?
               AND o.state IN ('admitted', 'running', 'indeterminate')
             ORDER BY o.updated_at_ms, o.task_id, o.occurrence
             LIMIT ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let mut work = Vec::with_capacity(rows.len());
        for row in rows {
            let occurrence = occurrence_from_row(&row, self.taskflow_owner_agent_id().as_str())?;
            let thread_id: String = row.try_get("thread_id").map_err(|_| AutomationError::Corrupt)?;
            let prompt: String = row.try_get("prompt").map_err(|_| AutomationError::Corrupt)?;
            work.push(AutomationOccurrenceWork {
                admission: AutomationAdmission {
                    agent_id: self.taskflow_owner_agent_id().clone(),
                    task_id: occurrence.task_id,
                    occurrence: occurrence.occurrence,
                    scheduled_for_ms: occurrence.scheduled_for_ms,
                    thread_id,
                    prompt,
                    client_user_message_id: occurrence.client_user_message_id.clone(),
                },
                occurrence,
            });
        }
        Ok(work)
    }
}

pub fn deterministic_occurrence_id(
    owner_agent_id: &str,
    task_id: AutomationTaskId,
    schedule_revision: u64,
    scheduled_for_ms: u64,
) -> String {
    let mut bytes = b"hepta.automation.occurrence.v1\0".to_vec();
    push_text(&mut bytes, owner_agent_id);
    push_text(&mut bytes, &task_id.to_string());
    bytes.extend_from_slice(&schedule_revision.to_be_bytes());
    bytes.extend_from_slice(&scheduled_for_ms.to_be_bytes());
    let digest = Sha256Digest::for_bytes(&bytes);
    format!("automation-occurrence:{}", digest.as_str())
}

async fn ensure_schedule_metadata(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
) -> Result<(), AutomationError> {
    sqlx::query(
        "INSERT OR IGNORE INTO automation_schedule_metadata (
            task_id, owner_agent_id, revision, missed_run_policy,
            max_catch_up_occurrences, catch_up_remaining, overlap_policy,
            created_at_ms, updated_at_ms, catch_up_active
         )
         SELECT task_id, owner_agent_id, 1, 'skip', 0, 0, 'allow',
                created_at_ms, updated_at_ms, 0
         FROM automation_tasks WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    let exists: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM automation_schedule_metadata
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    if exists != 1 {
        return Err(AutomationError::AccessDenied);
    }
    Ok(())
}

async fn load_schedule_policy(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
) -> Result<AutomationSchedulePolicy, AutomationError> {
    let row = sqlx::query(
        "SELECT revision, missed_run_policy, max_catch_up_occurrences, overlap_policy
         FROM automation_schedule_metadata
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .ok_or(AutomationError::AccessDenied)?;
    let revision = to_u64(row.try_get("revision").map_err(|_| AutomationError::Corrupt)?)?;
    let maximum = to_u16(
        row.try_get("max_catch_up_occurrences")
            .map_err(|_| AutomationError::Corrupt)?,
    )?;
    let missed_kind: String = row
        .try_get("missed_run_policy")
        .map_err(|_| AutomationError::Corrupt)?;
    let overlap_kind: String = row
        .try_get("overlap_policy")
        .map_err(|_| AutomationError::Corrupt)?;
    Ok(AutomationSchedulePolicy {
        revision,
        missed_run: AutomationMissedRunPolicy::parse(&missed_kind, maximum)?,
        overlap: AutomationOverlapPolicy::parse(&overlap_kind)?,
    })
}

async fn load_occurrence_row(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    occurrence: u64,
) -> Result<Option<AutomationOccurrence>, AutomationError> {
    let row = sqlx::query(
        "SELECT * FROM automation_occurrence_lifecycle
         WHERE task_id = ? AND occurrence = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    row.map(|row| occurrence_from_row(&row, store.taskflow_owner_agent_id().as_str()))
        .transpose()
}

fn occurrence_from_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &str,
) -> Result<AutomationOccurrence, AutomationError> {
    let owner: String = row.try_get("owner_agent_id").map_err(|_| AutomationError::Corrupt)?;
    if owner != expected_owner {
        return Err(AutomationError::AccessDenied);
    }
    let task_raw: String = row.try_get("task_id").map_err(|_| AutomationError::Corrupt)?;
    let task_id = AutomationTaskId::parse(&task_raw).map_err(|_| AutomationError::Corrupt)?;
    let state_raw: String = row.try_get("state").map_err(|_| AutomationError::Corrupt)?;
    let overlap_raw: String = row
        .try_get("overlap_policy")
        .map_err(|_| AutomationError::Corrupt)?;
    let terminal_raw: Option<String> = row
        .try_get("terminal_receipt_digest")
        .map_err(|_| AutomationError::Corrupt)?;
    let terminal_receipt_digest = terminal_raw
        .map(|value| {
            validate_digest_text(&value)?;
            Sha256Digest::parse(value).map_err(|_| AutomationError::Corrupt)
        })
        .transpose()?;
    Ok(AutomationOccurrence {
        task_id,
        occurrence: to_u64(row.try_get("occurrence").map_err(|_| AutomationError::Corrupt)?)?,
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
        client_user_message_id: row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?,
        state: AutomationOccurrenceState::parse(&state_raw)?,
        overlap: AutomationOverlapPolicy::parse(&overlap_raw)?,
        claim_generation: to_u64(
            row.try_get("claim_generation")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        claim_token: row
            .try_get("claim_token")
            .map_err(|_| AutomationError::Corrupt)?,
        step_attempt: u32::try_from(
            row.try_get::<i64, _>("step_attempt")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        taskflow_run_id: row
            .try_get("taskflow_run_id")
            .map_err(|_| AutomationError::Corrupt)?,
        queued_submission_id: row
            .try_get("queued_submission_id")
            .map_err(|_| AutomationError::Corrupt)?,
        provider_payload_sha256: row
            .try_get("provider_payload_sha256")
            .map_err(|_| AutomationError::Corrupt)?,
        turn_id: row.try_get("turn_id").map_err(|_| AutomationError::Corrupt)?,
        terminal_receipt_digest,
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

#[allow(clippy::too_many_arguments)]
async fn append_occurrence_event(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    task_id: AutomationTaskId,
    occurrence: u64,
    occurrence_id: &str,
    event_kind: &str,
    state: AutomationOccurrenceState,
    claim_generation: u64,
    claim_token: &str,
    queued_submission_id: Option<&str>,
    turn_id: Option<&str>,
    receipt_digest: Option<&str>,
    command_id: &str,
    recorded_at_ms: u64,
) -> Result<(), AutomationError> {
    let command = OccurrenceCommandCanonical {
        operation: event_kind,
        occurrence_id,
        state: state.as_str(),
        claim_generation,
        claim_token,
        queued_submission_id,
        turn_id,
        receipt_digest,
    };
    let command_bytes = serde_json::to_vec(&command).map_err(|_| AutomationError::Corrupt)?;
    let command_digest = Sha256Digest::for_bytes(&command_bytes);
    if let Some(existing) = sqlx::query(
        "SELECT command_digest FROM automation_occurrence_events
         WHERE task_id = ? AND occurrence = ? AND command_id = ?",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .bind(command_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    {
        let digest: String = existing
            .try_get("command_digest")
            .map_err(|_| AutomationError::Corrupt)?;
        if digest == command_digest.as_str() {
            return Ok(());
        }
        return Err(AutomationError::Conflict);
    }
    let previous = sqlx::query_scalar::<_, String>(
        "SELECT event_digest FROM automation_occurrence_events
         WHERE task_id = ? AND occurrence = ? ORDER BY event_seq DESC LIMIT 1",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .unwrap_or_else(|| ZERO_DIGEST.to_string());
    let next_seq = sqlx::query_scalar::<_, i64>(
        "SELECT COALESCE(MAX(event_seq), 0) + 1 FROM automation_occurrence_events
         WHERE task_id = ? AND occurrence = ?",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    let event = OccurrenceEventCanonical {
        previous_event_digest: &previous,
        command_digest: command_digest.as_str(),
        event_kind,
        state: state.as_str(),
        receipt_digest,
        recorded_at_ms,
    };
    let event_bytes = serde_json::to_vec(&event).map_err(|_| AutomationError::Corrupt)?;
    let event_digest = Sha256Digest::for_bytes(&event_bytes);
    sqlx::query(
        "INSERT INTO automation_occurrence_events (
            task_id, occurrence, event_seq, event_kind, command_id, command_digest,
            state, receipt_digest, previous_event_digest, event_digest, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(task_id.to_string())
    .bind(to_i64(occurrence)?)
    .bind(next_seq)
    .bind(event_kind)
    .bind(command_id)
    .bind(command_digest.as_str())
    .bind(state.as_str())
    .bind(receipt_digest)
    .bind(previous)
    .bind(event_digest.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(constraint_or_unavailable)?;
    Ok(())
}

async fn advance_schedule(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    scheduled_for_ms: u64,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    ensure_schedule_metadata(tx, store, task_id).await?;
    let policy = load_schedule_policy(tx, store, task_id).await?;
    let row = sqlx::query(
        "SELECT state, schedule_kind, interval_ms FROM automation_tasks
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .ok_or(AutomationError::AccessDenied)?;
    let state: String = row.try_get("state").map_err(|_| AutomationError::Corrupt)?;
    if state != "enabled" {
        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
        return Ok(());
    }
    let schedule_kind: String = row
        .try_get("schedule_kind")
        .map_err(|_| AutomationError::Corrupt)?;
    if schedule_kind == "once" {
        sqlx::query(
            "UPDATE automation_tasks
             SET state = 'completed', next_run_at_ms = NULL, updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
        )
        .bind(to_i64(observed_at_ms)?)
        .bind(task_id.to_string())
        .bind(store.taskflow_owner_agent_id().as_str())
        .execute(&mut **tx)
        .await
        .map_err(unavailable)?;
        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
        return Ok(());
    }
    if schedule_kind != "fixed_interval" {
        return Err(AutomationError::Corrupt);
    }
    let interval = to_u64(
        row.try_get::<Option<i64>, _>("interval_ms")
            .map_err(|_| AutomationError::Corrupt)?
            .ok_or(AutomationError::Corrupt)?,
    )?;
    let baseline = scheduled_for_ms
        .checked_add(interval)
        .ok_or(AutomationError::Invalid)?;

    let next = if baseline > observed_at_ms {
        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
        baseline
    } else {
        match policy.missed_run {
            AutomationMissedRunPolicy::Skip => {
                reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                first_after(baseline, interval, observed_at_ms)?
            }
            AutomationMissedRunPolicy::Coalesce => {
                reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                latest_not_after(baseline, interval, observed_at_ms)?
            }
            AutomationMissedRunPolicy::CatchUp { max_occurrences } => {
                let (active, remaining) = catch_up_state(tx, store, task_id).await?;
                if active {
                    if remaining == 0 {
                        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                        first_after(baseline, interval, observed_at_ms)?
                    } else {
                        set_catch_up_state(
                            tx,
                            store,
                            task_id,
                            true,
                            remaining - 1,
                            observed_at_ms,
                        )
                        .await?;
                        baseline
                    }
                } else {
                    let overdue_count = observed_at_ms
                        .checked_sub(baseline)
                        .ok_or(AutomationError::Invalid)?
                        .checked_div(interval)
                        .ok_or(AutomationError::Invalid)?
                        .checked_add(1)
                        .ok_or(AutomationError::Invalid)?;
                    let allowed = overdue_count.min(u64::from(max_occurrences));
                    let remaining = u16::try_from(allowed.saturating_sub(1))
                        .map_err(|_| AutomationError::Invalid)?;
                    set_catch_up_state(
                        tx,
                        store,
                        task_id,
                        true,
                        remaining,
                        observed_at_ms,
                    )
                    .await?;
                    baseline
                }
            }
        }
    };

    sqlx::query(
        "UPDATE automation_tasks
         SET next_run_at_ms = ?, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
    )
    .bind(to_i64(next)?)
    .bind(to_i64(observed_at_ms)?)
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn first_after(baseline: u64, interval: u64, now_ms: u64) -> Result<u64, AutomationError> {
    if baseline > now_ms {
        return Ok(baseline);
    }
    let missed = now_ms
        .checked_sub(baseline)
        .ok_or(AutomationError::Invalid)?
        / interval;
    baseline
        .checked_add(
            missed
                .checked_add(1)
                .ok_or(AutomationError::Invalid)?
                .checked_mul(interval)
                .ok_or(AutomationError::Invalid)?,
        )
        .ok_or(AutomationError::Invalid)
}

fn latest_not_after(
    baseline: u64,
    interval: u64,
    now_ms: u64,
) -> Result<u64, AutomationError> {
    if baseline > now_ms {
        return Ok(baseline);
    }
    let missed = now_ms
        .checked_sub(baseline)
        .ok_or(AutomationError::Invalid)?
        / interval;
    baseline
        .checked_add(missed.checked_mul(interval).ok_or(AutomationError::Invalid)?)
        .ok_or(AutomationError::Invalid)
}

async fn catch_up_state(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
) -> Result<(bool, u16), AutomationError> {
    let row = sqlx::query(
        "SELECT catch_up_active, catch_up_remaining
         FROM automation_schedule_metadata
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    let active: i64 = row
        .try_get("catch_up_active")
        .map_err(|_| AutomationError::Corrupt)?;
    let remaining = to_u16(
        row.try_get("catch_up_remaining")
            .map_err(|_| AutomationError::Corrupt)?,
    )?;
    match active {
        0 => Ok((false, remaining)),
        1 => Ok((true, remaining)),
        _ => Err(AutomationError::Corrupt),
    }
}

async fn set_catch_up_state(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    active: bool,
    remaining: u16,
    now_ms: u64,
) -> Result<(), AutomationError> {
    sqlx::query(
        "UPDATE automation_schedule_metadata
         SET catch_up_active = ?, catch_up_remaining = ?, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(if active { 1_i64 } else { 0_i64 })
    .bind(i64::from(remaining))
    .bind(to_i64(now_ms)?)
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn reset_catch_up(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    now_ms: u64,
) -> Result<(), AutomationError> {
    set_catch_up_state(tx, store, task_id, false, 0, now_ms).await
}

fn digest_suffix(value: &str) -> String {
    Sha256Digest::for_bytes(value.as_bytes()).as_str().to_string()
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn validate_digest_text(value: &str) -> Result<(), AutomationError> {
    if value == ZERO_DIGEST
        || value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn to_u16(value: i64) -> Result<u16, AutomationError> {
    u16::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

fn constraint_or_unavailable(error: sqlx::Error) -> AutomationError {
    match &error {
        sqlx::Error::Database(database) if database.is_unique_violation() => AutomationError::Conflict,
        _ => AutomationError::Unavailable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic_occurrence_identity_binds_revision_and_instant() {
        let task = AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75007")
            .expect("task id");
        let first = deterministic_occurrence_id("agent-1", task, 1, 1000);
        assert_eq!(first, deterministic_occurrence_id("agent-1", task, 1, 1000));
        assert_ne!(first, deterministic_occurrence_id("agent-1", task, 2, 1000));
        assert_ne!(first, deterministic_occurrence_id("agent-1", task, 1, 1001));
    }

    #[test]
    fn missed_run_math_is_bounded_and_deterministic() {
        assert_eq!(first_after(1100, 100, 1450).expect("first future"), 1500);
        assert_eq!(latest_not_after(1100, 100, 1450).expect("coalesce"), 1400);
    }
}
