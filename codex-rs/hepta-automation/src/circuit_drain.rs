//! Drain observations come from the same verified Circuit history as execution.

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::circuit_journal;
use crate::circuit_journal::unavailable;

impl AutomationStore {
    /// Count nonterminal Circuits, including stopped runs with unsettled work.
    /// All pages share one database snapshot and every projection is replayed.
    /// A missing or corrupt history fails the observation instead of reporting
    /// zero work. This is a read-only observation, not a cancellation receipt.
    pub async fn circuit_drain_blockers(&self) -> Result<u32, TaskFlowError> {
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        circuit_journal::verify_owner(&mut tx, self.owner_agent_id()).await?;
        let mut cursor: Option<String> = None;
        let mut blockers = 0_u32;
        loop {
            let runs: Vec<String> = sqlx::query_scalar(
                "SELECT run_id FROM circuit_v2_runs
                 WHERE owner_agent_id = ? AND (? IS NULL OR run_id > ?)
                 ORDER BY run_id LIMIT 128",
            )
            .bind(self.owner_agent_id().as_str())
            .bind(cursor.as_deref())
            .bind(cursor.as_deref())
            .fetch_all(&mut *tx)
            .await
            .map_err(unavailable)?;
            if runs.is_empty() {
                break;
            }
            for run_id in runs {
                let history = circuit_journal::load(&mut tx, self.owner_agent_id(), &run_id)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Corrupt("Circuit disappeared from drain snapshot".into())
                    })?;
                if history.run.outcome().is_none() || history.run.unresolved() != 0 {
                    blockers = blockers.checked_add(1).ok_or_else(|| {
                        TaskFlowError::Corrupt("Circuit drain count overflow".into())
                    })?;
                }
                cursor = Some(run_id);
            }
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(blockers)
    }
}

#[cfg(test)]
#[path = "circuit_drain_tests.rs"]
mod tests;
