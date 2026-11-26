//! Actual control client for the enrolled secrets capability; no effect retries.
use super::*;

impl AgentdClient {
    pub async fn secrets_consume_original(
        &self,
        original_id: String,
        budget_ms: u64,
    ) -> Result<crate::SecretsOriginalObservation, AgentdError> {
        self.secrets_call(crate::AgentdMethod::SecretsConsumeOriginal {
            original_id,
            budget_ms,
        })
        .await
    }
    pub async fn secrets_original_status(
        &self,
        original_id: String,
    ) -> Result<crate::SecretsOriginalObservation, AgentdError> {
        self.secrets_call(crate::AgentdMethod::SecretsOriginalStatus { original_id })
            .await
    }
    pub async fn secrets_recover_original(
        &self,
        original_id: String,
    ) -> Result<crate::SecretsOriginalObservation, AgentdError> {
        self.secrets_call(crate::AgentdMethod::SecretsRecoverOriginal { original_id })
            .await
    }
    async fn secrets_call(
        &self,
        method: crate::AgentdMethod,
    ) -> Result<crate::SecretsOriginalObservation, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method,
            })
            .await?
            .payload
        {
            AgentdPayload::SecretsOriginal(observation) => Ok(observation),
            payload => unexpected(payload),
        }
    }
}
