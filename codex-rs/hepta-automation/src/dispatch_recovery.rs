//! Recovery helpers for a queue request whose reply was lost after the durable
//! pre-dispatch intent was committed.
//!
//! These helpers never contact Core/provider state. The owning runtime performs
//! an exact stable-client-id lookup and supplies the observed receipt (or a
//! proof of absence) here.

use sqlx::Row;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationOccurrence;
use crate::AutomationQueueReceipt;
use crate::AutomationStore;
use crate::AutomationTaskId;

impl AutomationStore {
    /// Convert a previously quarantined `DispatchUnknown` into a durable Core
    /// admission using the exact lease/client identity that authored the
    /// uncertainty row. Lease expiry is irrelevant to historical
    /// reconciliation; no new provider effect is authorized here.
    pub async fn reconcile_uncertain_occurrence_admitted(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        receipt: &AutomationQueueReceipt,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let row = sqlx::query(
            "SELECT r.scheduled_for_ms, r.client_user_message_id,
                    r.lease_generation, r.lease_token, r.lease_expires_at_ms
             FROM automation_runs r
             JOIN automation_dispatch_outcomes d
               ON d.task_id = r.task_id AND d.occurrence = r.occurrence
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ?
               AND t.owner_agent_id = ?
               AND r.state = 'leased' AND d.outcome = 'uncertain'",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let client_user_message_id: String = row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?;
        if receipt.client_user_message_id != client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            return Err(AutomationError::Conflict);
        }
        let task = self
            .task(task_id)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        let lease = AutomationLease {
            task,
            occurrence,
            scheduled_for_ms: to_u64(
                row.try_get("scheduled_for_ms")
                    .map_err(|_| AutomationError::Corrupt)?,
            )?,
            client_user_message_id,
            lease_generation: to_u64(
                row.try_get::<Option<i64>, _>("lease_generation")
                    .map_err(|_| AutomationError::Corrupt)?
                    .ok_or(AutomationError::Corrupt)?,
            )?,
            lease_token: row
                .try_get::<Option<String>, _>("lease_token")
                .map_err(|_| AutomationError::Corrupt)?
                .ok_or(AutomationError::Corrupt)?,
            lease_expires_at_ms: to_u64(
                row.try_get::<Option<i64>, _>("lease_expires_at_ms")
                    .map_err(|_| AutomationError::Corrupt)?
                    .ok_or(AutomationError::Corrupt)?,
            )?,
        };
        self.record_occurrence_admitted(&lease, receipt, observed_at_ms)
            .await
    }

    /// Release a quarantined occurrence only after the queue owner proves the
    /// stable client identity is absent. The next generation reuses the same
    /// occurrence/client identity; materialization updates only the claim fence
    /// and allocates a new durable step attempt.
    pub async fn reconcile_uncertain_occurrence_absent(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
    ) -> Result<(), AutomationError> {
        self.release_uncertain_for_retry(task_id, occurrence, client_user_message_id)
            .await
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
