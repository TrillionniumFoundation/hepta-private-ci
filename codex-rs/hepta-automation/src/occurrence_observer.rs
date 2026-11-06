//! Fair scheduling of bounded occurrence-observer passes.

use crate::AutomationError;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceState;
use crate::AutomationOccurrenceTerminalState;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::TaskFlowTransition;
use sqlx::Row;

impl AutomationStore {
    /// Repair the crash-replayable tail of schedule cancellation. Only a
    /// cancelled compatibility row with exact retained provider-absence
    /// evidence can terminate its old local occurrence; unknown effects stay
    /// frozen. The TaskFlow mutation rechecks the same proof and fence in its
    /// own transaction before this lifecycle receives a terminal receipt.
    pub(crate) async fn finalize_cancelled_occurrence_intents(
        &self,
        task_id: AutomationTaskId,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        let rows = sqlx::query(
            "SELECT o.occurrence, e.payload_json
             FROM automation_occurrence_lifecycle o
             JOIN automation_runs r ON r.task_id = o.task_id AND r.occurrence = o.occurrence
             JOIN taskflow_runs tf ON tf.owner_agent_id = o.owner_agent_id AND tf.run_id = o.taskflow_run_id
             JOIN taskflow_events e ON e.owner_agent_id = tf.owner_agent_id AND e.run_id = tf.run_id
              AND e.command_id = CASE WHEN tf.state = 'cancelled'
                  THEN 'automation:run:cancel-absent:' || o.occurrence_id || ':' || o.step_attempt
                  ELSE 'automation:run:requeue-absent:' || o.occurrence_id || ':' || o.step_attempt END
             WHERE o.owner_agent_id = ? AND o.task_id = ? AND o.state = 'claimed'
               AND r.state = 'cancelled' AND tf.state IN ('queued', 'cancelled')
               AND NOT EXISTS(SELECT 1 FROM automation_dispatch_outcomes d
                   WHERE d.task_id = r.task_id AND d.occurrence = r.occurrence)
               AND NOT EXISTS(SELECT 1 FROM taskflow_effect_dispatch_attempts a
                   WHERE a.owner_agent_id = o.owner_agent_id AND a.run_id = o.taskflow_run_id
                     AND a.step_id = 'codex_turn' AND a.attempt = o.step_attempt)
             ORDER BY o.occurrence LIMIT 1024",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(task_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        for row in rows {
            let occurrence_number = u64::try_from(
                row.try_get::<i64, _>("occurrence")
                    .map_err(|_| AutomationError::Corrupt)?,
            )
            .map_err(|_| AutomationError::Corrupt)?;
            let transition: TaskFlowTransition = serde_json::from_str(
                &row.try_get::<String, _>("payload_json")
                    .map_err(|_| AutomationError::Corrupt)?,
            )
            .map_err(|_| AutomationError::Corrupt)?;
            let proof = match transition {
                TaskFlowTransition::RequeueProvenAbsent { proof_digest }
                | TaskFlowTransition::CancelProvenAbsent { proof_digest } => proof_digest,
                _ => return Err(AutomationError::Corrupt),
            };
            let occurrence = self
                .automation_occurrence(task_id, occurrence_number)
                .await?
                .ok_or(AutomationError::Corrupt)?;
            if occurrence.state == AutomationOccurrenceState::Cancelled {
                continue;
            }
            self.cancel_claimed_taskflow_after_proven_absence(&occurrence, &proof, observed_at_ms)
                .await
                .map_err(crate::store::map_taskflow_mutation_error)?;
            self.complete_occurrence(
                task_id,
                occurrence_number,
                AutomationOccurrenceTerminalState::Cancelled,
                &proof,
                observed_at_ms,
            )
            .await?;
        }
        Ok(())
    }

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
