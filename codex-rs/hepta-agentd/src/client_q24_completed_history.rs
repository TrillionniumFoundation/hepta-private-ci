//! Read current-recipient DATA only. A missing or lost reply is never evidence
//! that historical restoration completed, and grants no right to rerun work.

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;

use super::AgentdClient;
use super::unexpected;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;

impl AgentdClient {
    pub async fn original_q24_completed_history(
        &self,
    ) -> Result<Option<OriginalQ24CompletedHistoryDataV1>, AgentdError> {
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::OriginalQ24CompletedHistory {},
            })
            .await?;
        match response.payload {
            AgentdPayload::OriginalQ24CompletedHistory { data } => {
                if let Some(data) = &data {
                    data.validate_data().map_err(AgentdError::Protocol)?;
                }
                Ok(data)
            }
            payload => unexpected(payload),
        }
    }
}
