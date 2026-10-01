//! Fair scheduling of bounded occurrence-observer passes.

use crate::AutomationError;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceState;
use crate::AutomationStore;

impl AutomationStore {
    /// Rotate successfully observed, still-pending work behind newer work.
    /// Call only after the observer completed its lookup. Exact snapshot CAS
    /// prevents this progress write from overwriting a concurrent turn, cursor
    /// or terminal update. Failed lookups leave the recovery frontier intact.
    pub async fn defer_occurrence_observation(
        &self,
        occurrence: &AutomationOccurrence,
        observed_at_ms: u64,
    ) -> Result<bool, AutomationError> {
        let state = match occurrence.state {
            AutomationOccurrenceState::Admitted => "admitted",
            AutomationOccurrenceState::Running => "running",
            AutomationOccurrenceState::Indeterminate => "indeterminate",
            AutomationOccurrenceState::Claimed
            | AutomationOccurrenceState::Succeeded
            | AutomationOccurrenceState::Failed
            | AutomationOccurrenceState::Cancelled => return Err(AutomationError::Invalid),
        };
        let updated_at_ms = observed_at_ms.max(
            occurrence
                .updated_at_ms
                .checked_add(1)
                .ok_or(AutomationError::Invalid)?,
        );
        let to_i64 = |value: u64| i64::try_from(value).map_err(|_| AutomationError::Invalid);
        let (mut transaction, _) = self.begin_timer_write().await?;
        let changed = sqlx::query(
            "UPDATE automation_occurrence_lifecycle SET updated_at_ms = ?
             WHERE owner_agent_id = ? AND task_id = ? AND occurrence = ?
               AND occurrence_id = ? AND taskflow_run_id = ?
               AND state = ? AND updated_at_ms = ?
               AND client_user_message_id = ? AND claim_generation = ? AND claim_token = ?
               AND step_attempt = ? AND queued_submission_id IS ? AND turn_id IS ?
               AND terminal_scan_cursor IS ? AND terminal_receipt_digest IS ?",
        )
        .bind(to_i64(updated_at_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(occurrence.task_id.to_string())
        .bind(to_i64(occurrence.occurrence)?)
        .bind(&occurrence.occurrence_id)
        .bind(&occurrence.taskflow_run_id)
        .bind(state)
        .bind(to_i64(occurrence.updated_at_ms)?)
        .bind(&occurrence.client_user_message_id)
        .bind(to_i64(occurrence.claim_generation)?)
        .bind(&occurrence.claim_token)
        .bind(i64::from(occurrence.step_attempt))
        .bind(occurrence.queued_submission_id.as_deref())
        .bind(occurrence.turn_id.as_deref())
        .bind(occurrence.terminal_scan_cursor.as_deref())
        .bind(
            occurrence
                .terminal_receipt_digest
                .as_ref()
                .map(codex_hepta_contracts::Sha256Digest::as_str),
        )
        .execute(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        Ok(changed.rows_affected() == 1)
    }
}
