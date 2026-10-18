use super::AgentdClient;
use super::unexpected;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::CognitiveModelStatus;

impl AgentdClient {
    pub async fn cognitive_model_status(&self) -> Result<CognitiveModelStatus, AgentdError> {
        let supported = self.capabilities().await?.capabilities.iter().any(|capability| {
            capability.id == crate::COGNITIVE_MODEL_STATUS_CAPABILITY && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise cognitive model readback".to_owned(),
            ));
        }
        match self
            .send(AgentdRequest::cognitive_model_status(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::CognitiveModelStatus(status) => {
                if status.installed.as_ref().is_some_and(|installed| {
                    installed.spawn_generation != self.spawn_generation
                }) {
                    return Err(AgentdError::GenerationFenced(
                        "cognitive model readback belongs to another launch".to_owned(),
                    ));
                }
                Ok(status)
            }
            payload => unexpected(payload),
        }
    }
}
