//! Root-only transport borrows the already-installed original bounded owner.
use super::*;
impl AgentdState {
    pub(crate) async fn self_iteration_current_round(
        &self,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let handle = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("original iteration runtime unavailable".into()))?;
        let current = handle.inspect_current_round().await?;
        Ok(crate::AgentdPayload::SelfIterationCurrentRound {
            round_status_json: current
                .as_ref()
                .map(|value| value.status.to_json())
                .transpose()?,
            has_pending_model_requests: current
                .is_some_and(|value| value.has_pending_model_requests),
        })
    }

    pub(crate) async fn self_iteration_round_status(
        &self,
        goal_id: String,
        canonical_policy_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let goal = codex_hepta_agent_components::types::StableId::new(&goal_id)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let policy = canonical_policy_digest
            .parse::<codex_hepta_agent_components::types::Digest32>()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let handle = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("original iteration runtime unavailable".into()))?;
        let status = handle.inspect_round(goal, policy).await?;
        Ok(crate::AgentdPayload::SelfIterationRoundStatus {
            goal_id,
            canonical_policy_digest,
            round_status_json: status.to_json()?,
        })
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "state_self_iteration_round_tests.rs"]
mod tests;
