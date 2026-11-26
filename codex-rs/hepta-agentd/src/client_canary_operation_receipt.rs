use super::*;
use crate::CanaryOperationQueryV2;
use codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2;

impl AgentdClient {
    /// Inspect the complete original current operation through an actual Root
    /// caller. Production callers pin the independently installed Agent UID/PID;
    /// the returned portable record grants no execution or selection authority.
    pub async fn canary_operation_receipt(
        &self,
        query: CanaryOperationQueryV2,
    ) -> Result<(u64, NeuronAcknowledgedOperationV2), AgentdError> {
        crate::canary_operation_receipt::validate_query(&query)?;
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CanaryOperationReceipt {
                    query: query.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::CanaryOperationReceipt {
                query: actual,
                source_digest,
                receipt_hex,
            } if actual == query => {
                let receipt = crate::canary_operation_receipt::decode_receipt(
                    &query,
                    &receipt_hex,
                    &source_digest,
                )?;
                Ok((response.current_generation, receipt))
            }
            payload => unexpected(payload),
        }
    }
}
