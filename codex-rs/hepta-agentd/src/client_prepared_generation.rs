use super::*;
use codex_hepta_agent_components::neuron::NeuronPreparedGenerationV2;
use codex_hepta_agent_components::types::Digest32;
impl AgentdClient {
    /// Requires the actual Root peer; the response is factual and grants no use.
    /// The first result is the runtime generation. The original client also
    /// independently validates the configured spawn generation on every frame.
    pub async fn prepared_generation_v2(
        &self,
        generation: u64,
        configuration: Digest32,
        body: Digest32,
    ) -> Result<(u64, Option<NeuronPreparedGenerationV2>), AgentdError> {
        let request = AgentdRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: self.request_id(),
            spawn_generation: self.spawn_generation,
            method: crate::AgentdMethod::PreparedGenerationV2 {
                generation,
                configuration_digest: configuration.to_string(),
                body_digest: body.to_string(),
            },
        };
        let response = self.send(request).await?;
        match response.payload {
            AgentdPayload::PreparedGenerationV2 {
                generation: actual,
                configuration_digest,
                body_digest,
                prepared_hex,
            } if actual == generation
                && configuration_digest == configuration.to_string()
                && body_digest == body.to_string() =>
            {
                let packet=prepared_hex.map(|hex|{
                    let max=codex_hepta_agent_components::neuron::MAX_NEURON_PREPARED_GENERATION_BYTES_V2;
                    if hex.is_empty() || hex.len()>2*max || hex.len()%2!=0 {return Err(AgentdError::Protocol("whole prepared response bound".into()));}
                    let mut bytes=Vec::with_capacity(hex.len()/2);
                    for pair in hex.as_bytes().chunks_exact(2){
                        let decode=|c|match c {b'0'..=b'9'=>Ok(c-b'0'),b'a'..=b'f'=>Ok(c-b'a'+10),_=>Err(AgentdError::Protocol("prepared lowercase hex".into()))};
                        bytes.push((decode(pair[0])?<<4)|decode(pair[1])?);
                    }
                    NeuronPreparedGenerationV2::from_bytes(bytes.clone(),Digest32::of_bytes(&bytes))
                        .map_err(|e|AgentdError::Protocol(format!("whole prepared response: {e}")))
                }).transpose()?;
                Ok((response.current_generation, packet))
            }
            payload => unexpected(payload),
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "client_prepared_generation_tests.rs"]
mod tests;
