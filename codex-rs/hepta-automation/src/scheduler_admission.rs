//! Revalidate the original local preparation before the external queue seam.

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationStore;
use crate::AutomationTaskFlowDispatch;
use crate::TimerPhase;

impl AutomationStore {
    pub(crate) async fn verify_prepared_admission(
        &self,
        lease: &AutomationLease,
        prepared: &AutomationTaskFlowDispatch,
        claimed_at: u64,
        clock: &mut impl FnMut() -> Result<u64, AutomationError>,
    ) -> Result<bool, AutomationError> {
        let (mut tx, phase) = self.begin_timer_write().await?;
        if phase != TimerPhase::Active {
            return Ok(false);
        }
        crate::store::verify_claimed_dispatch_boundary_tx(&mut tx, self, lease).await?;
        let current: bool = sqlx::query_scalar(
            "SELECT EXISTS(
                SELECT 1 FROM automation_runs r
                JOIN taskflow_runs t ON t.owner_agent_id = ? AND t.run_id = ?
                WHERE r.task_id = ? AND r.occurrence = ? AND r.state = 'leased'
                  AND r.lease_generation = ? AND r.lease_token = ?
                  AND r.client_user_message_id = ? AND r.lease_expires_at_ms = ?
                  AND t.state = 'running' AND t.revision = ?
                  AND t.owner_id = ? AND t.owner_epoch = ? AND t.generation = ?
                  AND t.fencing_token = ? AND t.cancel_requested = 0
                  AND t.lease_expires_at_ms > ?
            )",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(&prepared.run.run_id)
        .bind(lease.task.task_id.to_string())
        .bind(i64::try_from(lease.occurrence).map_err(|_| AutomationError::Invalid)?)
        .bind(i64::try_from(lease.lease_generation).map_err(|_| AutomationError::Invalid)?)
        .bind(&lease.lease_token)
        .bind(&lease.client_user_message_id)
        .bind(i64::try_from(lease.lease_expires_at_ms).map_err(|_| AutomationError::Invalid)?)
        .bind(i64::try_from(prepared.run.revision).map_err(|_| AutomationError::Invalid)?)
        .bind(&prepared.fence.owner_id)
        .bind(i64::try_from(prepared.fence.owner_epoch).map_err(|_| AutomationError::Invalid)?)
        .bind(i64::try_from(prepared.fence.generation).map_err(|_| AutomationError::Invalid)?)
        .bind(prepared.fence.fencing_token.as_str())
        .bind(i64::try_from(clock()?).map_err(|_| AutomationError::Invalid)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let now = clock()?;
        tx.commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        Ok(current && now >= claimed_at && now < lease.lease_expires_at_ms)
    }
}
