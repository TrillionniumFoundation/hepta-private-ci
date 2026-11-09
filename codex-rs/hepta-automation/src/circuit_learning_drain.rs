//! Learning drain observes original claimed deliveries without treating a
//! scheduled intent or a future successor task as running computation.

use super::*;

impl AutomationStore {
    /// Count claimed deliveries that have no authenticated completion ACK.
    /// A claim can mean active work, an uncertain commit, or an iteration still
    /// waiting for its distinct successor. It never proves a job is running.
    /// Unclaimed intents have not authorized a submission and do not block.
    ///
    /// Read every retained row, including ACKs, in the same bounded snapshot;
    /// malformed metadata or source history must not silently look quiescent.
    /// Restarting without a learning profile cannot hide an earlier claim.
    pub async fn circuit_learning_drain_blockers(&self) -> Result<u32, Error> {
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        circuit_journal::verify_owner(&mut tx, self.owner_agent_id()).await?;
        let runs: Vec<String> = sqlx::query_scalar(
            "SELECT run_id FROM circuit_learning_outbox_v1
             WHERE owner_agent_id = ? ORDER BY run_id LIMIT ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(MAX_RECORDS + 1)
        .fetch_all(&mut *tx)
        .await
        .map_err(unavailable)?;
        if runs.len() > MAX_RECORDS as usize {
            return Err(Error::Capacity);
        }
        let mut claims = 0;
        for run in runs {
            let row = read(self, &mut tx, &run).await?.ok_or(Error::Conflict)?;
            if row.request_digest.is_some() && row.acknowledged_head.is_none() {
                claims += 1;
            }
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(claims)
    }
}
