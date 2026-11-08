//! Verify a task's original creation binding in the same read transaction as
//! its committed history. Readback never registers a definition or genesis.

use crate::AutomationStore;
use crate::BoundedCircuitDefinitionV2;
use crate::CircuitCommittedTraceV2;
use crate::CircuitStartV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::hash;

impl AutomationStore {
    /// Read only the task created from these exact original start/definition/
    /// fence bytes. Missing history returns None; corrupt or different history
    /// fails without attempting creation, repair, lease renewal or execution.
    pub async fn read_bounded_circuit_task(
        &self,
        definition: &BoundedCircuitDefinitionV2,
        start: &CircuitStartV2,
        original_fence: &TaskFlowFence,
    ) -> Result<Option<CircuitCommittedTraceV2>, TaskFlowError> {
        if original_fence.owner_agent_id != *self.owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        let event = CircuitLedgerEventV2::Created {
            start: start.clone(),
            fence: CircuitFenceIdentityV2::from_fence(original_fence)?,
        };
        let (initial, _) =
            event.replay(/*previous*/ None, definition, self.owner_agent_id())?;
        let command_digest = hash("hepta.circuit.command.v2", &event)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), &start.run_id).await?;
        let trace = match history {
            Some(history) => {
                if history.run.definition_digest != initial.definition_digest
                    || history.commands.get("create") != Some(&command_digest)
                {
                    return Err(TaskFlowError::Conflict(
                        "Circuit task has different original creation bytes".into(),
                    ));
                }
                Some(CircuitCommittedTraceV2 {
                    run: history.run,
                    completions: history.completions,
                    history_digest: history.last_digest,
                })
            }
            None => None,
        };
        tx.commit().await.map_err(unavailable)?;
        Ok(trace)
    }
}

#[cfg(test)]
#[path = "circuit_task_readback_tests.rs"]
mod tests;
