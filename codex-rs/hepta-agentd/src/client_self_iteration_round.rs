use super::*;
impl AgentdClient {
    /// Observe the sole cold reservation and all admitted model stages through
    /// the same Root-only channel. The response opens or reconciles no store.
    pub async fn self_iteration_current_round(
        &self,
    ) -> Result<(u64, Option<crate::AgentdSelfIterationCurrentRoundV1>), AgentdError> {
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::SelfIterationCurrentRound,
            })
            .await?;
        match response.payload {
            AgentdPayload::SelfIterationCurrentRound {
                round_status_json: Some(json),
                has_pending_model_requests,
            } => Ok((
                response.current_generation,
                Some(crate::AgentdSelfIterationCurrentRoundV1 {
                    status: crate::AgentdSelfIterationRoundStatusV1::from_json(&json)?,
                    has_pending_model_requests,
                }),
            )),
            AgentdPayload::SelfIterationCurrentRound {
                round_status_json: None,
                has_pending_model_requests: false,
            } => Ok((response.current_generation, None)),
            payload => unexpected(payload),
        }
    }

    /// The original server requires UID0; the client additionally pins the
    /// actual Agent process with with_peer_process. This grants no authority.
    pub async fn self_iteration_round_status(
        &self,
        goal: codex_hepta_agent_components::types::StableId,
        policy: codex_hepta_agent_components::types::Digest32,
    ) -> Result<(u64, crate::AgentdSelfIterationRoundStatusV1), AgentdError> {
        let goal_id = goal.to_string();
        let canonical_policy_digest = policy.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::SelfIterationRoundStatus {
                    goal_id: goal_id.clone(),
                    canonical_policy_digest: canonical_policy_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::SelfIterationRoundStatus {
                goal_id: actual_goal,
                canonical_policy_digest: actual_policy,
                round_status_json,
            } if actual_goal == goal_id && actual_policy == canonical_policy_digest => {
                let status =
                    crate::AgentdSelfIterationRoundStatusV1::from_json(&round_status_json)?;
                if status.round.goal_id() != goal.as_str()
                    || status.round.canonical_policy_digest() != policy
                {
                    return Err(AgentdError::Protocol(
                        "original round response scope differs".into(),
                    ));
                }
                Ok((response.current_generation, status))
            }
            payload => unexpected(payload),
        }
    }
}
