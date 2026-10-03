//! Verified historical authoring identity, without a live/settlement permit.

use super::*;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct StepAuthoringIdentity {
    pub(crate) owner_agent_id: codex_hepta_contracts::AgentId,
    pub(crate) run_id: String,
    pub(crate) step_id: String,
    pub(crate) attempt: u32,
    pub(crate) intent_digest: Sha256Digest,
    pub(crate) payload_digest: Sha256Digest,
    pub(crate) fence: TaskFlowFence,
    pub(crate) prepared_event_digest: Sha256Digest,
}

impl AutomationStore {
    /// Check immutable history without treating the run as settled or granting
    /// a write. Later attempts/owners do not erase this authoring identity.
    pub(crate) async fn read_step_authoring_identity(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<StepAuthoringIdentity>, TaskFlowError> {
        validate_common_without_digests(run_id, step_id, attempt, "read_identity")?;
        // Never invoke the legacy qualification schema-creation path in an audit read.
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let run = load_run(&mut tx, self, run_id).await?;
        let definition = load_definition(&mut tx, self, &run).await?;
        validate_step_node(&definition, step_id)?;
        let events = load_step_events(&mut tx, self, run_id, step_id, attempt).await?;
        let Some(first) = events.first() else {
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(None);
        };
        let receipt = reconstruct_step(
            self.taskflow_owner_agent_id(),
            run_id,
            step_id,
            attempt,
            &events,
        )?;
        let identity = StepAuthoringIdentity {
            owner_agent_id: receipt.owner_agent_id,
            run_id: receipt.run_id,
            step_id: receipt.step_id,
            attempt: receipt.attempt,
            intent_digest: receipt.intent_digest,
            payload_digest: receipt.payload_digest,
            fence: receipt.fence,
            prepared_event_digest: Sha256Digest::parse(first.event_digest.clone())
                .map_err(|_| corrupt("step authoring digest"))?,
        };
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(Some(identity))
    }
}
