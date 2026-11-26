use super::*;

impl AgentdClient {
    /// Read original native facts through the installed serial owner. The
    /// server requires an actual Root peer; this returns no execution grant.
    pub async fn native_model_receipt(
        &self,
        request_id: String,
    ) -> Result<(u64, Option<String>), AgentdError> {
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::NativeModelReceipt {
                    request_id: request_id.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::NativeModelReceipt {
                request_id: actual,
                native_record_json,
            } if actual == request_id => Ok((response.current_generation, native_record_json)),
            payload => unexpected(payload),
        }
    }
}

#[cfg(test)]
#[path = "client_native_model_receipt_tests.rs"]
mod tests;
