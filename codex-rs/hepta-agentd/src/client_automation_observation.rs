use super::*;

impl AgentdClient {
    /// Observe a completed exact effect through the original durable owner.
    /// This never renews a lease, consumes a nonce, settles or sends an effect.
    pub async fn automation_observe_effect(
        &self,
        intent: AuthorizedEffectIntent,
        command_id: String,
    ) -> Result<AutomationEffectReconcileSnapshot, AgentdError> {
        if !self.capabilities().await?.capabilities.iter().any(|capability| {
            capability.id == crate::AUTOMATION_TERMINAL_OBSERVATION_CAPABILITY && capability.major == 1
        }) {
            return Err(AgentdError::Protocol("Agentd has no terminal effect observation capability".to_owned()));
        }
        match self.send(AgentdRequest::automation_observe_effect(
            self.request_id(), self.spawn_generation, intent, command_id,
        )).await?.payload {
            AgentdPayload::AutomationEffectReconcile(observation) => Ok(observation),
            payload => unexpected(payload),
        }
    }
}
