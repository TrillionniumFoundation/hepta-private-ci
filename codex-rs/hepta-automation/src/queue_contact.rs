//! Exact live admission checks at the queue transport's first-contact cut.

use std::time::Instant;

use sqlx::Row;

use crate::AutomationAdmission;
use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationStore;
use crate::TimerPhase;

/// A scheduler-created, one-use check for the exact prepared queue admission.
/// Delayed transports consume it after connection and send-queue waits, directly
/// before their first request write. Failure retains durable dispatch uncertainty.
pub struct AutomationQueueContact {
    store: AutomationStore,
    lease: AutomationLease,
    tick_at_ms: u64,
    started_at: Instant,
}

impl AutomationQueueContact {
    pub(crate) fn new(
        store: AutomationStore,
        lease: AutomationLease,
        tick_at_ms: u64,
        started_at: Instant,
    ) -> Self {
        Self {
            store,
            lease,
            tick_at_ms,
            started_at,
        }
    }

    /// Revalidate exact durable intent, claim, payload and both lease horizons.
    /// The final time sample includes writer admission and transaction completion.
    /// Consuming this check does not authorize a second attempt or prove absence.
    pub async fn verify(self, admission: &AutomationAdmission) -> Result<(), AutomationError> {
        self.verify_before_contact(admission, || Ok(())).await
    }

    /// Check host readiness after durable writer waits, before the final lease
    /// sample. The bounded synchronous owner check must not contact the
    /// provider; its locking or generation refresh time is included in the
    /// lease horizon. No asynchronous wait follows the final time sample.
    pub async fn verify_before_contact(
        self,
        admission: &AutomationAdmission,
        host_ready: impl FnOnce() -> Result<(), AutomationError> + Send,
    ) -> Result<(), AutomationError> {
        if *admission != self.lease.admission() {
            return Err(AutomationError::AccessDenied);
        }
        let (mut transaction, phase) = self.store.begin_timer_write().await?;
        if phase != TimerPhase::Active {
            return Err(AutomationError::Conflict);
        }
        crate::store::verify_automation_lease_tx(&mut transaction, &self.store, &self.lease)
            .await?;
        crate::store::verify_claimed_dispatch_boundary_tx(
            &mut transaction,
            &self.store,
            &self.lease,
        )
        .await?;
        let row = sqlx::query(
            "SELECT r.lease_expires_at_ms AS timer_expiry, tf.lease_expires_at_ms AS run_expiry
             FROM automation_tasks t
             JOIN automation_runs r ON r.task_id = t.task_id
             JOIN automation_occurrence_lifecycle o
               ON o.task_id = r.task_id AND o.occurrence = r.occurrence
             JOIN taskflow_step_outbox s
               ON s.owner_agent_id = o.owner_agent_id AND s.run_id = o.taskflow_run_id
              AND s.step_id = 'codex_turn' AND s.attempt = o.step_attempt AND s.event_kind = 'claimed'
             JOIN taskflow_runs tf
               ON tf.owner_agent_id = s.owner_agent_id AND tf.run_id = s.run_id
              AND tf.owner_id = s.owner_id AND tf.owner_epoch = s.owner_epoch
              AND tf.generation = s.generation AND tf.fencing_token = s.fencing_token
             JOIN automation_dispatch_outcomes d
               ON d.task_id = r.task_id AND d.occurrence = r.occurrence
              AND d.client_user_message_id = r.client_user_message_id AND d.outcome = 'uncertain'
             WHERE t.task_id = ? AND r.occurrence = ? AND t.owner_agent_id = ?
               AND t.state = 'enabled' AND r.state = 'leased' AND tf.state = 'running'
               AND r.lease_generation = ? AND r.lease_token = ?
               AND r.client_user_message_id = ?",
        )
        .bind(self.lease.task.task_id.to_string())
        .bind(i64::try_from(self.lease.occurrence).map_err(|_| AutomationError::Invalid)?)
        .bind(self.lease.task.owner_agent_id.as_str())
        .bind(i64::try_from(self.lease.lease_generation).map_err(|_| AutomationError::Invalid)?)
        .bind(&self.lease.lease_token)
        .bind(&self.lease.client_user_message_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let timer_expiry: i64 = row
            .try_get("timer_expiry")
            .map_err(|_| AutomationError::Corrupt)?;
        let run_expiry: i64 = row
            .try_get("run_expiry")
            .map_err(|_| AutomationError::Corrupt)?;
        transaction
            .commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        host_ready()?;
        let now_ms = self
            .tick_at_ms
            .checked_add(
                u64::try_from(self.started_at.elapsed().as_millis())
                    .map_err(|_| AutomationError::Invalid)?,
            )
            .ok_or(AutomationError::Invalid)?;
        let now_ms = i64::try_from(now_ms).map_err(|_| AutomationError::Invalid)?;
        if timer_expiry <= now_ms || run_expiry <= now_ms {
            return Err(AutomationError::Conflict);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "queue_contact_tests.rs"]
mod tests;
